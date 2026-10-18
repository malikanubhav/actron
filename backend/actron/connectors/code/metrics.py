"""Caller counts, transitive callers, PageRank and criticality on CodeFunction (spec A, A6.9)."""

from __future__ import annotations

import math
from dataclasses import dataclass

from actron.graph import algos
from actron.graph.store import GraphStore

_PAGE = 5000


@dataclass
class MetricsResult:
    functions: int
    pagerank_method: str
    updated: int


def compute_metrics(store: GraphStore, *, use_procedure: bool = True, repo_prefix: str | None = None) -> MetricsResult:
    """Recompute metrics for every CodeFunction in the graph (tombstoned ones included, they keep values)."""
    callers = algos.caller_counts(store)
    transitive = algos.transitive_caller_counts(store)
    scores, method = algos.pagerank(store, use_procedure=use_procedure)
    rows: list[dict[str, object]] = []
    skip = 0
    test_flags: dict[str, bool] = {}
    current: dict[str, list[object]] = {}
    while True:
        res = store.query(
            "MATCH (f:CodeFunction) WHERE $p IS NULL OR f.id STARTS WITH $p "
            "RETURN f.id AS id, coalesce(f.isTest, false) AS t, coalesce(f.deleted, false) AS d, "
            "[f.callerCount, f.transitiveCallerCount, f.pageRank, f.criticalityPercentile] AS cur "
            "ORDER BY id SKIP $s LIMIT $l", {"p": repo_prefix, "s": skip, "l": _PAGE}, read_only=True,
            timeout_ms=60000)
        for r in res:
            test_flags[r["id"]] = bool(r["t"]) or bool(r["d"])
            current[r["id"]] = list(r["cur"] or [])
        if len(res) < _PAGE:
            break
        skip += _PAGE
    max_pr = max((scores.get(i, 0.0) for i in test_flags), default=0.0) or 1.0
    max_tc = max((math.log1p(transitive.get(i, 0)) for i in test_flags), default=0.0) or 1.0
    raw = {i: 0.6 * scores.get(i, 0.0) / max_pr + 0.4 * math.log1p(transitive.get(i, 0)) / max_tc
           for i, excluded in test_flags.items() if not excluded}
    pct = algos.percentile_ranks(raw)
    for i in test_flags:
        vals: list[object] = [callers.get(i, 0), transitive.get(i, 0), round(scores.get(i, 0.0), 8), pct.get(i, 0.0)]
        if current.get(i) == vals:
            continue  # unchanged: do not rewrite the node
        rows.append({"id": i, "callerCount": vals[0], "transitiveCallerCount": vals[1], "pageRank": vals[2],
                     "criticalityPercentile": vals[3]})
    updated = store.update_nodes("CodeFunction", rows) if rows else 0
    return MetricsResult(functions=len(test_flags), pagerank_method=method, updated=updated)
