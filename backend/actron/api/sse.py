"""Server-sent events (spec B, B1): per request (`id: seq`) and per workspace (`id: events.id`), heartbeat 15 s."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, Request
from sse_starlette.sse import EventSourceResponse

from actron.api.deps import ApiError, Ctx, current
from actron.flow.events import request_event_stream, workspace_event_stream
from actron.flow.service import request_exists

router = APIRouter(tags=["stream"])
HEARTBEAT_S = 15


def _last_id(request: Request) -> int | None:
    raw = request.headers.get("Last-Event-ID") or request.query_params.get("lastEventId")
    try:
        return int(raw) if raw else None
    except ValueError:
        return None


async def _guard(request: Request, gen: AsyncIterator[dict[str, Any]]) -> AsyncIterator[dict[str, Any]]:
    try:
        # A comment line at once, so proxies flush the response headers and the browser sees the stream open
        # before the first event or heartbeat.
        yield {"comment": "connected"}
        async for msg in gen:
            if await request.is_disconnected():
                return
            yield msg
    finally:
        aclose = getattr(gen, "aclose", None)
        if aclose is not None:
            await aclose()


@router.get("/api/requests/{request_id}/events", response_class=EventSourceResponse)
async def request_events(request_id: str, request: Request, ctx: Ctx = Depends(current)) -> EventSourceResponse:
    if not await asyncio.to_thread(request_exists, ctx.ws, request_id):
        raise ApiError(404, "not_found", f"Request {request_id} was not found.")

    async def stop() -> bool:
        return await request.is_disconnected()

    gen = request_event_stream(ctx.ws, request_id, _last_id(request), stop=stop)
    return EventSourceResponse(_guard(request, gen), ping=HEARTBEAT_S)


@router.get("/api/stream", response_class=EventSourceResponse)
async def workspace_stream(request: Request, ctx: Ctx = Depends(current)) -> EventSourceResponse:
    async def stop() -> bool:
        return await request.is_disconnected()

    gen = workspace_event_stream(ctx.ws, _last_id(request), stop=stop)
    return EventSourceResponse(_guard(request, gen), ping=HEARTBEAT_S)
