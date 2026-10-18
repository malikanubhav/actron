# FalkorDB in Actron: what we use, limits we hit, and how we worked around them

FalkorDB is Actron's primary graph database. Everything the agents reason over lives in it: code, git history, GitHub, Slack and Linear records, the links between them, decisions, and each request's evidence. This document records what we use, every limitation we hit, what the docs say, and the workaround we chose. Keep it current: add an entry whenever a new limitation appears.

**Version:** `falkordb/falkordb:v4.22.1` (Docker), Python client `falkordb` 1.8.0.
**Docs consulted:** https://docs.falkordb.com (Cypher functions, algorithms, full-text indexing, known limitations, configuration), read on 17 Oct 2026. Every behaviour marked "verified" was also tested on our own running instance.

---

## What Actron uses

| Feature | How Actron uses it | Verified |
|---|---|---|
| Typed property graph, one graph per workspace | 96+ node types from `ontology/*.json`; graph name `actron_<workspace>` | Yes |
| `MERGE` with `UNWIND` batches | Idempotent ingestion, about 500 rows per batch | Yes |
| Range indexes and unique `id` constraints | Fast lookups by id and by filtered properties | Planned in the loader |
| Full-text indexes (`db.idx.fulltext.createNodeIndex`, `db.idx.fulltext.queryNodes`) | Finding candidate code, messages, tickets and decisions for a request | Docs read |
| Variable-length paths `-[:REL*1..3]-` | Callers, callees, impact, neighbourhoods | Yes |
| `algo.pageRank('Label', 'REL') YIELD node, score` | Criticality of functions over `CALLS` (heavily called helpers rank highest) | Yes |
| `algo.SPpaths({..., relDirection: 'both'}) YIELD path` | "How is this connected?" between any two nodes | Yes |
| `algo.BFS(node, depth, 'REL') YIELD nodes, edges` | Outgoing traversals only (callees) | Yes |
| `algo.WCC(null) YIELD node, componentId` | Connected-component checks (data quality, clusters) | Yes |
| Append-only persistence (`REDIS_ARGS=--appendonly yes`) | Data survives restarts | Yes |

---

## Limitations and workarounds

### 1. Default query limits break bulk ingestion
- **What happened:** the image starts with `TIMEOUT 1000` (a deprecated setting) and `MAX_QUEUED_QUERIES 25`. Heavy queries time out after 1 second, and parallel writers beyond 25 pending queries are rejected.
- **Docs:** the configuration page lists `TIMEOUT_DEFAULT`, `TIMEOUT_MAX`, `MAX_QUEUED_QUERIES` and `THREAD_COUNT`, set at start through `FALKORDB_ARGS`.
- **Workaround:** `compose.yaml` sets `FALKORDB_ARGS="THREAD_COUNT 8 TIMEOUT_MAX 60000 TIMEOUT_DEFAULT 15000 MAX_QUEUED_QUERIES 2000 RESULTSET_SIZE 10000"`. Confirmed with `GRAPH.CONFIG GET *` after a restart.

### 2. `shortestPath` only inside `WITH` or `RETURN`
- **Error:** `FalkorDB currently only supports shortestPaths in WITH or RETURN clauses` (for `MATCH p = shortestPath(...)`).
- **Docs:** the Cypher functions page shows `WITH shortestPath((a)-[*]->(g)) AS p`, says the endpoints must be resolved before the call, and that no property filters may appear in the pattern.
- **Workaround:** use `shortestPath` only as `WITH shortestPath((a)-[:REL*]->(b)) AS p`, and only for directed questions.

### 3. No undirected `shortestPath`
- **Error:** `FalkorDB does not currently support undirected shortestPath traversals`.
- **Docs:** every documented example is directed; undirected use is not documented.
- **Workaround:** `algo.SPpaths({sourceNode: a, targetNode: b, relDirection: 'both', maxLen: 6}) YIELD path`. Verified: it finds a → b ← c → d across mixed directions, with no weight property needed. This powers the `shortest_path` MCP tool.

### 4. `algo.BFS` follows outgoing links only
- **Observed:** `algo.BFS(c, 3, 'CALLS')` returned only the functions `c` calls, never its callers. The procedure takes three arguments (start node, maximum depth, relationship type) and has no direction argument.
- **Docs:** the BFS page documents exactly those three arguments (it spells the name `algo.bfs`; the server also accepts `algo.BFS`).
- **Workaround:** callers and impact use a backwards variable-length match, `MATCH (f {id: $id})<-[:CALLS*1..3]-(c:CodeFunction)`. Verified: it returns all callers of a helper. `algo.BFS` is used only for callees.

### 5. Full-text index: one label per index
- **Docs:** `db.idx.fulltext.createNodeIndex('Label', 'field1', 'field2')` creates an index for one label; `db.idx.fulltext.queryNodes('Label', 'query')` queries one label. Prefix (`term*`, end of word only), fuzzy (`%term%1`), OR (`|`) and NOT (`-`) are supported; phrases follow RediSearch syntax.
- **Workaround:** one full-text index per node type over its text fields; a request is searched against each relevant label and the results are merged by score in Python.

### 6. Parameter prefix and persistence (resolved by upgrading)
- **Report:** an earlier project on v4.12.0 found that writes using the `CYPHER name=value` parameter prefix were truncated when the append-only file was replayed after a restart.
- **Tested on v4.22.1 (17 Oct 2026):** 51 values written with query parameters through the Python client (a 50 KB string, quotes, newlines, tabs, emoji, CJK, literal `$param` and `CYPHER x=1` text, plus an `UNWIND` batch), container restarted, all 51 read back identical. Not reproduced.
- **Decision:** use normal client parameters (`FALKORDB_BINDING=params`, shown as `falkordb_binding` in `/api/health`). The persistence test stays in the suite as a regression guard; if it ever fails, set `FALKORDB_BINDING=literal` (the safe single-pass literal binder in `graph/store.py`).
- **W1 re-check (17 Oct 2026, v4.22.1):** `tests/integration/test_persistence.py` writes 20 tricky values plus 31 ordinary ones (quotes, backslashes, newlines, tabs, emoji, CJK, literal `$param`, literal `CYPHER x=1`, a 50 KB string, lists, numbers) through `upsert_nodes`, restarts a FalkorDB container of the same image and settings, and reads everything back identical. It passes in both binding modes. The regression guard passed on v4.22.1.
- **Literal binder correction:** FalkorDB does not decode `\uXXXX` escapes in Cypher string literals (it stores the escape text). Spec A4's `json.dumps(..., ensure_ascii=True)` therefore corrupts every non-ASCII value. The binder escapes only backslash, quote, CR, LF and tab, passes other characters as they are, and rejects NUL and lone surrogates (a NUL ends the literal).

### 6a. Version choice
- **Hackathon guidance:** the WeMakeDevs Graph Hacks page says `docker pull falkordb/falkordb:latest`; its resources page also lists FalkorDB Cloud and the FalkorDB Browser.
- **Checked 17 Oct 2026:** `latest` is v4.22.1 (released 15 Oct 2026). A separate v6 line exists (v6.0.2), but `latest` points to v4.22.1.
- **Decision:** pin `falkordb/falkordb:v4.22.1` (the same build as `latest` today) so the build and the demo cannot change underneath us. It adds `algo.AStar`, `algo.HarmonicCentrality` and `algo.maxFlow` over v4.12.0, and the limits in entries 1 to 5 are unchanged (re-tested on v4.22.1).

### 7. Duplicate relationships may be counted once
- **Docs (known limitations):** when a relationship in a pattern is not referenced elsewhere, FalkorDB only checks that at least one matching relationship exists, so `MATCH (a)-[e]->(b) RETURN count(b)` can count two parallel edges as one.
- **Workaround:** Actron never relies on parallel edges: links are created with `MERGE`, so there is at most one relationship of a type between two nodes, and multiplicity is stored as a property (for example `CALLS.count`, `CALLS.callSiteLines`). Queries that must count edges reference the relationship alias.

### 8. `LIMIT` does not limit eager operations
- **Docs:** `LIMIT` in a later `WITH` or `RETURN` does not stop earlier `CREATE`, `SET`, `DELETE`, `MERGE` or aggregations from running on every row.
- **Workaround:** batches are bounded before the write (in Python, about 500 rows per `UNWIND`), never by a `LIMIT` after it.

### 9. Indexes do not serve `<>` filters
- **Docs:** the index implementation does not handle not-equal filters; use `GRAPH.EXPLAIN` to check index use.
- **Workaround:** tombstone filters are written as `coalesce(n.deleted, false) = false`, and frequently filtered properties are checked with `GRAPH.EXPLAIN` during the build.

### 10. No aggregations inside pattern comprehensions
- **Docs:** `count()`, `sum()` and similar are not allowed inside pattern comprehensions.
- **Workaround:** aggregate in a preceding `WITH`, or use `size()` on a list comprehension.

### 11. Cypher feature gaps that shape queries
- **Docs (Cypher support):** no regular-expression operator (use `CONTAINS`, `STARTS WITH`, `ENDS WITH` or the full-text index); label expressions are not supported, so Actron uses one label per node; results are capped at `RESULTSET_SIZE` rows (10,000 here), so every query has an explicit `LIMIT`.

### 12. Deleting a graph that had a unique constraint breaks the next restarts (server crash loop)
- **What happened (17 Oct 2026):** after test runs that created unique constraints and then deleted the graphs, `docker compose restart falkordb` left the container in a crash loop (exit 139, SIGSEGV in `GraphContext_GetSchemaByID` called from `Effects_Apply` -> `ApplyCreateConstraint`).
- **Mechanism (reproduced on a throwaway container):** constraints are built in the background. Replaying the append-only file creates the constraint and then replays the later `GRAPH.DELETE`; the background job finishes after the delete and writes a stray create-constraint effect for the deleted graph into the file. The restart after that one segfaults while applying it. First restart: fine. Second restart: crash. Waiting for the constraint to be `OPERATIONAL`, or dropping the constraint before deleting the graph, does not help. Graphs with constraints that are never deleted survive any number of restarts. Graphs without constraints can be created, deleted and restarted freely.
- **Docs:** the constraints page does not mention it.
- **Workaround:** unique id constraints are created only when `Settings.unique_constraints_enabled` is true (default: on, except `ACTRON_ENV=test`; override with `FALKORDB_UNIQUE_CONSTRAINTS`). `GraphStore.drop()` refuses a graph that has unique constraints. `ensure_indexes` reads `db.constraints()` first, so a second run writes nothing. `MERGE` on `id` is race-free anyway because FalkorDB runs one write at a time per graph. Production never deletes a workspace graph; if that feature is added, delete by `MATCH (n) DETACH DELETE n` and keep the key. Tests never restart the shared compose service: persistence and constraint tests use a throwaway container (`tests/integration/falkor_scratch.py`).
- **Recovery of a poisoned volume:** stop the container, remove the stray `GRAPH.EFFECT` create-constraint commands that follow a `GRAPH.DELETE` for the same key from `appendonlydir/appendonly.aof.*.incr.aof` (RESP format, parse and rewrite), start again. Or delete the volume and re-ingest.
- **Test that proves it:** `tests/integration/test_indexes.py::test_dropped_unconstrained_graphs_survive_restarts_a_ac_13` (the workaround) and `::test_drop_refuses_a_constrained_graph_a_ac_13`.

### 13. Reading a graph that was never written fails
- **Error:** `Invalid graph operation on empty key` from `GRAPH.RO_QUERY` (and `GRAPH.DELETE`) on a missing key.
- **Workaround:** `GraphStore.query(read_only=True)` runs one plain read to create the empty key and retries. `drop()` ignores the error.

### 14. Index and constraint effects are logged even when they change nothing
- **Observed:** a failed or repeated `CREATE CONSTRAINT` is still replicated as an effect.
- **Workaround:** `ensure_indexes` checks `db.indexes()` and `db.constraints()` first and creates only what is missing.

### 15. A per-query timeout above TIMEOUT_MAX is an error, not a cap
- **Error (verified 18 Oct 2026, v4.22.1 with `TIMEOUT_MAX 60000`):** `The query TIMEOUT parameter value cannot exceed the TIMEOUT_MAX configuration parameter value` for `GRAPH.RO_QUERY ... TIMEOUT 120000`. A 60000 ms timeout on the same query works.
- **Docs:** the configuration page describes `TIMEOUT_MAX` as the maximum allowed timeout; it does not say a larger value fails the query instead of being clamped.
- **Workaround:** keep every per-query timeout at or below 60000 ms (W5's tools use 2000 ms, the shared query 10000 ms). Code that catches the error and falls back silently (for example a PageRank wrapper falling back to Python) hides it, so wrappers should clamp to 60000.
- **Test that proves it:** found while running `tests/integration/graph/test_algos.py::test_pagerank_wrapper_from_w2_when_available` (W2's wrapper logged "algo.pageRank failed; using the Python fallback").

### 16. Full-text search does not split camelCase names and treats `-` as NOT
- **Observed:** a request "auto-evaluate on save" sent as-is would mean `auto` NOT `evaluate`; and `evaluateOnSave` is indexed as one token, so `save` does not match it.
- **Docs:** the full-text page follows RediSearch query syntax (`-` negates, `|` is OR, `term*` is a prefix).
- **Workaround:** `queries.fulltext_query` keeps only word characters, splits camelCase, drops stop words, adds one stripped English ending (`shown` -> `show`) and sends an OR of prefix terms (`auto*|evaluate*|save*`). The pipeline also scores how much of a candidate's name the request mentions. Test: `tests/integration/graph/test_queries.py::test_fulltext_query_builder`.

### 17. An `UNWIND`ed id inside a pattern with a labelled far end scans the far label
- **What happened (18 Oct 2026, Calva graph, 5,533 functions):** `UNWIND $ids AS fid MATCH (x:CodeFunction {id: fid})<-[:CALLS]-(c:CodeFunction)` took 2.3 s for 82 ids. `GRAPH.EXPLAIN` shows `Node By Label Scan | (c:CodeFunction)` then a traverse back to `x`: the planner starts from the far end and checks `x.id` per row instead of using the `id` index. With a `$param` instead of an unwound variable, the planner uses the index. Under load, `impact` on hub functions (hundreds of callers) timed out and the shared query took 4 s.
- **Also:** a variable-length `<-[:CALLS*1..3]-` enumerates every path; on hubs that is tens of thousands of paths for a few hundred distinct callers.
- **Docs:** the known-limitations page says to check index use with `GRAPH.EXPLAIN`; it does not describe this planner choice.
- **Workaround:** anchor first, then traverse: `UNWIND $ids AS fid MATCH (x:CodeFunction {id: fid}) WITH * MATCH (x)<-[:CALLS]-(c:CodeFunction)` (plan: `Node By Index Scan`, 4 ms for the same 82 ids). Callers and impact walk one hop per query over a deduplicated frontier (`queries.reverse_call_walk`), so each function is visited once at its minimum depth. All 20 `UNWIND ... {id: var})<-/-[` patterns in the code were rewritten this way. Result on the hub seeds: shared query 4.4 s → 0.5 s, `impact` timeout → 0.12 s; load test with 8 readers and 2 writers: 0 errors, shared query p95 1.7 s, impact p95 0.7 s.
- **Test that proves it:** `backend/tests/integration/graph/test_queries.py` (same results as before on the fixture graph), `backend/tests/integration/graph/test_load_test.py` (B-AC-68, no errors under concurrency), and `scripts/load_test.py` on the Calva graph.

---

## Template for new entries
```
### N. <short title>
- What happened / error text:
- Docs (page and what it says):
- Workaround:
- Test that proves it:
```
