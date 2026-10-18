"""Stand-in for W4's LinkingWorkflow in source-sync tests: returns how many ids it was given."""

from temporalio import workflow


@workflow.defn(name="LinkingWorkflow")
class FakeLinking:
    @workflow.run
    async def run(self, ws: str, changed_ids: list[str]) -> int:
        return len(changed_ids)
