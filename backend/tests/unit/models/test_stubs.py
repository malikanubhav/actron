"""A-AC-82: with no keys at all, every job returns its documented stub with `stub: true`."""

from __future__ import annotations

from typing import Any

import pytest

from actron import models
from actron.models import cache


async def test_judgment_stubs(usage_rows: list[Any]) -> None:
    """A-AC-82: the most conservative option for each judgment job."""
    cand = models.Candidate(kind="function", name="f")
    dec = models.DecisionView(statement="s", quote="q", status="approved")
    j1 = await models.classify_message("t", "slack", None)
    assert (j1.answer, j1.probability) == ("chatter", 0.0)
    assert (await models.is_approval("d", "r", False)).probability == 0.0
    assert (await models.judge_link("t", cand)).probability == 0.0
    assert [j.probability for j in await models.judge_links("t", [cand, cand])] == [0.0, 0.0]
    j6 = await models.judge_conflict("r", dec)
    assert (j6.answer, j6.probability) == ("unrelated", 0.0)
    assert (await models.needs_question("s", [], 99.0)).probability == 1.0
    assert (await models.is_scope_change({}, "d", ["x"])).probability == 1.0
    assert (await models.classify_request("r")).answer == "feature"
    assert (await models.check_link("q", "c")).probability == 0.5
    assert (await models.feedback_kind("f", {})).answer == "question"
    [j5] = await models.rank_candidates("r", [models.CandidateSummary(id="a", summary="s")])
    assert j5.answer == 0.0
    every = [j1, j6, j5]
    assert all(
        j.stub and j.provider == "stub" and j.model == "stub" and j.confidence == 0.0 for j in every
    )
    assert usage_rows and all(r.stub and r.provider == "stub" for r in usage_rows)


async def test_text_stubs_are_templates() -> None:
    """A-AC-82: text jobs fall back to deterministic templates marked as stubs."""
    findings = {
        "requestText": "Add PDF export to reports.",
        "seeds": [
            {"id": "code:fn:a/b:src/export.ts::exportReport", "type": "CodeFunction", "score": 0.9}
        ],
        "decisions": [
            {
                "id": "actron:decision:1",
                "statement": "Exports stay CSV only.",
                "status": "approved",
                "conflict": {"label": "conflict", "probability": 0.9},
            }
        ],
        "impact": {
            "callers": [{"id": "code:fn:a/b:x.ts::y", "depth": 1}],
            "tests": [{"id": "code:fn:a/b:t.ts::t"}],
        },
        "procedures": [{"id": "actron:procedure:src", "testCommand": "npm test"}],
        "label": "conflict",
    }
    qs = await models.write_questions(findings)
    assert len(qs) == 1 and qs[0].evidenceIds == ["actron:decision:1"]
    assert qs[0].text == "Should exports stay CSV only still hold for add PDF export to reports?"
    ticket = await models.write_ticket("Add PDF export to reports.", findings, [])
    assert ticket.stub and ticket.objective == "Add PDF export to reports."
    assert ticket.affectedFunctions == ["code:fn:a/b:src/export.ts::exportReport"]
    assert ticket.constraintsToPreserve[0].evidenceIds == ["actron:decision:1"]
    assert ticket.testPlan[0].command == "npm test"
    lifted = await models.write_ticket(
        "x",
        findings,
        [
            {"questionId": "q1", "value": "change", "evidenceIds": ["actron:decision:1"]},
            {"questionId": "target_branch", "value": "dev"},
        ],
    )
    assert lifted.constraintsToPreserve == [] and lifted.targetBranch == "dev"
    ans = await models.write_answer(
        "Who owns export?", [models.EvidenceItem(id="e1", text="Ana owns it.")]
    )
    assert ans.stub and ans.evidenceIds == ["e1"] and "[e1]" in ans.text
    empty = await models.write_answer("?", [])
    assert empty.text == "Nothing in your history answers this yet."
    summary = await models.summarize_findings(findings)
    assert summary.startswith("One earlier decision affects this request.")
    assert "!" not in summary
    assert (
        await models.summarize_findings({})
        == "Nothing in your history touches this. Safe to continue."
    )
    assert await models.extract_decision("We decided X.") is None


async def test_agent_completion_without_key_raises() -> None:
    """A-AC-82: the investigator's tool-calling call raises ModelUnavailable with no key."""
    with pytest.raises(models.ModelUnavailable):
        await models.agent_completion([{"role": "user", "content": "hi"}], [])


async def test_stubs_are_never_cached(redis_client: Any) -> None:
    """A-AC-82: nothing is cached when stubbed."""
    cache.set_enabled(True)
    await models.classify_message("t", "slack", None)
    await models.needs_question("s", [], 1.0)
    assert redis_client.keys("model:*") == []
