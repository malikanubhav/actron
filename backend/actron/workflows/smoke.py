"""Smoke workflow and activity: proves Temporal wiring (client, worker, task queue, activity call)."""

from __future__ import annotations

from datetime import timedelta

from temporalio import activity, workflow


@activity.defn(name="smoke_echo")
async def smoke_echo(name: str) -> str:
    return f"hello {name}"


@workflow.defn(name="SmokeWorkflow")
class SmokeWorkflow:
    @workflow.run
    async def run(self, name: str) -> str:
        greeting = await workflow.execute_activity(
            smoke_echo, name, start_to_close_timeout=timedelta(seconds=10)
        )
        # workflow.now() is the deterministic clock; it replays to the same value.
        return f"{greeting} @ {workflow.now().year >= 2024}"


# A workflow that holds for a while: lets schedule tests prove the SKIP overlap policy.
HOLD_RUNS: list[str] = []


@activity.defn(name="smoke_hold")
async def smoke_hold(tag: str, seconds: float) -> str:
    import asyncio

    HOLD_RUNS.append(tag)
    await asyncio.sleep(seconds)
    return tag


@workflow.defn(name="HoldWorkflow")
class HoldWorkflow:
    @workflow.run
    async def run(self, tag: str, seconds: float) -> str:
        return await workflow.execute_activity(
            smoke_hold, args=[tag, seconds], start_to_close_timeout=timedelta(seconds=60)
        )


ACTIVITIES = [smoke_echo, smoke_hold]
WORKFLOWS = [SmokeWorkflow, HoldWorkflow]
