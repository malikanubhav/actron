"""A-AC-79: each Jev job sends exactly the JSON of spec A, A.C4 (snapshot tests through the fake Jev)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from actron import models
from actron.models import Candidate, CandidateSummary, DecisionView
from tests.fakes.jev import FakeJev

J1_CRITERIA = {
    "decision": "States how the software should or should not behave, or settles a choice",
    "proposal": "Suggests a way the software should behave, without settling it",
    "question": "Asks for information",
    "request": "Asks for a feature or change to be built",
    "bug_report": "Reports something broken",
    "status_update": "Reports progress or what someone did",
    "chatter": "Social talk, thanks, jokes or anything off-topic",
}


async def _sent(jev_on: Callable[..., FakeJev], call: Any) -> dict[str, Any]:
    fake = jev_on()
    await call
    assert fake.calls == 1
    return fake.requests[0]


async def test_j1_classify_message_exact_json(jev_on: Callable[..., FakeJev]) -> None:
    """A-AC-79 J1."""
    body = await _sent(
        jev_on, models.classify_message("We will keep paredit strict.", "slack", None)
    )
    assert body == {
        "model": "jev-1.13.0",
        "state": {
            "text": "We will keep paredit strict.",
            "source": "slack",
            "thread_parent_text": None,
        },
        "questions": {
            "kind": {
                "type": "choice",
                "instructions": "What is this text mainly doing in a software team's conversation?",
                "criteria": J1_CRITERIA,
            }
        },
    }


async def test_j1_rejects_unknown_source() -> None:
    """A-AC-79 J1 source values are the six documented ones."""
    with pytest.raises(ValueError):
        await models.classify_message("x", "email", None)


async def test_j2_is_approval_exact_json(jev_on: Callable[..., FakeJev]) -> None:
    """A-AC-79 J2."""
    body = await _sent(
        jev_on, models.is_approval("Format on type stays off", "Agreed, ship it", False)
    )
    assert body["state"] == {
        "decision": "Format on type stays off",
        "reply": "Agreed, ship it",
        "reply_author_is_decision_author": False,
    }
    assert body["questions"] == {
        "approves": {
            "type": "noul",
            "instructions": "Does the reply explicitly approve or agree to adopt the decision in "
            "`decision`? Polite acknowledgement without agreement is not approval.",
            "criteria": {
                "true": "The reply clearly agrees the decision should be adopted",
                "false": "Anything else",
            },
        }
    }


async def test_j3_judge_link_exact_json(jev_on: Callable[..., FakeJev]) -> None:
    """A-AC-79 J3 (docstring cut at 400 characters)."""
    cand = Candidate(
        kind="function",
        name="activate",
        path="src/extension.ts",
        signature="activate(context)",
        docstring="d" * 500,
    )
    body = await _sent(jev_on, models.judge_link("The extension starts slowly", cand))
    assert body["state"] == {
        "text": "The extension starts slowly",
        "candidate": {
            "kind": "function",
            "name": "activate",
            "path": "src/extension.ts",
            "signature": "activate(context)",
            "docstring": "d" * 400,
        },
    }
    assert body["questions"] == {
        "refers": {
            "type": "noul",
            "instructions": "Does `text` talk about the code or feature described in `candidate`, "
            "even if it does not name it?",
        }
    }


async def test_j3_batched_is_one_request(jev_on: Callable[..., FakeJev]) -> None:
    """A-AC-79 J3 batched: several candidates go in one request, one noul each."""
    fake = jev_on(noul=0.7)
    cands = [Candidate(kind="file", name=f"f{i}.ts", path=f"src/f{i}.ts") for i in range(3)]
    out = await models.judge_links("text", cands)
    assert fake.calls == 1
    assert [j.probability for j in out] == [0.7, 0.7, 0.7]
    body = fake.requests[0]
    assert set(body["questions"]) == {"c0", "c1", "c2"}
    assert body["state"]["candidates"][1]["id"] == "c1"
    assert all(q["type"] == "noul" for q in body["questions"].values())


async def test_j4_check_link_exact_json(jev_on: Callable[..., FakeJev]) -> None:
    """A-AC-79 J4."""
    claim = "This message is about activate in src/extension.ts"
    body = await _sent(jev_on, models.check_link("activation is slow", claim))
    assert body["state"] == {"quote": "activation is slow", "claim": claim}
    assert body["questions"] == {
        "supported": {
            "type": "noul",
            "instructions": "Does `quote` support `claim` exactly as stated?",
        }
    }


async def test_j5_rank_candidates_exact_json(jev_on: Callable[..., FakeJev]) -> None:
    """A-AC-79 J5: one request, one score per candidate, ids c0..c19, at most 20."""
    cands = [
        CandidateSummary(id=f"code:fn:x/y:a.ts::f{i}", summary=f"function f{i}") for i in range(25)
    ]
    fake = jev_on(score=2.0)
    out = await models.rank_candidates("Add a setting", cands)
    assert fake.calls == 1 and len(out) == 20
    body = fake.requests[0]
    assert body["state"]["request"] == "Add a setting"
    assert body["state"]["candidates"][0] == {"id": "c0", "summary": "function f0"}
    assert len(body["questions"]) == 20
    assert body["questions"]["c0"] == {
        "type": "score",
        "instructions": "How relevant is candidate c0 in `candidates` to `request`?",
        "criteria": [
            "unrelated",
            "same area of the code",
            "directly involved in the change",
            "the exact place to change",
        ],
    }
    assert out[0].answer == 2.0


async def test_j6_judge_conflict_exact_json(jev_on: Callable[..., FakeJev]) -> None:
    """A-AC-79 J6."""
    dec = DecisionView(
        statement="Exports stay CSV only", quote="CSV only, please", status="approved"
    )
    body = await _sent(jev_on, models.judge_conflict("Add PDF export", dec))
    assert body["state"] == {
        "request": "Add PDF export",
        "decision": {
            "statement": "Exports stay CSV only",
            "quote": "CSV only, please",
            "status": "approved",
        },
    }
    assert body["questions"] == {
        "relation": {
            "type": "choice",
            "instructions": "How does `decision` relate to what `request` asks for?",
            "criteria": {
                "restricts": "Doing the request as written would break or contradict the decision",
                "supports": "The decision agrees with or enables the request",
                "unrelated": "The decision does not affect the request",
                "superseded_by_request": "The request explicitly replaces the decision",
            },
        }
    }


async def test_j7_to_j10_exact_json(jev_on: Callable[..., FakeJev]) -> None:
    """A-AC-79 J7-J10 (shapes completed from A.C4 and documented in docs/models-and-jev.md)."""
    fake = jev_on()
    await models.classify_request("Why does the REPL hang?")
    await models.needs_question("Two decisions apply", ["Keep CSV"], 97.5)
    await models.is_scope_change({"objective": "x"}, "adds a file", ["src/other.ts"])
    await models.feedback_kind("Looks good, merge it", {"objective": "x"})
    j7, j8, j9, j10 = fake.requests
    assert j7["state"] == {"request": "Why does the REPL hang?"}
    assert j7["questions"]["kind"]["type"] == "choice"
    assert j7["questions"]["kind"]["criteria"] == {
        "feature": "Asks for new behaviour",
        "bug": "Reports broken behaviour to fix",
        "question": "Asks for an explanation or information, not a change",
    }
    assert j8["state"] == {
        "findings_summary": "Two decisions apply",
        "conflicts": ["Keep CSV"],
        "max_criticality_percentile": 97.5,
    }
    assert j8["questions"] == {
        "needs_input": {
            "type": "noul",
            "instructions": "Is a product decision from a person needed before this can be implemented safely?",
        }
    }
    assert j9["state"] == {
        "ticket": {"objective": "x"},
        "diff_summary": "adds a file",
        "files_outside_affected_list": ["src/other.ts"],
    }
    assert j9["questions"] == {
        "scope_change": {
            "type": "noul",
            "instructions": "Does the proposed change go beyond the approved acceptance criteria in `ticket`?",
        }
    }
    assert j10["state"] == {"feedback": "Looks good, merge it", "ticket": {"objective": "x"}}
    assert set(j10["questions"]["kind"]["criteria"]) == {
        "code_change_within_scope",
        "scope_change",
        "question",
        "approval",
    }


async def test_model_pin_and_auth_header(jev_on: Callable[..., FakeJev]) -> None:
    """A-AC-79: model comes from JEV_MODEL; the key is sent as a Bearer token."""
    fake = jev_on()
    await models.check_link("q", "c")
    assert fake.requests[0]["model"] == "jev-1.13.0"
    assert fake.headers[0]["authorization"] == "Bearer test-jev-key"
