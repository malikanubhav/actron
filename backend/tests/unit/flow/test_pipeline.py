"""The fallback pipeline and investigation writes (spec B, B5). B-AC-25, B-AC-27, B-AC-28."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import jsonschema
import pytest

from actron.flow.findings import findings_json_schema
from actron.flow.investigate import investigate
from tests.integration.graph import fixture_graph as fx
from tests.integration.graph.fakes import EventLog, FakeJudge
from tests.integration.graph.fixture_graph import load_fixture_graph

pytestmark = pytest.mark.integration

SAVE_REQUEST = "Turn on auto-evaluate on save by default for every project."


@pytest.fixture
def g(indexed_graph: Any) -> Any:
    return load_fixture_graph(indexed_graph)


@pytest.fixture
def no_model_usage() -> Iterator[list[Any]]:
    """Collect model usage rows in memory instead of PostgreSQL."""
    from actron.models import usage

    rows: list[Any] = []
    usage.set_sink(usage.list_sink(rows))
    try:
        yield rows
    finally:
        usage.set_sink(None)


async def test_pipeline_with_stubs_only_gives_valid_findings(g: Any, no_model_usage: list[Any]) -> None:
    """B-AC-25: with no model keys (W4's stubs) the pipeline produces valid B.C3 findings on the fixture graph."""
    from actron.config import get_settings

    assert not get_settings().TYPESAFE_API_KEY and not get_settings().has_llm_key(), "test needs a key-free env"
    log = EventLog()
    res = await investigate(g.workspace_id, fx.REQUEST_ID, SAVE_REQUEST, "feature", emit=log, mode="auto", store=g)
    assert res.mode == "pipeline" and res.stub is True
    out = res.findings.to_json()
    jsonschema.validate(out, findings_json_schema())
    assert fx.EVAL_SAVE in {s["id"] for s in out["seeds"]}
    assert out["decisions"][0]["id"] == fx.D_SAVE
    # An approved decision that no model judged cannot be ruled out: possible conflict, never "conflict".
    assert out["decisions"][0]["conflict"] == {"label": "possible_conflict", "probability": 0.5}
    assert res.label == "possible_conflict"
    assert res.questions and res.questions[0].evidenceIds == [fx.D_SAVE]
    assert "Auto-evaluate on save stays off by default" in res.questions[0].text
    started = log.of("investigation.started")
    assert started == [{"mode": "pipeline", "reason": "No agent model is configured, so the deterministic pipeline ran."}]
    assert {r.provider for r in no_model_usage} <= {"stub"}


async def test_pipeline_events_in_order(g: Any) -> None:
    """B-AC-25: started, graph queries as tool calls, judgments, evidence, completed."""
    log = EventLog()
    res = await investigate(g.workspace_id, fx.REQUEST_ID, SAVE_REQUEST, "feature", emit=log, mode="pipeline",
                            store=g, judge=FakeJudge({fx.D_SAVE: 0.92}))
    types = log.types()
    assert types[0] == "investigation.started" and types[-1] == "investigation.completed"
    tools = [p["tool"] for p in log.of("tool.called")]
    assert tools == ["search", "decisions_for", "related_work", "impact", "criticality", "owners", "procedures_for"]
    assert len(log.of("tool.result")) == len(tools)
    assert all(p["by"] == "investigator" for p in log.of("tool.called"))
    jobs = [p["job"] for p in log.of("judgment.made")]
    assert jobs == ["rank_candidates", "judge_conflict", "needs_question"]
    assert log.of("judgment.made")[1] == {"job": "judge_conflict", "provider": "jev", "count": 1, "what": "decisions"}
    assert types.index("evidence.found") > types.index("judgment.made")
    first = log.of("evidence.found")[0]
    assert first["role"] == "conflict" and first["nodeId"] == fx.D_SAVE and first["path"][0] == fx.REQUEST
    assert first["source"]["author"] == "Alice Fixture"
    done = log.of("investigation.completed")[0]
    assert done["label"] == "conflict" and done["findingsRef"] == res.investigation_id
    assert done["counts"]["decisions"] == 1
    assert res.tool_calls == len(tools)


async def test_investigation_written_to_graph(g: Any) -> None:
    """B-AC-28: Investigation, HAS_INVESTIGATION, ABOUT (seeds) and FOUND with role, rank and path."""
    res = await investigate(g.workspace_id, fx.REQUEST_ID, SAVE_REQUEST, "feature", emit=EventLog(),
                            mode="pipeline", store=g, judge=FakeJudge({fx.D_SAVE: 0.92}))
    inv = g.query("MATCH (r:Request {id: $r})-[:HAS_INVESTIGATION]->(i:Investigation) RETURN i", {"r": fx.REQUEST})
    assert len(inv) == 1
    node = inv[0]["i"]
    assert node["id"] == res.investigation_id and node["conflictLabel"] == "conflict"
    assert node["summary"] == res.summary and node["toolCallCount"] == res.tool_calls and node["finishedAt"]
    about = {r["id"] for r in g.query("MATCH (:Request {id: $r})-[:ABOUT]->(s) RETURN s.id AS id", {"r": fx.REQUEST})}
    assert {s.id for s in res.findings.seeds} <= about
    found = g.query("MATCH (i:Investigation {id: $i})-[f:FOUND]->(e) RETURN e.id AS id, f.role AS role, "
                    "f.rank AS rank, f.path AS path ORDER BY f.rank", {"i": res.investigation_id})
    assert found[0]["id"] == fx.D_SAVE and found[0]["role"] == "conflict" and found[0]["rank"] == 1
    path = found[0]["path"]
    assert path[0] == fx.REQUEST and path[-1] == fx.D_SAVE and len(path) == 3
    assert path[1] in {s.id for s in res.findings.seeds}
    roles = {r["role"] for r in found}
    assert {"conflict", "impact", "similar_work", "test"} <= roles
    ranks = [r["rank"] for r in found]
    assert ranks == sorted(ranks) and len(set(ranks)) == len(ranks)
    # Running again adds a second investigation; the subgraph shows the latest one.
    from actron.graph import queries as Q

    sg = Q.subgraph_for_request(g, fx.REQUEST_ID, "expanded")
    assert fx.D_SAVE in {n.id for n in sg.nodes}


async def test_missing_request_node_is_created(g: Any) -> None:
    """B-AC-28: when the request is not mirrored in the graph yet, a minimal Request node is merged."""
    res = await investigate(g.workspace_id, "req_new", "Make prettyPrint faster.", "bug", emit=EventLog(),
                            mode="pipeline", store=g, judge=FakeJudge())
    rows = g.query("MATCH (r:Request {id: 'actron:request:req_new'})-[:HAS_INVESTIGATION]->(i) RETURN r, i.id AS i")
    assert rows and rows[0]["i"] == res.investigation_id and rows[0]["r"]["kind"] == "bug"


async def test_agent_failing_twice_falls_back_to_pipeline(g: Any) -> None:
    """B-AC-27: the agent fails twice, the pipeline runs, and investigation.started records the reason."""
    attempts: list[int] = []

    async def broken(messages: Any, tools: Any, **kw: Any) -> Any:
        attempts.append(1)
        raise RuntimeError("model unreachable")

    log = EventLog()
    res = await investigate(g.workspace_id, fx.REQUEST_ID, SAVE_REQUEST, "feature", emit=log, mode="auto",
                            store=g, judge=FakeJudge({fx.D_SAVE: 0.92}), complete=broken)
    assert len(attempts) == 2
    started = log.of("investigation.started")
    assert started[0] == {"mode": "agent"}
    assert started[1]["mode"] == "pipeline" and "failed twice" in started[1]["reason"]
    assert "model unreachable" in started[1]["reason"]
    assert res.mode == "pipeline" and res.fallback_reason and res.label == "conflict"


async def test_question_kind_asks_no_questions(g: Any) -> None:
    """B-AC-25: Q&A requests are investigated but never produce clarifying questions."""
    res = await investigate(g.workspace_id, "req_q", "Why does auto-evaluate on save stay off by default?",
                            "question", emit=EventLog(), mode="pipeline", store=g,
                            judge=FakeJudge({fx.D_SAVE: 0.9}), write=False)
    assert res.questions == [] and res.findings.decisions


async def test_nothing_found(g: Any) -> None:
    """B-AC-25: a request that matches nothing gives empty findings labelled nothing_found."""
    res = await investigate(g.workspace_id, "req_none", "Add Kubernetes deployment manifests with Helm charts.",
                            "feature", emit=EventLog(), mode="pipeline", store=g, judge=FakeJudge(), write=False)
    assert res.label == "nothing_found" and res.findings.seeds == [] and res.evidence == []
    assert res.summary == "Nothing in your history touches this."
