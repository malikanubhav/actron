"""Shared query (spec B, B.C3) and request subgraphs. B-AC-15: output validates and matches the snapshot."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from actron.flow.findings import Findings, findings_json_schema
from actron.graph import queries as Q
from tests.integration.graph import fixture_graph as fx

pytestmark = pytest.mark.integration

SNAPSHOT = Path(__file__).parent / "snapshots" / "shared_query_fixture.json"

# Appendix D, written out by hand so the test does not only check the model against itself.
APPENDIX_D_KEYS = {
    "requestId", "seeds", "decisions", "relatedWork", "impact", "owners", "procedures", "label", "graph",
}


def _run(small_graph: Any) -> dict[str, Any]:
    res = Q.shared_query(small_graph, fx.REQUEST_ID, [fx.EVAL_SAVE, fx.AUTO_EVAL, fx.FEATURE_SAVE],
                         {fx.EVAL_SAVE: 0.95, fx.AUTO_EVAL: 0.7, fx.FEATURE_SAVE: 0.6})
    return res.findings.to_json()


def test_shared_query_validates_against_bc3_schema(small_graph: Any) -> None:
    """B-AC-15: the output has exactly the appendix D keys and validates against the JSON schema."""
    out = _run(small_graph)
    assert set(out) == APPENDIX_D_KEYS
    jsonschema.validate(out, findings_json_schema())
    Findings.model_validate(out)
    assert out["requestId"] == fx.REQUEST
    assert set(out["impact"]) == {"callers", "tests", "criticality"}
    assert set(out["graph"]) == {"nodes", "edges"}
    for edge in out["graph"]["edges"]:
        assert set(edge) == {"from", "to", "type"}
    d = out["decisions"][0]
    assert {"id", "statement", "status", "quote", "source", "conflict", "path"} <= set(d)
    assert set(d["source"]) == {"id", "type", "url"}
    assert set(d["conflict"]) == {"label", "probability"}


def test_shared_query_ordering_limits_and_paths(small_graph: Any) -> None:
    """B-AC-15: seeds by score, decisions newest first, related work by recency, callers by depth then
    criticality; every list item has a path that starts at the request node."""
    out = _run(small_graph)
    assert [s["id"] for s in out["seeds"]] == [fx.EVAL_SAVE, fx.AUTO_EVAL, fx.FEATURE_SAVE]
    assert [d["id"] for d in out["decisions"]] == [fx.D_SAVE]
    assert out["decisions"][0]["path"][0] == fx.REQUEST
    assert {r["id"] for r in out["relatedWork"]} == {fx.PR101, fx.ISSUE55, fx.LI12, fx.M1}
    ats = [r["at"] for r in out["relatedWork"]]
    assert ats == sorted(ats, reverse=True)
    depths = [c["depth"] for c in out["impact"]["callers"]]
    assert depths == sorted(depths) and max(depths) <= 3 and len(depths) <= 50
    for section in ("seeds", "decisions", "relatedWork", "owners", "procedures"):
        for item in out[section]:
            assert item["path"][0] == fx.REQUEST, section
    for section in ("callers", "tests", "criticality"):
        for item in out["impact"][section]:
            assert item["path"][0] == fx.REQUEST, section
    assert len(out["owners"]) <= 5 and out["owners"][0]["personId"] == fx.ALICE
    assert [p["id"] for p in out["procedures"]] == [fx.PROC_EVAL]
    node_ids = {n["id"] for n in out["graph"]["nodes"]}
    assert len(node_ids) <= 300
    for section in ("seeds", "decisions", "relatedWork"):
        for item in out[section]:
            assert set(item["path"]) <= node_ids
    assert {(e["from"], e["to"]) for e in out["graph"]["edges"]} >= {(fx.REQUEST, fx.EVAL_SAVE)}


def test_shared_query_snapshot(small_graph: Any) -> None:
    """B-AC-15: the fixture request's findings match the stored snapshot (set UPDATE_SNAPSHOTS=1 to refresh)."""
    out = _run(small_graph)
    if os.environ.get("UPDATE_SNAPSHOTS") == "1" or not SNAPSHOT.exists():
        SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    assert out == json.loads(SNAPSHOT.read_text(encoding="utf-8"))


def test_shared_query_without_seeds_is_nothing_found(small_graph: Any) -> None:
    """B-AC-15: no seeds gives an empty, valid result labelled nothing_found; unknown and tombstoned ids drop."""
    out = Q.shared_query(small_graph, fx.REQUEST_ID, [fx.LEGACY, "code:fn:fixture/calva-lite:x.ts::missing"])
    js = out.findings.to_json()
    jsonschema.validate(js, findings_json_schema())
    assert js["label"] == "nothing_found" and js["seeds"] == [] and js["decisions"] == []


def test_shared_query_records_each_named_query(small_graph: Any) -> None:
    """B-AC-15: each named query is reported once with the node ids it returned (pipeline timeline)."""
    calls: list[tuple[str, list[str]]] = []
    Q.shared_query(small_graph, fx.REQUEST_ID, [fx.SEND], {fx.SEND: 1.0},
                   record=lambda tool, args, nodes, ms, err: calls.append((tool, nodes)))
    tools = [c[0] for c in calls]
    assert tools == ["decisions_for", "related_work", "impact", "criticality", "owners", "procedures_for"]
    assert dict(calls)["decisions_for"] == [fx.D_NREPL]


def test_shared_query_critical_seed_without_decision(small_graph: Any) -> None:
    """B-AC-15: a seed at the 95th percentile with no decision is labelled possible_conflict before judging."""
    out = Q.shared_query(small_graph, fx.REQUEST_ID, [fx.EVAL_CODE], {fx.EVAL_CODE: 1.0}).findings
    assert out.decisions == [] and out.label == "possible_conflict"
    assert out.impact.criticality[0].percentile == 95.0


def test_subgraph_for_request(small_graph: Any) -> None:
    """B-AC-14: subgraph_for_request returns the request, its ABOUT seeds, the latest investigation's FOUND
    nodes and their paths; aggregated mode groups by type above the budget."""
    small_graph.query(
        "MATCH (r:Request {id: $rid}) "
        "CREATE (i:Investigation {id: 'actron:investigation:fx1', summary: 's', conflictLabel: 'conflict', "
        "startedAt: '2026-10-17T09:01:00Z'}), (r)-[:HAS_INVESTIGATION {method: 'structural', confidence: 1.0}]->(i) "
        "WITH i MATCH (d:Decision {id: $d}) CREATE (i)-[:FOUND {method: 'structural', confidence: 1.0, role: 'conflict', "
        "rank: 1, path: [$rid, $s, $d]}]->(d) "
        "WITH i MATCH (pr:GithubPullRequest {id: $pr}) CREATE (i)-[:FOUND {method: 'structural', confidence: 1.0, "
        "role: 'similar_work', rank: 50, path: [$rid, $s, $pr]}]->(pr)",
        {"rid": fx.REQUEST, "d": fx.D_SAVE, "s": fx.EVAL_SAVE, "pr": fx.PR101},
    )
    sg = Q.subgraph_for_request(small_graph, fx.REQUEST_ID, "expanded")
    ids = [n.id for n in sg.nodes]
    assert ids[:2] == [fx.REQUEST, fx.EVAL_SAVE]
    assert fx.D_SAVE in ids and not sg.truncated
    assert any(lk.from_ == fx.D_SAVE and lk.to == fx.EVAL_SAVE and lk.type == "CONSTRAINS" for lk in sg.links)
    groups = {n.group for n in sg.nodes}
    assert {"core", "code"} <= groups
    small = Q.subgraph_for_request(small_graph, fx.REQUEST_ID, "aggregated", budget=2)
    assert small.mode == "aggregated"
    assert any(n.id.startswith("group:") and n.count for n in small.nodes)
    assert {fx.REQUEST, fx.EVAL_SAVE, fx.D_SAVE} <= {n.id for n in small.nodes}
    cut = Q.subgraph_for_request(small_graph, fx.REQUEST_ID, "expanded", budget=2)
    assert cut.truncated and len(cut.nodes) == 2
    assert Q.subgraph_for_request(small_graph, "req_missing").nodes == []


def test_aggregated_request_graph_keeps_tests_in_their_own_cluster(small_graph: Any) -> None:
    """B-AC-14: above the aggregation threshold, test functions collapse into a "N tests" cluster apart from
    other functions, and kept ids stay individual (a crowded request graph is never a hairball)."""
    ids = [
        "code:fn:fixture/calva-lite:src/evaluate.ts::evaluateCode",
        "code:fn:fixture/calva-lite:src/evaluate.ts::formatEvalResult",
        "code:fn:fixture/calva-lite:src/extension.ts::activate",
        "code:fn:fixture/calva-lite:src/extension-test/evaluate.test.ts::evaluate > evaluates a form",
    ]
    sg = Q.subgraph_for_ids(small_graph, ids, mode="aggregated", keep=[ids[0]], aggregate_above=2)
    by_id = {n.id: n for n in sg.nodes}
    assert ids[0] in by_id
    assert by_id["group:CodeFunction"].count == 2
    assert by_id["group:CodeFunction"].label == "2 functions"
    tests = by_id["group:CodeFunction:test"]
    assert tests.count == 1 and tests.label == "1 test"
    expanded = Q.subgraph_for_ids(small_graph, ids, mode="expanded", aggregate_above=2)
    assert len(expanded.nodes) == 4 and not expanded.truncated
