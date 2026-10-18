"""Answers from Slack and the UI, and the Q&A path, end to end (spec B, B6, B14; B-AC-31, B-AC-13, B-AC-79)."""

from __future__ import annotations

from typing import Any

import pytest

from actron.flow import service
from tests.api._fixtures import FakeGateway, W6Env, gateway, stack, w6  # noqa: F401
from tests.api._wf_harness import fake_investigation, wait_db_state

Q1 = {"questionId": "q1", "text": "Should invoice exports stay Finance-only?", "kind": "choice", "required": True,
      "options": [{"value": "yes", "label": "Yes, keep Finance-only"}, {"value": "no", "label": "No, admins too"}],
      "evidenceIds": ["actron:decision:1"]}
EVIDENCE = [{"evidenceId": "actron:decision:1", "role": "constraint", "nodeId": "actron:decision:1",
             "nodeType": "Decision", "title": "Exports are Finance-only", "quote": "Keep exports Finance-only.",
             "source": {"type": "SlackMessage", "id": "slack:msg:C1:1.0"}, "confidence": 0.9, "tier": "HIGH"}]


async def test_answers_from_slack_and_ui(w6: W6Env, stack: Any) -> None:  # noqa: F811
    """B-AC-31: answers from Slack and the UI both record `answer.received` with the surface; the branch answer
    becomes the ticket's targetBranch (B-AC-79)."""
    stack.module.investigate = fake_investigation("conflict", [Q1], EVIDENCE)
    view = await service.create_request(w6.ws, text="Let project admins export invoices", actor=w6.actor(),
                                        source="ui", kind_hint="feature")
    rid = view["id"]
    await wait_db_state(w6.ws, rid, "Needs your input")
    detail = await service.get_request_view(w6.ws, rid)
    assert [q["questionId"] for q in detail["questions"]] == ["q1", "target_branch"]
    branch_q = detail["questions"][1]
    assert branch_q["options"][0]["value"] == "main" and branch_q["options"][0]["preselected"] is True
    slack_actor = service.Actor(slack_user_id="USLACK1", surface="slack", name="Sam")
    await service.answer(w6.ws, rid, "q1", "no", slack_actor, "a-1")
    with pytest.raises(service.Invalid):
        await service.answer(w6.ws, rid, "q1", "perhaps", w6.actor(), "a-bad")
    await service.answer(w6.ws, rid, "target_branch", "new:main", w6.actor(), "a-2")
    await wait_db_state(w6.ws, rid, "Awaiting approval")
    evs = [e for e in w6.events(rid) if e.type == "answer.received"]
    assert [(e.surface, e.payload["questionId"]) for e in evs] == [("slack", "q1"), ("ui", "target_branch")]
    detail = await service.get_request_view(w6.ws, rid)
    q1 = detail["questions"][0]
    assert q1["answer"]["value"] == "no" and q1["answer"]["surface"] == "slack" and q1["answer"]["by"]["name"] == "Sam"
    assert detail["revisions"][0]["content"]["targetBranch"] == "main"
    assert detail["evidence"][0]["tier"] == "HIGH"
    notes = [e for e in w6.events(rid) if e.type == "notification.sent"]
    assert {e.payload["kind"] for e in notes} == {"needs_input", "awaiting_approval"}


async def test_answer_after_ticket_drafted_is_refused(w6: W6Env, stack: Any) -> None:  # noqa: F811
    """B-AC-31: once the ticket is drafted, answers are no longer accepted (409)."""
    view = await service.create_request(w6.ws, text="Add CSV export", actor=w6.actor(), source="ui",
                                        kind_hint="feature")
    rid = view["id"]
    await wait_db_state(w6.ws, rid, "Needs your input")
    await service.answer(w6.ws, rid, "target_branch", "main", w6.actor(), "b-1")
    await wait_db_state(w6.ws, rid, "Awaiting approval")
    with pytest.raises(service.Conflict):
        await service.answer(w6.ws, rid, "target_branch", "main", w6.actor(), "b-2")


async def test_branch_named_in_request_skips_question(w6: W6Env, stack: Any) -> None:  # noqa: F811
    """B-AC-79: a request that names the working branch goes straight to the ticket."""
    view = await service.create_request(w6.ws, text="Add CSV export, merge into main please", actor=w6.actor(),
                                        source="ui", kind_hint="bug")
    await wait_db_state(w6.ws, view["id"], "Awaiting approval")
    detail = await service.get_request_view(w6.ws, view["id"])
    assert detail["questions"] == [] and detail["revisions"][0]["content"]["targetBranch"] == "main"


async def test_question_request_answered(w6: W6Env, stack: Any) -> None:  # noqa: F811
    """B-AC-13 / B-AC-64: a question ends Done (answered) with `answer.ready`, citations, and no ticket."""
    stack.module.investigate = fake_investigation("clear", [], EVIDENCE)
    view = await service.create_request(w6.ws, text="Why are invoice exports Finance-only?", actor=w6.actor(),
                                        source="slack", kind_hint="question",
                                        slack=service.SlackRef("C1", "1700000000.1"))
    rid = view["id"]
    await wait_db_state(w6.ws, rid, "Done")
    detail = await service.get_request_view(w6.ws, rid)
    assert detail["outcome"] == "answered" and detail["revisions"] == []
    assert detail["answer"]["text"]
    assert detail["headline"].startswith("Answered.")
    assert "answer.ready" in w6.types(rid)
