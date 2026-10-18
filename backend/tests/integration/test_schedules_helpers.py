"""Schedule helpers against the real Temporal server: ensure (idempotent), trigger, pause, SKIP overlap."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import timedelta

import pytest
from temporalio.client import Client, ScheduleOverlapPolicy
from temporalio.worker import Worker

from actron.config import get_settings
from actron.workflows.schedules import (
    delete_schedule,
    ensure_schedule,
    pause_schedule,
    schedule_id,
    trigger_schedule,
    unpause_schedule,
)
from actron.workflows.smoke import ACTIVITIES, HOLD_RUNS, WORKFLOWS, HoldWorkflow

pytestmark = pytest.mark.integration

RUNS = HOLD_RUNS


@pytest.fixture
async def env(temporal_address: str) -> AsyncIterator[tuple[Client, str]]:
    client = await Client.connect(temporal_address, namespace=get_settings().TEMPORAL_NAMESPACE)
    queue = f"sched-{uuid.uuid4().hex[:8]}"
    RUNS.clear()
    async with Worker(client, task_queue=queue, workflows=WORKFLOWS, activities=ACTIVITIES):
        yield client, queue


async def wait_for(predicate, timeout: float = 15.0) -> None:  # type: ignore[no-untyped-def]
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.1)
    raise AssertionError("condition not reached in time")


async def test_ensure_creates_and_is_idempotent(env: tuple[Client, str]) -> None:
    client, queue = env
    ws = f"ws{uuid.uuid4().hex[:6]}"
    sid = schedule_id(ws, "github")
    try:
        await ensure_schedule(
            client, ws, "github", timedelta(hours=1), "HoldWorkflow", ["a", 0.0], task_queue=queue
        )
        await ensure_schedule(
            client, ws, "github", timedelta(hours=2), "HoldWorkflow", ["b", 0.0], task_queue=queue
        )
        desc = await client.get_schedule_handle(sid).describe()
        assert desc.schedule.spec.intervals[0].every == timedelta(hours=2)
        assert desc.schedule.policy.overlap == ScheduleOverlapPolicy.SKIP
        assert desc.schedule.action.task_queue == queue  # type: ignore[union-attr]
        matches = [s.id async for s in await client.list_schedules(query=f'ScheduleId = "{sid}"')]
        assert matches == [sid]
    finally:
        await delete_schedule(client, sid)


async def test_trigger_runs_the_workflow(env: tuple[Client, str]) -> None:
    client, queue = env
    ws = f"ws{uuid.uuid4().hex[:6]}"
    sid = schedule_id(ws, "slack")
    try:
        await ensure_schedule(
            client,
            ws,
            "slack",
            timedelta(days=1),
            HoldWorkflow.run,
            ["trig", 0.0],
            task_queue=queue,
        )
        await trigger_schedule(client, sid)
        await wait_for(lambda: "trig" in RUNS)
    finally:
        await delete_schedule(client, sid)


async def test_pause_stops_and_unpause_resumes_and_ensure_keeps_pause(
    env: tuple[Client, str],
) -> None:
    client, queue = env
    ws = f"ws{uuid.uuid4().hex[:6]}"
    sid = schedule_id(ws, "linear")
    try:
        await ensure_schedule(
            client, ws, "linear", timedelta(days=1), "HoldWorkflow", ["p", 0.0], task_queue=queue
        )
        await pause_schedule(client, sid, "maintenance")
        desc = await client.get_schedule_handle(sid).describe()
        assert desc.schedule.state.paused is True
        assert desc.schedule.state.note == "maintenance"
        await ensure_schedule(
            client, ws, "linear", timedelta(hours=6), "HoldWorkflow", ["p", 0.0], task_queue=queue
        )
        assert (await client.get_schedule_handle(sid).describe()).schedule.state.paused is True
        await unpause_schedule(client, sid)
        assert (await client.get_schedule_handle(sid).describe()).schedule.state.paused is False
    finally:
        await delete_schedule(client, sid)


async def test_overlap_is_skipped_while_a_run_is_going(env: tuple[Client, str]) -> None:
    client, queue = env
    ws = f"ws{uuid.uuid4().hex[:6]}"
    sid = schedule_id(ws, "code")
    try:
        await ensure_schedule(
            client, ws, "code", timedelta(days=1), "HoldWorkflow", ["slow", 3.0], task_queue=queue
        )
        await trigger_schedule(client, sid)
        await wait_for(lambda: RUNS.count("slow") == 1)
        await trigger_schedule(
            client, sid
        )  # first run still holds the activity: this one is skipped
        await asyncio.sleep(1.5)
        assert RUNS.count("slow") == 1
        info = (await client.get_schedule_handle(sid).describe()).info
        assert info.num_actions_skipped_overlap >= 1
    finally:
        await delete_schedule(client, sid)
