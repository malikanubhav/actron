"""Conservative stub answers used when neither Jev nor an LLM is available (spec A, A13).

Every stub is marked `stub: true`, has confidence 0.0 and is never cached.
"""

from __future__ import annotations

from typing import Any

from actron.models.questions import JevAsk
from actron.models.types import Judgment

STUB_MODEL = "stub"

# job -> (answer for choice jobs or None, probability)
STUB_ANSWERS: dict[str, tuple[Any, float]] = {
    "classify_message": ("chatter", 0.0),
    "is_approval": (None, 0.0),
    "judge_link": (None, 0.0),
    # A link check stub keeps the link but flags it "possible" (0.5): neither trust nor delete.
    "check_link": (None, 0.5),
    "rank_candidates": (None, 0.0),
    "judge_conflict": ("unrelated", 0.0),
    "judge_supersession": ("unrelated", 0.0),
    "classify_request": ("feature", 0.0),
    "needs_question": (None, 1.0),  # ask when unsure
    "is_scope_change": (None, 1.0),  # stop when unsure
    "feedback_kind": ("question", 0.0),  # never act on feedback without a person
}


def stub_judgment(job: str, primitive: str) -> Judgment:
    choice, prob = STUB_ANSWERS.get(job, (None, 0.0))
    answer: Any
    if primitive == "choice":
        answer = choice
    elif primitive == "score":
        answer = 0.0
    else:
        answer = prob >= 0.5
    return Judgment(
        job=job,
        answer=answer,
        probability=prob,
        probabilities=None,
        confidence=0.0,
        model=STUB_MODEL,
        provider="stub",
        cached=False,
        stub=True,
    )


def stub_judgments(ask: JevAsk) -> dict[str, Judgment]:
    return {qid: stub_judgment(ask.job, ask.primitive(qid)) for qid in ask.questions}
