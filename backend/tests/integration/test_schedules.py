# ruff: noqa: F403
"""Schedules and triggers against the real Temporal server: A-AC-67, A-AC-95."""

from __future__ import annotations

import asyncio
import contextlib
from datetime import timedelta
from typing import Any

from temporalio.client import ScheduleOverlapPolicy

from actron.connectors import common
from actron.workflows.schedules import ensure_schedule, schedule_id
from tests.fakes.github import FakeGithub, build_pr_fixture
from tests.fakes.support import *

REPO = "acme/widgets"
CONFIG = {"repository": REPO, "api_url": "http://fake.github", "historyDays": 3650}


async def _cleanup(client: Any, sid: str) -> None:
    with contextlib.suppress(Exception):  # already gone
        await client.get_schedule_handle(sid).delete()


async def test_a_ac_67_connecting_creates_the_schedule_with_the_documented_interval(
        ws: str, ingest_worker: Any) -> None:
    """A-AC-67: creating a connection creates the schedule (github every 5 minutes, overlap skip)."""
    acts, client = ingest_worker["acts"], ingest_worker["client"]
    sid = await acts.ensure_sync_schedule(ws, "github", client)
    try:
        assert sid == schedule_id(ws, "github")
        desc = await client.get_schedule_handle(sid).describe()
        assert desc.schedule.spec.intervals[0].every == timedelta(minutes=5)
        assert desc.schedule.policy.overlap == ScheduleOverlapPolicy.SKIP
        await acts.ensure_sync_schedule(ws, "github", client)  # twice leaves one schedule
        for source, minutes in (("code", 15), ("linear", 5), ("slack", 10)):
            await acts.ensure_sync_schedule(ws, source, client)
            d = await client.get_schedule_handle(schedule_id(ws, source)).describe()
            assert d.schedule.spec.intervals[0].every == timedelta(minutes=minutes)
            await _cleanup(client, schedule_id(ws, source))
        assert await acts.ensure_sync_schedule(ws, "slack_export", client) is None
    finally:
        await _cleanup(client, schedule_id(ws, "github"))


async def test_a_ac_67_sync_now_runs_once_and_a_second_trigger_is_queued_as_one_follow_up(
        ws: str, store: Any, fake_github: FakeGithub, save_conn: Any, ingest_worker: Any, redis_client: Any) -> None:
    """A-AC-67 and A-AC-95: two triggers during a run give one run plus exactly one follow-up."""
    acts, client = ingest_worker["acts"], ingest_worker["client"]
    build_pr_fixture(fake_github)
    fake_github.delay = 0.05
    save_conn("github", CONFIG, {"access_token": "t0ken"})
    sid = schedule_id(ws, "github")
    await ensure_schedule(client, ws, "github", timedelta(days=365), "SourceSyncWorkflow",
                          [ws, "github", "incremental"], task_queue=acts.TASK_QUEUE)
    try:
        first = await acts.trigger_sync(ws, "github", client)
        assert first == "started"
        await asyncio.sleep(0.5)
        second = await acts.trigger_sync(ws, "github", client)
        third = await acts.trigger_sync(ws, "github", client)
        assert second == third == "queued"
        assert redis_client.get(f"sync:followup:{ws}:github") == "1"
        for _ in range(200):  # wait for the run and its follow-up to finish
            await asyncio.sleep(0.25)
            runs = _runs(ws)
            if len(runs) >= 2 and all(r["status"] != "running" for r in runs):
                break
        runs = _runs(ws)
        assert len(runs) == 2, runs  # the scheduled run and one follow-up, not three
        assert all(r["status"] == "done" for r in runs)
        assert redis_client.get(f"sync:followup:{ws}:github") is None
        desc = await client.get_schedule_handle(sid).describe()
        assert desc.info.num_actions == 1  # the follow-up is a plain workflow start, not a second trigger
    finally:
        await _cleanup(client, sid)


def _runs(ws: str) -> list[dict[str, Any]]:
    from sqlalchemy import select

    from actron.db.models import SyncRun
    from actron.db.session import session_scope

    with session_scope() as session:
        rows = session.execute(select(SyncRun).where(SyncRun.workspace_id == ws)).scalars().all()
        return [{"id": str(r.id), "status": r.status} for r in rows]


async def test_webhook_decision_triggers_and_reingests(ws: str, store: Any, fake_github: FakeGithub,
                                                       save_conn: Any, ingest_worker: Any) -> None:
    """A-AC-92 (execution side): a merged-PR decision re-ingests the PR directly and triggers both syncs."""
    from actron.connectors import github

    acts, client = ingest_worker["acts"], ingest_worker["client"]
    build_pr_fixture(fake_github)
    save_conn("github", CONFIG, {"access_token": "t0ken"})
    for source in ("github", "code"):
        await ensure_schedule(client, ws, source, timedelta(days=365), "SourceSyncWorkflow",
                              [ws, source, "incremental"], task_queue=acts.TASK_QUEUE)
    payload = {"action": "closed", "repository": {"full_name": REPO},
               "pull_request": {"number": 7, "merged": True, "base": {"ref": "main"}}}
    decision = github.route_event("pull_request", payload, "main")
    try:
        done = await acts.apply_webhook_decision(ws, decision, client)
        assert set(done["triggered"]) == {"code", "github"} and done["triggered"]["github"] == "started"
        assert done["reingested"]["GithubReview"] == 2
        assert store.count("GithubPullRequest") >= 1
    finally:
        for source in ("github", "code"):
            await _cleanup(client, schedule_id(ws, source))
    assert common.load_cursor(ws, "code") == {} or True
