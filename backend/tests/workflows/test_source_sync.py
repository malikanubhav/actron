"""SourceSyncWorkflow with mocked activities in a time-skipping environment: A-AC-63..66."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

import pytest
from temporalio import activity
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from actron.connectors.common import Batch, WriteResult
from actron.workflows.source_sync import SourceSyncWorkflow

TQ = "ingest-test"


class Recorder:
    def __init__(self) -> None:
        self.cursor_saves: list[dict[str, Any]] = []
        self.writes: list[tuple[str, str | None]] = []
        self.fetch_calls: list[tuple[str, str | None]] = []
        self.progress: list[tuple[str, dict[str, Any]]] = []
        self.finished: list[dict[str, Any]] = []
        self.linking: list[list[str]] = []
        self.paused: list[str] = []
        self.fail_times = 0
        self.fail_with: BaseException | None = None
        self.pages_per_step = 3
        self.steps_seen: list[str] = []
        self.partial_on: tuple[str, int] | None = None


def build(rec: Recorder) -> list[Any]:
    @activity.defn(name="load_cursor")
    async def load_cursor(ws: str, source: str) -> dict[str, Any]:
        return {}

    @activity.defn(name="start_run")
    async def start_run(ws: str, source: str, mode: str) -> str:
        return "run-1"

    @activity.defn(name="fetch_page")
    async def fetch_page(ws: str, source: str, step: str, cursor: dict[str, Any], page_token: str | None) -> Batch:
        rec.fetch_calls.append((step, page_token))
        if rec.fail_with is not None:
            raise rec.fail_with
        if rec.fail_times > 0:
            rec.fail_times -= 1
            raise ApplicationError("rate limited", type="RetryableProviderError",
                                   next_retry_delay=timedelta(seconds=90))
        n = int(page_token or 1)
        b = Batch(step=step, cursor_update={step: n}, next_page_token=str(n + 1) if n < rec.pages_per_step else None)
        if rec.partial_on == (step, n):
            b.partial_reason = "public rate limit"
        return b

    @activity.defn(name="write_batch")
    async def write_batch(ws: str, source: str, step: str, batch: Batch, run_id: str) -> WriteResult:
        rec.writes.append((step, str(batch.cursor_update.get(step))))
        return WriteResult(counts={"Thing": 2}, changed_ids=[f"x:{step}:{batch.cursor_update[step]}"])

    @activity.defn(name="save_cursor")
    async def save_cursor(ws: str, source: str, cursor: dict[str, Any]) -> None:
        rec.cursor_saves.append(dict(cursor))

    @activity.defn(name="publish_progress")
    async def publish_progress(ws: str, run_id: str, source: str, kind: str, payload: dict[str, Any]) -> None:
        rec.progress.append((kind, payload))

    @activity.defn(name="finish_run")
    async def finish_run(ws: str, source: str, run_id: str, status: str, reason: str | None, counts: dict[str, int],
                         errors: list[dict[str, Any]], duration_ms: int, auth_failed: bool = False) -> None:
        rec.finished.append({"status": status, "reason": reason, "counts": counts, "errors": errors,
                             "auth_failed": auth_failed})

    @activity.defn(name="pause_schedule")
    async def pause_schedule(ws: str, source: str, reason: str) -> None:
        rec.paused.append(reason)

    @activity.defn(name="start_linking")
    async def start_linking(ws: str, source: str, run_id: str, changed_ids: list[str]) -> int:
        rec.linking.append(changed_ids)
        return len(changed_ids)

    @activity.defn(name="run_followup")
    async def run_followup(ws: str, source: str) -> bool:
        return False

    return [load_cursor, start_run, fetch_page, write_batch, save_cursor, publish_progress, finish_run, pause_schedule,
            start_linking, run_followup]


@pytest.fixture
async def env() -> AsyncIterator[WorkflowEnvironment]:
    async with await WorkflowEnvironment.start_time_skipping() as e:
        yield e


async def run(env: WorkflowEnvironment, rec: Recorder, source: str = "linear", mode: str = "backfill",
              resume: dict[str, Any] | None = None) -> dict[str, Any]:
    async with Worker(env.client, task_queue=TQ, workflows=[SourceSyncWorkflow], activities=build(rec)):
        result: dict[str, Any] = await env.client.execute_workflow(
            SourceSyncWorkflow.run, args=[f"ws{uuid.uuid4().hex[:4]}", source, mode, resume], id=f"t-{uuid.uuid4().hex}",
            task_queue=TQ, execution_timeout=timedelta(hours=12))
    return result


async def test_a_ac_63_three_pages_cursor_saved_each_page_done_and_linking_started(env: WorkflowEnvironment) -> None:
    """A-AC-63"""
    rec = Recorder()
    out = await run(env, rec, source="slack_export")  # five steps, three pages each
    assert out["status"] == "done" and out["pages"] == 15
    assert len(rec.cursor_saves) == 15  # saved after every page
    assert rec.cursor_saves[-1] == {"workspace": 3, "users": 3, "channels": 3, "history": 3, "events": 3}
    assert rec.finished[0]["status"] == "done" and rec.finished[0]["counts"] == {"Thing": 30}
    assert len(rec.linking) == 1 and len(rec.linking[0]) == 15 and "x:history:3" in rec.linking[0]
    kinds = [k for k, _ in rec.progress]
    assert kinds[0] == "started" and kinds.count("progress") == 15  # A-AC-69 shape: one per page, with counts
    assert rec.progress[-1][1]["counts"] == {"Thing": 30} and "perMinute" in rec.progress[-1][1]


async def test_a_ac_64_retryable_failures_then_success_writes_each_page_once(env: WorkflowEnvironment) -> None:
    """A-AC-64, and next_retry_delay is honoured: two failures at 90 s each take at least 180 s."""
    rec = Recorder()
    rec.fail_times = 2
    rec.pages_per_step = 1
    start = await env.get_current_time()
    out = await run(env, rec, source="linear")
    elapsed = (await env.get_current_time()) - start
    assert out["status"] == "done"
    assert len(rec.writes) == len(set(rec.writes)) == 6  # one write per page: six steps, one page each
    assert elapsed >= timedelta(seconds=180)


async def test_a_ac_65_auth_error_fails_the_run_with_reason_and_pauses_the_schedule(env: WorkflowEnvironment) -> None:
    """A-AC-65"""
    rec = Recorder()
    rec.fail_with = ApplicationError("Linear refused the API key", type="AuthError", non_retryable=True)
    out = await run(env, rec, mode="incremental")
    assert out["status"] == "failed" and "AuthError" in out["reason"]
    assert len(rec.fetch_calls) == 1  # not retried
    assert rec.finished[0]["auth_failed"] is True and rec.finished[0]["status"] == "failed"
    assert rec.paused and "refused" in rec.paused[0]
    assert rec.linking == []


async def test_validation_error_fails_without_pausing(env: WorkflowEnvironment) -> None:
    rec = Recorder()
    rec.fail_with = ApplicationError("bad config", type="ValidationError", non_retryable=True)
    out = await run(env, rec)
    assert out["status"] == "failed" and not rec.paused and len(rec.fetch_calls) == 1


async def test_partial_reason_makes_the_run_partial(env: WorkflowEnvironment) -> None:
    rec = Recorder()
    rec.partial_on = ("pulls", 2)
    out = await run(env, rec, source="github", mode="incremental")
    assert out["status"] == "partial" and out["reason"] == "public rate limit"
    assert rec.finished[0]["status"] == "partial"


async def test_a_ac_66_continue_as_new_resumes_at_the_right_step_and_page(env: WorkflowEnvironment,
                                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    """A-AC-66: with a low page threshold the run continues as new and loses nothing."""
    import actron.workflows.source_sync as mod

    monkeypatch.setattr(mod, "PAGES_PER_RUN", 4)
    rec = Recorder()
    out = await run(env, rec, source="slack_export")
    assert out["status"] == "done" and out["pages"] == 15
    assert len(rec.finished) == 1  # one logical run across several workflow runs
    fetched = [c for c in rec.fetch_calls]
    expected = [(s, None if n == 1 else str(n)) for s in ["workspace", "users", "channels", "history", "events"]
                for n in (1, 2, 3)]
    assert fetched == expected  # no page skipped or repeated across the continue-as-new boundaries
    assert len(rec.linking[0]) == 15
    assert rec.cursor_saves[-1]["events"] == 3


async def test_resume_argument_starts_at_the_given_step_and_token(env: WorkflowEnvironment) -> None:
    rec = Recorder()
    resume = {"run_id": "run-9", "cursor": {"users": 3}, "counts": {"Thing": 4}, "errors": [], "partial": [],
              "step_index": 3, "page_token": "2", "started": "2026-01-01T00:00:00+00:00", "total_pages": 5}
    out = await run(env, rec, source="slack_export", resume=resume)
    assert rec.fetch_calls[0] == ("history", "2") and out["run_id"] == "run-9"
    assert out["counts"]["Thing"] == 4 + 5 * 2  # history pages 2 and 3, events pages 1 to 3
