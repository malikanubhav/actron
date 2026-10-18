"""Temporal schedule helpers for incremental sync (PRD 9.4). Overlap policy is SKIP: a slow run is never doubled."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from datetime import timedelta
from typing import Any

from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleAlreadyRunningError,
    ScheduleHandle,
    ScheduleIntervalSpec,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
    ScheduleState,
    ScheduleUpdate,
    ScheduleUpdateInput,
)

WorkflowRef = str | Callable[..., Awaitable[Any]]


def schedule_id(ws: str, source: str) -> str:
    return f"sync-{ws}-{source}"


def _schedule(
    ws: str,
    source: str,
    interval: timedelta,
    workflow: WorkflowRef,
    args: Sequence[Any],
    task_queue: str,
    paused: bool,
) -> Schedule:
    sid = schedule_id(ws, source)
    return Schedule(
        action=ScheduleActionStartWorkflow(
            workflow,
            args=list(args),
            id=f"{sid}-run",
            task_queue=task_queue,
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=interval)]),
        policy=SchedulePolicy(
            overlap=ScheduleOverlapPolicy.SKIP, catchup_window=timedelta(minutes=1)
        ),
        state=ScheduleState(paused=paused, note=f"Incremental {source} sync for {ws}"),
    )


async def ensure_schedule(
    client: Client,
    ws: str,
    source: str,
    interval: timedelta,
    workflow: WorkflowRef,
    args: Sequence[Any] = (),
    *,
    task_queue: str = "ingest",
) -> ScheduleHandle:
    """Create the schedule, or update its interval, workflow and args when it already exists.

    Calling it twice leaves one schedule. A paused schedule stays paused.
    """
    sid = schedule_id(ws, source)
    try:
        return await client.create_schedule(
            sid, _schedule(ws, source, interval, workflow, args, task_queue, paused=False)
        )
    except ScheduleAlreadyRunningError:
        handle = client.get_schedule_handle(sid)

        def update(inp: ScheduleUpdateInput) -> ScheduleUpdate:
            paused = inp.description.schedule.state.paused
            return ScheduleUpdate(
                schedule=_schedule(ws, source, interval, workflow, args, task_queue, paused=paused)
            )

        await handle.update(update)
        return handle


async def trigger_schedule(client: Client, schedule_id_: str) -> None:
    """Run the schedule's workflow now. With SKIP, nothing starts while a run is still going."""
    await client.get_schedule_handle(schedule_id_).trigger(overlap=ScheduleOverlapPolicy.SKIP)


async def pause_schedule(client: Client, schedule_id_: str, note: str = "paused") -> None:
    await client.get_schedule_handle(schedule_id_).pause(note=note)


async def unpause_schedule(client: Client, schedule_id_: str, note: str = "resumed") -> None:
    await client.get_schedule_handle(schedule_id_).unpause(note=note)


async def delete_schedule(client: Client, schedule_id_: str) -> None:
    await client.get_schedule_handle(schedule_id_).delete()
