"""Request service (spec B, B1): create, actions, member and approver checks, seq, read model.

Uses the real test database and Redis with a fake workflow gateway.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from actron.flow import service
from actron.flow.approvals import publish_outcome
from tests.api._fixtures import FakeGateway, W6Env, gateway, w6  # noqa: F401

REQUEST_DETAIL_KEYS = {
    "id", "title", "kind", "state", "label", "requester", "source", "createdAt", "updatedAt", "lastEvent",
    "pipelineStep", "needsYou", "text", "headline", "purpose", "slack", "findings", "evidence", "questions",
    "revisions", "currentRevision", "approvals", "builds", "pr", "investigation", "outcome", "answer",
    "allowedActions",
}


async def _create(w6: W6Env, **kw: Any) -> dict[str, Any]:  # noqa: F811
    return await service.create_request(w6.ws, text=kw.pop("text", "Let admins export invoices"),
                                        actor=kw.pop("actor", w6.actor()), source=kw.pop("source", "ui"),
                                        kind_hint=kw.pop("kind_hint", "feature"), **kw)


def _set(w6: W6Env, rid: str, **values: Any) -> None:  # noqa: F811
    data = values.pop("data", None)
    if data is not None:
        from actron.db import models as m
        from actron.db.session import session_scope

        with session_scope() as s:
            row = s.get(m.Request, rid)
            assert row is not None
            row.data = {**(row.data or {}), **data}
    if values:
        service.set_request_fields(rid, **values)


async def test_create_request_ui(w6: W6Env, gateway: FakeGateway) -> None:  # noqa: F811
    """B-AC-1: a row, `request.created` with seq 1, a Request node and a running workflow."""
    view = await _create(w6)
    rid = view["id"]
    assert rid.startswith("req_")
    assert view["state"] == "Investigating" and view["source"] == "ui" and view["kind"] == "feature"
    evs = w6.events(rid)
    assert [(e.seq, e.type) for e in evs] == [(1, "request.created")]
    assert evs[0].payload["requester"]["userId"] == w6.owner_id
    assert gateway.started[0][1] == rid and gateway.started[0][2]["kind"] == "feature"
    from actron.graph import ids
    from actron.graph.store import store_for

    node = store_for(w6.ws).get_node(ids.request(rid))
    assert node is not None and node["state"] == "Investigating"


async def test_create_request_from_slack(w6: W6Env, gateway: FakeGateway) -> None:  # noqa: F811
    """B-AC-1: Slack source works; the Slack user is created on first contact and joins the workspace."""
    actor = service.Actor(slack_user_id="U123", surface="slack", name="Sam")
    view = await _create(w6, actor=actor, source="slack", slack=service.SlackRef("C1", "1700.1"))
    assert view["source"] == "slack"
    assert view["slack"] == {"channel": "C1", "threadTs": "1700.1", "permalink": None}
    assert view["requester"]["name"] == "Sam"
    ev = w6.events(view["id"])[0]
    assert ev.actor == "slack" and ev.surface == "slack" and ev.payload["slack"]["channel"] == "C1"


async def test_create_rejects_bad_text(w6: W6Env) -> None:  # noqa: F811
    """B.C7: text must be 3..4000 characters."""
    with pytest.raises(service.Invalid):
        await _create(w6, text="hi")
    with pytest.raises(service.Invalid):
        await _create(w6, text="x" * 4001)


async def test_workflow_start_failure_is_recorded(w6: W6Env, gateway: FakeGateway) -> None:  # noqa: F811
    """B1: when Temporal is down the request still exists and is marked for the reconciler."""
    gateway.fail_start = True
    view = await _create(w6)
    from actron.db import models as m
    from actron.db.session import session_scope

    with session_scope() as s:
        row = s.get(m.Request, view["id"])
        assert row is not None and row.data["workflowStarted"] is False


async def test_non_member_refused(w6: W6Env, gateway: FakeGateway) -> None:  # noqa: F811
    """B-AC-3: a non-member is refused with 403 and no event is written."""
    view = await _create(w6)
    outsider = w6.add_user("Outsider", role=None)
    with pytest.raises(service.Forbidden) as exc:
        await service.cancel(w6.ws, view["id"], "no", w6.actor(outsider), "k1")
    assert exc.value.code == "not_a_member"
    assert w6.types(view["id"]) == ["request.created"]
    with pytest.raises(service.Forbidden):
        await _create(w6, actor=w6.actor(outsider))


async def test_non_approver_refused_with_event(w6: W6Env, gateway: FakeGateway) -> None:  # noqa: F811
    """B-AC-3 / B-AC-84: a member who is not an approver gets 403 `not_an_approver` and `approval.refused`."""
    view = await _create(w6)
    _set(w6, view["id"], state="Awaiting approval")
    member = w6.add_user("Member", slack_user_id="U9")
    with pytest.raises(service.Forbidden) as exc:
        await service.approve(w6.ws, view["id"], "ticket", "h" * 64, w6.actor(member), "k2")
    assert exc.value.code == "not_an_approver"
    assert w6.types(view["id"])[-1] == "approval.refused"
    detail = await service.get_request_view(w6.ws, view["id"])
    assert detail["approvals"][0]["status"] == "refused" and detail["approvals"][0]["reason"] == "not_an_approver"
    assert not gateway.signals


async def test_invalid_transition_precheck(w6: W6Env, gateway: FakeGateway) -> None:  # noqa: F811
    """B1: the quick pre-check returns a 409 for an action the state does not allow, without an event."""
    view = await _create(w6)
    with pytest.raises(service.Conflict) as exc:
        await service.approve(w6.ws, view["id"], "pr", "abc", w6.actor(), "k3")
    assert exc.value.code == "invalid_transition"
    assert w6.types(view["id"]) == ["request.created"]


async def test_precheck_uses_workflow_query(w6: W6Env, gateway: FakeGateway) -> None:  # noqa: F811
    """B1: the workflow's state() query wins over the PostgreSQL mirror."""
    view = await _create(w6)
    gateway.state_view[view["id"]] = {"state": "Needs attention"}
    res = await service.retry(w6.ws, view["id"], w6.actor(), "k4")
    assert res["status"] == "accepted"
    assert gateway.signals[-1][1] == "retry"


async def test_action_event_pending_then_sent(w6: W6Env, gateway: FakeGateway) -> None:  # noqa: F811
    """B1: the action event is written with signal_status pending, the workflow is signalled, then sent."""
    view = await _create(w6)
    res = await service.cancel(w6.ws, view["id"], "changed my mind", w6.actor(), "k5")
    ev = w6.events(view["id"])[-1]
    assert ev.type == "request.cancel_requested" and ev.signal_status == "sent" and ev.id == res["eventId"]
    rid, name, payload = gateway.signals[0]
    assert (rid, name) == (view["id"], "cancel")
    assert payload["idempotencyKey"] == "k5" and payload["actor"]["userId"] == w6.owner_id
    assert payload["eventId"] == ev.id


async def test_answer_validated_before_recording(w6: W6Env, gateway: FakeGateway) -> None:  # noqa: F811
    """B-AC-31: an answer that is not an option is refused (422) before any event."""
    view = await _create(w6)
    q = {"questionId": "q1", "text": "Keep?", "kind": "choice", "required": True,
         "options": [{"value": "yes", "label": "Yes"}], "evidenceIds": []}
    _set(w6, view["id"], state="Needs your input", data={"questions": [q]})
    with pytest.raises(service.Invalid):
        await service.answer(w6.ws, view["id"], "q1", "maybe", w6.actor(), "k6")
    res = await service.answer(w6.ws, view["id"], "q1", "yes", w6.actor(), "k7")
    assert res["status"] == "accepted"
    assert w6.types(view["id"])[-1] == "answer.received"


async def test_approval_waits_for_outcome(w6: W6Env, gateway: FakeGateway) -> None:  # noqa: F811
    """B1: approvals wait for the workflow's decision: accepted -> 200 shape, refused -> reason."""
    view = await _create(w6)
    _set(w6, view["id"], state="Awaiting approval")

    async def decide(rid: str, name: str, payload: dict[str, Any]) -> None:
        ok = payload["revisionHash"] == "good"
        await publish_outcome(rid, payload["idempotencyKey"], {"status": "accepted" if ok else "refused",
                                                          "reason": None if ok else "stale_revision",
                                                          "state": "Building" if ok else "Awaiting approval"})

    gateway.on_signal = decide
    good = await service.approve(w6.ws, view["id"], "ticket", "good", w6.actor(), "k8")
    assert good["status"] == "accepted" and good["state"] == "Building"
    bad = await service.approve(w6.ws, view["id"], "ticket", "old", w6.actor(), "k9")
    assert bad["status"] == "refused" and bad["reason"] == "stale_revision"


async def test_approval_pending_after_timeout(w6: W6Env, gateway: FakeGateway, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    """B1: no outcome within the wait -> status pending (API answers 202)."""
    monkeypatch.setattr(service, "OUTCOME_WAIT_S", 0.2)
    view = await _create(w6)
    _set(w6, view["id"], state="Awaiting approval")
    res = await service.approve(w6.ws, view["id"], "ticket", "h", w6.actor(), "k10")
    assert res["status"] == "pending"


async def test_seq_gap_free_under_concurrency(w6: W6Env, gateway: FakeGateway) -> None:  # noqa: F811
    """B-AC-6: Slack and UI actions at the same time keep seq gap-free and unique per request."""
    view = await _create(w6)
    q = {"questionId": "q1", "text": "Free text?", "kind": "text", "required": True, "options": [], "evidenceIds": []}
    _set(w6, view["id"], state="Needs your input", data={"questions": [q]})
    slack_actor = service.Actor(slack_user_id="U55", surface="slack", name="S")
    tasks = []
    for i in range(12):
        actor = slack_actor if i % 2 else w6.actor()
        tasks.append(service.answer(w6.ws, view["id"], "q1", f"v{i}", actor, f"conc-{i}"))
    from actron.flow.events import emit

    tasks += [emit(w6.ws, view["id"], "build.step", {"text": f"s{i}"}) for i in range(8)]
    await asyncio.gather(*tasks)
    seqs = [e.seq for e in w6.events(view["id"])]
    assert seqs == list(range(1, len(seqs) + 1))
    assert len(seqs) == 1 + 12 + 8


async def test_request_view_has_contract_shape(w6: W6Env) -> None:  # noqa: F811
    """B.C7: RequestDetail has exactly the contract fields (plus memory and budget notes)."""
    view = await _create(w6)
    assert set(view) >= REQUEST_DETAIL_KEYS
    assert set(view) - REQUEST_DETAIL_KEYS <= {"memory", "budget"}
    assert view["headline"] == "Investigating. 0 graph queries so far."
    assert view["allowedActions"] == ["cancel"]
    assert view["pipelineStep"] == 1 and view["needsYou"] is False
    assert view["lastEvent"]["type"] == "request.created"
    assert view["requester"] == {"personId": None, "userId": w6.owner_id, "name": "Owner", "avatarUrl": None}


@pytest.mark.parametrize(("state", "headline"), [
    ("Awaiting approval", "The ticket is ready for your approval."),
    ("Building", "Building."),
    ("PR ready for review", "PR #12 is ready for review."),
    ("Done", "Done. Merged scope recorded in memory."),
    ("Cancelled", "Cancelled."),
])
async def test_headline_per_state(w6: W6Env, state: str, headline: str) -> None:  # noqa: F811
    """PROMPT 8.8 D: the header sentence follows the state."""
    view = await _create(w6)
    _set(w6, view["id"], state=state, data={"pr": {"number": 12, "headSha": "abc", "url": "u"}})
    detail = await service.get_request_view(w6.ws, view["id"])
    assert detail["headline"] == headline
    assert detail["needsYou"] is (state in ("Awaiting approval", "PR ready for review"))


async def test_evidence_tiers_and_conflict_headline(w6: W6Env) -> None:  # noqa: F811
    """B.C7: evidence carries a tier from its confidence; the headline counts constraining decisions."""
    view = await _create(w6)
    ev = [{"evidenceId": "e1", "role": "conflict", "nodeId": "actron:decision:1", "nodeType": "Decision",
           "title": "Finance only", "confidence": 0.9, "source": {"type": "SlackMessage", "id": "s"}},
          {"evidenceId": "e2", "role": "impact", "nodeId": "code:fn:a", "nodeType": "CodeFunction", "title": "f",
           "confidence": 0.65, "source": {"type": "CodeFunction", "id": "code:fn:a"}},
          {"evidenceId": "e3", "role": "similar_work", "nodeId": "github:pr:x", "nodeType": "GithubPullRequest",
           "title": "PR", "confidence": 0.3, "source": {"type": "GithubPullRequest", "id": "x"}}]
    findings = {"decisions": [{"id": "d1"}, {"id": "d2"}]}
    _set(w6, view["id"], state="Ticket ready", label="conflict", data={"evidence": ev, "findings": findings})
    detail = await service.get_request_view(w6.ws, view["id"])
    assert [e["tier"] for e in detail["evidence"]] == ["HIGH", "MEDIUM", "POSSIBLE"]
    assert detail["headline"] == "Two earlier decisions affect this request."


async def test_list_requests_groups(w6: W6Env) -> None:  # noqa: F811
    """B.C7: GET /api/requests groups needs_you, running, done with counts."""
    a = await _create(w6)
    b = await _create(w6)
    c = await _create(w6)
    _set(w6, a["id"], state="Awaiting approval")
    _set(w6, c["id"], state="Done")
    out = await service.list_requests(w6.ws)
    assert out["counts"] == {"needsYou": 1, "running": 1, "done": 1}
    needs = await service.list_requests(w6.ws, "needs_you")
    assert [r["id"] for r in needs["requests"]] == [a["id"]]
    running = await service.list_requests(w6.ws, "running")
    assert [r["id"] for r in running["requests"]] == [b["id"]]
