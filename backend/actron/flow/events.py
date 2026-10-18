"""Event journal and live updates (spec B, B1, B.C2).

`emit` stores one event in PostgreSQL with the next gap-free `seq` for its request, creates notifications for the
four interrupting kinds (B13), publishes on Redis (`req:<id>` and `ws:<ws>:requests`) and hands the envelope to
the Slack sender (best effort). SSE helpers replay from PostgreSQL and then follow Redis.
"""

from __future__ import annotations

import asyncio
import json
import weakref
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

import redis.asyncio as aioredis
from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from actron.config import get_settings
from actron.db import models as m
from actron.db.events_seq import next_seq
from actron.db.session import session_scope
from actron.logging import get_logger

log = get_logger(__name__)

ACTORS = ("actron", "person", "slack")
SURFACES = ("slack", "ui", "system")


class EventSink(Protocol):
    async def __call__(self, type: str, payload: dict[str, Any], *, actor: str = "actron",
                       surface: str = "system") -> None: ...


def req_channel(request_id: str) -> str:
    return f"req:{request_id}"


def ws_requests_channel(ws: str) -> str:
    return f"ws:{ws}:requests"


def ws_ingestion_channel(ws: str) -> str:
    return f"ws:{ws}:ingestion"


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass
class Event:
    id: int
    workspace_id: str
    request_id: str | None
    seq: int | None
    type: str
    at: datetime
    actor: str
    surface: str
    payload: dict[str, Any] = field(default_factory=dict)
    signal_status: str | None = None

    def envelope(self) -> dict[str, Any]:
        """B.C2 envelope, the same shape for PostgreSQL readers, SSE and Slack."""
        return {
            "id": self.id,
            "requestId": self.request_id,
            "seq": self.seq,
            "type": self.type,
            "at": iso(self.at),
            "actor": self.actor,
            "surface": self.surface,
            "payload": self.payload,
        }

    @classmethod
    def from_row(cls, row: m.Event) -> Event:
        return cls(
            id=row.id, workspace_id=row.workspace_id, request_id=row.request_id, seq=row.seq, type=row.type,
            at=row.at, actor=row.actor, surface=row.surface, payload=dict(row.payload or {}),
            signal_status=row.signal_status,
        )


# Redis: one asyncio client per event loop (tests and the worker run several loops over time).
# Typed as Any: the installed redis stubs predate redis 8's asyncio API (`aclose`).
_REDIS: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, Any] = weakref.WeakKeyDictionary()


def redis_client() -> Any:
    loop = asyncio.get_running_loop()
    client = _REDIS.get(loop)
    if client is None:
        client = aioredis.Redis.from_url(
            get_settings().REDIS_URL, decode_responses=True, socket_connect_timeout=3, socket_timeout=10,
        )
        _REDIS[loop] = client
    return client


def reset_redis_clients() -> None:
    """Tests only: forget cached clients after changing REDIS_URL."""
    _REDIS.clear()


# Storage
def insert_event(
    session: Session,
    ws: str,
    request_id: str | None,
    type: str,
    payload: dict[str, Any],
    *,
    actor: str = "actron",
    surface: str = "system",
    signal_status: str | None = None,
    idempotency_key: str | None = None,
) -> Event:
    """Insert one event in the caller's transaction (seq taken under the request row lock)."""
    if actor not in ACTORS:
        actor = "person"
    if surface not in SURFACES:
        surface = "system"
    seq = next_seq(session, request_id) if request_id else None
    row = m.Event(
        workspace_id=ws, request_id=request_id, seq=seq, type=type, at=datetime.now(UTC), actor=actor,
        surface=surface, payload=_jsonable(payload), signal_status=signal_status, idempotency_key=idempotency_key,
    )
    session.add(row)
    session.flush()
    return Event.from_row(row)


def _jsonable(payload: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = json.loads(json.dumps(payload, default=str))
    return out


def _store(
    ws: str, request_id: str | None, type: str, payload: dict[str, Any], actor: str, surface: str
) -> list[Event]:
    from actron.flow import notifications

    with session_scope() as session:
        ev = insert_event(session, ws, request_id, type, payload, actor=actor, surface=surface)
        extra = notifications.create_for_event(session, ev) if request_id else []
    return [ev, *extra]


async def publish(ev: Event) -> None:
    """Publish an already stored event. Failures are logged: SSE replay from PostgreSQL recovers them."""
    data = json.dumps(ev.envelope())
    try:
        client = redis_client()
        if ev.request_id:
            await client.publish(req_channel(ev.request_id), data)
            await client.publish(ws_requests_channel(ev.workspace_id), data)
        else:
            await client.publish(ws_ingestion_channel(ev.workspace_id), data)
    except Exception as exc:
        log.warning("event publish failed", extra={"event_type": ev.type, "error": type(exc).__name__})


async def notify_slack(ws: str, ev: Event) -> None:
    """Hand the envelope to W9's Slack sender. Never raises; a missing module is a no-op."""
    if ev.request_id is None:
        return
    try:
        from actron.integrations import slack_sender
    except Exception:
        return
    try:
        await slack_sender.on_event(ws, ev.envelope())
    except Exception as exc:
        log.warning("slack sender failed", extra={"event_type": ev.type, "error": type(exc).__name__})


async def emit(
    ws: str,
    request_id: str | None,
    type: str,
    payload: dict[str, Any] | None = None,
    actor: str = "actron",
    surface: str = "system",
) -> Event:
    """Store, notify, publish. Returns the stored event."""
    events = await asyncio.to_thread(_store, ws, request_id, type, dict(payload or {}), actor, surface)
    for ev in events:
        await publish(ev)
    for ev in events:
        await notify_slack(ws, ev)
    return events[0]


async def publish_workspace_event(ws: str, type: str, payload: dict[str, Any]) -> Event:
    """Workspace-level events (ingestion and linking progress, A.C6): stored with request_id null."""
    return await emit(ws, None, type, payload)


def sink_for(ws: str, request_id: str | None) -> EventSink:
    """The EventSink handed to producers (investigator, build, linking)."""

    async def sink(type: str, payload: dict[str, Any], *, actor: str = "actron", surface: str = "system") -> None:
        await emit(ws, request_id, type, payload, actor, surface)

    return sink


async def publish_stored(ws: str, event_ids: list[int]) -> None:
    """Publish events that were inserted inside a caller's own transaction."""
    evs = await asyncio.to_thread(_load_by_ids, ws, event_ids)
    for ev in evs:
        await publish(ev)
    for ev in evs:
        await notify_slack(ws, ev)


def _load_by_ids(ws: str, event_ids: list[int]) -> list[Event]:
    with session_scope() as s:
        rows = s.scalars(select(m.Event).where(m.Event.workspace_id == ws, m.Event.id.in_(event_ids))
                         .order_by(m.Event.id)).all()
        return [Event.from_row(r) for r in rows]


def mark_signal_sent(event_id: int) -> None:
    with session_scope() as s:
        s.execute(update(m.Event).where(m.Event.id == event_id).values(signal_status="sent"))


# Reads
def load_request_events(ws: str, request_id: str, after_seq: int = 0, limit: int = 5000) -> list[Event]:
    with session_scope() as s:
        rows = s.scalars(
            select(m.Event)
            .where(m.Event.workspace_id == ws, m.Event.request_id == request_id, m.Event.seq > after_seq)
            .order_by(m.Event.seq)
            .limit(limit)
        ).all()
        return [Event.from_row(r) for r in rows]


def load_workspace_events(ws: str, after_id: int = 0, limit: int = 1000) -> list[Event]:
    with session_scope() as s:
        rows = s.scalars(
            select(m.Event).where(m.Event.workspace_id == ws, m.Event.id > after_id).order_by(m.Event.id).limit(limit)
        ).all()
        return [Event.from_row(r) for r in rows]


def latest_workspace_event_id(ws: str) -> int:
    with session_scope() as s:
        val = s.execute(text("SELECT coalesce(max(id), 0) FROM events WHERE workspace_id = :ws"), {"ws": ws}).scalar()
        return int(val or 0)


# SSE
def sse_message(ev_id: int | None, ev: dict[str, Any]) -> dict[str, Any]:
    return {"id": str(ev_id) if ev_id is not None else None, "event": ev["type"], "data": json.dumps(ev)}


async def request_event_stream(
    ws: str, request_id: str, last_seq: int | None, *, poll_s: float = 1.0,
    stop: Callable[[], Awaitable[bool]] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Replay `seq > last_seq` from PostgreSQL, then follow Redis `req:<id>`; gaps are filled from PostgreSQL."""
    client = redis_client()
    pubsub = client.pubsub()
    await pubsub.subscribe(req_channel(request_id))
    last = last_seq or 0
    try:
        for ev in await asyncio.to_thread(load_request_events, ws, request_id, last):
            last = ev.seq or last
            yield sse_message(ev.seq, ev.envelope())
        while True:
            if stop is not None and await stop():
                return
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=poll_s)
            if not msg:
                continue
            env = json.loads(msg["data"])
            seq = int(env.get("seq") or 0)
            if seq <= last:
                continue
            if seq > last + 1:
                for ev in await asyncio.to_thread(load_request_events, ws, request_id, last):
                    last = ev.seq or last
                    yield sse_message(ev.seq, ev.envelope())
                continue
            last = seq
            yield sse_message(seq, env)
    finally:
        try:
            await pubsub.unsubscribe()
            await pubsub.aclose()
        except Exception:
            pass


async def workspace_event_stream(
    ws: str, last_id: int | None, *, poll_s: float = 1.0,
    stop: Callable[[], Awaitable[bool]] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Workspace stream (`GET /api/stream`): ids are the global `events.id`; replay `id > Last-Event-ID`."""
    client = redis_client()
    pubsub = client.pubsub()
    await pubsub.subscribe(ws_requests_channel(ws), ws_ingestion_channel(ws))
    # Two channels can interleave, so ids may arrive slightly out of order: dedupe by id, not by "greater than".
    seen: set[int] = set()
    if last_id is None:
        floor = await asyncio.to_thread(latest_workspace_event_id, ws)
    else:
        floor = last_id
        for ev in await asyncio.to_thread(load_workspace_events, ws, floor):
            seen.add(ev.id)
            yield sse_message(ev.id, ev.envelope())
    try:
        while True:
            if stop is not None and await stop():
                return
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=poll_s)
            if not msg:
                continue
            env = json.loads(msg["data"])
            eid = int(env.get("id") or 0)
            if eid <= floor or eid in seen:
                continue
            seen.add(eid)
            if len(seen) > 5000:
                seen = {i for i in seen if i > eid - 2000}
            yield sse_message(eid, env)
    finally:
        try:
            await pubsub.unsubscribe()
            await pubsub.aclose()
        except Exception:
            pass
