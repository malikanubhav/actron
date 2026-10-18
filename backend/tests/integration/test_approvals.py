"""Approvals end to end through the service, the real workflow and real activities (spec B, B8).

B-AC-36 (approve moves to Building; live update within a second), B-AC-37 (stale revision and stale head
refused with the reason), B-AC-38 (simultaneous Slack and UI approvals: one accepted, one no-op, one build).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from actron.db import models as m
from actron.db.session import session_scope
from actron.flow import service
from actron.flow.events import request_event_stream
from tests.api._fixtures import FakeGateway, W6Env, gateway, stack, w6  # noqa: F401
from tests.api._wf_harness import wait_db_state


async def to_awaiting(w6: W6Env) -> tuple[str, str]:  # noqa: F811
    view = await service.create_request(w6.ws, text="Let project admins export invoices", actor=w6.actor(),
                                        source="ui", kind_hint="feature")
    rid = view["id"]
    await wait_db_state(w6.ws, rid, "Needs your input")
    detail = await service.get_request_view(w6.ws, rid)
    assert [q["questionId"] for q in detail["questions"]] == ["target_branch"]
    await service.answer(w6.ws, rid, "target_branch", "main", w6.actor(), f"ans-{rid}")
    await wait_db_state(w6.ws, rid, "Awaiting approval")
    detail = await service.get_request_view(w6.ws, rid)
    return rid, detail["currentRevision"]["hash"]


def _approval_rows(rid: str) -> list[tuple[str, str, str | None, str]]:
    with session_scope() as s:
        rows = s.query(m.Approval).filter(m.Approval.request_id == rid).order_by(m.Approval.created_at).all()
        return [(r.kind, r.status, r.reason, r.surface) for r in rows]


async def test_slack_approval_builds_and_ui_sees_it_fast(w6: W6Env, stack: Any) -> None:  # noqa: F811
    """B-AC-36: approving the current revision from Slack moves to Building; the SSE stream shows it within 1 s."""
    rid, h = await to_awaiting(w6)
    last_seq = w6.events(rid)[-1].seq
    gen = request_event_stream(w6.ws, rid, last_seq, poll_s=0.05)
    seen: list[dict[str, Any]] = []

    async def watch() -> None:
        async for msg in gen:
            env = json.loads(msg["data"])
            seen.append(env)
            if env["type"] == "request.state_changed" and env["payload"]["to"] == "Building":
                return

    task = asyncio.create_task(watch())
    await asyncio.sleep(0.2)
    loop = asyncio.get_running_loop()
    slack_actor = service.Actor(user_id=w6.owner_id, surface="slack")
    res = await service.approve(w6.ws, rid, "ticket", h, slack_actor, "appr-1")
    answered = loop.time()
    assert res["status"] == "accepted"
    await asyncio.wait_for(task, 5)
    assert loop.time() - answered < 1.0
    await gen.aclose()
    await wait_db_state(w6.ws, rid, "PR ready for review")
    assert _approval_rows(rid) == [("ticket", "accepted", None, "slack")]


async def test_stale_revision_refused(w6: W6Env, stack: Any) -> None:  # noqa: F811
    """B-AC-37 / B-AC-9: an edit makes a new revision; approving the old hash is refused with stale_revision."""
    rid, old = await to_awaiting(w6)
    res = await service.edit_ticket(w6.ws, rid, {"objective": "Smaller scope", "targetBranch": "main"}, w6.actor(),
                                    "edit-1")
    assert res["status"] == "accepted" and res["revision"]["n"] == 2
    refused = await service.approve(w6.ws, rid, "ticket", old, w6.actor(), "appr-old")
    assert refused["status"] == "refused" and refused["reason"] == "stale_revision"
    types = [e.type for e in w6.events(rid)]
    assert "approval.refused" in types
    detail = await service.get_request_view(w6.ws, rid)
    assert detail["state"] == "Awaiting approval" and detail["currentRevision"]["n"] == 2


async def test_simultaneous_approvals_one_build(w6: W6Env, stack: Any) -> None:  # noqa: F811
    """B-AC-38 / B-AC-8: Slack and UI approve at once: one accepted row, one no-op, one build."""
    rid, h = await to_awaiting(w6)
    a, b = await asyncio.gather(
        service.approve(w6.ws, rid, "ticket", h, service.Actor(user_id=w6.owner_id, surface="slack"), "dual-1"),
        service.approve(w6.ws, rid, "ticket", h, w6.actor(), "dual-2"),
        return_exceptions=True,
    )
    results = [r for r in (a, b) if isinstance(r, dict)]
    statuses = sorted(str(r["status"]) for r in results)
    assert "accepted" in statuses
    assert all(s in ("accepted", "duplicate", "pending") for s in statuses)
    for r in (a, b):
        if not isinstance(r, dict):
            assert getattr(r, "code", "") == "invalid_transition"
    await wait_db_state(w6.ws, rid, "PR ready for review")
    assert [row[1] for row in _approval_rows(rid)] == ["accepted"]
    with session_scope() as s:
        assert s.query(m.BuildRun).filter(m.BuildRun.request_id == rid).count() == 1


async def test_stale_head_refused(w6: W6Env, stack: Any) -> None:  # noqa: F811
    """B-AC-37: approving a PR head that is not the current one is refused with stale_head."""
    rid, h = await to_awaiting(w6)
    await service.approve(w6.ws, rid, "ticket", h, w6.actor(), "appr-h")
    await wait_db_state(w6.ws, rid, "PR ready for review")
    res = await service.approve(w6.ws, rid, "pr", "not-the-head", w6.actor(), "pr-stale")
    assert res["status"] == "refused" and res["reason"] == "stale_head"
    ok = await service.approve(w6.ws, rid, "pr", "head1", w6.actor(), "pr-ok")
    assert ok["status"] == "accepted"
    await wait_db_state(w6.ws, rid, "Done")
    types = [e.type for e in w6.events(rid)]
    assert "pr.approved" in types and "writeback.done" in types and types[-1] == "request.done"
