"""Activities of the source-sync workflow, plus schedule and trigger helpers (spec A, A11).

Every activity is idempotent: writes are `MERGE` upserts, cursors and run totals are saved as
absolute values, and the activity that starts a run reuses the row of its own workflow run. Provider
errors become Temporal errors here: rate limits carry `next_retry_delay` (the provider's Retry-After),
authorisation and validation problems are non-retryable.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from collections.abc import Callable
from dataclasses import asdict
from datetime import timedelta
from typing import Any

from temporalio import activity
from temporalio.client import Client
from temporalio.exceptions import ApplicationError, WorkflowAlreadyStartedError

from actron.config import get_settings
from actron.connectors import common
from actron.connectors.common import (
    AuthError,
    Batch,
    RetryableProviderError,
    ValidationError,
    WriteResult,
)
from actron.connectors.steps import SCHEDULE_MINUTES
from actron.graph.ontology import OntologyViolation
from actron.logging import get_logger

log = get_logger(__name__)

TASK_QUEUE = "ingest"
LINK_QUEUE = "link"
SPILL_BYTES = 1_000_000
LINK_CHUNK = 5000
SOURCES = ("code", "github", "slack", "linear", "slack_export")


def connector(source: str) -> Any:
    """The connector module for a source (imported when first needed)."""
    import importlib

    names = {"github": "github", "slack": "slack", "linear": "linear", "slack_export": "slack_export",
             "code": "code_steps"}
    if source not in names:
        raise ValidationError(f"unknown source {source!r}")
    return importlib.import_module(f"actron.connectors.{names[source]}")


def to_application_error(exc: Exception) -> ApplicationError:
    """Map a connector error to a Temporal error with the right retry behaviour."""
    if isinstance(exc, RetryableProviderError):
        delay = timedelta(seconds=exc.retry_after) if exc.retry_after else None
        return ApplicationError(str(exc), type="RetryableProviderError", next_retry_delay=delay)
    if isinstance(exc, AuthError):
        return ApplicationError(str(exc), type="AuthError", non_retryable=True)
    if isinstance(exc, ValidationError):
        return ApplicationError(str(exc), type="ValidationError", non_retryable=True)
    if isinstance(exc, OntologyViolation):
        return ApplicationError(str(exc), type="OntologyViolation", non_retryable=True)
    return ApplicationError(f"{type(exc).__name__}: {exc}", type=type(exc).__name__)


def _redis() -> Any:
    import redis

    return redis.Redis.from_url(get_settings().REDIS_URL, socket_timeout=5, decode_responses=True)


# Activities
@activity.defn
async def load_cursor(ws: str, source: str) -> dict[str, Any]:
    return await asyncio.to_thread(common.load_cursor, ws, source)


@activity.defn
async def start_run(ws: str, source: str, mode: str) -> str:
    info = activity.info()
    from sqlalchemy import select

    from actron.db.models import SyncRun
    from actron.db.session import session_scope

    def find_existing() -> str | None:
        with session_scope() as session:
            row = session.execute(
                select(SyncRun).where(SyncRun.temporal_run_id == info.workflow_run_id,
                                      SyncRun.workspace_id == ws, SyncRun.source == source)).scalars().first()
            return str(row.id) if row else None

    existing = await asyncio.to_thread(find_existing)
    if existing:
        return existing
    return await asyncio.to_thread(common.start_run, ws, source, mode, workflow_id=info.workflow_id,
                                   temporal_run_id=info.workflow_run_id)


@activity.defn
async def fetch_page(ws: str, source: str, step: str, cursor: dict[str, Any], page_token: str | None) -> Batch:
    module = connector(source)
    try:
        config = (await asyncio.to_thread(common.resolve_config, ws, source)).values
        batch: Batch = await module.fetch_page(ws, step, cursor, page_token, config)
    except (RetryableProviderError, AuthError, ValidationError, OntologyViolation) as exc:
        raise to_application_error(exc) from exc
    return await asyncio.to_thread(_maybe_spill, batch)


def _maybe_spill(batch: Batch) -> Batch:
    """Keep Temporal payloads small: a big batch goes to Redis and travels as a key."""
    body = {"nodes": batch.nodes, "only_if_missing": batch.only_if_missing, "links": batch.links,
            "tombstones": batch.tombstones, "extra": batch.extra}
    raw = json.dumps(body, default=str)
    if len(raw) <= SPILL_BYTES:
        return batch
    key = f"ingest:batch:{uuid.uuid4().hex}"
    client = _redis()
    try:
        client.set(key, raw, ex=86400)
    finally:
        client.close()
    return Batch(step=batch.step, cursor_update=batch.cursor_update, next_page_token=batch.next_page_token,
                 errors=batch.errors, partial_reason=batch.partial_reason, meta=batch.meta, spill_key=key)


def _unspill(batch: Batch) -> Batch:
    if not batch.spill_key:
        return batch
    client = _redis()
    try:
        raw = client.get(batch.spill_key)
    finally:
        client.close()
    if raw is None:
        raise ApplicationError("a spilled batch expired before it was written", type="BatchExpired",
                               non_retryable=True)
    body = json.loads(raw)
    batch.nodes, batch.only_if_missing = body["nodes"], body["only_if_missing"]
    batch.links, batch.tombstones, batch.extra = body["links"], body["tombstones"], body["extra"]
    batch.spill_key = None
    return batch


@activity.defn
async def write_batch(ws: str, source: str, step: str, batch: Batch, run_id: str) -> WriteResult:
    module = connector(source)
    batch = await asyncio.to_thread(_unspill, batch)
    try:
        result: WriteResult = await asyncio.to_thread(module.write_batch, ws, step, batch)
    except (RetryableProviderError, AuthError, ValidationError, OntologyViolation) as exc:
        raise to_application_error(exc) from exc
    if result.changed_ids:
        await asyncio.to_thread(common.remember_changed, run_id, result.changed_ids)
    activity.heartbeat(sum(result.counts.values()))
    # the ids are in Redis for linking; the workflow only needs a bounded sample
    result.changed_ids = result.changed_ids[:500]
    return result


@activity.defn
async def save_cursor(ws: str, source: str, cursor: dict[str, Any]) -> None:
    await asyncio.to_thread(common.save_cursor, ws, source, cursor)


async def _publish(ws: str, type_: str, payload: dict[str, Any]) -> None:
    """One event row (request_id null) and a Redis message on ws:<ws>:ingestion."""
    try:
        from actron.flow.events import publish_workspace_event
    except ImportError:
        await asyncio.to_thread(common.publish_ingestion_event, ws, type_, payload)
        return
    await publish_workspace_event(ws, type_, payload)


@activity.defn
async def publish_progress(ws: str, run_id: str, source: str, kind: str, payload: dict[str, Any]) -> None:
    """kind is started, progress, partial or finished; the event type is `ingestion.<kind>`."""
    body = {"source": source, "runId": run_id, **payload}
    if kind == "progress":
        await asyncio.to_thread(common.update_run, run_id, items=payload.get("counts") or {})
    await _publish(ws, f"ingestion.{kind}", body)


@activity.defn
async def finish_run(ws: str, source: str, run_id: str, status: str, reason: str | None, counts: dict[str, int],
                     errors: list[dict[str, Any]], duration_ms: int, auth_failed: bool = False) -> None:
    await asyncio.to_thread(common.finish_run, run_id, status, reason=reason, items=counts, errors=errors[:200])
    if auth_failed:
        await asyncio.to_thread(_mark_connection, ws, source, "error")
    elif status in ("done", "partial"):
        await asyncio.to_thread(_mark_connection, ws, source, "connected", only_if="error")
    if status == "partial":
        await _publish(ws, "ingestion.partial", {"source": source, "runId": run_id, "reason": reason})
    await _publish(ws, "ingestion.finished", {"source": source, "runId": run_id, "status": status,
                                              "counts": counts, "durationMs": duration_ms, "reason": reason})


def _mark_connection(ws: str, source: str, status: str, only_if: str | None = None) -> None:
    from sqlalchemy import update

    from actron.db.models import Connection
    from actron.db.session import session_scope

    providers = [source] if source != "github" else ["github"]
    with session_scope() as session:
        stmt = update(Connection).where(Connection.workspace_id == ws, Connection.provider.in_(providers))
        if only_if:
            stmt = stmt.where(Connection.status == only_if)
        session.execute(stmt.values(status=status))


@activity.defn
async def pause_schedule(ws: str, source: str, reason: str) -> None:
    """Pause the source's schedule after an authorisation failure (the run record carries the reason)."""
    from actron.workflows.schedules import pause_schedule as pause
    from actron.workflows.schedules import schedule_id

    client = await get_client()
    try:
        await pause(client, schedule_id(ws, source), note=reason[:200])
    except Exception as exc:  # no schedule yet (a manual run): nothing to pause
        log.warning("could not pause the schedule", extra={"error": str(exc), "source": source})


@activity.defn
async def start_linking(ws: str, source: str, run_id: str, changed_ids: list[str]) -> int:
    """Start LinkingWorkflow (W4, task queue `link`) for the ids changed in this run. Returns how many.

    Started through the client rather than as a child: nothing waits for linking, and it must outlive this run.
    """
    remembered = await asyncio.to_thread(common.take_changed, run_id)
    all_ids = sorted(set(remembered) | set(changed_ids))
    client = await get_client()
    for n, start in enumerate(range(0, max(len(all_ids), 1), LINK_CHUNK)):
        chunk = all_ids[start : start + LINK_CHUNK]
        with contextlib.suppress(WorkflowAlreadyStartedError):  # a retried activity
            await client.start_workflow("LinkingWorkflow", args=[ws, chunk], id=f"link-{ws}-{run_id}-{n}",
                                        task_queue=LINK_QUEUE)
    return len(all_ids)


@activity.defn
async def run_followup(ws: str, source: str) -> bool:
    """If a trigger arrived while this run was going, start one more incremental run now."""
    key = f"sync:followup:{ws}:{source}"

    def take() -> bool:
        client = _redis()
        try:
            return bool(client.getdel(key))
        finally:
            client.close()

    if not await asyncio.to_thread(take):
        return False
    client = await get_client()
    await client.start_workflow("SourceSyncWorkflow", args=[ws, source, "incremental"],
                                id=f"sync-{ws}-{source}-followup-{uuid.uuid4().hex[:10]}", task_queue=TASK_QUEUE)
    return True


ACTIVITIES: list[Callable[..., Any]] = [
    load_cursor, start_run, fetch_page, write_batch, save_cursor, publish_progress, finish_run, pause_schedule,
    start_linking, run_followup,
]

_CLIENT: Client | None = None


async def get_client() -> Client:
    global _CLIENT
    if _CLIENT is None:
        settings = get_settings()
        _CLIENT = await Client.connect(settings.TEMPORAL_ADDRESS, namespace=settings.TEMPORAL_NAMESPACE)
    return _CLIENT


# Schedules and triggers (called by the API, the webhook route and the request flow; not activities)
async def ensure_sync_schedule(ws: str, source: str, client: Client | None = None) -> str | None:
    """Create or update the source's Temporal Schedule (overlap SKIP). Returns its id; None for one-off sources."""
    from actron.workflows.schedules import ensure_schedule, schedule_id

    minutes = SCHEDULE_MINUTES.get(source)
    if minutes is None:
        return None
    client = client or await get_client()
    await ensure_schedule(client, ws, source, timedelta(minutes=minutes), "SourceSyncWorkflow",
                          [ws, source, "incremental"], task_queue=TASK_QUEUE)
    return schedule_id(ws, source)


async def start_backfill(ws: str, source: str, client: Client | None = None) -> str:
    """Start `SourceSyncWorkflow(ws, source, "backfill")` with id `sync-<ws>-<source>-backfill-<id>`."""
    client = client or await get_client()
    workflow_id = f"sync-{ws}-{source}-backfill-{uuid.uuid4().hex[:12]}"
    await client.start_workflow("SourceSyncWorkflow", args=[ws, source, "backfill"], id=workflow_id,
                                task_queue=TASK_QUEUE)
    return workflow_id


async def connect_source(ws: str, source: str, client: Client | None = None) -> dict[str, str | None]:
    """What saving a connection does (A11 step 1): start the backfill and create the incremental schedule."""
    client = client or await get_client()
    workflow_id = await start_backfill(ws, source, client)
    schedule = await ensure_sync_schedule(ws, source, client)
    return {"workflowId": workflow_id, "scheduleId": schedule}


async def sync_running(client: Client, ws: str, source: str) -> bool:
    from actron.workflows.schedules import schedule_id

    desc = await client.get_schedule_handle(schedule_id(ws, source)).describe()
    return bool(desc.info.running_actions)


async def trigger_sync(ws: str, source: str, client: Client | None = None) -> str:
    """"Sync now". Returns `started`, or `queued` when a run is going: one follow-up runs after it, so
    a merge that arrives mid-run is never missed (A11, event-driven sync)."""
    from actron.workflows.schedules import schedule_id, trigger_schedule

    client = client or await get_client()
    if await sync_running(client, ws, source):
        def flag() -> None:
            c = _redis()
            try:
                c.set(f"sync:followup:{ws}:{source}", "1", ex=3600)
            finally:
                c.close()

        await asyncio.to_thread(flag)
        return "queued"
    await trigger_schedule(client, schedule_id(ws, source))
    return "started"


_DEBOUNCE_TASKS: dict[tuple[str, str], asyncio.Task[None]] = {}


async def apply_webhook_decision(ws: str, decision: Any, client: Client | None = None,
                                 sleep: Callable[[float], Any] = asyncio.sleep) -> dict[str, Any]:
    """Carry out what `github.handle_webhook` decided: immediate triggers, one debounced trigger per burst
    (30 s after its first event) and the direct re-ingest of a merged PR."""
    done: dict[str, Any] = {"triggered": {}, "debounced": [], "reingested": None}
    for source in decision.triggers:
        done["triggered"][source] = await trigger_sync(ws, source, client)

    async def later(source: str) -> None:
        await sleep(decision.debounce_seconds)
        _DEBOUNCE_TASKS.pop((ws, source), None)
        await trigger_sync(ws, source, client)

    for source in decision.debounced:
        if source in decision.triggers or (ws, source) in _DEBOUNCE_TASKS:
            continue
        _DEBOUNCE_TASKS[(ws, source)] = asyncio.create_task(later(source))
        done["debounced"].append(source)
    if decision.reingest_pr and decision.reingest_pr.get("number"):
        result = await reingest_pull_request(ws, decision.reingest_pr["repo"], int(decision.reingest_pr["number"]))
        done["reingested"] = result.counts
    return done


async def reingest_pull_request(ws: str, repo: str, number: int) -> WriteResult:
    """Fetch one PR with its files, reviews and comments and write it now (merged PRs, Actron's own PRs)."""
    from actron.connectors import github

    config = (await asyncio.to_thread(common.resolve_config, ws, "github")).values
    result = await github.ingest_pull(ws, config, repo, number)
    if result.changed_ids:
        run_id = f"reingest-{uuid.uuid4().hex[:8]}"
        await asyncio.to_thread(common.remember_changed, run_id, result.changed_ids)
        await start_linking(ws, "github", run_id, result.changed_ids)
    return result


def run_asdict(batch: Batch) -> dict[str, Any]:
    """Plain dict of a batch, for logs and tests."""
    return asdict(batch)
