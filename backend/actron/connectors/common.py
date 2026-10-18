"""Shared pieces for the source connectors (spec A, A8 to A11).

Typed errors, retry and paging helpers for HTTP clients, the ETag store, the batch and write-result
shapes that cross the Temporal boundary, run records and cursors in PostgreSQL (A.C5), progress
events (A.C6) and connection settings resolution (A11 step 3).
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from collections import defaultdict
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx

from actron.config import get_settings
from actron.graph.store import GraphStore, LinkRow, store_for
from actron.logging import get_logger

log = get_logger(__name__)

DEFAULT_TIMEOUT = 30.0

# Labels whose rows are text that linking should look at (changed ids go to LinkingWorkflow).
LINKABLE_LABELS = frozenset(
    {
        "GithubPullRequest",
        "GithubIssue",
        "GithubIssueComment",
        "GithubReview",
        "GithubReviewComment",
        "SlackMessage",
        "LinearIssue",
        "LinearComment",
    }
)


# Errors
class ProviderError(Exception):
    """A provider call failed in a way that is not worth retrying blindly."""

    def __init__(self, message: str, *, status: int | None = None, code: str | None = None,
                 url: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.url = url


class RetryableProviderError(ProviderError):
    """Rate limit or transient failure; `retry_after` is the provider's delay in seconds, if known."""

    def __init__(self, message: str, *, retry_after: float | None = None, status: int | None = None,
                 code: str | None = None, url: str | None = None) -> None:
        super().__init__(message, status=status, code=code, url=url)
        self.retry_after = retry_after


class AuthError(ProviderError):
    """The credential is wrong, revoked or lacks a permission. Never retried."""


class ValidationError(ProviderError):
    """The input or configuration is invalid. Never retried."""


class NotFoundError(ProviderError):
    """The provider says the thing does not exist (HTTP 404)."""


class ForbiddenError(ProviderError):
    """The credential is valid but may not do this (HTTP 403 without a rate limit)."""


# Retry helpers


async def with_backoff[T](
    fn: Callable[[], Awaitable[T]],
    *,
    attempts: int = 3,
    base: float = 0.5,
    cap: float = 8.0,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> T:
    """Call `fn`, retrying transient failures (network errors, 5xx) with exponential backoff.

    Rate limits are not retried here: they raise `RetryableProviderError` at once so the Temporal
    activity can wait the provider's `Retry-After` and retry.
    """
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            return await fn()
        except TransientError as exc:
            last = exc
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            last = exc
        if attempt < attempts - 1:
            await sleep(min(cap, base * (2**attempt)))
    raise RetryableProviderError(f"provider unavailable: {last}", retry_after=None) from last


class TransientError(Exception):
    """A 5xx answer; `with_backoff` retries it."""


def parse_retry_after(value: str | None, now: float | None = None) -> float | None:
    """Seconds from a Retry-After header (delta seconds or an HTTP date)."""
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        from email.utils import parsedate_to_datetime

        when = parsedate_to_datetime(value)
        return max(0.0, when.timestamp() - (now if now is not None else time.time()))
    except (TypeError, ValueError):
        return None


_LINK_RE = re.compile(r'<([^>]+)>\s*;\s*rel="([^"]+)"')


def parse_link_header(value: str | None) -> dict[str, str]:
    """`{"next": url, "last": url, ...}` from a GitHub style Link header."""
    if not value:
        return {}
    return {rel: url for url, rel in _LINK_RE.findall(value)}


class EtagStore:
    """ETags by URL, kept inside the connector cursor under `etags`."""

    def __init__(self, etags: Mapping[str, str] | None = None) -> None:
        self._etags: dict[str, str] = dict(etags or {})

    def get(self, url: str) -> str | None:
        return self._etags.get(url)

    def set(self, url: str, etag: str | None) -> None:
        if etag:
            self._etags[url] = etag

    def as_dict(self) -> dict[str, str]:
        return dict(self._etags)


# Batch and result shapes. Plain dataclasses of JSON values so Temporal can carry them.
@dataclass
class Batch:
    """What one `fetch_page` call produced, ready for `write_batch`."""

    step: str
    nodes: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    only_if_missing: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    links: list[dict[str, Any]] = field(default_factory=list)
    tombstones: dict[str, list[str]] = field(default_factory=dict)
    cursor_update: dict[str, Any] = field(default_factory=dict)
    next_page_token: str | None = None
    errors: list[dict[str, Any]] = field(default_factory=list)
    partial_reason: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)
    spill_key: str | None = None

    def add_node(self, label: str, row: dict[str, Any]) -> None:
        self.nodes.setdefault(label, []).append(row)

    def add_missing(self, label: str, row: dict[str, Any]) -> None:
        self.only_if_missing.setdefault(label, []).append(row)

    def add_link(self, rel: str, from_label: str, from_id: str, to_label: str, to_id: str, *,
                 method: str = "structural", confidence: float = 1.0, **props: Any) -> None:
        self.links.append(
            {
                "rel": rel,
                "from_label": from_label,
                "to_label": to_label,
                "from_id": from_id,
                "to_id": to_id,
                "props": {"method": method, "confidence": confidence, **props},
            }
        )

    def add_error(self, action: str, error: str, url: str | None = None) -> None:
        self.errors.append({"action": action, "error": error, "url": url, "at": now_iso()})


@dataclass
class WriteResult:
    counts: dict[str, int] = field(default_factory=dict)
    changed_ids: list[str] = field(default_factory=list)
    links_created: int = 0
    links_missing: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def iso(value: str | None) -> str | None:
    """Pass an ISO string through (providers already send ISO 8601 with Z); None stays None."""
    return value or None


def encode_token(data: Mapping[str, Any]) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"))


def decode_token(token: str | None) -> dict[str, Any]:
    if not token:
        return {}
    out: dict[str, Any] = json.loads(token)
    return out


def merge_cursor(base: Mapping[str, Any], update: Mapping[str, Any]) -> dict[str, Any]:
    """Deep merge; a value of None in `update` removes the key."""
    out: dict[str, Any] = dict(base)
    for key, value in update.items():
        if value is None:
            out.pop(key, None)
        elif isinstance(value, Mapping) and isinstance(out.get(key), Mapping):
            out[key] = merge_cursor(out[key], value)
        elif isinstance(value, Mapping):
            out[key] = merge_cursor({}, value)
        else:
            out[key] = value
    return out


def dedupe_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """One row per id; later rows add or overwrite properties of earlier ones."""
    merged: dict[str, dict[str, Any]] = {}
    for row in rows:
        merged.setdefault(row["id"], {}).update(row)
    return list(merged.values())


# Writing a batch into the graph
def existing_ids(store: GraphStore, label: str, node_ids: Sequence[str]) -> set[str]:
    if not node_ids:
        return set()
    out: set[str] = set()
    ids_list = list(node_ids)
    for i in range(0, len(ids_list), 1000):
        rows = store.query(
            f"MATCH (n:`{label}`) WHERE n.id IN $ids RETURN n.id AS id",
            {"ids": ids_list[i : i + 1000]},
            read_only=True,
        )
        out.update(r["id"] for r in rows)
    return out


def write_generic(ws: str, batch: Batch, *, store: GraphStore | None = None) -> WriteResult:
    """Idempotent upserts of a batch: nodes, create-only nodes, links, tombstones."""
    store = store or store_for(ws)
    result = WriteResult()
    changed: list[str] = []
    for label, rows in batch.nodes.items():
        rows = dedupe_rows(rows)
        n = store.upsert_nodes(label, rows)
        result.counts[label] = result.counts.get(label, 0) + n
        if label in LINKABLE_LABELS:
            changed.extend(r["id"] for r in rows)
    for label, rows in batch.only_if_missing.items():
        rows = dedupe_rows(rows)
        have = existing_ids(store, label, [r["id"] for r in rows])
        fresh = [r for r in rows if r["id"] not in have]
        if fresh:
            n = store.upsert_nodes(label, fresh)
            result.counts[label] = result.counts.get(label, 0) + n
    grouped: dict[tuple[str, str, str], list[LinkRow]] = defaultdict(list)
    for link in batch.links:
        grouped[(link["rel"], link["from_label"], link["to_label"])].append(
            LinkRow(link["from_id"], link["to_id"], link["props"])
        )
    for (rel, from_label, to_label), link_rows in grouped.items():
        res = store.upsert_links(rel, from_label, to_label, link_rows)
        result.links_created += res.created
        result.links_missing += len(res.missing)
    for label, node_ids in batch.tombstones.items():
        if node_ids:
            store.tombstone(label, node_ids)
    result.changed_ids = list(dict.fromkeys(changed))
    return result


# Graph reads from async code
async def graph_query(ws: str, cypher: str, params: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    store = store_for(ws)
    return await asyncio.to_thread(store.query, cypher, params, read_only=True)


# Connection settings (A11 step 3: a saved connection wins; .env values are the development fallback)
@dataclass
class ResolvedConfig:
    """Connector configuration with the secret resolved. Never log or return this object."""

    provider: str
    values: dict[str, Any]

    def __repr__(self) -> str:  # keep secrets out of tracebacks
        keys = ", ".join(sorted(k for k in self.values if "token" not in k and "key" not in k))
        return f"ResolvedConfig({self.provider}: {keys})"


def effective_github(config: Mapping[str, Any], secret: Mapping[str, Any]) -> dict[str, Any]:
    s = get_settings()
    repository = config.get("repository") or s.GITHUB_REPOSITORY
    return {
        "repository": repository,
        "fork": config.get("fork") or s.GITHUB_FORK or repository,
        "upstream": config.get("upstream") or s.GITHUB_UPSTREAM,
        "working_branch": config.get("workingBranch") or config.get("working_branch"),
        "history_days": int(config.get("historyDays") or config.get("history_days")
                            or s.ACTRON_BACKFILL_DAYS),
        "token": secret.get("access_token") or s.GITHUB_TOKEN,
        "webhook_secret": secret.get("webhook_secret") or s.GITHUB_WEBHOOK_SECRET,
        "api_url": config.get("api_url") or s.GITHUB_API_URL,
    }


def effective_slack(config: Mapping[str, Any], secret: Mapping[str, Any]) -> dict[str, Any]:
    s = get_settings()
    channels = config.get("channels") or s.slack_channels
    return {
        "token": secret.get("bot_token") or s.SLACK_BOT_TOKEN,
        "app_token": secret.get("app_token") or s.SLACK_APP_TOKEN,
        "channels": list(channels or []),
        "requests_channel": config.get("requests_channel"),
        "history_days": int(config.get("historyDays") or config.get("history_days")
                            or s.ACTRON_BACKFILL_DAYS),
        "team_id": config.get("teamId"),
        "bot_user_id": config.get("botUserId"),
        "api_url": config.get("api_url") or s.SLACK_API_URL,
    }


def effective_linear(config: Mapping[str, Any], secret: Mapping[str, Any]) -> dict[str, Any]:
    s = get_settings()
    return {
        "token": secret.get("api_key") or s.LINEAR_API_KEY,
        "team": config.get("team") or s.LINEAR_TEAM_ID,
        "ticket_label": config.get("ticket_label"),
        "history_days": int(config.get("historyDays") or config.get("history_days")
                            or s.ACTRON_BACKFILL_DAYS),
        "api_url": config.get("api_url") or s.LINEAR_API_URL,
    }


def resolve_config(ws: str, source: str) -> ResolvedConfig:
    """Load the connection row, decrypt its secret and apply the `.env` fallbacks."""
    from sqlalchemy import select

    from actron.db.crypto import decrypt_secret
    from actron.db.models import Connection
    from actron.db.session import session_scope

    config: dict[str, Any] = {}
    secret: dict[str, Any] = {}
    with session_scope() as session:
        row = session.execute(
            select(Connection).where(Connection.workspace_id == ws, Connection.provider == source)
        ).scalar_one_or_none()
        if row is not None:
            config = dict(row.config or {})
            if row.secret_encrypted:
                secret = decrypt_secret(bytes(row.secret_encrypted))
    if source in ("github", "code"):
        values = effective_github(config, secret)
    elif source == "slack":
        values = effective_slack(config, secret)
    elif source == "linear":
        values = effective_linear(config, secret)
    else:
        values = dict(config)
    values["ws"] = ws
    return ResolvedConfig(source, values)


# Run records and cursors (PostgreSQL, A.C5)
def load_cursor(ws: str, source: str) -> dict[str, Any]:
    from actron.db.models import SyncCursor
    from actron.db.session import session_scope

    with session_scope() as session:
        row = session.get(SyncCursor, (ws, source))
        return dict(row.cursor) if row else {}


def save_cursor(ws: str, source: str, cursor: Mapping[str, Any]) -> None:
    from sqlalchemy.dialects.postgresql import insert

    from actron.db.models import SyncCursor
    from actron.db.session import session_scope

    stmt = insert(SyncCursor).values(workspace_id=ws, source=source, cursor=dict(cursor))
    stmt = stmt.on_conflict_do_update(
        index_elements=["workspace_id", "source"],
        set_={"cursor": stmt.excluded.cursor, "updated_at": datetime.now(UTC)},
    )
    with session_scope() as session:
        session.execute(stmt)


def start_run(ws: str, source: str, mode: str, *, workflow_id: str | None = None,
              temporal_run_id: str | None = None) -> str:
    from actron.db.models import SyncRun
    from actron.db.session import session_scope

    run_id = uuid.uuid4()
    with session_scope() as session:
        session.add(
            SyncRun(id=run_id, workspace_id=ws, source=source, mode=mode, status="running",
                    started_at=datetime.now(UTC), items={}, errors=[],
                    temporal_workflow_id=workflow_id, temporal_run_id=temporal_run_id)
        )
    return str(run_id)


def update_run(run_id: str, *, items: Mapping[str, Any] | None = None,
               errors: Sequence[Mapping[str, Any]] | None = None) -> None:
    """Set the totals so far (absolute values, so a retried call changes nothing)."""
    from actron.db.models import SyncRun
    from actron.db.session import session_scope

    with session_scope() as session:
        row = session.get(SyncRun, uuid.UUID(run_id))
        if row is None:
            return
        if items is not None:
            row.items = dict(items)
        if errors is not None:
            row.errors = [dict(e) for e in errors]


def finish_run(run_id: str, status: str, *, reason: str | None = None,
               items: Mapping[str, Any] | None = None,
               errors: Sequence[Mapping[str, Any]] | None = None) -> None:
    """status is done, partial or failed. `reason` explains partial and failed runs."""
    from actron.db.models import SyncRun
    from actron.db.session import session_scope

    if status not in ("done", "partial", "failed"):
        raise ValueError(f"bad run status {status!r}")
    with session_scope() as session:
        row = session.get(SyncRun, uuid.UUID(run_id))
        if row is None:
            return
        row.status = status
        row.finished_at = datetime.now(UTC)
        row.reason = reason
        if items is not None:
            row.items = dict(items)
        if errors is not None:
            row.errors = [dict(e) for e in errors]


def get_run(run_id: str) -> dict[str, Any] | None:
    from actron.db.models import SyncRun
    from actron.db.session import session_scope

    with session_scope() as session:
        row = session.get(SyncRun, uuid.UUID(run_id))
        if row is None:
            return None
        return {
            "id": str(row.id), "workspace_id": row.workspace_id, "source": row.source,
            "mode": row.mode, "status": row.status, "items": dict(row.items or {}),
            "errors": list(row.errors or []), "reason": row.reason,
            "started_at": row.started_at, "finished_at": row.finished_at,
        }


# Progress (A.C6)
class ProgressCounter:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.started = time.monotonic()

    def add(self, counts: Mapping[str, int]) -> None:
        for key, n in counts.items():
            self.counts[key] = self.counts.get(key, 0) + int(n)

    def total(self) -> int:
        return sum(self.counts.values())

    def per_minute(self) -> float:
        minutes = max((time.monotonic() - self.started) / 60.0, 1e-6)
        return round(self.total() / minutes, 1)


def add_counts(a: Mapping[str, int], b: Mapping[str, int]) -> dict[str, int]:
    out = dict(a)
    for k, v in b.items():
        out[k] = out.get(k, 0) + int(v)
    return out


def ingestion_channel(ws: str) -> str:
    return f"ws:{ws}:ingestion"


def publish_ingestion_event(ws: str, type_: str, payload: Mapping[str, Any]) -> int:
    """Store the event (request_id null) and publish it on Redis `ws:<ws>:ingestion`. Returns the event id."""
    import redis

    from actron.db.models import Event
    from actron.db.session import session_scope

    at = datetime.now(UTC)
    with session_scope() as session:
        event = Event(workspace_id=ws, request_id=None, seq=None, type=type_, at=at,
                      actor="actron", surface="system", payload=dict(payload))
        session.add(event)
        session.flush()
        event_id = int(event.id)
    message = json.dumps({"id": event_id, "type": type_, "at": at.isoformat(), "payload": dict(payload)},
                         default=str)
    try:
        client = redis.Redis.from_url(get_settings().REDIS_URL, socket_timeout=5)
        try:
            client.publish(ingestion_channel(ws), message)
        finally:
            client.close()
    except redis.RedisError as exc:  # the journal row is already stored; live fan-out is best effort
        log.warning("progress publish failed", extra={"error": str(exc)})
    return event_id


# Changed ids for linking, kept per run in Redis so workflow payloads stay small
def _changed_key(run_id: str) -> str:
    return f"ingest:changed:{run_id}"


def remember_changed(run_id: str, changed: Sequence[str]) -> None:
    if not changed:
        return
    import redis

    client = redis.Redis.from_url(get_settings().REDIS_URL, socket_timeout=5)
    try:
        for i in range(0, len(changed), 500):
            client.sadd(_changed_key(run_id), *changed[i : i + 500])
        client.expire(_changed_key(run_id), 7 * 86400)
    finally:
        client.close()


def take_changed(run_id: str) -> list[str]:
    import redis

    client = redis.Redis.from_url(get_settings().REDIS_URL, socket_timeout=5, decode_responses=True)
    try:
        members = sorted(client.smembers(_changed_key(run_id)))
        return [str(m) for m in members]
    finally:
        client.close()


# Test seam: tests route provider traffic to in-process fake servers.
_TRANSPORTS: dict[str, httpx.AsyncBaseTransport] = {}


def set_transport(provider: str, transport: httpx.AsyncBaseTransport | None) -> None:
    if transport is None:
        _TRANSPORTS.pop(provider, None)
    else:
        _TRANSPORTS[provider] = transport


def transport_for(provider: str) -> httpx.AsyncBaseTransport | None:
    return _TRANSPORTS.get(provider)
