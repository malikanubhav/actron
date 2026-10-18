"""RequestWorkflow on the real Temporal server (compose): a worker restart while waiting for approval loses
nothing (B-AC-12)."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest
from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from actron.config import get_settings
from actron.workflows.request import RequestWorkflow
from tests.api._fixtures import FakeGateway, W6Env, gateway, w6  # noqa: F401
from tests.api._wf_harness import (
    CURRENT,
    FakeBuildWorkflow,
    Fakes,
    FakeWritebackWorkflow,
    Run,
    fake_build_result,
    fake_pi,
    fake_writeback,
)

pytestmark = pytest.mark.integration


async def test_worker_restart_while_waiting_for_approval(temporal_address: str) -> None:
    """B-AC-12: stop the worker while the workflow waits for approval, start a new one, signal, it continues."""
    client = await Client.connect(temporal_address, namespace=get_settings().TEMPORAL_NAMESPACE,
                                  data_converter=pydantic_data_converter)
    fakes = Fakes()
    CURRENT["fakes"] = fakes
    tag = uuid.uuid4().hex[:8]
    request_queue, build_queue = f"w6-request-{tag}", f"w6-build-{tag}"

    def workers() -> tuple[Worker, Worker]:
        from temporalio.worker.workflow_sandbox import SandboxedWorkflowRunner, SandboxRestrictions

        runner = SandboxedWorkflowRunner(restrictions=SandboxRestrictions.default.with_passthrough_modules("tests"))
        return (
            Worker(client, task_queue=request_queue, workflows=[RequestWorkflow, FakeWritebackWorkflow],
                   activities=[*fakes.activities(), fake_writeback], workflow_runner=runner),
            Worker(client, task_queue=build_queue, workflows=[FakeBuildWorkflow],
                   activities=[fake_pi, fake_build_result], workflow_runner=UnsandboxedWorkflowRunner()),
        )

    wf_id = f"request:w6-real-{tag}"
    first_req, first_build = workers()
    async with first_req, first_build:
        handle = await client.start_workflow(
            "RequestWorkflow", {"ws": "w", "requestId": f"req_{tag}", "kind": "feature", "title": "T", "text": "x",
                                "options": {"buildQueue": build_queue}},
            id=wf_id, task_queue=request_queue)
        run = Run(client, fakes, handle)
        await run.wait_state("Awaiting approval", timeout=30)
        # The query reports the state as soon as it changes, before its mirror activity has run. Stop the worker
        # only once nothing is in flight, so the workflow is idle, waiting for the approval.
        for _ in range(300):
            if not (await handle.describe()).raw_description.pending_activities:
                break
            await asyncio.sleep(0.1)
    # The worker is gone. Signals are durable on the server while nobody polls.
    await run.signal("approve_ticket", {"revisionHash": "hash1"})
    second_req, second_build = workers()
    async with second_req, second_build:
        await run.wait_state("PR ready for review", timeout=30)
        await run.signal("approve_pr", {"headSha": "head1"})
        result = await handle.result()
    assert result == {"state": "Done", "outcome": "approved"}
    assert fakes.approvals() == [("ticket", "accepted", None), ("pr", "accepted", None)]
    assert len(fakes.called("save_revision")) == 1


# Freshness gate activity (B2)
class _Graph:
    def __init__(self, sha: str | None) -> None:
        self.sha = sha


@pytest.fixture
def fresh_env(w6: W6Env, monkeypatch: pytest.MonkeyPatch, gateway: FakeGateway) -> dict[str, Any]:  # noqa: F811
    from actron.activities import request as acts

    state: dict[str, Any] = {"graph": _Graph("old"), "heads": {"main": "new"}, "fail": False}
    monkeypatch.setattr(acts, "_github_cfg", lambda ws: {"repository": "o/r", "working_branch": "main"})
    monkeypatch.setattr(acts, "_graph_repo", lambda ws: {"sha": state["graph"].sha, "branch": "main"})

    async def head(ws: str, branch: str, cfg: Any = None) -> str | None:
        if state["fail"]:
            raise acts.ExternalError("unreachable")
        value: str | None = state["heads"].get(branch)
        return value

    monkeypatch.setattr(acts, "remote_head", head)
    state["acts"] = acts
    return state


async def _request(w6: W6Env) -> str:  # noqa: F811
    from actron.flow import service

    view = await service.create_request(w6.ws, text="Add an export", actor=w6.actor(), source="ui",
                                        kind_hint="feature")
    return str(view["id"])


async def test_fresh_when_heads_match(w6: W6Env, fresh_env: dict[str, Any]) -> None:  # noqa: F811
    """B-AC-77: when the graph already has the branch head, nothing is synced."""
    fresh_env["graph"].sha = "new"
    rid = await _request(w6)
    res = await fresh_env["acts"].ensure_fresh({"ws": w6.ws, "requestId": rid})
    assert res == {"status": "fresh", "sha": "new", "targetSha": None}


async def test_refreshes_when_head_ahead(w6: W6Env, fresh_env: dict[str, Any], gateway: FakeGateway) -> None:  # noqa: F811
    """B-AC-77: a head ahead of the graph triggers code and GitHub syncs and waits until the graph has it."""
    rid = await _request(w6)

    async def advance() -> None:
        await asyncio.sleep(0.3)
        fresh_env["graph"].sha = "new"

    task = asyncio.create_task(advance())
    res = await fresh_env["acts"].ensure_fresh({"ws": w6.ws, "requestId": rid, "pollSeconds": 0.1,
                                                "timeoutSeconds": 5})
    await task
    assert res["status"] == "refreshed" and res["sha"] == "new"
    assert {s[2] for s in gateway.schedules if s[0] == "trigger"} == {"code", "github"}
    types = w6.types(rid)
    assert "memory.refreshing" in types and "memory.refreshed" in types


async def test_stale_after_timeout(w6: W6Env, fresh_env: dict[str, Any]) -> None:  # noqa: F811
    """B-AC-78: a sync that does not finish in time returns memory_stale."""
    rid = await _request(w6)
    res = await fresh_env["acts"].ensure_fresh({"ws": w6.ws, "requestId": rid, "pollSeconds": 0.05,
                                                "timeoutSeconds": 0.3})
    assert res["status"] == "stale" and res["reason"] == "memory_stale"


async def test_unreachable_records_unverified(w6: W6Env, fresh_env: dict[str, Any]) -> None:  # noqa: F811
    """B-AC-78: GitHub unreachable -> `memory.unverified`, continue with the graph's head."""
    fresh_env["fail"] = True
    rid = await _request(w6)
    res = await fresh_env["acts"].ensure_fresh({"ws": w6.ws, "requestId": rid})
    assert res["status"] == "unverified" and res["sha"] == "old"
    assert "memory.unverified" in w6.types(rid)
    from actron.flow import service

    assert (await service.get_request_view(w6.ws, rid))["lastEvent"]["type"] == "memory.unverified"


async def test_missing_target_branch(w6: W6Env, fresh_env: dict[str, Any]) -> None:  # noqa: F811
    """B-AC-81: a deleted target branch is reported as missing_branch; an existing one returns its head."""
    fresh_env["graph"].sha = "new"
    fresh_env["heads"]["release-2.3"] = "rel1"
    rid = await _request(w6)
    gone = await fresh_env["acts"].ensure_fresh({"ws": w6.ws, "requestId": rid, "branch": "deleted"})
    assert gone["status"] == "missing_branch"
    ok = await fresh_env["acts"].ensure_fresh({"ws": w6.ws, "requestId": rid, "branch": "release-2.3"})
    assert ok == {"status": "fresh", "sha": "new", "targetSha": "rel1"}
