# Before an AI changes your code, it should know what your team decided

*Draft for the FalkorDB Graph Hacks blog prize. Numbers are from the real build on 18 October 2026.*

## The problem

A coding agent can read a repository. It cannot read the Slack thread where the team agreed that a helper must stay strict, the review comment that explains why a function retries twice, or the ticket that says exports stay Finance-only. So it satisfies the new request and quietly breaks an old decision. Afterwards nobody can see why it did what it did.

We built Actron to put that history in front of the agent, and to make the agent act on it.

## One graph for code and conversation

Actron reads five sources into one FalkorDB graph per workspace: the code (parsed with tree-sitter), git history, GitHub, Slack and Linear. The schema is fixed in five ontology files: 96 node types, and 275 concrete link types after node groups are expanded. Nothing is invented at runtime, and every link carries how it was made (`explicit`, `structural`, `extracted`, `inferred`) and a confidence.

On Calva, the open-source Clojure extension for VS Code we used as the demo repository, that is 19,952 nodes and 76,532 links: 5,533 functions, 11,754 `CALLS`, 4,150 `TESTS` links, 2,000 commits mapped to the functions they touched, and blame ownership per function. Every line of every stored file belongs to a function, class, chunk or document node, so the agent can read source from the graph instead of walking the file tree.

## The graph changes what the agent does

When a request arrives, the investigator gets 20 graph tools over MCP and decides which to call: `search`, `find_symbol`, `callers`, `impact`, `criticality`, `decisions_for`, `related_work`, `owners`, `tests_for`, `shortest_path`, `history`, `get_code` and others. What it finds changes its behaviour:

- A decision that constrains the function → Actron asks a person before writing anything.
- A function in the 99th percentile of PageRank over the call graph → Actron asks whether its callers should keep their behaviour. For `docFromTextNotation` the question read: "docFromTextNotation is called from 5 functions and 964 tests. Should its current behaviour stay the same for them?"
- The affected functions, the constraints and the covering tests become the ticket, and the ticket becomes the build's scope.

The coding agent, Pi, runs in a container with one model key and the same MCP tools, plus a context pack built from the graph: the source of every affected function, its callers with call-site lines, the tests that cover it, and the decisions it must preserve. The orchestrator watches Pi's event stream and reminds it to ask the graph instead of exploring the repository.

## The evidence path

Every finding carries the path from the request to the thing found: request → function → caller → test, or request → function → decision → the Slack message it was extracted from. In the UI that path traces hop by hop on the canvas, with the quote typeset next to each hop. It is the answer to "why did the agent do that?".

## What FalkorDB taught us

We kept a log of every limit we hit (`docs/falkordb.md`, 17 entries). Three mattered most:

1. **`algo.BFS` only follows outgoing links**, so "who calls this?" is a backwards traversal we write ourselves. Cypher's `shortestPath` is directed-only and allowed only in `WITH`/`RETURN`; `algo.SPpaths` with `relDirection: 'both'` answers "how are these connected?".
2. **Anchor before you traverse.** `UNWIND $ids AS fid MATCH (x:CodeFunction {id: fid})<-[:CALLS]-(c:CodeFunction)` made the planner scan every function per id: 2.3 s for 82 ids. Writing `MATCH (x:CodeFunction {id: fid}) WITH * MATCH (x)<-[:CALLS]-(c)` uses the id index: 4 ms. Walking callers one hop at a time over a deduplicated frontier, instead of enumerating every path, took impact on the most-called functions from a timeout to 0.12 s.
3. **Don't drop a graph that has unique constraints** on v4.22.1 with append-only persistence: the server crashed replaying the file after a restart. Our test graphs now skip constraints, and the store refuses to drop a constrained graph.

Under a 60-second load test (8 reader and 2 writer processes, the 50 most-called functions as seeds) the graph served shared queries at p95 1.7 s, impact at p95 0.7 s, with 4,609 node writes a second and no errors.

## Two windows, one request

Slack and the web app are two views of one request that lives in a Temporal workflow. Approvals from either surface are signals; the first valid one wins and is bound to a SHA-256 of the ticket revision (or the PR head commit), so a stale approval is refused with a plain reason. Answer a question on your phone, and the web page updates within a second.

## What we would do next

Calibrate the judgment thresholds on real model answers (our labelled fixtures are ready), resolve the TypeScript method calls that need type information, and learn more procedures from merged PRs.
