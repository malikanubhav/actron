"""Investigation evaluation on the fixture graph (spec B, B5). B-AC-29.

Each request in `tests/fixtures/eval/requests.yaml` runs through the pipeline twice: with the scripted J6
answers (the label a working model should give) and with the real model layer (live when keys exist,
stubs otherwise). Results are written to `.actron/eval/investigation_sample.json` (git-ignored) with the
mode, provider and label, so a live run can be compared with the stub run.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

from actron.config import REPO_ROOT, get_settings
from actron.flow.investigate import investigate
from tests.integration.graph.fakes import EventLog, FakeJudge
from tests.integration.graph.fixture_graph import load_fixture_graph

pytestmark = pytest.mark.integration

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "eval"
REQUESTS = yaml.safe_load((FIXTURES / "requests.yaml").read_text(encoding="utf-8"))["requests"]
QA = yaml.safe_load((FIXTURES / "qa.yaml").read_text(encoding="utf-8"))["questions"]
RESULTS = REPO_ROOT / ".actron" / "eval" / "investigation_sample.json"
_recorded: list[dict[str, Any]] = []


@pytest.fixture(scope="module", autouse=True)
def record_results() -> Iterator[None]:
    yield
    if _recorded:
        RESULTS.parent.mkdir(parents=True, exist_ok=True)
        RESULTS.write_text(json.dumps(_recorded, indent=2) + "\n", encoding="utf-8")


@pytest.fixture
def g(indexed_graph: Any) -> Any:
    return load_fixture_graph(indexed_graph)


@pytest.fixture
def usage_rows() -> Iterator[list[Any]]:
    from actron.models import usage

    rows: list[Any] = []
    usage.set_sink(usage.list_sink(rows))
    try:
        yield rows
    finally:
        usage.set_sink(None)


def test_every_label_is_covered() -> None:
    """B-AC-29: the evaluation set has at least one request per label."""
    assert {r["expected_label"] for r in REQUESTS} == {"conflict", "possible_conflict", "nothing_found", "clear"}
    assert len(QA) >= 3


@pytest.mark.parametrize("item", REQUESTS, ids=[r["id"] for r in REQUESTS])
async def test_expected_label_with_scripted_judgments(g: Any, item: dict[str, Any]) -> None:
    """B-AC-29: with J6 answering as scripted, each request gets its expected label, seeds and decisions."""
    res = await investigate(g.workspace_id, f"req_eval_{item['id']}", item["text"], item["kind"], emit=EventLog(),
                            mode="pipeline", store=g, judge=FakeJudge(item.get("judgments") or {}), write=False)
    seeds = {s.id for s in res.findings.seeds}
    decisions = {d.id for d in res.findings.decisions}
    _recorded.append({"id": item["id"], "run": "scripted_j6", "label": res.label, "expected": item["expected_label"],
                      "seeds": sorted(seeds), "decisions": sorted(decisions)})
    assert res.label == item["expected_label"]
    assert set(item.get("expected_seeds") or []) <= seeds
    assert set(item.get("expected_decisions") or []) <= decisions
    if res.label in ("conflict", "possible_conflict") and item["kind"] != "question":
        assert res.questions, "a conflict should lead to at least one evidence-tied question"
        assert all(set(q.evidenceIds) <= res.findings.node_ids() for q in res.questions)


@pytest.mark.parametrize("item", REQUESTS, ids=[r["id"] for r in REQUESTS])
async def test_label_with_model_layer(g: Any, item: dict[str, Any], usage_rows: list[Any]) -> None:
    """B-AC-29: the real model layer (stubs without keys) gives the recorded stub label; live runs are
    recorded with their provider for comparison."""
    res = await investigate(g.workspace_id, f"req_eval_{item['id']}", item["text"], item["kind"], emit=EventLog(),
                            mode="pipeline", store=g, write=False)
    live = bool(get_settings().TYPESAFE_API_KEY or get_settings().has_llm_key())
    providers = sorted({r.provider for r in usage_rows})
    _recorded.append({"id": item["id"], "run": "live" if live else "stub", "label": res.label,
                      "expected": item["expected_label"], "expected_stub": item["expected_stub_label"],
                      "providers": providers, "stub": res.stub})
    if live:
        pytest.skip(f"live run recorded: {res.label} (expected {item['expected_label']})")
    assert res.stub is True
    assert res.label == item["expected_stub_label"]


@pytest.mark.parametrize("item", QA, ids=[q["id"] for q in QA])
async def test_qa_questions_find_their_citations(g: Any, item: dict[str, Any]) -> None:
    """B-AC-29 (Q&A sample): investigating a question finds the nodes a good answer must cite."""
    res = await investigate(g.workspace_id, f"req_qa_{item['id']}", item["text"], "question", emit=EventLog(),
                            mode="pipeline", store=g, judge=FakeJudge(), write=False)
    cited = res.findings.node_ids()
    _recorded.append({"id": item["id"], "run": "qa", "label": res.label, "found": sorted(set(item["must_cite"]) & cited)})
    assert set(item["must_cite"]) <= cited
    assert res.questions == []
