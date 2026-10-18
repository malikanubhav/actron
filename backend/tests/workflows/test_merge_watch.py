"""Merge watch without webhooks (spec A, A11): poll the PR every 2 minutes, trigger syncs on merge (A-AC-94)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import timedelta

import pytest_asyncio
from temporalio.testing import WorkflowEnvironment

from tests.api._wf_harness import Fakes, Run, run_workflow


@pytest_asyncio.fixture
async def tenv() -> AsyncIterator[WorkflowEnvironment]:
    env = await WorkflowEnvironment.start_time_skipping()
    try:
        yield env
    finally:
        await env.shutdown()


async def _pr_ready(run: Run) -> None:
    await run.wait_state("Awaiting approval")
    await run.signal("approve_ticket", {"revisionHash": "hash1"})
    await run.wait_state("PR ready for review")


async def test_merge_detected_within_one_interval(tenv: WorkflowEnvironment) -> None:
    """A-AC-94: a merged PR is detected within one polling interval and triggers the code and GitHub syncs."""
    fakes = Fakes(script={"check_pr": [{"state": "open"}, {"state": "merged"}]})

    async def body(run: Run) -> None:
        await _pr_ready(run)
        assert not fakes.called("check_pr")
        await tenv.sleep(timedelta(minutes=2, seconds=5))
        await run.wait_for(lambda: len(fakes.called("check_pr")) == 1)
        assert not fakes.called("trigger_syncs")
        await tenv.sleep(timedelta(minutes=2, seconds=5))
        await run.wait_for(lambda: len(fakes.called("trigger_syncs")) == 1)
        await tenv.sleep(timedelta(minutes=10))
        assert len(fakes.called("check_pr")) == 2

    await run_workflow(tenv.client, fakes, body)


async def test_closed_pr_stops_watch_without_sync(tenv: WorkflowEnvironment) -> None:
    """A-AC-94: a closed (not merged) PR stops the watch and triggers nothing."""
    fakes = Fakes(script={"check_pr": {"state": "closed"}})

    async def body(run: Run) -> None:
        await _pr_ready(run)
        await tenv.sleep(timedelta(minutes=2, seconds=5))
        await run.wait_for(lambda: len(fakes.called("check_pr")) == 1)
        await tenv.sleep(timedelta(minutes=10))
        assert len(fakes.called("check_pr")) == 1
        assert not fakes.called("trigger_syncs")

    await run_workflow(tenv.client, fakes, body)
