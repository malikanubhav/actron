"""A-AC-77: precision and recall of links and conflict judgments on the labelled fixtures.

- Explicit links: the reference patterns (A12.2), no model needed, always measured for real.
- Inferred links: J3 `judge_link` at thresholds 0.5..0.8 (A12.3).
- Conflicts: J6 `judge_conflict`; `conflict` at >= 0.8 `restricts`, any conflict at >= 0.5 (PRD 10.4).

Without TYPESAFE_API_KEY and LLM keys the model jobs return stubs; the result then says `"mode": "stub"` and the
numbers describe the stub, not the models. Results go to `.actron/eval/link_quality.json` (git-ignored) and are
copied into BUILD-LOG.md / BUILD-REPORT.md.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from actron import models
from actron.config import REPO_ROOT, get_settings
from actron.linking.references import RefContext, find_references

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
OUT = REPO_ROOT / ".actron" / "eval" / "link_quality.json"
THRESHOLDS = (0.5, 0.6, 0.7, 0.8)


def prf(pairs: list[tuple[bool, bool]]) -> dict[str, float | int | None]:
    """(predicted, label) pairs -> precision, recall, counts. Precision is None with no positive prediction."""
    tp = sum(p and y for p, y in pairs)
    fp = sum(p and not y for p, y in pairs)
    fn = sum(y and not p for p, y in pairs)
    return {
        "precision": round(tp / (tp + fp), 3) if tp + fp else None,
        "recall": round(tp / (tp + fn), 3) if tp + fn else None,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "n": len(pairs),
    }


def _mode() -> str:
    s = get_settings()
    if s.TYPESAFE_API_KEY:
        return "live-jev"
    if s.has_llm_key() and s.MODEL_DECISION:
        return "live-llm"
    return "stub"


@pytest.fixture(scope="module")
def link_cases() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load((FIXTURES / "link_labels.yaml").read_text())
    return data


@pytest.fixture(scope="module")
def conflict_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = yaml.safe_load((FIXTURES / "conflict_labels.yaml").read_text())[
        "cases"
    ]
    return cases


def test_fixture_sizes(link_cases: dict[str, Any], conflict_cases: list[dict[str, Any]]) -> None:
    """A-AC-77: at least 40 link cases and 30 conflict cases, never from data/sample/."""
    assert len(link_cases["cases"]) >= 40 and len(conflict_cases) >= 30
    assert len({c["id"] for c in link_cases["cases"]}) == len(link_cases["cases"])


def explicit_scores(link_cases: dict[str, Any]) -> dict[str, Any]:
    ctx = RefContext(
        repo=link_cases["context"]["repo"], team_keys=frozenset(link_cases["context"]["team_keys"])
    )
    pairs = []
    for case in (c for c in link_cases["cases"] if c["method"] == "explicit"):
        refs = find_references(case["text"], ctx)
        kind, key = case["expect"]["kind"], str(case["expect"]["key"])
        if case["label"]:
            predicted = any(r.kind == kind and r.key == key for r in refs)
        else:
            predicted = any(r.kind == kind for r in refs)
        pairs.append((predicted, bool(case["label"])))
    return prf(pairs)


async def inferred_scores(link_cases: dict[str, Any]) -> dict[str, Any]:
    probs: list[tuple[float, bool]] = []
    stub = False
    for case in (c for c in link_cases["cases"] if c["method"] == "inferred"):
        j = await models.judge_link(case["text"], models.Candidate(**case["candidate"]))
        stub = stub or j.stub
        probs.append((float(j.probability or 0.0), bool(case["label"])))
    return {
        "stub": stub,
        "by_threshold": {str(t): prf([(p >= t, y) for p, y in probs]) for t in THRESHOLDS},
    }


async def conflict_scores(conflict_cases: list[dict[str, Any]]) -> dict[str, Any]:
    rows: list[tuple[float, str]] = []
    stub = False
    for case in conflict_cases:
        j = await models.judge_conflict(case["request"], models.DecisionView(**case["decision"]))
        stub = stub or j.stub
        restricts = (j.probabilities or {}).get(
            "restricts", j.probability if j.answer == "restricts" else 0.0
        )
        rows.append((float(restricts or 0.0), case["label"]))
    s = get_settings()
    return {
        "stub": stub,
        "conflict_at_0.8": prf([(p >= s.CONFLICT_THRESHOLD, y == "conflict") for p, y in rows]),
        "any_conflict_at_0.5": prf(
            [(p >= s.POSSIBLE_CONFLICT_THRESHOLD, y != "none") for p, y in rows]
        ),
        "by_threshold": {str(t): prf([(p >= t, y != "none") for p, y in rows]) for t in THRESHOLDS},
    }


async def test_link_quality(
    link_cases: dict[str, Any], conflict_cases: list[dict[str, Any]]
) -> None:
    """A-AC-77: compute precision and recall; with stubs, say so."""
    from actron.models import cache, usage

    cache.set_enabled(False)
    usage.set_sink(usage.list_sink([]))
    try:
        result = {
            "mode": _mode(),
            "explicit": explicit_scores(link_cases),
            "inferred": await inferred_scores(link_cases),
            "conflicts": await conflict_scores(conflict_cases),
        }
    finally:
        cache.set_enabled(True)
        usage.set_sink(None)
    if result["mode"] == "stub":
        result["note"] = (
            "No model keys: inferred links and conflicts use stubs (probability 0.0), so they "
            "predict nothing. These numbers measure the stub, not Jev or an LLM."
        )
        assert result["inferred"]["stub"] and result["conflicts"]["stub"]
        assert result["inferred"]["by_threshold"]["0.6"]["tp"] == 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    explicit = result["explicit"]
    assert explicit["precision"] is not None and explicit["precision"] >= 0.9
    assert explicit["recall"] is not None and explicit["recall"] >= 0.9
