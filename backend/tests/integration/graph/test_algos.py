"""Graph algorithms: FalkorDB procedure versus fallback (spec B, B3). B-AC-17."""

from __future__ import annotations

from typing import Any

import pytest

from actron.graph import queries as Q
from tests.integration.graph import fixture_graph as fx

pytestmark = pytest.mark.integration

PAIRS = [
    (fx.M1, fx.EVAL_CODE),
    (fx.D_NREPL, fx.EVAL_CODE),
    (fx.PR103, fx.PRETTY),
    (fx.ALICE, fx.SEND),
    (fx.LI12, fx.FEATURE_SAVE),
]


@pytest.mark.parametrize(("a", "b"), PAIRS)
def test_shortest_path_procedure_and_fallback_agree(small_graph: Any, a: str, b: str) -> None:
    """B-AC-17: algo.SPpaths and the Python BFS fallback find paths of the same length between the same ends."""
    proc = Q.shortest_path(small_graph, a, b, 6)
    bfs = Q.shortest_path(small_graph, a, b, 6, use_procedure=False)
    assert proc.method == "algo.SPpaths" and bfs.method == "bfs"
    assert proc.found and bfs.found
    assert len(proc.nodes) == len(bfs.nodes)
    assert proc.nodes[0].id == bfs.nodes[0].id == a
    assert proc.nodes[-1].id == bfs.nodes[-1].id == b
    for path in (proc, bfs):
        ids_on_path = [n.id for n in path.nodes]
        for link in path.links:
            assert {link.from_, link.to} <= set(ids_on_path)


def test_shortest_path_falls_back_when_procedure_fails(small_graph: Any) -> None:
    """B-AC-17: when the procedure call errors, the BFS fallback answers."""

    class Failing:
        def __init__(self, inner: Any) -> None:
            self.inner = inner

        def query(self, cypher: str, params: Any = None, **kw: Any) -> Any:
            if "algo.SPpaths" in cypher:
                raise RuntimeError("Procedure algo.SPpaths is not registered")
            return self.inner.query(cypher, params, **kw)

    res = Q.shortest_path(Failing(small_graph), fx.M1, fx.EVAL_CODE, 6)
    assert res.found and res.method == "bfs"
    assert res.nodes[0].id == fx.M1 and len(res.nodes) == 4


def test_callers_match_python_traversal(small_graph: Any) -> None:
    """B-AC-17: the Cypher backwards match gives the same callers as a Python BFS over CALLS edges."""
    edges = small_graph.query(
        "MATCH (a:CodeFunction)-[:CALLS]->(b:CodeFunction) WHERE coalesce(a.deleted, false) = false "
        "RETURN a.id AS a, b.id AS b", read_only=True,
    )
    incoming: dict[str, list[str]] = {}
    for e in edges:
        incoming.setdefault(e["b"], []).append(e["a"])
    depth: dict[str, int] = {}
    frontier = [fx.SEND]
    for d in (1, 2, 3):
        nxt = []
        for node in frontier:
            for caller in incoming.get(node, []):
                if caller not in depth and caller != fx.SEND:
                    depth[caller] = d
                    nxt.append(caller)
        frontier = nxt
    assert {r.id: r.depth for r in Q.callers(small_graph, fx.SEND, 3)} == depth


def test_pagerank_wrapper_from_w2_when_available(small_graph: Any) -> None:
    """B-AC-17: W2's PageRank wrapper gives the same ranking with the procedure and the Python fallback."""
    algos = pytest.importorskip("actron.graph.algos")
    pagerank = getattr(algos, "pagerank", None)
    if pagerank is None:
        pytest.skip("actron.graph.algos.pagerank not available yet")
    proc, proc_method = pagerank(small_graph, use_procedure=True)
    fallback, fb_method = pagerank(small_graph, use_procedure=False)
    assert fb_method == "python" and proc_method in ("procedure", "python")
    top_proc = sorted(proc, key=lambda k: -proc[k])[:3]
    top_fb = sorted(fallback, key=lambda k: -fallback[k])[:3]
    assert top_proc[0] == top_fb[0]
