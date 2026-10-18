"""Daily model budget (spec B, B12a): builds wait, raising the cap resumes them, spend is computed (B-AC-85)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from temporalio.client import Client
from temporalio.testing import WorkflowEnvironment

from tests.api._fixtures import FakeGateway, W6Env, gateway, w6  # noqa: F401
from tests.api._wf_harness import Fakes, Run, run_workflow

REACHED = {"reached": True, "spentTodayUsd": 21.0, "capUsd": 20.0}
OK = {"reached": False, "spentTodayUsd": 1.0, "capUsd": 40.0}


@pytest_asyncio.fixture
async def tenv() -> AsyncIterator[WorkflowEnvironment]:
    env = await WorkflowEnvironment.start_time_skipping()
    try:
        yield env
    finally:
        await env.shutdown()


async def _approve(run: Run) -> None:
    await run.wait_state("Awaiting approval")
    await run.signal("approve_ticket", {"revisionHash": "hash1"})
    await run.wait_state("Building")


async def test_build_waits_until_budget_raised(tenv: WorkflowEnvironment) -> None:
    """B-AC-85: at the cap the build waits (visible reason); budget_raised resumes it."""
    fakes = Fakes(script={"budget_check": [REACHED, OK]})

    async def body(run: Run) -> None:
        await _approve(run)
        await run.wait_for(lambda: len(fakes.called("budget_check")) == 1)
        st = await run.state()
        assert st["state"] == "Building" and st["build"]["status"] == "waiting_budget"
        assert not fakes.called("prepare_build")
        await run.signal("budget_raised", {"capUsd": 40})
        await run.wait_state("PR ready for review")
        assert len(fakes.called("budget_resumed")) == 1
        assert len(fakes.called("prepare_build")) == 1

    await run_workflow(tenv.client, fakes, body)


async def test_build_resumes_next_utc_day(tenv: WorkflowEnvironment) -> None:
    """B-AC-85: without a raise, the durable timer resumes the build at the next UTC day."""
    fakes = Fakes(script={"budget_check": [REACHED, OK]})

    async def body(run: Run) -> None:
        await _approve(run)
        await run.wait_for(lambda: len(fakes.called("budget_check")) == 1)
        await tenv.sleep(timedelta(hours=25))
        await run.wait_state("PR ready for review")

    await run_workflow(tenv.client, fakes, body)


async def test_budget_raised_ignored_when_not_waiting(tenv: WorkflowEnvironment) -> None:
    """B.C1: budget_raised outside the wait is a no-op."""
    fakes = Fakes()

    async def body(run: Run) -> None:
        await run.wait_state("Awaiting approval")
        await run.signal("budget_raised", {"capUsd": 50})
        await run.signal("approve_ticket", {"revisionHash": "hash1"})
        await run.wait_state("PR ready for review")

    await run_workflow(tenv.client, fakes, body)


def _client(env: WorkflowEnvironment) -> Client:
    return env.client


# Spend computation and the activities (database)
def _model_call(ws: str, cost: float, *, stub: bool = False, when: datetime | None = None) -> None:
    from actron.db import models as m
    from actron.db.session import session_scope

    with session_scope() as s:
        s.add(m.ModelCall(workspace_id=ws, job="j", provider="llm", model="anthropic/claude-sonnet-4-5",
                          input_tokens=1000, output_tokens=100, cost_usd=cost, stub=stub,
                          created_at=when or datetime.now(UTC)))


def test_spent_today_counts_today_only(w6: W6Env) -> None:  # noqa: F811
    """B-AC-85: spend = today's model calls (stubs excluded) plus build tokens."""
    from actron.db.session import session_scope
    from actron.flow import budget

    _model_call(w6.ws, 2.5)
    _model_call(w6.ws, 100.0, stub=True)
    _model_call(w6.ws, 50.0, when=datetime.now(UTC) - timedelta(days=2))
    with session_scope() as s:
        st = budget.status(s, w6.ws)
    assert st["spentTodayUsd"] == pytest.approx(2.5)
    assert st["capUsd"] == 20.0 and st["reached"] is False


def test_cap_from_settings_and_reached(w6: W6Env) -> None:  # noqa: F811
    """B-AC-85: the workspace cap overrides the default; reaching it is reported."""
    from actron.db.session import session_scope
    from actron.flow import budget

    _model_call(w6.ws, 3.0)
    with session_scope() as s:
        budget.set_cap(s, w6.ws, 2.0)
    with session_scope() as s:
        assert budget.status(s, w6.ws)["reached"] is True


async def test_investigation_uses_pipeline_over_budget(w6: W6Env, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    """B-AC-85: over the cap, investigations use the pipeline and `budget.reached` is recorded."""
    import sys
    import types

    from actron.activities import request as acts
    from actron.flow import service

    view = await service.create_request(w6.ws, text="Add an export button", actor=w6.actor(), source="ui",
                                        kind_hint="feature")
    rid = view["id"]
    _model_call(w6.ws, 25.0)
    seen: dict[str, Any] = {}

    async def fake_investigate(ws: str, request_id: str, text: str, kind: str, *, emit: Any, mode: str = "auto") -> Any:
        seen["mode"] = mode
        raise RuntimeError("stop here")

    mod = types.ModuleType("actron.flow.investigate")
    mod.investigate = fake_investigate  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "actron.flow.investigate", mod)
    with pytest.raises(RuntimeError):
        await acts.investigate_request({"ws": w6.ws, "requestId": rid, "kind": "feature"})
    assert seen["mode"] == "pipeline"
    assert "budget.reached" in w6.types(rid)


async def test_raise_budget_signals_waiting_builds(w6: W6Env, gateway: FakeGateway) -> None:  # noqa: F811
    """B-AC-85: raising the cap signals budget_raised to requests in Building."""
    from actron.flow import service

    view = await service.create_request(w6.ws, text="Add an export button", actor=w6.actor(), source="ui",
                                        kind_hint="feature")
    service.set_request_fields(view["id"], state="Building")
    res = await service.raise_budget(w6.ws, 50.0, w6.actor(), "k-budget")
    assert res["signalled"] == 1
    assert [s[1] for s in gateway.signals] == ["budget_raised"]
    from actron.db.session import session_scope
    from actron.flow import budget

    with session_scope() as s:
        assert budget.cap_usd(s, w6.ws) == 50.0


async def test_raise_budget_needs_owner_or_approver(w6: W6Env) -> None:  # noqa: F811
    """B12a: a plain member cannot raise the cap."""
    from actron.flow import service

    member = w6.add_user("Member")
    with pytest.raises(service.Forbidden):
        await service.raise_budget(w6.ws, 50.0, w6.actor(member), "k-m")
