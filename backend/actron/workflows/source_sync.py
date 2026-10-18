"""SourceSyncWorkflow (spec A, A11): page through a source, write, save the cursor, report progress.

Deterministic: all I/O is in activities (`actron.activities.ingest`). After PAGES_PER_RUN pages the
workflow continues as new with `resume` (run id, cursor, totals, step and page token).
Authorisation and validation failures end the run `failed` and pause the schedule; other failures
that exhaust the retries end it `failed` too, leaving the schedule on.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError

with workflow.unsafe.imports_passed_through():
    from actron.activities import ingest as acts
    from actron.connectors.common import add_counts, merge_cursor
    from actron.connectors.steps import SOURCE_STEPS

PAGES_PER_RUN = 200
RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=5),
    maximum_attempts=8,
    non_retryable_error_types=["AuthError", "ValidationError", "OntologyViolation"],
)
FETCH_TIMEOUT = timedelta(minutes=10)
FAST_TIMEOUT = timedelta(minutes=2)
MAX_ERRORS = 200


def _cause_type(exc: BaseException) -> str:
    cause = exc.cause if isinstance(exc, ActivityError) else exc
    return cause.type or "" if isinstance(cause, ApplicationError) else type(cause).__name__


def _cause_message(exc: BaseException) -> str:
    cause = exc.cause if isinstance(exc, ActivityError) else exc
    return str(cause.message) if isinstance(cause, ApplicationError) else str(cause)


@workflow.defn(name="SourceSyncWorkflow")
class SourceSyncWorkflow:
    def __init__(self) -> None:
        self.state: dict[str, Any] = {}

    @workflow.query
    def progress(self) -> dict[str, Any]:
        return self.state

    @workflow.run
    async def run(self, ws: str, source: str, mode: str, resume: dict[str, Any] | None = None) -> dict[str, Any]:
        steps = SOURCE_STEPS[source]
        started = workflow.now()
        if resume:
            cursor: dict[str, Any] = resume["cursor"]
            run_id: str = resume["run_id"]
            counts: dict[str, int] = resume["counts"]
            errors: list[dict[str, Any]] = resume["errors"]
            partial: list[str] = resume["partial"]
            start_step, token = int(resume["step_index"]), resume.get("page_token")
            started_iso = resume["started"]
            total_pages = int(resume.get("total_pages", 0))
        else:
            cursor = await workflow.execute_activity(acts.load_cursor, args=[ws, source],
                                                     start_to_close_timeout=FAST_TIMEOUT, retry_policy=RETRY)
            run_id = await workflow.execute_activity(acts.start_run, args=[ws, source, mode],
                                                     start_to_close_timeout=FAST_TIMEOUT, retry_policy=RETRY)
            counts, errors, partial = {}, [], []
            start_step, token, total_pages = 0, None, 0
            started_iso = started.isoformat()
            await workflow.execute_activity(
                acts.publish_progress, args=[ws, run_id, source, "started", {"mode": mode}],
                start_to_close_timeout=FAST_TIMEOUT, retry_policy=RETRY)
        changed: list[str] = []
        pages = 0
        failure: tuple[str, str] | None = None
        try:
            for si in range(start_step, len(steps)):
                step = steps[si]
                page_token = token if si == start_step else None
                while True:
                    batch = await workflow.execute_activity(
                        acts.fetch_page, args=[ws, source, step, cursor, page_token],
                        start_to_close_timeout=FETCH_TIMEOUT, retry_policy=RETRY)
                    written = await workflow.execute_activity(
                        acts.write_batch, args=[ws, source, step, batch, run_id],
                        start_to_close_timeout=FETCH_TIMEOUT, retry_policy=RETRY)
                    cursor = merge_cursor(cursor, batch.cursor_update)
                    await workflow.execute_activity(acts.save_cursor, args=[ws, source, cursor],
                                                    start_to_close_timeout=FAST_TIMEOUT, retry_policy=RETRY)
                    counts = add_counts(counts, written.counts)
                    for e in batch.errors + written.errors:
                        if len(errors) < MAX_ERRORS:
                            errors.append(e)
                    if batch.partial_reason and batch.partial_reason not in partial:
                        partial.append(batch.partial_reason)
                    changed.extend(i for i in written.changed_ids if i not in changed)
                    pages += 1
                    total_pages += 1
                    minutes = max((workflow.now() - started).total_seconds() / 60.0, 1e-6)
                    self.state = {"run_id": run_id, "step": step, "pages": total_pages, "counts": counts}
                    await workflow.execute_activity(
                        acts.publish_progress,
                        args=[ws, run_id, source, "progress",
                              {"counts": counts, "perMinute": round(sum(counts.values()) / minutes, 1), "phase": step}],
                        start_to_close_timeout=FAST_TIMEOUT, retry_policy=RETRY)
                    page_token = batch.next_page_token
                    more = page_token is not None or si + 1 < len(steps)
                    if pages >= PAGES_PER_RUN and more:
                        workflow.continue_as_new(args=[ws, source, mode, {
                            "run_id": run_id, "cursor": cursor, "counts": counts, "errors": errors,
                            "partial": partial, "step_index": si if page_token is not None else si + 1,
                            "page_token": page_token, "started": started_iso, "total_pages": total_pages}])
                    if page_token is None:
                        break
        except ActivityError as exc:
            failure = (_cause_type(exc), _cause_message(exc))
        status = "failed" if failure else ("partial" if partial else "done")
        reason = "; ".join(partial)[:300] if partial else None
        auth_failed = bool(failure and failure[0] == "AuthError")
        if failure:
            reason = f"{failure[0]}: {failure[1]}"[:300]
            errors.append({"action": "run", "error": failure[1], "url": None, "at": workflow.now().isoformat()})
        duration_ms = int((workflow.now() - datetime.fromisoformat(started_iso)).total_seconds() * 1000)
        if auth_failed:
            await workflow.execute_activity(acts.pause_schedule, args=[ws, source, reason or "authorisation failed"],
                                            start_to_close_timeout=FAST_TIMEOUT, retry_policy=RETRY)
        await workflow.execute_activity(
            acts.finish_run, args=[ws, source, run_id, status, reason, counts, errors, duration_ms, auth_failed],
            start_to_close_timeout=FAST_TIMEOUT, retry_policy=RETRY)
        linked = 0
        if status != "failed" and (changed or mode == "backfill"):
            linked = await workflow.execute_activity(
                acts.start_linking, args=[ws, source, run_id, changed],
                start_to_close_timeout=FAST_TIMEOUT, retry_policy=RETRY)
        await workflow.execute_activity(acts.run_followup, args=[ws, source],
                                        start_to_close_timeout=FAST_TIMEOUT, retry_policy=RETRY)
        return {"run_id": run_id, "status": status, "reason": reason, "counts": counts,
                "pages": total_pages, "linked": linked}
