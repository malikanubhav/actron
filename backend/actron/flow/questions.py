"""Questions and answers, including the target-branch question (spec B, B6).

Pure functions only: the workflow imports this module, so no I/O here. Branch lists are fetched by activities.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

TARGET_BRANCH_ID = "target_branch"
NEW_BRANCH_PREFIX = "new:"
MAX_FINDING_QUESTIONS = 3
MAX_OTHER_BRANCHES = 5

# Words that may follow a branch name in a sentence without making it a different phrase ("into dev please").
_TRAILING_OK = {"branch", "please", "and", "then", "too", "as", "so", "because", "with", "for", "first", "only"}
_PREPOSITIONS = r"(?:on|into|to|against|onto|in|from|off)"


class InvalidAnswer(ValueError):
    """The answer does not fit the question (unknown question, or a value that is not an option)."""

    code = "invalid_answer"


@dataclass(frozen=True)
class Branch:
    name: str
    protected: bool = False
    updated_at: str | None = None


def target_branch_question(working_branch: str, branches: Sequence[Branch]) -> dict[str, Any]:
    """B6: working branch first and preselected, up to 5 recent others, then a new branch."""
    others = sorted(
        (b for b in branches if b.name != working_branch),
        key=lambda b: b.updated_at or "",
        reverse=True,
    )[:MAX_OTHER_BRANCHES]
    options: list[dict[str, Any]] = [
        {"value": working_branch, "label": working_branch, "note": "tracked by Actron's memory", "preselected": True}
    ]
    for b in others:
        note = "not tracked: Actron reads its differing files directly"
        if b.protected:
            note = "protected; " + note
        options.append({"value": b.name, "label": b.name, "note": note})
    options.append({
        "value": f"{NEW_BRANCH_PREFIX}{working_branch}",
        "label": f"A new branch from {working_branch}",
        "note": "Actron creates its own branch from the working branch",
    })
    return {
        "questionId": TARGET_BRANCH_ID,
        "text": "Which branch should this change go into?",
        "kind": "choice",
        "options": options,
        "evidenceIds": [],
        "required": True,
    }


def branch_named_in_text(text: str, branch_names: Iterable[str]) -> str | None:
    """The existing branch the request names ("on release-2.3", "into dev", "`feat/a`"), else None."""
    names = sorted({n for n in branch_names if n}, key=len, reverse=True)
    for name in names:
        esc = re.escape(name)
        quoted = rf"[`'\"]{esc}[`'\"]"
        if re.search(quoted, text):
            return name
        if re.search(rf"(?i)\bbranch\s+{esc}(?![\w/.-])", text) or re.search(rf"(?i)(?<![\w/.-]){esc}\s+branch\b", text):
            return name
        for m in re.finditer(rf"(?i)\b{_PREPOSITIONS}\s+(?:the\s+)?{esc}(?![\w/.-])", text):
            rest = text[m.end():]
            nxt = re.match(r"\s+([A-Za-z]+)", rest)
            if not rest.strip() or not nxt or rest[:1] in ".,;:!?)" or nxt.group(1).lower() in _TRAILING_OK:
                return name
    return None


def target_branch_from_answer(value: str | None, working_branch: str) -> str:
    """The ticket's targetBranch for an answer. A new branch starts from (and targets) the working branch."""
    if not value:
        return working_branch
    if value.startswith(NEW_BRANCH_PREFIX):
        return value[len(NEW_BRANCH_PREFIX):] or working_branch
    return value


def limit_finding_questions(questions: Sequence[dict[str, Any]], evidence_ids: set[str]) -> list[dict[str, Any]]:
    """B-AC-30: at most 3 questions, each tied only to evidence ids that exist in the findings."""
    out: list[dict[str, Any]] = []
    for q in questions[:MAX_FINDING_QUESTIONS]:
        item = dict(q)
        item["evidenceIds"] = [e for e in q.get("evidenceIds") or [] if e in evidence_ids]
        item.setdefault("kind", "choice" if item.get("options") else "text")
        item.setdefault("options", [])
        item.setdefault("required", True)
        out.append(item)
    return out


def apply_answer(
    questions: Sequence[dict[str, Any]],
    answers: dict[str, str],
    question_id: str,
    value: str,
    *,
    branch_names: Iterable[str],
) -> None:
    """Validate and record one answer in `answers` (replacing an earlier one)."""
    q = next((q for q in questions if q.get("questionId") == question_id), None)
    if q is None:
        raise InvalidAnswer(f"unknown question {question_id}")
    value = (value or "").strip()
    if not value:
        raise InvalidAnswer("empty answer")
    if q.get("kind") == "choice":
        option_values = {o.get("value") for o in q.get("options") or []}
        if value not in option_values:
            if question_id == TARGET_BRANCH_ID and value in set(branch_names):
                pass
            else:
                raise InvalidAnswer(f"{value!r} is not one of the options")
    answers[question_id] = value


def all_required_answered(questions: Sequence[dict[str, Any]], answers: dict[str, str]) -> bool:
    return all(q.get("questionId") in answers for q in questions if q.get("required", True))


def pending_questions(questions: Sequence[dict[str, Any]], answers: dict[str, str]) -> list[str]:
    return [str(q["questionId"]) for q in questions if q.get("questionId") not in answers]
