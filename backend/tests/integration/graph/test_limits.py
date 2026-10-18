"""Depth, row and time limits on a large synthetic call graph (spec B, B3). B-AC-16."""

from __future__ import annotations

import random
import time
from typing import Any

import pytest

from actron.graph import queries as Q
from actron.graph.store import GraphTimeout

pytestmark = [pytest.mark.integration, pytest.mark.slow]

N_FUNCTIONS = 10_000
N_EDGES = 50_000
REPO = "synthetic/limits"


def _fn(i: int) -> str:
    return f"code:fn:{REPO}:src/m{i % 50}.ts::f{i}"


@pytest.fixture
def big_graph(indexed_graph: Any) -> Any:
    rng = random.Random(16)
    nodes = [{"id": _fn(i), "name": f"f{i}", "qualifiedName": f"f{i}", "startLine": 1, "endLine": 3,
              "body": f"function f{i}() {{ return helper{i % 7}(); }}", "contentHash": f"h{i}",
              "criticalityPercentile": float(i % 100)} for i in range(N_FUNCTIONS)]
    for start in range(0, N_FUNCTIONS, 2000):
        indexed_graph.query("UNWIND $rows AS r CREATE (f:CodeFunction) SET f = r", {"rows": nodes[start:start + 2000]},
                            timeout_ms=60000)
    # Function 0 is a hub: many callers, so deep caller queries produce very many paths.
    pairs = [(rng.randrange(1, N_FUNCTIONS), 0) for _ in range(500)]
    while len(pairs) < N_EDGES:
        a, b = rng.randrange(N_FUNCTIONS), rng.randrange(N_FUNCTIONS)
        if a != b:
            pairs.append((a, b))
    for start in range(0, len(pairs), 5000):
        batch = [{"a": _fn(a), "b": _fn(b)} for a, b in pairs[start:start + 5000]]
        indexed_graph.query(
            "UNWIND $rows AS r MATCH (a:CodeFunction {id: r.a}), (b:CodeFunction {id: r.b}) "
            "CREATE (a)-[:CALLS {method: 'structural', confidence: 1.0, callSiteLines: [2]}]->(b)",
            {"rows": batch}, timeout_ms=60000,
        )
    return indexed_graph


def test_synthetic_graph_has_50000_edges(big_graph: Any) -> None:
    """B-AC-16: the synthetic graph really has 50,000 CALLS edges."""
    res = big_graph.query("MATCH ()-[r:CALLS]->() RETURN count(r) AS c", read_only=True)
    assert res[0]["c"] == N_EDGES


def test_callers_on_hub_respects_row_and_time_limits(big_graph: Any) -> None:
    """B-AC-16: callers of a hub at depth 3 return at most the row limit within the 2 s timeout, or the
    query is stopped by the timeout (never runs unbounded)."""
    started = time.monotonic()
    try:
        rows = Q.callers(big_graph, _fn(0), 3, limit=200, timeout_ms=Q.TOOL_TIMEOUT_MS)
    except GraphTimeout:
        rows = None
    elapsed = time.monotonic() - started
    assert elapsed < Q.TOOL_TIMEOUT_MS / 1000 + 1.5
    if rows is not None:
        assert 0 < len(rows) <= 200
        assert all(1 <= r.depth <= 3 for r in rows)


def test_depth_is_clamped(big_graph: Any) -> None:
    """B-AC-16: depth above 3 is clamped to 3; row limits above 200 are clamped to 200."""
    rows = Q.callers(big_graph, _fn(5), 9, limit=10_000, timeout_ms=Q.TOOL_TIMEOUT_MS)
    assert len(rows) <= Q.MAX_ROWS
    assert all(r.depth <= 3 for r in rows)


def test_tiny_timeout_raises_typed_error(big_graph: Any) -> None:
    """B-AC-16: a query that cannot finish in its timeout raises GraphTimeout."""
    with pytest.raises(GraphTimeout):
        big_graph.query(
            "MATCH p = (f:CodeFunction)<-[:CALLS*1..4]-(c:CodeFunction) RETURN count(p) AS c",
            read_only=True, timeout_ms=5,
        )


def test_impact_and_shortest_path_bounded(big_graph: Any) -> None:
    """B-AC-16: impact and shortest path stay within limits on the large graph."""
    started = time.monotonic()
    try:
        res = Q.impact(big_graph, [_fn(7)], 2, limit=50, timeout_ms=Q.TOOL_TIMEOUT_MS)
        assert len(res.functions) <= 50
    except GraphTimeout:
        pass
    assert time.monotonic() - started < 3 * Q.TOOL_TIMEOUT_MS / 1000 + 2
    path = Q.shortest_path(big_graph, _fn(1), _fn(2), 6, timeout_ms=Q.TOOL_TIMEOUT_MS)
    assert len(path.nodes) <= 7


def test_fulltext_limit(big_graph: Any, ontology: Any) -> None:
    """B-AC-16: full-text seeds honour the limit."""
    rows = Q.seeds_fulltext(big_graph, "helper3 function", search_fields=ontology.search_fields(),
                            types=["CodeFunction"], limit=20)
    assert 0 < len(rows) <= 20
