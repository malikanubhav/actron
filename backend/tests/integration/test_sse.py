"""SSE replay and live updates (spec B, B1): `Last-Event-ID` replay then Redis live, no duplicates (B-AC-4)."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from actron.flow import service
from actron.flow.events import (
    emit,
    publish_workspace_event,
    request_event_stream,
    workspace_event_stream,
)
from tests.api._fixtures import FakeGateway, W6Env, gateway, w6  # noqa: F401


async def _collect(gen: Any, n: int, timeout: float = 5.0) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    async def run() -> None:
        async for msg in gen:
            out.append(msg)
            if len(out) >= n:
                return

    await asyncio.wait_for(run(), timeout)
    return out


async def test_replay_after_last_event_id_then_live(w6: W6Env, gateway: FakeGateway) -> None:  # noqa: F811
    """B-AC-4: reconnect with Last-Event-ID 5 delivers 6.. in order, no duplicates, then live events."""
    view = await service.create_request(w6.ws, text="Add an export", actor=w6.actor(), source="ui",
                                        kind_hint="feature")
    rid = view["id"]
    for i in range(7):
        await emit(w6.ws, rid, "build.step", {"text": f"step {i}"})
    gen = request_event_stream(w6.ws, rid, 5, poll_s=0.1)
    replay = await _collect(gen, 3)
    assert [int(m["id"]) for m in replay] == [6, 7, 8]
    assert all(m["event"] == "build.step" for m in replay)

    async def later() -> None:
        await asyncio.sleep(0.2)
        await emit(w6.ws, rid, "tests.result", {"passed": 3, "failed": 0, "skipped": 0, "failing": []})

    task = asyncio.create_task(later())
    live = await _collect(gen, 1)
    await task
    await gen.aclose()
    assert int(live[0]["id"]) == 9 and live[0]["event"] == "tests.result"
    env = json.loads(live[0]["data"])
    assert env["requestId"] == rid and env["seq"] == 9 and env["payload"]["passed"] == 3


async def test_full_replay_without_last_event_id(w6: W6Env, gateway: FakeGateway) -> None:  # noqa: F811
    """B1: without Last-Event-ID every event is replayed from seq 1."""
    view = await service.create_request(w6.ws, text="Add an export", actor=w6.actor(), source="ui",
                                        kind_hint="feature")
    await emit(w6.ws, view["id"], "investigation.started", {"mode": "pipeline"})
    gen = request_event_stream(w6.ws, view["id"], None, poll_s=0.1)
    got = await _collect(gen, 2)
    await gen.aclose()
    assert [m["event"] for m in got] == ["request.created", "investigation.started"]
    assert set(json.loads(got[0]["data"])) == {"id", "requestId", "seq", "type", "at", "actor", "surface", "payload"}


async def test_workspace_stream_replays_by_global_id(w6: W6Env, gateway: FakeGateway) -> None:  # noqa: F811
    """B1: the workspace stream uses events.id and replays id > Last-Event-ID (ingestion and request events)."""
    first = await publish_workspace_event(w6.ws, "ingestion.started", {"source": "code", "mode": "backfill"})
    second = await publish_workspace_event(w6.ws, "ingestion.progress", {"source": "code", "counts": {}})
    gen = workspace_event_stream(w6.ws, first.id, poll_s=0.1)
    got = await _collect(gen, 1)
    assert int(got[0]["id"]) == second.id

    async def later() -> None:
        await asyncio.sleep(0.2)
        await publish_workspace_event(w6.ws, "ingestion.finished", {"source": "code", "status": "done"})

    task = asyncio.create_task(later())
    live = await _collect(gen, 1)
    await task
    await gen.aclose()
    assert live[0]["event"] == "ingestion.finished"
    assert json.loads(live[0]["data"])["requestId"] is None
