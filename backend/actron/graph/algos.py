"""Graph algorithms over FalkorDB with Python fallbacks (PRD 7.3, spec A, A6.9).

- PageRank: `CALL algo.pageRank('Label', 'REL') YIELD node, score`; fallback power iteration (damping 0.85,
  30 iterations, tolerance 1e-6) over the exported edge list.
- Callers: backwards variable-length match `(f)<-[:CALLS*1..3]-(c)` (`algo.BFS` follows outgoing links only).
- Shortest path: `algo.SPpaths({sourceNode, targetNode, relDirection: 'both', maxLen})`; fallback Python BFS.
- Callees: `algo.BFS(node, depth, 'CALLS')`; fallback forward variable-length match.
"""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Iterable, Sequence
from typing import Any

from actron.graph import ids
from actron.graph.store import GraphError, GraphStore
from actron.logging import get_logger

log = get_logger(__name__)
PAGE = 5000


def _label(node_id: str) -> str:
    return ids.label_of(node_id)


def edge_list(store: GraphStore, label: str = "CodeFunction", rel: str = "CALLS") -> list[tuple[str, str]]:
    store._rel(rel, label, label)
    out: list[tuple[str, str]] = []
    skip = 0
    while True:
        rows = store.query(
            f"MATCH (a:`{label}`)-[r:`{rel}`]->(b:`{label}`) RETURN a.id AS a, b.id AS b ORDER BY a, b "
            "SKIP $s LIMIT $l", {"s": skip, "l": PAGE}, read_only=True, timeout_ms=60000)
        out.extend((r["a"], r["b"]) for r in rows)
        if len(rows) < PAGE:
            return out
        skip += PAGE


def node_ids(store: GraphStore, label: str = "CodeFunction") -> list[str]:
    store._label(label)
    out: list[str] = []
    skip = 0
    while True:
        rows = store.query(f"MATCH (n:`{label}`) RETURN n.id AS id ORDER BY id SKIP $s LIMIT $l",
                           {"s": skip, "l": PAGE}, read_only=True, timeout_ms=60000)
        out.extend(r["id"] for r in rows)
        if len(rows) < PAGE:
            return out
        skip += PAGE


def pagerank_python(nodes: Iterable[str], edges: Sequence[tuple[str, str]], damping: float = 0.85,
                    iterations: int = 30, tol: float = 1e-6) -> dict[str, float]:
    all_nodes = list(dict.fromkeys([*nodes, *(a for a, _ in edges), *(b for _, b in edges)]))
    n = len(all_nodes)
    if n == 0:
        return {}
    out_links: dict[str, list[str]] = defaultdict(list)
    for a, b in edges:
        out_links[a].append(b)
    rank = dict.fromkeys(all_nodes, 1.0 / n)
    for _ in range(iterations):
        dangling = sum(rank[v] for v in all_nodes if not out_links.get(v))
        new = dict.fromkeys(all_nodes, (1.0 - damping) / n + damping * dangling / n)
        for a, targets in out_links.items():
            share = damping * rank[a] / len(targets)
            for b in targets:
                new[b] += share
        delta = sum(abs(new[v] - rank[v]) for v in all_nodes)
        rank = new
        if delta < tol:
            break
    return rank


def pagerank(store: GraphStore, label: str = "CodeFunction", rel: str = "CALLS", *,
             use_procedure: bool = True) -> tuple[dict[str, float], str]:
    """Scores per node id and which method produced them (`procedure` or `python`)."""
    store._rel(rel, label, label)
    if use_procedure:
        try:
            scores: dict[str, float] = {}
            skip = 0
            while True:
                rows = store.query(
                    f"CALL algo.pageRank('{label}', '{rel}') YIELD node, score "
                    "RETURN node.id AS id, score ORDER BY id SKIP $s LIMIT $l",
                    {"s": skip, "l": PAGE}, read_only=True, timeout_ms=60000)
                scores.update({r["id"]: float(r["score"]) for r in rows})
                if len(rows) < PAGE:
                    return scores, "procedure"
                skip += PAGE
        except GraphError as exc:
            log.warning("algo.pageRank failed; using the Python fallback", extra={"error": str(exc)})
    return pagerank_python(node_ids(store, label), edge_list(store, label, rel)), "python"


def caller_counts(store: GraphStore) -> dict[str, int]:
    out: dict[str, int] = {}
    skip = 0
    while True:
        rows = store.query(
            "MATCH (c:CodeFunction)-[:CALLS]->(f:CodeFunction) WHERE c <> f "
            "WITH f, count(DISTINCT c) AS n RETURN f.id AS id, n ORDER BY id SKIP $s LIMIT $l",
            {"s": skip, "l": PAGE}, read_only=True, timeout_ms=60000)
        out.update({r["id"]: int(r["n"]) for r in rows})
        if len(rows) < PAGE:
            return out
        skip += PAGE


def transitive_caller_counts(store: GraphStore, depth: int = 3) -> dict[str, int]:
    out: dict[str, int] = {}
    skip = 0
    while True:
        rows = store.query(
            f"MATCH (f:CodeFunction)<-[:CALLS*1..{int(depth)}]-(c:CodeFunction) WHERE c <> f "
            "WITH f, count(DISTINCT c) AS n RETURN f.id AS id, n ORDER BY id SKIP $s LIMIT $l",
            {"s": skip, "l": PAGE}, read_only=True, timeout_ms=60000)
        out.update({r["id"]: int(r["n"]) for r in rows})
        if len(rows) < PAGE:
            return out
        skip += PAGE


def transitive_callers_python(edges: Sequence[tuple[str, str]], depth: int = 3) -> dict[str, int]:
    callers: dict[str, set[str]] = defaultdict(set)
    for a, b in edges:
        callers[b].add(a)
    out: dict[str, int] = {}
    for f in list(callers):
        seen: set[str] = set()
        frontier = {f}
        for _ in range(depth):
            nxt = set()
            for x in frontier:
                nxt |= callers.get(x, set())
            nxt -= seen
            seen |= nxt
            frontier = nxt
        seen.discard(f)
        out[f] = len(seen)
    return out


def percentile_ranks(values: dict[str, float]) -> dict[str, float]:
    """Mid-rank percentile (0-100): ties share the same value."""
    if not values:
        return {}
    ordered = sorted(values.values())
    n = len(ordered)
    from bisect import bisect_left, bisect_right

    return {k: round(100.0 * (bisect_left(ordered, v) + 0.5 * (bisect_right(ordered, v) - bisect_left(ordered, v))) / n, 2)
            for k, v in values.items()}


def shortest_path(store: GraphStore, a: str, b: str, max_len: int = 6) -> dict[str, Any] | None:
    """Undirected shortest path between two nodes: `{"nodes": [...], "edges": [...], "method": ...}`."""
    la, lb = _label(a), _label(b)
    store._label(la)
    store._label(lb)
    try:
        rows = store.query(
            f"MATCH (s:`{la}` {{id: $a}}), (t:`{lb}` {{id: $b}}) "
            "CALL algo.SPpaths({sourceNode: s, targetNode: t, relDirection: 'both', maxLen: $m}) "
            "YIELD path RETURN path LIMIT 1", {"a": a, "b": b, "m": int(max_len)}, read_only=True, timeout_ms=30000)
        if rows:
            path = rows[0]["path"]
            return {"nodes": path["nodes"], "edges": path["edges"], "method": "procedure"}
        return None
    except GraphError as exc:
        log.warning("algo.SPpaths failed; using Python BFS", extra={"error": str(exc)})
    return _bfs_path(store, a, b, max_len)


def _bfs_path(store: GraphStore, a: str, b: str, max_len: int) -> dict[str, Any] | None:
    prev: dict[str, tuple[str, dict[str, Any]] | None] = {a: None}
    q: deque[tuple[str, int]] = deque([(a, 0)])
    while q:
        cur, d = q.popleft()
        if cur == b:
            break
        if d >= max_len:
            continue
        label = _label(cur)
        rows = store.query(
            f"MATCH (n:`{label}` {{id: $id}})-[r]-(m) RETURN m.id AS id, type(r) AS t, startNode(r).id AS s LIMIT 500",
            {"id": cur}, read_only=True)
        for r in rows:
            nid = r["id"]
            if nid is None or nid in prev:
                continue
            prev[nid] = (cur, {"_type": r["t"], "from": r["s"], "to": nid if r["s"] == cur else cur})
            q.append((nid, d + 1))
    if b not in prev:
        return None
    nodes: list[str] = []
    edges: list[dict[str, Any]] = []
    cur2: str | None = b
    while cur2 is not None:
        nodes.append(cur2)
        step = prev[cur2]
        if step is None:
            break
        edges.append(step[1])
        cur2 = step[0]
    nodes.reverse()
    edges.reverse()
    return {"nodes": [store.get_node(n) or {"id": n} for n in nodes], "edges": edges, "method": "python"}


def bfs_callees(store: GraphStore, fn_id: str, depth: int = 3) -> list[str]:
    """Function ids reachable from `fn_id` over outgoing CALLS within `depth` hops."""
    try:
        rows = store.query(
            "MATCH (f:CodeFunction {id: $id}) CALL algo.BFS(f, $d, 'CALLS') YIELD nodes "
            "UNWIND nodes AS n RETURN DISTINCT n.id AS id", {"id": fn_id, "d": int(depth)}, read_only=True)
        return sorted(r["id"] for r in rows if r["id"] != fn_id)
    except GraphError as exc:
        log.warning("algo.BFS failed; using a variable-length match", extra={"error": str(exc)})
    rows = store.query(
        f"MATCH (f:CodeFunction {{id: $id}})-[:CALLS*1..{int(depth)}]->(c:CodeFunction) RETURN DISTINCT c.id AS id",
        {"id": fn_id}, read_only=True)
    return sorted(r["id"] for r in rows if r["id"] != fn_id)
