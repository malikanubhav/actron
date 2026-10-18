"""Jev question catalog J1-J10 (spec A, A.C4). Builders return the exact `state` and `questions`.

Question ids (`kind`, `approves`, ...) are for code only; Jev does not use them for inference.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

Primitive = Literal["noul", "choice", "score"]
JsonDict = dict[str, Any]

MESSAGE_SOURCES = (
    "slack",
    "github_pr",
    "github_review_comment",
    "github_issue",
    "linear_issue",
    "linear_comment",
)

J1_CRITERIA: dict[str, str] = {
    "decision": "States how the software should or should not behave, or settles a choice",
    "proposal": "Suggests a way the software should behave, without settling it",
    "question": "Asks for information",
    "request": "Asks for a feature or change to be built",
    "bug_report": "Reports something broken",
    "status_update": "Reports progress or what someone did",
    "chatter": "Social talk, thanks, jokes or anything off-topic",
}
J5_LEVELS = [
    "unrelated",
    "same area of the code",
    "directly involved in the change",
    "the exact place to change",
]
J6_CRITERIA: dict[str, str] = {
    "restricts": "Doing the request as written would break or contradict the decision",
    "supports": "The decision agrees with or enables the request",
    "unrelated": "The decision does not affect the request",
    "superseded_by_request": "The request explicitly replaces the decision",
}
J7_CRITERIA: dict[str, str] = {
    "feature": "Asks for new behaviour",
    "bug": "Reports broken behaviour to fix",
    "question": "Asks for an explanation or information, not a change",
}
J10_CRITERIA: dict[str, str] = {
    "code_change_within_scope": "Asks for a code change that stays within the approved ticket",
    "scope_change": "Asks for something the approved ticket does not cover",
    "question": "Asks for an explanation or information",
    "approval": "Approves the pull request as it is",
}
SUPERSESSION_CRITERIA: dict[str, str] = {
    "replaces": "The later decision replaces the earlier one, fully or for part of what it covers",
    "supports": "The later decision agrees with or extends the earlier one",
    "unrelated": "The two decisions are about different things",
}
MAX_RANK_CANDIDATES = 20


@dataclass(frozen=True)
class JevAsk:
    """One Jev request: a state and the questions asked over it."""

    job: str
    state: JsonDict
    questions: JsonDict

    def primitive(self, qid: str) -> Primitive:
        kind: Primitive = self.questions[qid]["type"]
        return kind

    def body(self, model: str) -> JsonDict:
        return {"model": model, "state": self.state, "questions": self.questions}


def j1_classify_message(text: str, source: str, thread_parent_text: str | None) -> JevAsk:
    if source not in MESSAGE_SOURCES:
        raise ValueError(f"unknown message source {source!r}")
    return JevAsk(
        "classify_message",
        {"text": text, "source": source, "thread_parent_text": thread_parent_text},
        {
            "kind": {
                "type": "choice",
                "instructions": "What is this text mainly doing in a software team's conversation?",
                "criteria": dict(J1_CRITERIA),
            }
        },
    )


def j2_is_approval(decision: str, reply: str, same_author: bool) -> JevAsk:
    return JevAsk(
        "is_approval",
        {"decision": decision, "reply": reply, "reply_author_is_decision_author": same_author},
        {
            "approves": {
                "type": "noul",
                "instructions": (
                    "Does the reply explicitly approve or agree to adopt the decision in "
                    "`decision`? "
                    "Polite acknowledgement without agreement is not approval."
                ),
                "criteria": {
                    "true": "The reply clearly agrees the decision should be adopted",
                    "false": "Anything else",
                },
            }
        },
    )


def j3_candidate_state(candidate: Any) -> JsonDict:
    doc = candidate.docstring
    return {
        "kind": candidate.kind,
        "name": candidate.name,
        "path": candidate.path,
        "signature": candidate.signature,
        "docstring": doc[:400] if doc else None,
    }


J3_QUESTION: JsonDict = {
    "refers": {
        "type": "noul",
        "instructions": (
            "Does `text` talk about the code or feature described in `candidate`, "
            "even if it does not name it?"
        ),
    }
}


def j3_judge_link(text: str, candidate: Any) -> JevAsk:
    return JevAsk(
        "judge_link",
        {"text": text, "candidate": j3_candidate_state(candidate)},
        {"refers": dict(J3_QUESTION["refers"])},
    )


def j3_judge_links(text: str, candidates: list[Any]) -> JevAsk:
    """J3 batched: one request per text, one `noul` per candidate (ids `c0`..), all in the state.

    With a single candidate this is exactly the A.C4 J3 form.
    """
    if len(candidates) == 1:
        return j3_judge_link(text, candidates[0])
    return JevAsk(
        "judge_link",
        {
            "text": text,
            "candidates": [
                {"id": f"c{i}", **j3_candidate_state(c)} for i, c in enumerate(candidates)
            ],
        },
        {
            f"c{i}": {
                "type": "noul",
                "instructions": (
                    "Does `text` talk about the code or feature described in "
                    f"candidate c{i} in `candidates`, even if it does not name it?"
                ),
            }
            for i in range(len(candidates))
        },
    )


def j4_check_link(quote: str, claim: str) -> JevAsk:
    return JevAsk(
        "check_link",
        {"quote": quote, "claim": claim},
        {
            "supported": {
                "type": "noul",
                "instructions": "Does `quote` support `claim` exactly as stated?",
            }
        },
    )


def j5_rank_candidates(request: str, candidates: list[Any]) -> JevAsk:
    items = candidates[:MAX_RANK_CANDIDATES]
    state_items = [{"id": f"c{i}", "summary": c.summary} for i, c in enumerate(items)]
    questions = {
        f"c{i}": {
            "type": "score",
            "instructions": f"How relevant is candidate c{i} in `candidates` to `request`?",
            "criteria": list(J5_LEVELS),
        }
        for i in range(len(items))
    }
    return JevAsk("rank_candidates", {"request": request, "candidates": state_items}, questions)


def j6_judge_conflict(request: str, decision: Any) -> JevAsk:
    return JevAsk(
        "judge_conflict",
        {
            "request": request,
            "decision": {
                "statement": decision.statement,
                "quote": decision.quote,
                "status": decision.status,
            },
        },
        {
            "relation": {
                "type": "choice",
                "instructions": "How does `decision` relate to what `request` asks for?",
                "criteria": dict(J6_CRITERIA),
            }
        },
    )


def j6b_judge_supersession(earlier: JsonDict, later: JsonDict) -> JevAsk:
    """A12.4: does a later decision replace an earlier one (J6-style, state `{earlier, later}`)."""
    return JevAsk(
        "judge_supersession",
        {"earlier": earlier, "later": later},
        {
            "relation": {
                "type": "choice",
                "instructions": "How does the `later` decision relate to the `earlier` decision?",
                "criteria": dict(SUPERSESSION_CRITERIA),
            }
        },
    )


def j7_classify_request(text: str) -> JevAsk:
    return JevAsk(
        "classify_request",
        {"request": text},
        {
            "kind": {
                "type": "choice",
                "instructions": "What kind of message is `request`?",
                "criteria": dict(J7_CRITERIA),
            }
        },
    )


def j8_needs_question(summary: str, conflicts: list[str], max_criticality: float) -> JevAsk:
    return JevAsk(
        "needs_question",
        {
            "findings_summary": summary,
            "conflicts": list(conflicts),
            "max_criticality_percentile": max_criticality,
        },
        {
            "needs_input": {
                "type": "noul",
                "instructions": (
                    "Is a product decision from a person needed before this can be "
                    "implemented safely?"
                ),
            }
        },
    )


def j9_is_scope_change(ticket: JsonDict, diff_summary: str, outside_files: list[str]) -> JevAsk:
    return JevAsk(
        "is_scope_change",
        {
            "ticket": ticket,
            "diff_summary": diff_summary,
            "files_outside_affected_list": list(outside_files),
        },
        {
            "scope_change": {
                "type": "noul",
                "instructions": (
                    "Does the proposed change go beyond the approved acceptance criteria "
                    "in `ticket`?"
                ),
            }
        },
    )


def j10_feedback_kind(feedback: str, ticket: JsonDict) -> JevAsk:
    return JevAsk(
        "feedback_kind",
        {"feedback": feedback, "ticket": ticket},
        {
            "kind": {
                "type": "choice",
                "instructions": "What is `feedback` asking for, given the approved `ticket`?",
                "criteria": dict(J10_CRITERIA),
            }
        },
    )
