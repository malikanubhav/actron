"""Slack sender: keeps one status message per request and sends the four interrupting notifications.

`on_event(ws, envelope)` is called best effort by W6 after every request event is stored and published.
It never raises. It does nothing when Slack is not connected (spec B, B11, B13; WORKSTREAMS "Slack sender").
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from slack_sdk.errors import SlackApiError
from slack_sdk.web.async_client import AsyncWebClient
from sqlalchemy import select, update

from actron.db.models import Request, User, Workspace
from actron.db.session import async_session
from actron.integrations import slack_blocks as sb
from actron.integrations.slack_common import (
    claim,
    credentials_for_workspace,
    dumps,
    get_service,
    kv_get,
    kv_set,
    log,
    redis_client,
    web_client,
)

# Events after which the status message is rebuilt from the current request view.
# Chatty events (tool.called, tool.result, evidence.found, build.step, judgment.made) are left out.
STATUS_EVENTS = frozenset(
    {
        "request.created",
        "request.state_changed",
        "investigation.completed",
        "question.asked",
        "answer.received",
        "ticket.revised",
        "ticket.synced",
        "approval.recorded",
        "approval.refused",
        "handoff.created",
        "build.queued",
        "build.started",
        "tests.result",
        "build.repair",
        "build.failed",
        "build.passed",
        "pr.opened",
        "pr.updated",
        "review.feedback",
        "pr.approved",
        "writeback.done",
        "request.cancelled",
        "request.done",
        "answer.ready",
        "budget.reached",
    }
)

# state -> (notification kind, who gets the DM). Only these four interrupt (PRD 11.4, B13).
INTERRUPTS: dict[str, tuple[str, str]] = {
    "Needs your input": ("needs_input", "requester"),
    "Awaiting approval": ("ticket", "requester_and_approvers"),
    "Needs attention": ("attention", "requester"),
    "PR ready for review": ("pr", "requester_and_approvers"),
}

MESSAGE_GONE = {"message_not_found", "cant_update_message", "cant_edit_message"}
TTL_DAY = 86400


@dataclass
class RequestContext:
    request_id: str
    channel: str | None
    thread_ts: str | None
    status_ts: str | None
    requester_slack_id: str | None
    approvers: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- storage


async def load_context(ws: str, request_id: str) -> RequestContext | None:
    async with async_session() as session:
        row = (
            await session.execute(
                select(Request, User.slack_user_id)
                .outerjoin(User, User.id == Request.requester_user_id)
                .where(Request.id == request_id, Request.workspace_id == ws)
            )
        ).first()
        if row is None:
            return None
        req, slack_id = row
        settings = (
            await session.execute(select(Workspace.settings).where(Workspace.id == ws))
        ).scalar_one_or_none() or {}
    approvers = [str(a) for a in (settings.get("approvers") or [])]
    return RequestContext(
        request_id, req.slack_channel, req.slack_thread_ts, req.slack_status_ts, slack_id, approvers
    )


async def store_status_ts(request_id: str, ts: str) -> None:
    async with async_session() as session:
        await session.execute(
            update(Request).where(Request.id == request_id).values(slack_status_ts=ts)
        )


# ---------------------------------------------------------------- locking

_LOCKS: dict[tuple[int, str], asyncio.Lock] = {}


@contextlib.asynccontextmanager
async def _status_lock(request_id: str) -> AsyncIterator[None]:
    """One writer per request: an in-process lock plus a Redis lock for other processes."""
    key = (id(asyncio.get_running_loop()), request_id)
    local = _LOCKS.setdefault(key, asyncio.Lock())
    async with local:
        redis_lock: Any = None
        r = None
        try:
            r = redis_client()
            redis_lock = r.lock(f"slack:lock:{request_id}", timeout=30, blocking_timeout=10)
            if not await redis_lock.acquire():
                redis_lock = None
        except Exception:
            redis_lock = None
        try:
            yield
        finally:
            if redis_lock is not None:
                with contextlib.suppress(Exception):
                    await redis_lock.release()
            if r is not None:
                with contextlib.suppress(Exception):
                    await r.aclose()  # type: ignore[attr-defined]


# ---------------------------------------------------------------- posting


def _payload(msg: sb.Message) -> dict[str, Any]:
    out: dict[str, Any] = {"text": msg["text"]}
    if msg.get("blocks"):
        out["blocks"] = msg["blocks"]
    if msg.get("attachments"):
        out["attachments"] = msg["attachments"]
    return out


async def _post(
    client: AsyncWebClient, channel: str, msg: sb.Message, thread_ts: str | None = None
) -> str:
    kwargs: dict[str, Any] = {
        "channel": channel,
        **_payload(msg),
        "unfurl_links": False,
        "unfurl_media": False,
    }
    if thread_ts:
        kwargs["thread_ts"] = thread_ts
    resp = await client.chat_postMessage(**kwargs)
    return str(resp["ts"])


async def post_thread_message(ws: str, ctx: RequestContext, msg: sb.Message) -> str | None:
    """Post any message in the request's thread. Returns the ts, or None when Slack is not connected."""
    creds = await credentials_for_workspace(ws)
    if creds is None or not ctx.channel:
        return None
    return await _post(web_client(creds.token), ctx.channel, msg, ctx.thread_ts)


async def post_acknowledgement(ws: str, view: dict[str, Any]) -> str | None:
    """First message in the thread (within 3 seconds of the request). It becomes the status message:
    later events edit it in place. Does nothing if a status message already exists."""
    rid = view["id"]
    creds = await credentials_for_workspace(ws)
    ctx = await load_context(ws, rid)
    if creds is None or ctx is None or not ctx.channel:
        return None
    async with _status_lock(rid):
        ctx = await load_context(ws, rid)
        if ctx is None or not ctx.channel:
            return None
        if ctx.status_ts:
            return ctx.status_ts
        ts = await _post(
            web_client(creds.token), ctx.channel, sb.acknowledgement(view), ctx.thread_ts
        )
        await store_status_ts(rid, ts)
        return ts


async def _sync_status(
    client: AsyncWebClient, ws: str, view: dict[str, Any], envelope: dict[str, Any]
) -> None:
    rid = view["id"]
    async with _status_lock(rid):
        ctx = await load_context(ws, rid)
        if ctx is None or not ctx.channel:
            return
        payload = envelope.get("payload") or {}
        if (
            envelope.get("type") == "approval.recorded"
            and payload.get("kind") == "ticket"
            and view["state"] == "Awaiting approval"
        ):
            by = (payload.get("by") or {}).get("name")
            msg = sb.approval_confirmation(
                view, by, "ticket", str(payload.get("surface") or "slack")
            )
        elif (
            not ctx.status_ts
            and envelope.get("type") == "request.created"
            and view["state"] == "Investigating"
        ):
            msg = sb.acknowledgement(view)  # first message in the thread (PROMPT 8.9)
        else:
            msg = sb.status_message(view)
        digest = hashlib.sha256(_digest_source(msg).encode()).hexdigest()
        if ctx.status_ts and await kv_get(f"status_hash:{rid}") == digest:
            return
        if ctx.status_ts:
            try:
                await client.chat_update(channel=ctx.channel, ts=ctx.status_ts, **_payload(msg))
            except SlackApiError as exc:
                if exc.response.get("error") not in MESSAGE_GONE:
                    raise
                ctx.status_ts = None
        if not ctx.status_ts:
            ts = await _post(client, ctx.channel, msg, ctx.thread_ts)
            await store_status_ts(rid, ts)
        await kv_set(f"status_hash:{rid}", digest, 30 * TTL_DAY)


def _digest_source(msg: sb.Message) -> str:
    # the elapsed time changes every minute; leave it out so unchanged messages are not re-sent
    import re

    return re.sub(r"· \d+[smhd]( \d+[smhd])?\"", '"', dumps(msg))


# ---------------------------------------------------------------- questions and answers


async def _question_index(
    view: dict[str, Any], question_id: str
) -> tuple[dict[str, Any], int, int] | None:
    qs = view.get("questions") or []
    for i, q in enumerate(qs, start=1):
        if q["questionId"] == question_id:
            return q, i, len(qs)
    return None


async def _post_question(
    client: AsyncWebClient, ctx: RequestContext, view: dict[str, Any], qid: str
) -> None:
    found = await _question_index(view, qid)
    if not found or not ctx.channel or await kv_get(f"q:{ctx.request_id}:{qid}"):
        return
    q, i, n = found
    ts = await _post(
        client,
        ctx.channel,
        sb.question_message(view, q, i, n, ctx.requester_slack_id),
        ctx.thread_ts,
    )
    await kv_set(f"q:{ctx.request_id}:{qid}", ts, 30 * TTL_DAY)


async def _mark_answered(
    client: AsyncWebClient, ctx: RequestContext, view: dict[str, Any], qid: str
) -> None:
    found = await _question_index(view, qid)
    ts = await kv_get(f"q:{ctx.request_id}:{qid}")
    if not found or not ts or not ctx.channel or not found[0].get("answer"):
        return
    q, i, n = found
    msg = sb.question_answered_message(view, q, i, n)
    try:
        await client.chat_update(channel=ctx.channel, ts=ts, **_payload(msg))
    except SlackApiError as exc:
        if exc.response.get("error") not in MESSAGE_GONE:
            raise


# ---------------------------------------------------------------- notifications


def recipients(ctx: RequestContext, who: str) -> list[str]:
    people = [ctx.requester_slack_id] if ctx.requester_slack_id else []
    if who == "requester_and_approvers":
        people += ctx.approvers
    seen: list[str] = []
    for p in people:
        if p and p not in seen:
            seen.append(p)
    return seen


async def _dm(client: AsyncWebClient, user_id: str, msg: sb.Message) -> None:
    opened = await client.conversations_open(users=user_id)
    channel = opened["channel"]["id"]
    await _post(client, str(channel), msg)


async def _notify(
    client: AsyncWebClient, ctx: RequestContext, view: dict[str, Any], envelope: dict[str, Any]
) -> None:
    payload = envelope.get("payload") or {}
    to = payload.get("to")
    if to not in INTERRUPTS or payload.get("from") == to:
        return
    kind, who = INTERRUPTS[to]
    marker = envelope.get("id") or envelope.get("seq") or "x"
    link = (view.get("slack") or {}).get("permalink")
    for user in recipients(ctx, who):
        if await claim(f"dm:{ctx.request_id}:{kind}:{marker}:{user}", 7 * TTL_DAY):
            try:
                await _dm(client, user, sb.needs_you_dm(view, kind, thread_url=link))
            except SlackApiError:
                log.warning("slack dm failed", exc_info=True)
    if not ctx.channel or not await claim(f"thread:{ctx.request_id}:{kind}:{marker}", 7 * TTL_DAY):
        return
    msg: sb.Message | None
    if kind == "ticket":
        msg = sb.needs_you_thread(view, kind, ctx.requester_slack_id)
    elif kind == "attention":
        msg = sb.failure(view)
    elif kind == "pr" and view.get("pr"):
        msg = sb.build_finished(view)
    else:
        msg = None  # needs_input: the question messages are the thread notification
    if msg:
        await _post(client, ctx.channel, msg, ctx.thread_ts)


# ---------------------------------------------------------------- entry point


async def _on_event(ws: str, envelope: dict[str, Any]) -> None:
    rid, typ = envelope.get("requestId"), envelope.get("type")
    if not rid or not typ:
        return
    creds = await credentials_for_workspace(ws)
    if creds is None:
        return
    ctx = await load_context(ws, rid)
    if ctx is None:
        return
    interesting = typ in STATUS_EVENTS
    if not interesting:
        return
    view = await get_service().get_request_view(ws, rid)
    client = web_client(creds.token)
    if ctx.channel and ctx.thread_ts:
        await _sync_status(client, ws, view, envelope)
    payload = envelope.get("payload") or {}
    if typ == "question.asked":
        await _post_question(client, ctx, view, str(payload.get("questionId")))
    elif typ == "answer.received":
        await _mark_answered(client, ctx, view, str(payload.get("questionId")))
    elif typ == "answer.ready" and ctx.channel and view.get("answer"):
        if await claim(f"answer:{rid}:{envelope.get('id') or envelope.get('seq')}", 7 * TTL_DAY):
            await _post(client, ctx.channel, sb.answer_message(view), ctx.thread_ts)
    elif typ == "request.state_changed":
        ctx = await load_context(ws, rid) or ctx
        await _notify(client, ctx, view, envelope)


async def on_event(ws: str, envelope: dict[str, Any]) -> None:
    """Best effort: errors are logged, never raised."""
    try:
        await _on_event(ws, envelope)
    except Exception:
        log.warning("slack sender failed for %s", envelope.get("type"), exc_info=True)
