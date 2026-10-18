"""The investigation label rule (spec B, B5). B-AC-26."""

from __future__ import annotations

from typing import Any

import pytest

from actron.flow.investigate import investigate
from actron.flow.labels import Thresholds, compute_label, conflict_label
from tests.integration.graph import fixture_graph as fx
from tests.integration.graph.fakes import EventLog, FakeJudge
from tests.integration.graph.fixture_graph import load_fixture_graph


def test_rule_produces_each_label() -> None:
    """B-AC-26: conflict, possible conflict (judgment or criticality), nothing found and clear."""
    base: dict[str, Any] = {"seed_count": 2, "decision_count": 1, "max_seed_criticality": 40.0}
    assert compute_label(restricts=[0.85], **base) == "conflict"
    assert compute_label(restricts=[0.8], **base) == "conflict"
    assert compute_label(restricts=[0.79], **base) == "possible_conflict"
    assert compute_label(restricts=[0.5], **base) == "possible_conflict"
    assert compute_label(restricts=[0.49], **base) == "clear"
    assert compute_label(restricts=[], seed_count=1, decision_count=0, max_seed_criticality=92.0) == \
        "possible_conflict"
    assert compute_label(restricts=[0.1], seed_count=1, decision_count=1, max_seed_criticality=92.0) == "clear"
    assert compute_label(restricts=[], seed_count=0, decision_count=0, max_seed_criticality=None) == "nothing_found"
    assert compute_label(restricts=[], seed_count=3, decision_count=0, max_seed_criticality=50.0) == "clear"


def test_thresholds_are_configurable(monkeypatch: pytest.MonkeyPatch) -> None:
    """B-AC-26: thresholds come from settings."""
    from actron.config import get_settings

    monkeypatch.setenv("CONFLICT_THRESHOLD", "0.9")
    monkeypatch.setenv("POSSIBLE_CONFLICT_THRESHOLD", "0.3")
    get_settings.cache_clear()
    try:
        th = Thresholds.from_settings()
    finally:
        get_settings.cache_clear()
    assert (th.conflict, th.possible) == (0.9, 0.3)
    assert conflict_label(0.85, th) == "possible_conflict"
    assert conflict_label(0.35, th) == "possible_conflict"
    assert compute_label(restricts=[0.85], seed_count=1, decision_count=1, max_seed_criticality=0.0,
                         thresholds=th) == "possible_conflict"


REQUESTS = [
    ("conflict", "Turn on auto-evaluate on save by default for every project.", {fx.D_SAVE: 0.92}),
    ("possible_conflict", "Let pretty printing of maps ignore the print width.", {fx.D_WIDTH: 0.65}),
    ("nothing_found", "Add Kubernetes deployment manifests with Helm charts.", {}),
    ("clear", "Show a progress spinner in the output window while results stream.",
     {fx.D_OUTPUT: 0.05, fx.D_INLINE: 0.1}),
]


@pytest.mark.integration
@pytest.mark.parametrize(("label", "text", "restricts"), REQUESTS, ids=[r[0] for r in REQUESTS])
async def test_label_on_fixture_requests(indexed_graph: Any, label: str, text: str,
                                         restricts: dict[str, float]) -> None:
    """B-AC-26: the four fixture requests get the four labels (J6 scripted, everything else real)."""
    load_fixture_graph(indexed_graph)
    res = await investigate(indexed_graph.workspace_id, f"req_{label}", text, "feature", emit=EventLog(),
                            mode="pipeline", store=indexed_graph, judge=FakeJudge(restricts), write=False)
    assert res.label == label, (res.findings.seeds, [(d.id, d.conflict) for d in res.findings.decisions])
