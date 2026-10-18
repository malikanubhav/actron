"""Load test: concurrent graph readers (shared query, callers, impact) and writers (ingestion batches).

Readers run against a workspace graph that already holds real data (default `dev`, Calva). Writers upsert
batches into a separate scratch graph (`actron_loadtest`, no unique constraints, dropped afterwards), so the
real graph is never modified. Reports throughput and p50/p95/p99 latency per operation (spec B, B14, B-AC-68).

Usage: uv run --project backend python scripts/load_test.py [--ws dev] [--seconds 60] [--readers 16] [--writers 4]
       [--json out.json]
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import random
import statistics
import time
import uuid
from collections import defaultdict
from typing import Any

from actron.config import get_settings
from actron.graph import ids
from actron.graph import queries as Q
from actron.graph.ontology import default_ontology
from actron.graph.store import GraphStore


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = min(len(ordered) - 1, max(0, round(p / 100 * (len(ordered) - 1))))
    return ordered[k]


def pick_seeds(store: GraphStore, n: int = 50) -> list[str]:
    rows = store.query(
        "MATCH (f:CodeFunction) WHERE coalesce(f.isTest, false) = false AND f.callerCount > 0 "
        "RETURN f.id AS id ORDER BY f.pageRank DESC LIMIT $n",
        {"n": n},
        read_only=True,
    )
    return [str(r["id"]) for r in rows]


def _reader(ws: str, graph: str, seeds: list[str], stop: float, i: int) -> tuple[dict[str, list[float]], dict[str, int], int]:
    settings = get_settings()
    rnd = random.Random(i)
    store = GraphStore(settings.FALKORDB_URL, graph, default_ontology(), workspace_id=ws)
    lat: dict[str, list[float]] = defaultdict(list)
    errors: dict[str, int] = defaultdict(int)
    while time.time() < stop:
        op = rnd.choice(["shared_query", "callers", "impact"])
        seed = rnd.choice(seeds)
        t = time.monotonic()
        try:
            if op == "shared_query":
                Q.shared_query(store, f"req_load_{i}", [seed], {seed: 1.0})
            elif op == "callers":
                Q.callers(store, seed, 3)
            else:
                Q.impact(store, [seed], 3)
            lat[op].append((time.monotonic() - t) * 1000)
        except Exception:
            errors[op] += 1
    store.close()
    return dict(lat), dict(errors), 0


def _writer(graph: str, stop: float, i: int) -> tuple[dict[str, list[float]], dict[str, int], int]:
    settings = get_settings()
    store = GraphStore(settings.FALKORDB_URL, graph, default_ontology(), workspace_id="loadtest")
    lat: dict[str, list[float]] = defaultdict(list)
    errors: dict[str, int] = defaultdict(int)
    written = n = 0
    while time.time() < stop:
        batch = [
            {"id": ids.code_fn("load/test", f"src/w{i}.ts", f"fn{n}_{k}"), "name": f"fn{n}_{k}",
             "qualifiedName": f"fn{n}_{k}", "startLine": 1, "endLine": 3, "body": "return 1", "contentHash": "h"}
            for k in range(500)
        ]
        t = time.monotonic()
        try:
            store.upsert_nodes("CodeFunction", batch)
            lat["upsert_500"].append((time.monotonic() - t) * 1000)
            written += len(batch)
        except Exception:
            errors["upsert_500"] += 1
        n += 1
    store.close()
    return dict(lat), dict(errors), written


def run(ws: str, seconds: float, readers: int, writers: int, graph: str | None = None) -> dict[str, Any]:
    """Readers and writers run in separate processes, so the numbers measure FalkorDB, not Python's GIL."""
    settings = get_settings()
    ontology = default_ontology()
    graph = graph or ids.graph_name(settings.FALKORDB_GRAPH_PREFIX, ws)
    seeds = pick_seeds(GraphStore(settings.FALKORDB_URL, graph, ontology, workspace_id=ws))
    if not seeds:
        raise SystemExit(f"workspace {ws!r} has no functions with callers; ingest a repository first")
    scratch_name = f"actron_loadtest_{uuid.uuid4().hex[:6]}"
    # Same index as a real ingestion graph (MERGE on id); no unique constraint, so the graph can be dropped.
    GraphStore(settings.FALKORDB_URL, scratch_name, ontology, workspace_id="loadtest").query(
        "CREATE INDEX FOR (n:CodeFunction) ON (n.id)"
    )
    stop = time.time() + seconds
    started = time.monotonic()
    with mp.get_context("spawn").Pool(readers + writers) as pool:
        jobs = [pool.apply_async(_reader, (ws, graph, seeds, stop, i)) for i in range(readers)]
        jobs += [pool.apply_async(_writer, (scratch_name, stop, i)) for i in range(writers)]
        results = [j.get(timeout=seconds + 120) for j in jobs]
    elapsed = time.monotonic() - started
    GraphStore(settings.FALKORDB_URL, scratch_name, ontology, workspace_id="loadtest").drop()
    lat: dict[str, list[float]] = defaultdict(list)
    errors: dict[str, int] = defaultdict(int)
    rows_written = 0
    for part_lat, part_err, written in results:
        for op, values in part_lat.items():
            lat[op].extend(values)
        for op, count in part_err.items():
            errors[op] += count
        rows_written += written
    report: dict[str, Any] = {
        "workspace": ws, "seconds": round(elapsed, 1), "readers": readers, "writers": writers,
        "seedPolicy": "top 50 non-test functions by PageRank (the most-called code: worst case)",
        "rowsWritten": rows_written, "rowsPerSecond": round(rows_written / elapsed, 1), "operations": {},
    }
    for op in sorted(set(lat) | set(errors)):
        values = lat.get(op, [])
        report["operations"][op] = {
            "count": len(values), "perSecond": round(len(values) / elapsed, 2),
            "p50Ms": round(statistics.median(values), 1) if values else None,
            "p95Ms": round(percentile(values, 95), 1), "p99Ms": round(percentile(values, 99), 1),
            "errors": errors.get(op, 0),
        }
    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ws", default="dev")
    ap.add_argument("--seconds", type=float, default=60)
    ap.add_argument("--readers", type=int, default=16)
    ap.add_argument("--writers", type=int, default=4)
    ap.add_argument("--json")
    ap.add_argument("--graph", help="read from this graph name instead of the workspace graph")
    args = ap.parse_args()
    report = run(args.ws, args.seconds, args.readers, args.writers, args.graph)
    print(json.dumps(report, indent=2))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2)


if __name__ == "__main__":
    main()
