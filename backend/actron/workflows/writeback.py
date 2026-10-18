"""WritebackWorkflow (spec B, B10; PRD 9.4): record a delivered request in the graph. Child of RequestWorkflow."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from actron.activities import request as acts


@workflow.defn(name="WritebackWorkflow")
class WritebackWorkflow:
    @workflow.run
    async def run(self, inp: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = await workflow.execute_activity(
            acts.writeback, dict(inp), start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=5, initial_interval=timedelta(seconds=2)),
        )
        return result


WORKFLOWS = [WritebackWorkflow]
