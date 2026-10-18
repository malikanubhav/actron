"""A-AC-79: noul, choice and score responses (documented fixtures) parse into `Judgment`."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from actron import models
from actron.models import jev
from actron.models.questions import j1_classify_message
from tests.fakes.jev import FakeJev

# Response bodies copied from https://docs.typesafe.ai/api.md (read 17 Oct 2026).
NOUL_DOC = {"type": "noul", "noul": 0.95}
CHOICE_DOC = {
    "type": "choice",
    "choice": "billing",
    "probabilities": {"billing": 0.88, "technical": 0.12, "sales": 0.0},
    "confidence": 0.81,
}
SCORE_DOC = {
    "type": "score",
    "score": 1.05,
    "legend": {"0": "Calm", "1": "Frustrated", "2": "Very angry"},
    "probabilities": {"0": 0.0, "1": 0.95, "2": 0.05},
    "confidence": 0.92,
}


def test_parse_documented_answers() -> None:
    """A-AC-79: field names as documented."""
    n = jev.parse_answer("q", "noul", NOUL_DOC)
    assert n.value == 0.95 and n.confidence is None
    c = jev.parse_answer("q", "choice", CHOICE_DOC)
    assert c.value == "billing" and c.probabilities == {
        "billing": 0.88,
        "technical": 0.12,
        "sales": 0.0,
    }
    assert c.confidence == 0.81
    s = jev.parse_answer("q", "score", SCORE_DOC)
    assert s.value == 1.05 and s.legend == {"0": "Calm", "1": "Frustrated", "2": "Very angry"}


@pytest.mark.parametrize(
    ("primitive", "raw"),
    [
        ("noul", {"type": "noul"}),
        ("noul", {"type": "noul", "noul": "high"}),
        ("choice", {"type": "choice", "probabilities": {}}),
        ("score", {"type": "score", "score": 1.0, "probabilities": "x"}),
        ("noul", {"type": "choice", "choice": "a", "probabilities": {}}),
        ("noul", "not an object"),
    ],
)
def test_parse_rejects_malformed(primitive: str, raw: Any) -> None:
    """A-AC-79: malformed answers raise a typed error."""
    with pytest.raises(jev.JevResponseError):
        jev.parse_answer("q", primitive, raw)


async def test_choice_judgment_fields(jev_on: Callable[..., FakeJev]) -> None:
    """A-AC-79: choice -> answer, probability of the answer, probabilities, confidence."""
    jev_on(choice="decision")
    j = await models.classify_message("We decided to keep it.", "slack", None)
    assert j.answer == "decision" and j.provider == "jev" and not j.stub
    assert j.probability == pytest.approx(0.8)
    assert j.probabilities is not None and set(j.probabilities) == set(
        j1_classify_message("x", "slack", None).questions["kind"]["criteria"]
    )
    assert j.confidence == pytest.approx(0.72)
    assert j.model == "jev-1.13.0"


async def test_noul_judgment_fields(jev_on: Callable[..., FakeJev]) -> None:
    """A-AC-79: noul -> probability and a boolean answer at 0.5."""
    jev_on(noul=0.91)
    j = await models.is_approval("d", "yes, agreed", False)
    assert j.probability == pytest.approx(0.91) and j.answer is True and j.job == "is_approval"


async def test_score_judgment_fields(jev_on: Callable[..., FakeJev]) -> None:
    """A-AC-79: score -> fractional level index, normalised probability."""
    jev_on(score=2.5)
    [j] = await models.rank_candidates("r", [models.CandidateSummary(id="a", summary="s")])
    assert j.answer == 2.5 and j.probability == pytest.approx(2.5 / 3)
    assert j.probabilities == {"0": 0.0, "1": 0.0, "2": 0.5, "3": 0.5}
