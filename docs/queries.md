# Graph queries and algorithms

Every question Actron asks the graph is a named query in `backend/actron/graph/queries.py`. The MCP tools
(`backend/actron/mcp_graph/tools.py`), the investigator (`backend/actron/flow/investigate.py`) and the API quick
queries all call these functions. This page lists what each one answers, where it is called, the Cypher it runs, and
real output from the test fixture graph (`backend/tests/fixtures/graph_small.cypher`, a made-up extension called
"calva-lite"; ids are shortened below with `…`).

Rules every query follows (see `docs/falkordb.md`):
- A lookup by id always names the label, taken from the id (`ids.parse_id`), for example `MATCH (f:CodeFunction {id: $id})`.
- Tombstoned nodes and links are left out with `coalesce(x.deleted, false) = false`.
- Every query has an explicit `LIMIT`, runs read-only, and has a timeout: 2 s for tools, 10 s for the shared query.
- Callers and impact walk backwards one hop per query over a deduplicated frontier (`reverse_call_walk`), so each function is visited once at its minimum depth. A `<-[:CALLS*1..3]-` match enumerates every path and timed out on Calva's hub functions; `algo.BFS` only follows outgoing links, so it is not used for callers either (docs/falkordb.md 4 and 17).
- Lists of ids are grouped by label and sent as `UNWIND $ids AS x MATCH (n:Label {id: x}) WITH * MATCH (n)<-[...]-(...)`: the node is anchored through its `id` index before the traversal, because written as one pattern FalkorDB scans the far label instead (docs/falkordb.md 17).
- Every result row that ends up in findings carries `path`: the node ids from the request (or seed) to the item.

## seeds_fulltext(text, types, limit)
**Answers:** which nodes the request text is about. **Called by:** the `search` and `search_code` tools; step 1 of the pipeline (top 20 candidates).

The text is turned into a RediSearch OR query of prefix terms (`fulltext_query`): punctuation dropped (a `-` would mean NOT), camelCase split, stop words dropped, one English ending stripped (`shown` -> `show`). For "auto-evaluate on save" that is `auto*|evaluate*|save*`. Each label's own full-text index is queried (fields from `ontology.search_fields()`), results are merged and divided by the best raw score so the top is 1.0. Each row also gets `nameMatch` (share of the node's name the request mentions) and `isTest`.

```cypher
CALL db.idx.fulltext.queryNodes($label, $q) YIELD node, score
WHERE coalesce(node.deleted, false) = false AND NOT (node.id CONTAINS '@v')
RETURN node AS n, score ORDER BY score DESC LIMIT $limit
```
Example (`types` = code and features, limit 3):
```json
[{"id": "code:fn:…:src/evaluate.ts::evaluateCode", "type": "CodeFunction", "score": 1.0},
 {"id": "code:fn:…:evaluate.test.ts::evaluate > skips evaluation on save when disabled", "type": "CodeFunction", "score": 0.9167},
 {"id": "actron:feature:evaluate-on-save", "type": "Feature", "score": 0.5}]
```
The pipeline drops tests and reranks with J5 (or, when J5 is a stub, `0.6 * score + 0.4 * nameMatch`).

## expand_renames(ids) and code_anchors(ids)
**Answers:** the earlier names of a function, class or file (following `RENAMED_TO`, `CLASS_RENAMED_TO`, `FILE_RENAMED_TO` backwards up to 5 hops), and the code a feature, class, file or component stands for. **Called by:** decisions, related work, owners, impact, tests and the history tools, so knowledge attached to an old name is not lost.
```cypher
UNWIND $ids AS sid
MATCH p = (old:CodeFunction)-[:RENAMED_TO*1..5]->(s:CodeFunction {id: sid})
RETURN sid, [n IN nodes(p) | n.id] AS chain LIMIT $cap
```

## decisions_constraining(ids, include_superseded)
**Answers:** which team decisions limit this code or feature, with their quote, source and approval. **Called by:** `decisions_for` tool, shared query. Only `approved`, `proposed` (and, when asked, `superseded`) decisions that are not tombstoned, through `CONSTRAINS` links that are active (`active` is not false). Earlier names and, for features and classes, the implementing code are included. Newest first.
```cypher
UNWIND $tids AS tid
MATCH (t:CodeFunction {id: tid})<-[c:CONSTRAINS]-(d:Decision)
WHERE coalesce(d.deleted, false) = false AND coalesce(c.deleted, false) = false
  AND coalesce(c.active, true) = true AND d.status IN $statuses
OPTIONAL MATCH (d)-[e:EXTRACTED_FROM]->(src)
OPTIONAL MATCH (src)-[:POSTED_BY|REVIEW_COMMENT_BY|COMMENT_BY|ISSUE_CREATED_BY|OPENED_BY|AUTHORED_BY|ISSUE_OPENED_BY]->(au)
OPTIONAL MATCH (d)-[:APPROVED_IN]->(ap)
RETURN tid, d, e.quote AS equote, src, labels(src)[0] AS srcLabel,
       coalesce(au.realName, au.displayName, au.name, au.login) AS author, collect(DISTINCT ap.id) AS approved
LIMIT $cap
```
Example for `formatEvalResult`, which was renamed from `formatResult` (the decision was made about the old name):
```json
[{"id": "actron:decision:fixture-ns-prefix", "status": "approved",
  "path": ["code:fn:…::formatEvalResult", "code:fn:…::formatResult", "actron:decision:fixture-ns-prefix"]}]
```

## related_work(ids)
**Answers:** earlier work on this code: PRs that touched it (`PR_TOUCHED`, and review comments via `COMMENT_ON_FUNCTION` -> `COMMENTS_ON_PR`), Linear tickets implemented by those PRs (`IMPLEMENTED_BY`), and issues, tickets and Slack messages that mention it (`MENTIONS`). **Called by:** `related_work` tool, shared query. Newest first.
```cypher
UNWIND $tids AS tid MATCH (t:CodeFunction {id: tid})<-[:PR_TOUCHED]-(pr:GithubPullRequest)
WHERE coalesce(pr.deleted, false) = false RETURN tid, pr LIMIT $cap
-- and
UNWIND $pids AS pid MATCH (pr:GithubPullRequest {id: pid})<-[:IMPLEMENTED_BY]-(li:LinearIssue) RETURN pid, li LIMIT $cap
```
Example for `evaluateOnSave`:
```json
[{"id": "github:issue:…#55", "state": "open", "path": ["code:fn:…::evaluateOnSave", "github:issue:…#55"]},
 {"id": "linear:issue:fx-cal-12", "state": "completed",
  "path": ["code:fn:…::evaluateOnSave", "github:pr:…#101", "linear:issue:fx-cal-12"]}]
```

## callers(id, depth) and callees(id, depth)
**Answers:** who calls this function (and what it calls), up to 3 hops, each at its smallest depth, with the call-site lines. **Called by:** `callers`, `callees`, `references` tools; the agent. Depth is clamped to 1..3.
Callers run one query per hop (`reverse_call_walk`), starting from the function and then from the callers found
at the previous hop that are not tests (nothing calls a test). Python keeps the parent of each caller, which gives
the path and the weakest confidence on it:
```cypher
UNWIND $ids AS fid
MATCH (x:CodeFunction {id: fid}) WITH x, fid
MATCH (x)<-[r:CALLS]-(c:CodeFunction)
WHERE coalesce(c.deleted, false) = false
RETURN fid, c.id AS id, c.qualifiedName AS name, c.criticalityPercentile AS crit,
       c.isTest AS isTest, r.confidence AS conf, r.callSiteLines AS lines
LIMIT $cap
```
On Calva's most-called function this takes 0.05 s where the earlier `<-[:CALLS*1..3]-` path match timed out.
Callees use a forward variable-length pattern (`-[:CALLS*1..3]->`); fan-out forwards is small. Example, callers of `evaluateCode` (the tombstoned `legacyEvaluate` is left out):
```json
[{"id": "…::evaluateOnSave", "depth": 1, "callSiteLines": [29]},
 {"id": "…::evaluateSelection", "depth": 1, "callSiteLines": [18]},
 {"id": "…::evaluateTopLevelForm", "depth": 1, "callSiteLines": [22]},
 {"id": "…::evaluate > evaluates a form", "depth": 1, "callSiteLines": [4]}]
```

## impact(ids, depth)
**Answers:** everything that could break: callers backwards over `CALLS` and `INSTANTIATES` (a class also starts from its methods via `METHOD_OF`), their files and components, and covering tests. **Called by:** `impact` tool, shared query (callers to depth 3, sorted by depth then criticality, max 50).
```cypher
UNWIND $ids AS sid
MATCH p = (s:CodeClass {id: sid})<-[:CALLS|INSTANTIATES*1..3]-(c:CodeFunction)
WHERE all(n IN nodes(p)[1..] WHERE coalesce(n.deleted, false) = false)
RETURN sid, c.id AS id, length(p) AS depth, [n IN nodes(p) | n.id] AS pathIds LIMIT $cap
```
Example for the class `ReplSession`, depth 2:
```json
{"functions": [["…::evaluateCode", 1], ["…::connect", 1], ["…::evaluateOnSave", 2]],
 "files": ["src/connector.ts", "src/evaluate.ts", "src/extension.ts"]}
```

## tests_for(ids)
**Answers:** which test functions exercise this code (`TESTS`, `TESTS_CLASS`; files and features resolve to their functions first). **Called by:** `tests_for` tool, impact, shared query.
```cypher
UNWIND $ids AS tid MATCH (x:CodeFunction {id: tid})<-[r:TESTS]-(t:CodeFunction)
WHERE coalesce(t.deleted, false) = false
RETURN tid, t.id AS id, t.qualifiedName AS name, r.method AS method, r.confidence AS conf LIMIT $cap
```
Example for `prettyPrint`: `[{"id": "…::printer > pretty prints maps", "method": "calls", "confidence": 0.9}]`.

## criticality(ids)
**Answers:** how central a function is. Reads what ingestion stored: PageRank over `CALLS` (`algo.pageRank('CodeFunction', 'CALLS')`, computed by W2's `actron/graph/algos.py`), caller counts and the percentile. **Called by:** `criticality` tool, shared query, the label rule (a seed at the 90th percentile or above with no decision is a possible conflict).
```cypher
UNWIND $ids AS fid MATCH (f:CodeFunction {id: fid})
RETURN f.id AS id, f.pageRank AS pr, f.callerCount AS cc, f.transitiveCallerCount AS tc,
       f.criticalityPercentile AS pct LIMIT $cap
```
Example: `[{"id": "…::sendMessage", "pageRank": 0.14, "callerCount": 3, "transitiveCallerCount": 8, "criticalityPercentile": 97.5}]`.

## shortest_path(a, b, max)
**Answers:** "how is this connected?", in either direction. **Called by:** `shortest_path` tool, `GET /api/graph/path`. Uses `algo.SPpaths` because Cypher `shortestPath` is directed-only and allowed only in `WITH`/`RETURN`. If the procedure fails, a breadth-first search in Python over labelled neighbour lookups gives a path of the same length (tested on five fixture pairs).
```cypher
MATCH (a:SlackMessage {id: $a}), (b:CodeFunction {id: $b})
CALL algo.SPpaths({sourceNode: a, targetNode: b, relDirection: 'both', maxLen: 6}) YIELD path
RETURN [n IN nodes(path) | n] AS ns,
       [r IN relationships(path) | [startNode(r).id, type(r), endNode(r).id]] AS rs LIMIT 1
```
Example, from the Slack message where the team decided to keep auto-evaluate off, to `evaluateCode`:
`slack:msg:… -> actron:feature:evaluate-on-save -> …::evaluateOnSave -> …::evaluateCode`.

## owners(ids)
**Answers:** who owns or knows this code. `KNOWS_ABOUT` (score and signals), `OWNS` (CODEOWNERS or dominant blame) and `BLAME_OWNS` through `IS_GIT_AUTHOR` identities. A person's score is their strongest signal (CODEOWNERS counts as 1.0). **Called by:** `owners` tool, shared query (max 5).
```cypher
UNWIND $tids AS tid MATCH (t:CodeFunction {id: tid})<-[b:BLAME_OWNS]-(a:GitAuthor)
OPTIONAL MATCH (a)<-[:IS_GIT_AUTHOR]-(i:Identity)<-[:HAS_IDENTITY]-(p:Person)
RETURN tid, a.id AS aid, b.lineShare AS share, i.id AS iid, p.id AS pid, p.displayName AS pname LIMIT $cap
```
Example for `sendMessage`: `[{"personId": "actron:person:fixture-carol", "basis": ["codeowners", "blame"], "score": 1.0}]`.

## procedures_for(ids)
**Answers:** how changes are usually made here (steps, test command), from `Procedure -[:APPLIES_TO]->` the code or its file. **Called by:** `procedures_for` tool, shared query, the build's context pack.
Example for `formatEvalResult`: `[{"procedureId": "actron:procedure:src-evaluate", "testCommand": "npm run unit-test -- --grep evaluate", "path": ["…::formatEvalResult", "code:file:…:src/evaluate.ts", "actron:procedure:src-evaluate"]}]`.

## subgraph_for_request(request_id, mode)
**Answers:** what to draw on the request's canvas: the request, its `ABOUT` seeds, everything its latest `Investigation` `FOUND`, and every node on the stored `FOUND.path` lists, plus all links among them. `expanded` returns up to 300 nodes one by one (above that it keeps the first 300 and sets `truncated`). `aggregated` (the default view) returns every node individually up to 40 nodes; above 40 it keeps the request, seeds, decisions and the 12 highest-ranked findings with the nodes on their paths, and folds the rest into one counted cluster per type, with test functions in their own cluster ("194 tests", "21 functions"). The 40-node threshold replaces spec B3's 300: on Calva a single request found 229 nodes (mostly tests of a hub helper), which drew as an unreadable wall. **Called by:** `GET /api/graph/subgraph`.

## shared_query(request_id, seed_ids)
**Answers:** the findings for a request (spec B, B.C3, the JSON in PROMPT appendix D). **Called by:** both investigation modes; the agent's seeds always go through it, so the output never depends on the model. It runs, in order: `decisions_for`, `related_work`, `impact`, `criticality`, `owners`, `procedures_for` (each reported as a tool call on the timeline in pipeline mode), then builds `graph` from every path. Limits: seeds 10 (by score), decisions 15, related work 15 (newest first), callers 50 (depth, then criticality), owners 5, graph nodes 300. The stored snapshot for the fixture request is `backend/tests/integration/graph/snapshots/shared_query_fixture.json`.

## Where the label comes from
`flow/labels.py`: `conflict` if any decision's J6 `restricts` is at least `CONFLICT_THRESHOLD` (0.8); `possible_conflict` if any is between `POSSIBLE_CONFLICT_THRESHOLD` (0.5) and 0.8, or a seed is at the 90th criticality percentile or above with no decision; `nothing_found` if there are no seeds and no decisions; otherwise `clear`. In the graph, `Investigation.conflictLabel` uses `none` for both `nothing_found` and `clear`.

## Tests
`backend/tests/integration/graph/test_queries.py` (one test per query, tombstones excluded), `test_shared_query.py` (schema and snapshot), `test_algos.py` (procedure versus fallback), `test_limits.py` (a synthetic 50,000-edge graph; marked slow).
