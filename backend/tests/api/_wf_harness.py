"""Shared harness for RequestWorkflow tests: scripted fake activities and a fake BuildWorkflow.

Each fake activity is registered under the real activity's name, records its calls, and returns a scripted value
(a single value, or a list consumed one call at a time; callables are called with the args).
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from temporalio import activity, workflow
from temporalio.client import Client, WorkflowHandle
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError
from temporalio.worker import UnsandboxedWorkflowRunner, Worker
from temporalio.worker.workflow_sandbox import SandboxedWorkflowRunner, SandboxRestrictions

from actron.activities import request as real_acts
from actron.workflows.request import RequestWorkflow

DEFAULT_SCRIPT: dict[str, Any] = {
    "ensure_fresh": {"status": "fresh", "sha": "base123"},
    "investigate_request": {"label": "conflict", "questionCount": 0, "evidenceCount": 2},
    "prepare_questions": {"questions": [], "branchNames": ["main"], "workingBranch": "main", "targetBranch": "main"},
    "draft_ticket": {"objective": "Do it", "targetBranch": "main"},
    "check_external_edit": {"externalEdit": False},
    "budget_check": {"reached": False, "spentTodayUsd": 0.0, "capUsd": 20.0},
    "read_pr_head": {"headSha": "head1", "verified": True},
    "classify_feedback": {"kind": "question"},
    "check_pr": {"state": "open"},
    "build": {"status": "passed", "headSha": "head1", "prNumber": 7, "prUrl": "https://example.test/pr/7"},
}


@dataclass
class Fakes:
    script: dict[str, Any] = field(default_factory=dict)
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    gates: dict[str, asyncio.Event] = field(default_factory=dict)
    revision_n: int = 0
    pi_cancelled: list[str] = field(default_factory=list)
    builds: list[dict[str, Any]] = field(default_factory=list)

    def value(self, name: str, args: dict[str, Any]) -> Any:
        v = self.script.get(name, DEFAULT_SCRIPT.get(name, {}))
        if isinstance(v, list):
            v = v.pop(0) if len(v) > 1 else v[0]
        if callable(v):
            v = v(args)
        if isinstance(v, Exception):
            raise v
        return v

    def called(self, name: str) -> list[dict[str, Any]]:
        return [a for n, a in self.calls if n == name]

    def states(self) -> list[str]:
        return [a["to"] for a in self.called("set_state")]

    def approvals(self) -> list[tuple[str, str, str | None]]:
        return [(a["kind"], a["status"], a.get("reason")) for a in self.called("record_approval")]

    def outcomes(self) -> list[dict[str, Any]]:
        return [a["outcome"] for a in self.called("publish_outcome")]

    def activities(self) -> list[Callable[..., Any]]:
        out: list[Callable[..., Any]] = []
        for fn in real_acts.ACTIVITIES:
            name = activity._Definition.must_from_callable(fn).name  # type: ignore[attr-defined]
            out.append(self._make(str(name)))
        return out

    def _make(self, name: str) -> Callable[..., Any]:
        fakes = self

        async def fake(args: dict[str, Any]) -> dict[str, Any]:
            fakes.calls.append((name, dict(args)))
            gate = fakes.gates.get(name)
            if gate is not None:
                await gate.wait()
            if name == "save_revision":
                fakes.revision_n += 1
                content = args.get("content") or {}
                return {"n": fakes.revision_n, "hash": f"hash{fakes.revision_n}",
                        "targetBranch": content.get("targetBranch", "main")}
            if name == "prepare_build":
                return {"requestId": args["requestId"], "buildId": f"b{len(fakes.called('prepare_build'))}",
                        "branch": "actron/x", "baseSha": args.get("baseSha"), "feedback": args.get("feedback"),
                        **fakes.script.get("build_input", {})}
            if name == "record_build_result":
                res = args["result"]
                pr = None
                if res.get("status") == "passed":
                    pr = {"number": res.get("prNumber", 7), "headSha": res.get("headSha", "head1"), "url": "u",
                          "state": "open", "targetBranch": "main"}
                return {"status": res.get("status"), "pr": pr, "stopReason": res.get("stopReason")}
            if name in ("set_state", "record_answer", "publish_outcome", "send_reminder", "budget_resumed",
                        "sync_ticket", "trigger_syncs", "answer_feedback", "close_pr", "write_answer",
                        "mark_build_cancelled", "record_approval"):
                if name == "record_approval":
                    return {"status": args["status"], "reason": args.get("reason"), "eventId": 1}
                return {"ok": True, "state": args.get("to")}
            v = fakes.value(name, args)
            return dict(v) if isinstance(v, dict) else v

        return activity.defn(name=name)(fake)


CURRENT: dict[str, Fakes] = {}


@activity.defn(name="fake_pi")
async def fake_pi(args: dict[str, Any]) -> dict[str, Any]:
    fakes = CURRENT["fakes"]
    try:
        while True:
            activity.heartbeat()
            await asyncio.sleep(0.1)
    except asyncio.CancelledError:
        fakes.pi_cancelled.append(str(args.get("buildId")))
        raise


@activity.defn(name="fake_build_result")
async def fake_build_result(args: dict[str, Any]) -> dict[str, Any]:
    fakes = CURRENT["fakes"]
    fakes.builds.append(args)
    v = fakes.value("build", args)
    return dict(v)


@workflow.defn(name="BuildWorkflow")
class FakeBuildWorkflow:
    @workflow.run
    async def run(self, inp: dict[str, Any]) -> dict[str, Any]:
        if inp.get("hang"):
            await workflow.execute_activity(fake_pi, inp, start_to_close_timeout=timedelta(hours=1),
                                            heartbeat_timeout=timedelta(seconds=5),
                                            cancellation_type=workflow.ActivityCancellationType.WAIT_CANCELLATION_COMPLETED)
        result: dict[str, Any] = await workflow.execute_activity(
            fake_build_result, inp, start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=1))
        return result


@workflow.defn(name="WritebackWorkflow")
class FakeWritebackWorkflow:
    @workflow.run
    async def run(self, inp: dict[str, Any]) -> dict[str, Any]:
        await workflow.execute_activity(fake_writeback, inp, start_to_close_timeout=timedelta(seconds=30))
        return {"ok": True}


@activity.defn(name="fake_writeback")
async def fake_writeback(args: dict[str, Any]) -> dict[str, Any]:
    CURRENT["fakes"].calls.append(("writeback", dict(args)))
    return {"ok": True}


def fake_investigation(label: str = "conflict", questions: list[dict[str, Any]] | None = None,
                       evidence: list[dict[str, Any]] | None = None) -> Callable[..., Awaitable[Any]]:
    """A stand-in for W5's `investigate` that returns a real InvestigationResult and emits two events."""
    from actron.flow.findings import Findings, InvestigationResult

    async def investigate(ws: str, request_id: str, text: str, kind: str, *, emit: Any, mode: str = "auto") -> Any:
        await emit("investigation.started", {"mode": "pipeline"})
        await emit("investigation.completed", {"label": label, "summary": "Scripted findings.",
                                               "counts": {"decisions": 0, "relatedWork": 0, "callers": 0, "tests": 0},
                                               "findingsRef": request_id})
        return InvestigationResult.model_validate({
            "findings": Findings(requestId=f"actron:request:{request_id}", label=label).model_dump(by_alias=True),
            "label": label, "summary": "Scripted findings.", "mode": "pipeline", "stub": True,
            "evidence": evidence or [], "questions": questions or []})

    return investigate


class RealStack:
    """Time-skipping Temporal with the real RequestWorkflow, WritebackWorkflow and activities (real PostgreSQL,
    Redis and FalkorDB), a fake BuildWorkflow, and the service wired to that Temporal client."""

    def __init__(self, client: Client, fakes: Fakes) -> None:
        self.client = client
        self.fakes = fakes

    async def __aenter__(self) -> RealStack:
        from actron.activities import request as acts
        from actron.flow import service
        from actron.workflows.writeback import WritebackWorkflow

        CURRENT["fakes"] = self.fakes
        self._workers = [
            Worker(self.client, task_queue="request", workflows=[RequestWorkflow, WritebackWorkflow],
                   activities=list(acts.ACTIVITIES)),
            Worker(self.client, task_queue="build", workflows=[FakeBuildWorkflow],
                   activities=[fake_pi, fake_build_result], workflow_runner=UnsandboxedWorkflowRunner()),
        ]
        for w in self._workers:
            await w.__aenter__()
        service.set_gateway(service.TemporalGateway(fixed_client=self.client))
        return self

    async def __aexit__(self, *exc: object) -> None:
        for w in reversed(self._workers):
            await w.__aexit__(None, None, None)


async def wait_db_state(ws: str, request_id: str, state: str, timeout: float = 20.0) -> None:
    from actron.db import models as m
    from actron.db.session import session_scope

    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    last = None
    while loop.time() < deadline:
        with session_scope() as s:
            row = s.get(m.Request, request_id)
            last = row.state if row else None
        if last == state:
            return
        await asyncio.sleep(0.1)
    raise AssertionError(f"request {request_id} stayed {last!r}, expected {state!r}")


def failing(times: int, then: Any) -> Callable[[dict[str, Any]], Any]:
    count = {"n": 0}

    def fn(args: dict[str, Any]) -> Any:
        count["n"] += 1
        if count["n"] <= times:
            raise ApplicationError("scripted failure")
        return then

    return fn


class Run:
    def __init__(self, client: Client, fakes: Fakes, handle: WorkflowHandle[Any, Any]) -> None:
        self.client = client
        self.fakes = fakes
        self.handle = handle

    async def state(self) -> dict[str, Any]:
        result: dict[str, Any] = await self.handle.query("state")
        return result

    async def wait_state(self, state: str, timeout: float = 15.0) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        last: dict[str, Any] = {}
        while loop.time() < deadline:
            last = await self.state()
            # The query reports a new state before its set_state mirror activity runs; tests that read the
            # mirror next (fakes.states()) wait for it too. Investigating is set at creation, not mirrored.
            if last["state"] == state and (state == "Investigating" or state in self.fakes.states()):
                return last
            await asyncio.sleep(0.05)
        raise AssertionError(f"state {state!r} not reached; last {last} states {self.fakes.states()}")

    async def wait_for(self, cond: Callable[[], bool], timeout: float = 15.0) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            if cond():
                return
            await asyncio.sleep(0.05)
        raise AssertionError(f"condition not met; calls {[n for n, _ in self.fakes.calls]}")

    async def signal(self, name: str, payload: dict[str, Any] | None = None, key: str | None = None) -> None:
        body = {"actor": {"userId": "u1", "name": "Ann", "surface": "ui"},
                "idempotencyKey": key or str(uuid.uuid4()), **(payload or {})}
        await self.handle.signal(name, body)

    async def result(self) -> dict[str, Any]:
        out: dict[str, Any] = await self.handle.result()
        return out


async def run_workflow(
    client: Client,
    fakes: Fakes,
    body: Callable[[Run], Awaitable[None]],
    *,
    kind: str = "feature",
    options: dict[str, Any] | None = None,
) -> None:
    CURRENT["fakes"] = fakes
    tq = f"request-{uuid.uuid4().hex[:8]}"
    runner = SandboxedWorkflowRunner(restrictions=SandboxRestrictions.default.with_passthrough_modules("tests"))
    async with Worker(client, task_queue=tq, workflows=[RequestWorkflow, FakeWritebackWorkflow],
                      activities=[*fakes.activities(), fake_writeback], workflow_runner=runner), \
            Worker(client, task_queue="build", workflows=[FakeBuildWorkflow],
                   activities=[fake_pi, fake_build_result], workflow_runner=UnsandboxedWorkflowRunner()):
        handle = await client.start_workflow(
            "RequestWorkflow",
            {"ws": "w", "requestId": f"req_{uuid.uuid4().hex[:6]}", "kind": kind, "title": "T", "text": "Do it",
             "options": options or {}},
            id=f"request:{uuid.uuid4().hex}", task_queue=tq,
        )
        await body(Run(client, fakes, handle))
