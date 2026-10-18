"""Questions: the target-branch question, branch detection, answer validation (spec B, B6)."""

from __future__ import annotations

import pytest

from actron.flow.questions import (
    TARGET_BRANCH_ID,
    Branch,
    InvalidAnswer,
    all_required_answered,
    apply_answer,
    branch_named_in_text,
    limit_finding_questions,
    target_branch_from_answer,
    target_branch_question,
)

BRANCHES = [
    Branch("main", protected=True, updated_at="2026-10-10T00:00:00Z"),
    Branch("dev", protected=False, updated_at="2026-10-16T00:00:00Z"),
    Branch("release-2.3", protected=True, updated_at="2026-10-15T00:00:00Z"),
    Branch("feat/a", protected=False, updated_at="2026-10-14T00:00:00Z"),
    Branch("feat/b", protected=False, updated_at="2026-10-13T00:00:00Z"),
    Branch("feat/c", protected=False, updated_at="2026-10-12T00:00:00Z"),
    Branch("feat/d", protected=False, updated_at="2026-10-11T00:00:00Z"),
    Branch("old", protected=False, updated_at="2025-01-01T00:00:00Z"),
]


def test_branch_question_order_and_notes() -> None:
    """B-AC-79: working branch first and preselected, up to 5 recent others (protected marked), then new branch."""
    q = target_branch_question("dev", BRANCHES)
    assert q["questionId"] == TARGET_BRANCH_ID
    assert q["text"] == "Which branch should this change go into?"
    assert q["required"] is True and q["kind"] == "choice"
    opts = q["options"]
    assert opts[0]["value"] == "dev" and opts[0]["preselected"] is True
    assert "tracked by Actron's memory" in opts[0]["note"]
    others = [o["value"] for o in opts[1:-1]]
    assert others == ["release-2.3", "feat/a", "feat/b", "feat/c", "feat/d"]
    rel = next(o for o in opts if o["value"] == "release-2.3")
    assert "protected" in rel["note"] and "not tracked" in rel["note"]
    assert opts[-1]["label"] == "A new branch from dev"
    assert all(not o.get("preselected") for o in opts[1:])


def test_branch_question_without_branch_list() -> None:
    """B-AC-79: with no branch list (GitHub not connected) the working branch and new branch are still offered."""
    q = target_branch_question("main", [])
    assert [o["value"] for o in q["options"]] == ["main", "new:main"]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Add CSV export on release-2.3", "release-2.3"),
        ("Fix the login bug, merge into dev please", "dev"),
        ("Port the fix to `feat/a`", "feat/a"),
        ("Fix the main menu colours", None),
        ("Add export to the feature page", None),
        ("Target branch main: add a button", "main"),
    ],
)
def test_branch_named_in_text(text: str, expected: str | None) -> None:
    """B-AC-79: a request naming an existing branch skips the question; plain words do not count."""
    assert branch_named_in_text(text, [b.name for b in BRANCHES]) == expected


def test_apply_choice_and_text_answers() -> None:
    """B-AC-31: choice answers must match an option; a text answer naming any existing branch is accepted."""
    q = target_branch_question("dev", BRANCHES)
    qs = [q, {"questionId": "q1", "text": "Keep Finance-only?", "kind": "choice", "required": True,
              "options": [{"value": "yes", "label": "Yes"}, {"value": "no", "label": "No"}], "evidenceIds": []}]
    answers: dict[str, str] = {}
    apply_answer(qs, answers, "q1", "yes", branch_names=[b.name for b in BRANCHES])
    assert answers == {"q1": "yes"}
    assert not all_required_answered(qs, answers)
    apply_answer(qs, answers, TARGET_BRANCH_ID, "old", branch_names=[b.name for b in BRANCHES])
    assert answers[TARGET_BRANCH_ID] == "old"
    assert all_required_answered(qs, answers)
    apply_answer(qs, answers, "q1", "no", branch_names=[])
    assert answers["q1"] == "no"
    with pytest.raises(InvalidAnswer):
        apply_answer(qs, answers, "q1", "maybe", branch_names=[])
    with pytest.raises(InvalidAnswer):
        apply_answer(qs, answers, TARGET_BRANCH_ID, "nope", branch_names=["dev"])
    with pytest.raises(InvalidAnswer):
        apply_answer(qs, answers, "unknown", "x", branch_names=[])


def test_target_branch_from_answer() -> None:
    assert target_branch_from_answer("new:dev", "dev") == "dev"
    assert target_branch_from_answer("release-2.3", "dev") == "release-2.3"
    assert target_branch_from_answer(None, "dev") == "dev"


def test_finding_questions_capped_and_evidence_checked() -> None:
    """B-AC-30: at most 3 questions; evidence ids must exist in the findings."""
    qs = [{"questionId": f"q{i}", "text": f"Q{i}?", "kind": "choice", "required": True,
           "options": [{"value": "yes", "label": "Yes"}], "evidenceIds": ["e1", "missing"]} for i in range(5)]
    out = limit_finding_questions(qs, evidence_ids={"e1"})
    assert len(out) == 3
    assert all(q["evidenceIds"] == ["e1"] for q in out)
