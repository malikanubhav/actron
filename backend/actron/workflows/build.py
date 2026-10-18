"""BuildWorkflow (task queue `build`): a child of RequestWorkflow (spec B, B9; PRD 9.4 and 12).

1. Daily model budget: if reached, wait for the `budget_raised` signal or the next UTC day (durable timer).
2. Queue: enter the build line; while no slot is free, emit `build.queued {buildId, position}` when the
   position changes and check again every 5 seconds.
3. `run_build` (actron.flow.build) with every step as an activity. `build_run_pi` heartbeats every 10 s and
   has a start-to-close timeout of the build timeout (plus 30 s for cleanup); cancelling the workflow cancels
   the activity, which kills and removes Pi's container.
4. Release the slot (also on failure and cancellation).

Input and result are B.C6 dicts (`BuildInput.wire()` / `BuildResult.wire()`); the query `status()` returns
`{status, queuePosition, attempts}` for the request view.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime, timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError

with workflow.unsafe.imports_passed_through():
    from actron.flow import build as b
    from actron.flow import diff_check as dc
    from actron.flow import test_runner as tr

QUEUE_POLL = timedelta(seconds=5)
SHORT = timedelta(minutes=2)
STEP = timedelta(minutes=30)
NO_RETRY = RetryPolicy(maximum_attempts=1)
RETRY = RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=2), non_retryable_error_types=["BuildStop"])


def _as_stop(err: ActivityError) -> b.BuildStop | None:
    cause = err.cause
    if isinstance(cause, ApplicationError) and cause.type == "BuildStop":
        reason = str(cause.details[0]) if cause.details else "stopped"
        return b.BuildStop(reason, cause.message)
    return None


class TemporalSteps:
    """`BuildSteps` where each step is an activity."""

    def __init__(self, wf: BuildWorkflow, inp: b.BuildInput) -> None:
        self.wf = wf
        self.inp = inp
        self.wire = inp.wire()

    async def _call(self, name: str, *args: Any, timeout: timedelta = STEP, retry: RetryPolicy = RETRY,
                    heartbeat: timedelta | None = None) -> Any:
        try:
            return await workflow.execute_activity(
                name, args=list(args), start_to_close_timeout=timeout, retry_policy=retry,
                heartbeat_timeout=heartbeat, cancellation_type=workflow.ActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
            )
        except ActivityError as err:
            stop = _as_stop(err)
            if stop is not None:
                raise stop from None
            raise

    async def prepare_checkout(self, inp: b.BuildInput) -> b.CheckoutInfo:
        return b.CheckoutInfo.model_validate(await self._call("build_prepare_checkout", self.wire))

    async def write_context(self, inp: b.BuildInput, checkout: b.CheckoutInfo) -> b.ContextInfo:
        return b.ContextInfo.model_validate(await self._call("build_write_context", self.wire, checkout.wire()))

    async def run_pi(self, inp: b.BuildInput, attempt: int) -> b.PiAttempt:
        self.wf._attempts = attempt
        value = await self._call("build_run_pi", self.wire, attempt,
                                 timeout=timedelta(seconds=inp.timeout_seconds + 30), retry=NO_RETRY,
                                 heartbeat=timedelta(seconds=30))
        return b.PiAttempt.model_validate(value)

    async def check_diff(self, inp: b.BuildInput, checkout: b.CheckoutInfo) -> dc.DiffCheck:
        return dc.DiffCheck.model_validate(await self._call("build_check_diff", self.wire, checkout.wire()))

    async def run_tests(self, inp: b.BuildInput, checkout: b.CheckoutInfo) -> tr.TestResult:
        value = await self._call("build_run_tests", self.wire, checkout.wire(), timeout=timedelta(minutes=45),
                                 retry=NO_RETRY)
        return tr.TestResult.model_validate(value)

    async def write_failures(self, inp: b.BuildInput, checkout: b.CheckoutInfo, text: str,
                             reminders: list[str]) -> None:
        await self._call("build_write_failures", self.wire, checkout.wire(), text, reminders, timeout=SHORT)

    async def commit_and_push(self, inp: b.BuildInput, checkout: b.CheckoutInfo) -> str:
        return str(await self._call("build_commit_and_push", self.wire, checkout.wire(), timeout=timedelta(minutes=10)))

    async def open_pr(self, inp: b.BuildInput, result: b.BuildResult) -> b.PrInfo:
        return b.PrInfo.model_validate(await self._call("build_open_pr", self.wire, result.wire(), timeout=SHORT))

    async def read_notes(self, inp: b.BuildInput) -> str:
        return str(await self._call("build_read_notes", self.wire, timeout=SHORT))

    async def emit(self, type: str, payload: dict[str, Any]) -> None:
        await self._call("build_emit", self.inp.ws, self.inp.request_id, type, payload, timeout=SHORT)

    def now_ms(self) -> int:
        return int(workflow.now().timestamp() * 1000)


def _next_utc_midnight(now: datetime) -> datetime:
    now = now.astimezone(UTC)
    return datetime(now.year, now.month, now.day, tzinfo=UTC) + timedelta(days=1)


@workflow.defn(name="BuildWorkflow")
class BuildWorkflow:
    def __init__(self) -> None:
        self._status = "queued"
        self._position: int | None = None
        self._attempts = 0
        self._budget_raised = False

    @workflow.signal
    async def budget_raised(self, payload: dict[str, Any]) -> None:
        self._budget_raised = True

    @workflow.query
    def status(self) -> dict[str, Any]:
        return {"status": self._status, "queuePosition": self._position, "attempts": self._attempts}

    @workflow.run
    async def run(self, input: dict[str, Any]) -> dict[str, Any]:
        inp = b.BuildInput.model_validate(input)
        steps = TemporalSteps(self, inp)
        await self._wait_for_budget(inp, steps)
        await steps._call("build_queue_enter", inp.build_id, steps.now_ms(), timeout=SHORT)
        try:
            await self._wait_for_slot(inp, steps)
            self._status = "running"
            self._position = None
            result = await b.run_build(inp, steps)
        except asyncio.CancelledError:
            self._status = "stopped"
            await asyncio.shield(steps._call("build_queue_release", inp.build_id, timeout=SHORT))
            raise
        except BaseException:
            await steps._call("build_queue_release", inp.build_id, timeout=SHORT)
            raise
        await steps._call("build_queue_release", inp.build_id, timeout=SHORT)
        self._status = result.status
        return result.wire()

    async def _wait_for_budget(self, inp: b.BuildInput, steps: TemporalSteps) -> None:
        announced = False
        while True:
            budget = await steps._call("build_check_budget", inp.ws, timeout=SHORT)
            if not budget.get("reached"):
                if announced:
                    await steps.emit("build.step", {"buildId": inp.build_id, "step": "budget.resumed",
                                                    "text": "The build continues: the model budget allows it."})
                self._status = "queued"
                return
            self._status = "waiting_budget"
            if not announced:
                announced = True
                await steps.emit("build.step", {
                    "buildId": inp.build_id, "step": "budget.wait",
                    "text": "Daily model budget reached. The build waits until the cap is raised or the next day.",
                    "detail": {"spentUsd": budget.get("spentUsd"), "capUsd": budget.get("capUsd")}})
            self._budget_raised = False
            wait = _next_utc_midnight(workflow.now()) - workflow.now()
            with contextlib.suppress(TimeoutError):
                await workflow.wait_condition(lambda: self._budget_raised, timeout=wait)

    async def _wait_for_slot(self, inp: b.BuildInput, steps: TemporalSteps) -> None:
        last: int | None = None
        while True:
            position = int(await steps._call("build_queue_try_acquire", inp.build_id, timeout=SHORT))
            if last is None or position != last:
                self._position = position
                await steps.emit("build.queued", {"buildId": inp.build_id, "position": position})
                last = position
            if position == 0:
                return
            await workflow.sleep(QUEUE_POLL)


WORKFLOWS = [BuildWorkflow]
