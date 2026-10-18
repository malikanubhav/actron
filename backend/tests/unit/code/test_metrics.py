"""A-AC-35: caller counts, transitive callers and PageRank ordering on a known call graph, with the
algo.pageRank procedure and with the Python fallback. Also the shortest_path / bfs_callees helpers."""

from __future__ import annotations

from typing import Any

from actron.connectors.code.metrics import compute_metrics
from actron.graph import algos, ids
from actron.graph.store import LinkRow

REPO = "acme/metrics"
EDGES = [("a", "c"), ("b", "c"), ("c", "d"), ("e", "d"), ("f", "a"), ("t", "d")]


def _fid(name: str) -> str:
    return ids.code_fn(REPO, "m.py", name)


def _build(graph: Any) -> None:
    names = sorted({x for e in EDGES for x in e} | {"lonely"})
    graph.upsert_nodes("CodeFunction", [
        {"id": _fid(n), "name": n, "qualifiedName": n, "startLine": 1, "endLine": 2, "body": f"def {n}(): pass",
         "contentHash": n, "isTest": n == "t"} for n in names])
    graph.upsert_links("CALLS", "CodeFunction", "CodeFunction",
                       [LinkRow(_fid(a), _fid(b), {"method": "structural", "confidence": 1.0}) for a, b in EDGES])


def _props(graph: Any) -> dict[str, dict[str, Any]]:
    rows = graph.query("MATCH (f:CodeFunction) RETURN f.name AS n, f.callerCount AS c, f.transitiveCallerCount AS t, "
                       "f.pageRank AS pr, f.criticalityPercentile AS p")
    return {r["n"]: r for r in rows}


def test_metrics_with_procedure_and_fallback(indexed_graph: Any) -> None:
    """A-AC-35"""
    graph = indexed_graph
    _build(graph)
    res = compute_metrics(graph, use_procedure=True)
    assert res.pagerank_method == "procedure"
    p = _props(graph)
    assert {n: p[n]["c"] for n in "acd"} == {"a": 1, "c": 2, "d": 3}
    assert p["d"]["t"] == 6  # c, e, t, a, b, f within three hops
    assert p["c"]["t"] == 3 and p["lonely"]["t"] == 0
    order = sorted(p, key=lambda n: -p[n]["pr"])
    assert order[0] == "d" and order[1] == "c"
    assert p["d"]["p"] > p["c"]["p"] > p["lonely"]["p"]
    assert p["t"]["p"] == 0.0  # tests are not ranked
    procedure_order = order[:3]

    res2 = compute_metrics(graph, use_procedure=False)
    assert res2.pagerank_method == "python"
    p2 = _props(graph)
    assert sorted(p2, key=lambda n: -p2[n]["pr"])[:3] == procedure_order


def test_python_fallbacks_match() -> None:
    """A-AC-35"""
    pr = algos.pagerank_python(["x"], [("a", "b"), ("c", "b"), ("b", "d")])
    assert max(pr, key=lambda k: pr[k]) == "d"
    assert abs(sum(pr.values()) - 1.0) < 1e-6
    tc = algos.transitive_callers_python([("a", "b"), ("b", "c"), ("c", "d"), ("d", "e")], depth=3)
    assert tc["e"] == 3 and tc["b"] == 1
    assert algos.percentile_ranks({"a": 1.0, "b": 2.0, "c": 2.0}) == {"a": 16.67, "b": 66.67, "c": 66.67}


def test_shortest_path_and_callees(indexed_graph: Any) -> None:
    """A-AC-35"""
    graph = indexed_graph
    _build(graph)
    path = algos.shortest_path(graph, _fid("a"), _fid("e"), 6)  # a -> c -> d <- e (mixed directions)
    assert path is not None
    assert [n["id"] for n in path["nodes"]] == [_fid("a"), _fid("c"), _fid("d"), _fid("e")]
    fallback = algos._bfs_path(graph, _fid("a"), _fid("e"), 6)
    assert fallback is not None and [n["id"] for n in fallback["nodes"]] == [_fid(x) for x in "acde"]
    assert algos.shortest_path(graph, _fid("a"), _fid("lonely"), 4) is None
    assert algos.bfs_callees(graph, _fid("f"), 3) == sorted([_fid("a"), _fid("c"), _fid("d")])
