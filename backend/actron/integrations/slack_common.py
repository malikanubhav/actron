"""Shared pieces of the Slack integration (W9): scope lists, bot token lookup, the flow service
adapter, links and Redis idempotency. Kept free of Bolt so the blocks, sender, bot and OAuth modules
can all import it."""

from __future__ import annotations

import dataclasses
import inspect
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

import redis.asyncio as aioredis
from slack_sdk.http_retry.builtin_async_handlers import (
    AsyncConnectionErrorRetryHandler,
    AsyncRateLimitErrorRetryHandler,
)
from slack_sdk.web.async_client import AsyncWebClient
from sqlalchemy import or_, select

from actron.config import get_settings
from actron.db.crypto import SecretDecryptError, SecretKeyMissing, decrypt_secret
from actron.db.models import Connection, Workspace
from actron.db.session import async_session
from actron.logging import get_logger

log = get_logger("actron.slack")

# One list for the manifest, the OAuth install URL and the docs (spec B, B12a).
BOT_SCOPES: tuple[str, ...] = (
    "app_mentions:read",
    "channels:history",
    "channels:read",
    "chat:write",
    "commands",
    "groups:history",
    "groups:read",
    "im:write",
    "reactions:read",
    "team:read",
    "users:read",
    "users:read.email",
)
USER_SCOPES: tuple[str, ...] = ("openid", "profile", "email")
BOT_EVENTS: tuple[str, ...] = (
    "app_mention",
    "message.channels",
    "message.groups",
    "member_joined_channel",
    "channel_rename",
    "app_uninstalled",
    "tokens_revoked",
)
SLASH_COMMAND = "/actron"
# Backend routes the manifest must point at (spec B, B11).
EVENTS_PATH = "/slack/events"
COMMANDS_PATH = "/slack/commands"
INTERACTIONS_PATH = "/slack/interactions"
OAUTH_CALLBACK_PATH = "/api/slack/oauth/callback"
OAUTH_INSTALL_PATH = "/api/slack/install"
SIGNIN_CALLBACK_PATH = "/api/auth/slack/callback"


# ---------------------------------------------------------------- links


def public_url() -> str:
    s = get_settings()
    return (s.ACTRON_PUBLIC_URL or "http://localhost:3000").rstrip("/")


def request_url(request_id: str) -> str:
    return f"{public_url()}/app/requests/{request_id}"


def web_client(token: str | None) -> AsyncWebClient:
    """Web API client against SLACK_API_URL (tests point it at the fake server)."""
    client = AsyncWebClient(token=token, base_url=get_settings().SLACK_API_URL, timeout=15)
    client.retry_handlers.append(AsyncRateLimitErrorRetryHandler(max_retry_count=2))
    client.retry_handlers.append(AsyncConnectionErrorRetryHandler())
    return client


# ---------------------------------------------------------------- tokens


@dataclass(frozen=True)
class BotCredentials:
    token: str
    team_id: str | None
    workspace_id: str | None
    bot_user_id: str | None = None
    bot_id: str | None = None
    app_token: str | None = None


def secret_dict(blob: bytes | None) -> dict[str, Any]:
    if not blob:
        return {}
    try:
        return decrypt_secret(blob)
    except (SecretDecryptError, SecretKeyMissing):
        log.warning("slack connection secret cannot be decrypted")
        return {}


def _creds(conn: Connection, team_id: str | None) -> BotCredentials | None:
    secret = secret_dict(conn.secret_encrypted)
    token = secret.get("bot_token")
    if not token or conn.status != "connected":
        return None
    cfg = conn.config or {}
    return BotCredentials(
        token=str(token),
        team_id=cfg.get("teamId") or team_id,
        workspace_id=conn.workspace_id,
        bot_user_id=cfg.get("botUserId"),
        bot_id=cfg.get("botId"),
        app_token=secret.get("app_token"),
    )


async def credentials_for_workspace(ws: str) -> BotCredentials | None:
    """Stored connection first (B-AC-90), else the SLACK_BOT_TOKEN development fallback."""
    async with async_session() as session:
        conn = (
            await session.execute(
                select(Connection).where(
                    Connection.workspace_id == ws, Connection.provider == "slack"
                )
            )
        ).scalar_one_or_none()
    if conn is not None:
        found = _creds(conn, None)
        if found:
            return found
    fallback = get_settings().SLACK_BOT_TOKEN
    if fallback:
        return BotCredentials(token=fallback, team_id=None, workspace_id=ws)
    return None


async def credentials_for_team(team_id: str | None) -> BotCredentials | None:
    if not team_id:
        return None
    async with async_session() as session:
        rows = (
            (
                await session.execute(
                    select(Connection)
                    .join(Workspace, Workspace.id == Connection.workspace_id)
                    .where(
                        Connection.provider == "slack",
                        or_(
                            Connection.config["teamId"].astext == team_id,
                            Workspace.slack_team_id == team_id,
                        ),
                    )
                )
            )
            .scalars()
            .all()
        )
    for conn in rows:
        found = _creds(conn, team_id)
        if found:
            return found
    return None


async def workspace_for_team(team_id: str | None) -> str | None:
    """Actron workspace id for a Slack team: workspace row, then the connection, then the lone dev workspace."""
    async with async_session() as session:
        if team_id:
            ws = (
                await session.execute(
                    select(Workspace.id).where(Workspace.slack_team_id == team_id)
                )
            ).scalar_one_or_none()
            if ws:
                return str(ws)
            ws = (
                (
                    await session.execute(
                        select(Connection.workspace_id).where(
                            Connection.provider == "slack",
                            Connection.config["teamId"].astext == team_id,
                        )
                    )
                )
                .scalars()
                .first()
            )
            if ws:
                return str(ws)
        if get_settings().SLACK_BOT_TOKEN:
            only = (await session.execute(select(Workspace.id).limit(2))).scalars().all()
            if len(only) == 1:
                return str(only[0])
    return None


# ---------------------------------------------------------------- redis


def redis_client() -> aioredis.Redis[str]:
    return aioredis.Redis.from_url(get_settings().REDIS_URL, decode_responses=True)


async def claim(key: str, ttl_seconds: int = 3600) -> bool:
    """True the first time `key` is seen (Redis SET NX). If Redis is down, claim succeeds (best effort)."""
    try:
        async with redis_client() as r:
            return bool(await r.set(f"slack:idem:{key}", "1", nx=True, ex=ttl_seconds))
    except Exception:
        log.warning("redis unavailable for slack idempotency", exc_info=True)
        return True


async def kv_set(key: str, value: str, ttl_seconds: int) -> None:
    try:
        async with redis_client() as r:
            await r.set(f"slack:{key}", value, ex=ttl_seconds)
    except Exception:
        log.warning("redis unavailable", exc_info=True)


async def kv_get(key: str) -> str | None:
    try:
        async with redis_client() as r:
            value = await r.get(f"slack:{key}")
            return None if value is None else str(value)
    except Exception:
        return None


# ---------------------------------------------------------------- flow service adapter


class FlowService(Protocol):
    """What the Slack code needs from actron.flow.service (W6). Tests inject a fake."""

    async def create_request(
        self,
        ws: str,
        *,
        text: str,
        kind_hint: str | None,
        actor: dict[str, Any],
        slack: dict[str, str],
        idempotency_key: str,
    ) -> dict[str, Any]: ...
    async def answer(
        self,
        ws: str,
        request_id: str,
        *,
        question_id: str,
        value: str,
        actor: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any]: ...
    async def approve(
        self,
        ws: str,
        request_id: str,
        *,
        kind: str,
        revision_hash: str | None,
        head_sha: str | None,
        actor: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any]: ...
    async def feedback(
        self,
        ws: str,
        request_id: str,
        *,
        text: str,
        head_sha: str | None,
        actor: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any]: ...
    async def cancel(
        self,
        ws: str,
        request_id: str,
        *,
        reason: str | None,
        actor: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any]: ...
    async def retry(
        self, ws: str, request_id: str, *, actor: dict[str, Any], idempotency_key: str
    ) -> dict[str, Any]: ...
    async def close_pr(
        self,
        ws: str,
        request_id: str,
        *,
        reason: str | None,
        actor: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any]: ...
    async def get_request_view(self, ws: str, request_id: str) -> dict[str, Any]: ...


def _plain(value: Any) -> Any:
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        try:
            return dump(by_alias=True, mode="json")
        except TypeError:
            return dump()
    return value


class ServiceAdapter:
    """Calls actron.flow.service lazily and translates the Slack-side arguments into W6's signatures.

    W6 takes an `Actor` dataclass and a `SlackRef`, names the feedback text `text_` and passes the ticket
    hash or head SHA as `target`. Only keyword arguments a function accepts are passed, so small changes
    on either side do not break the bot. Service errors carry a `code` and become refused results."""

    def _module(self) -> Any:
        import importlib

        return importlib.import_module("actron.flow.service")

    @staticmethod
    def _typed(mod: Any, kwargs: dict[str, Any]) -> dict[str, Any]:
        out = dict(kwargs)
        actor = out.get("actor")
        actor_cls = getattr(mod, "Actor", None)
        if isinstance(actor, dict) and actor_cls is not None:
            known = {f.name for f in dataclasses.fields(actor_cls)}
            raw = {
                "user_id": actor.get("userId"),
                "slack_user_id": actor.get("slackUserId"),
                "surface": actor.get("surface", "slack"),
                "name": actor.get("name"),
                "team_id": actor.get("teamId"),
            }
            out["actor"] = actor_cls(**{k: v for k, v in raw.items() if k in known})
        slack = out.get("slack")
        ref_cls = getattr(mod, "SlackRef", None)
        if isinstance(slack, dict) and ref_cls is not None:
            out["slack"] = ref_cls(
                channel=slack["channel"],
                thread_ts=slack["threadTs"],
                permalink=slack.get("permalink"),
            )
        if "text" in out:
            out["text_"] = out["text"]
        if "revision_hash" in out or "head_sha" in out:
            out["target"] = out.get("revision_hash") or out.get("head_sha")
        out.setdefault("source", "slack")
        return out

    async def _call(self, name: str, ws: str, *args: Any, **kwargs: Any) -> Any:
        mod = self._module()
        fn: Callable[..., Any] = getattr(mod, name)
        sig = inspect.signature(fn)
        typed = self._typed(mod, kwargs)
        accepts_any = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
        use = typed if accepts_any else {k: v for k, v in typed.items() if k in sig.parameters}
        try:
            result = fn(ws, *args, **use)
            if inspect.isawaitable(result):
                result = await result
        except Exception as exc:
            code = getattr(exc, "code", None)
            reason = code if isinstance(code, str) else _REFUSAL_ERRORS.get(type(exc).__name__)
            if name == "get_request_view" or reason is None:
                raise
            return {"status": "refused", "reason": reason, "state": None}
        return _plain(result)

    async def create_request(self, ws: str, **kw: Any) -> dict[str, Any]:
        out = await self._call("create_request", ws, **kw)
        return dict(out.get("request", out)) if isinstance(out, dict) else {}

    async def answer(self, ws: str, request_id: str, **kw: Any) -> dict[str, Any]:
        return _result(await self._call("answer", ws, request_id, **kw))

    async def approve(self, ws: str, request_id: str, **kw: Any) -> dict[str, Any]:
        return _result(await self._call("approve", ws, request_id, **kw))

    async def feedback(self, ws: str, request_id: str, **kw: Any) -> dict[str, Any]:
        return _result(await self._call("feedback", ws, request_id, **kw))

    async def cancel(self, ws: str, request_id: str, **kw: Any) -> dict[str, Any]:
        return _result(await self._call("cancel", ws, request_id, **kw))

    async def retry(self, ws: str, request_id: str, **kw: Any) -> dict[str, Any]:
        return _result(await self._call("retry", ws, request_id, **kw))

    async def close_pr(self, ws: str, request_id: str, **kw: Any) -> dict[str, Any]:
        return _result(await self._call("close_pr", ws, request_id, **kw))

    async def get_request_view(self, ws: str, request_id: str) -> dict[str, Any]:
        out = await self._call("get_request_view", ws, request_id)
        return dict(out.get("request", out)) if isinstance(out, dict) else {}


_REFUSAL_ERRORS = {
    "InvalidTransition": "invalid_transition",
    "NotAnApprover": "not_an_approver",
    "StaleRevision": "stale_revision",
    "StaleHead": "stale_head",
}


def _result(out: Any) -> dict[str, Any]:
    if isinstance(out, dict):
        return dict(out.get("result", out))
    return {"status": "accepted", "reason": None}


_service: FlowService | None = None


def get_service() -> FlowService:
    return _service if _service is not None else ServiceAdapter()


def set_service(service: FlowService | None) -> None:
    """Tests inject a fake; None restores the adapter."""
    global _service
    _service = service


# ---------------------------------------------------------------- misc


def now_utc() -> datetime:
    return datetime.now(UTC)


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


Hook = Callable[..., Awaitable[None]]
