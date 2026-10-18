# Spec B: Agents and workflow

**Scope:** PRD sections 2 (Track 01 points), 3, 9.4, 10, 11, 12, 14, 15. The request lifecycle on Temporal, events and live updates, the shared query and graph algorithms, the MCP graph server, the investigator agent and its fallback, questions, tickets, approvals, the Pi build, write-back, the Slack bot, the API and auth, notifications, and the bonus items (Q&A mode, tenancy, load test).

Conventions from spec A apply (ids, times, `ws`, test roots). **[VERIFY]** marks tool behaviour to confirm and record in `docs/runbook.md`.

---

## Contracts (frozen before parallel work)

### B.C1 Request states, signals and transitions
States (exact strings, shared by API, UI, Slack): `Investigating`, `Needs your input`, `Ticket ready`, `Awaiting approval`, `Building`, `Needs attention`, `PR ready for review`, `Changes requested`, `Done`, `Cancelled`. Q&A requests use `Investigating` → `Done`.

Signals on `RequestWorkflow` (all carry `actor` = `{userId|null, slackUserId|null, surface: "slack"|"ui"}` and `idempotencyKey`):
| Signal | Payload | Valid in | Effect |
|---|---|---|---|
| `answer` | `{questionId, value}` | `Needs your input` | records the answer; when all required questions are answered → ticket drafting |
| `edit_ticket` | `{content}` | `Ticket ready`, `Awaiting approval`, `Needs attention` | new revision; voids approvals of earlier revisions; → `Awaiting approval` after sync |
| `approve_ticket` | `{revisionHash}` | `Awaiting approval` | accepted only if `revisionHash` equals the current revision's hash → `Building`; otherwise refused with reason `stale_revision` |
| `pr_feedback` | `{text, headSha}` | `PR ready for review` | J10 classifies; `code_change_within_scope` → `Changes requested` and a new build on the same branch; `scope_change` → `Needs attention`; `question` → answer posted; `approval` → treated as `approve_pr` |
| `approve_pr` | `{headSha}` | `PR ready for review` | accepted only if `headSha` equals the PR's current head (re-read from GitHub) → write-back → `Done`; otherwise refused `stale_head` |
| `cancel` | `{reason}` | any non-final | → `Cancelled`; running build activities are cancelled |
| `close_pr` | `{reason}` | `PR ready for review` | closes the PR on GitHub (activity) → `Cancelled` with outcome `closed` |
| `budget_raised` | `{capUsd}` | `Building` (waiting on the budget) | resumes the waiting build |
All signals and the queries are also listed in PRD 9.4.
| `retry` | `{}` | `Needs attention` | re-runs the failed step (investigation or build) |

The full transitions table is PROMPT appendix F. `flow/states.py` holds it as data: `TRANSITIONS: dict[tuple[State, Action], State]`; both the workflow and the API use it; invalid pairs raise `InvalidTransition(state, action)`.

Queries on `RequestWorkflow`: `state() -> RequestStateView` (`state`, `currentRevision {n, hash}`, `pendingQuestions`, `build {status, queuePosition}`, `pr {number, headSha}`).

### B.C2 Events
Type list: PROMPT appendix E. Envelope (PostgreSQL `events` row and SSE message):
```json
{"id": 1234, "requestId": "req_01J…", "seq": 17, "type": "tool.called", "at": "2026-10-18T09:12:03.120Z",
 "actor": "actron|person|slack", "surface": "slack|ui|system",
 "payload": {…}}
```
Payloads (required fields):
- `request.created {kind, title, text, requester {personId, name}, source: "slack"|"ui", slack {channel, threadTs}?}`
- `investigation.started {mode: "agent"|"pipeline"}`
- `tool.called {callId, tool, args, by: "investigator"|"pi"}` and `tool.result {callId, ok, summary, nodeIds[], durationMs, error?}`
- `evidence.found {evidenceId, role, nodeId, nodeType, quote?, source {type, url, author, at}, confidence, path[]}`
- `investigation.completed {label, summary, counts {decisions, relatedWork, callers, tests}, findingsRef}`
- `question.asked {questionId, text, options[]?, evidenceIds[]}` / `answer.received {questionId, value, by {personId, name}, surface}`
- `ticket.revised {n, hash, contentRef, by}` / `ticket.synced {linearIssueId, identifier, url}`
- `approval.recorded {kind, target, by, surface}` / `approval.refused {kind, target, reason, by, surface}`
- `handoff.created {investigationId, buildId, evidenceCount}`
- `build.queued {buildId, position}` / `build.started {buildId, branch, baseSha}` / `build.step {buildId, step, text, file?, detail?}` / `tests.result {buildId, passed, failed, skipped, failing[] {name, output}}` / `build.repair {buildId, attempt, reason}` / `build.failed {buildId, reason}` / `build.passed {buildId, headSha}`
- `pr.opened {number, url, headSha}` / `pr.updated {number, headSha}` / `review.feedback {kind, text, by, surface}` / `pr.approved {headSha, by, surface}`
- `writeback.done {counts {prs, commits, functions, procedures}}`
- `notification.sent {kind, toPersonId, channel: "slack_dm"|"slack_thread"|"ui"}`
- `request.cancelled {reason, by}` / `request.done {outcome}` / `answer.ready {answerRef}` (Q&A)
- `request.state_changed {from, to, reason}`: written for every transition by `set_state` (drives the header, chips, Slack status message and inbox).
- `judgment.made {job, provider, count, what}`: one per batched Jev (or fallback) call during investigation, linking shown on the timeline, or build checks (system map: actron → jev "Judging {count} {what}").
- `budget.reached {spentUsd, capUsd}` (system map: footer and header notice).
- Workspace-level events (no `requestId`): the ingestion and linking events in spec A, A.C6.
- `memory.refreshing {fromSha, toSha}` / `memory.refreshed {sha, functionsChanged}` / `memory.unverified {reason}` (freshness gate; system map: github → falkordb "Syncing merged code", caption on the request header "Updating memory with the latest merged code.")

Every event also drives the **live system map** (spec C): `actorsFor(type)` mapping (B.C2a below) is part of the contract.

**B.C2a Event → system map actors** (from → to, caption template):
`request.created` slack|ui → actron "New request from {name}"; `tool.called` actron(investigator)|pi → falkordb "{tool}({args short})"; `tool.result` falkordb → actron|pi "{summary}"; judgments (logged as `build.step`/`investigation` sub-steps with `detail.provider = "jev"`) actron → jev "Judging {n} {what}"; `question.asked` actron → slack "Asked: {text short}"; `ticket.synced` actron → linear "Ticket {identifier} v{n}"; `approval.recorded` slack|ui → actron "Approved by {name}"; `handoff.created` actron → pi "Evidence handed to the build"; `build.step` pi → pi "{text}"; `tests.result` pi → actron "{passed}/{total} tests passed"; `pr.opened` actron → github "PR #{number} opened"; `writeback.done` actron → falkordb "Memory updated".

### B.C3 Shared query output
Exactly the JSON in PROMPT appendix D. Additional rules: `seeds` sorted by score desc (max 10); `decisions` only status `approved`, `proposed` or `superseded` that are not tombstoned, sorted by conflict probability desc then `decidedAt` desc (max 15); `relatedWork` sorted by recency (max 15); `impact.callers` depth ≤ 3, sorted by depth then criticality (max 50); `owners` max 5; `graph.nodes` max 300 (aggregated mode collapses beyond that); every list item includes `path` = node ids from the request node to the item.

### B.C4 MCP tools (names, input and output schemas)
Server: `actron.mcp_graph.server` built with the official MCP Python SDK (`mcp` package, `FastMCP`). Transports: in-process client for the investigator; Streamable HTTP on `http://worker:8765/mcp` (internal network only) for Pi **[VERIFY Pi's MCP client supports HTTP; else stdio through a small proxy]**. All tools are read-only, scoped to one workspace by a token issued per run (header `X-Actron-Run`), limited to 2 seconds and 200 rows each.
| Tool | Input | Output |
|---|---|---|
| `search` | `{query: str, types?: [str], limit?: int≤20}` | `[{id, type, label, snippet, score}]` |
| `get_node` | `{id}` | `{id, type, properties (no secrets, bodies truncated to 4,000 chars), links: {outgoing: [{type, toId, toType, method, confidence}], incoming: [...]}}` (max 50 each) |
| `callers` | `{functionId, depth?: 1..3}` | `[{id, label, depth, callSiteLines, confidence}]` |
| `callees` | `{functionId, depth?: 1..3}` | same shape |
| `impact` | `{ids: [str], depth?: 1..3}` | `{functions: [{id, depth, criticalityPercentile}], files: [...], tests: [...], components: [...]}` (backwards traversal over `CALLS` and `INSTANTIATES` from the given ids, plus `METHOD_OF` and covering tests) |
| `criticality` | `{ids: [str]}` | `[{id, pageRank, callerCount, transitiveCallerCount, criticalityPercentile}]` |
| `shortest_path` | `{fromId, toId, maxHops?: ≤6}` | `{nodes: [...], links: [...]}` or `{found: false}` |
| `decisions_for` | `{ids: [str], includeSuperseded?: bool}` | `[{decisionId, statement, status, quote, source {type, id, url, author, at}, scope, constrains: [ids]}]` |
| `related_work` | `{ids: [str]}` | `[{id, type, title, state, url, at}]` (PRs that touched, tickets implemented by them, issues mentioning) |
| `tests_for` | `{ids: [str]}` | `[{testId, label, method, confidence}]` |
| `owners` | `{ids: [str]}` | `[{personId, name, basis: [str], score}]` |
| `procedures_for` | `{ids: [str]}` | `[{procedureId, title, testCommand, coChangedPaths, steps}]` |
| `get_code` | `{id}` (function, class, chunk or file id) | `{id, path, startLine, endLine, language, code}` with line-numbered full source (files over 2,000 lines return an outline plus a hint to request ranges) |
| `get_code_range` | `{path, startLine, endLine}` (≤ 400 lines) | `{path, startLine, endLine, code}` from the snapshot stored in the graph |
| `file_outline` | `{path}` | `{path, language, classes: [{id, name, startLine, endLine, methods: [...]}], functions: [{id, qualifiedName, signature, startLine, endLine}], imports: [...]}` |
| `find_symbol` | `{name, kind?: "function"\|"class"}` | `[{id, qualifiedName, path, startLine, signature}]` (exact, then case-insensitive, then suffix match) |
| `references` | `{id}` | `[{callerId, callerQualifiedName, path, line, snippet}]` (call sites with ±2 lines of context) |
| `history` | `{id, limit?: ≤20}` | `[{commitSha, shortSha, subject, author, authoredAt, changeType, linesChanged, prNumber?}]` newest first, following `RENAMED_TO` backwards so history from earlier names is included (each item says which name it was then) |
| `get_code_at` | `{id, commitSha}` | `{id, commitSha, path, startLine, endLine, code}`: the symbol's source as it was at that commit, read from git; `{found: false}` if it did not exist then |
| `search_code` | `{query, pathPrefix?, limit?: ≤20}` | `[{id, path, startLine, endLine, snippet, score}]` (full-text over function and class bodies and chunks) |
These code tools serve source from the graph (the ingested snapshot), so the agent reads code through the graph instead of walking the file tree. When the working copy has changed during a build, Pi reads its own edits from the files it changed; the tools always describe the base snapshot and say so in each response (`"snapshot": "<sha>"`).
Each call produces `tool.called` and `tool.result` events (B.C2) with the node ids touched.

### B.C5 Ticket format
```json
{"objective": "One sentence.",
 "context": "Two to four sentences: what was found and why it matters.",
 "acceptanceCriteria": ["Given … when … then …"],
 "constraintsToPreserve": [{"text": "Invoice exports stay Finance-only.", "evidenceIds": ["actron:decision:…"]}],
 "affectedFunctions": ["code:fn:…"],
 "testPlan": [{"kind": "existing|new", "target": "code:fn:… or test id", "command": "pytest tests/test_x.py::test_y"}],
 "outOfScope": ["…"],
 "targetBranch": "main",
 "requestId": "req_…", "revision": 2}
```
Canonical JSON: `json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)` over the object **without** `revision`; hash = SHA-256 hex. The Linear description renders the ticket in markdown, then a line `<!-- actron:ticket sha256=<hash> rev=<n> -->` and a fenced ```json block with the canonical JSON. Reading the issue: parse the block, recompute the hash, compare to the marker and to the stored revision; any mismatch → `external_edit`.

### B.C6 Build inputs and outputs
`BuildInput {requestId, buildId, revisionHash, ticket, evidence (shared-query JSON subset), procedures, baseSha, branch, testCommand, maxRepairs, timeoutSeconds}`; `BuildResult {status: passed|failed|stopped, headSha?, filesChanged[], testsPassed, testsFailed, failing[], attempts, stopReason?, prNumber?, prUrl?, tokens {input, output}, durationMs}`.

### B.C7 API request and response schemas (added by the build, 17 Oct 2026; frozen)
The authoritative machine-readable form is the OpenAPI document generated by FastAPI (`/api/openapi.json`, written to `frontend/lib/api/openapi.json` by `scripts/gen_types.sh`); this section is the human contract both halves built against. JSON uses camelCase. Times are ISO 8601 UTC strings. Every write takes `Idempotency-Key` (UUID) and, when a session cookie is used, `X-CSRF-Token`. Errors are always `{"error": {"code": str, "message": str, "details"?: object}}`.

**Shared shapes**
```ts
type State = "Investigating" | "Needs your input" | "Ticket ready" | "Awaiting approval" | "Building"
           | "Needs attention" | "PR ready for review" | "Changes requested" | "Done" | "Cancelled";
type Label = "conflict" | "possible_conflict" | "nothing_found" | "clear";
type Kind = "feature" | "bug" | "question";
type Surface = "slack" | "ui" | "system";
type PersonRef = { personId: string | null; userId: string | null; name: string; avatarUrl: string | null };
type EventEnvelope = { id: number; requestId: string | null; seq: number | null; type: string; at: string;
                       actor: "actron" | "person" | "slack"; surface: Surface; payload: Record<string, unknown> };
type Question = { questionId: string; text: string; kind: "choice" | "text";
                  options: { value: string; label: string; note?: string; preselected?: boolean }[];
                  evidenceIds: string[]; required: boolean;
                  answer: { value: string; by: PersonRef; surface: Surface; at: string } | null };
type TicketContent = /* B.C5 without requestId/revision */ {...};
type Revision = { n: number; hash: string; content: TicketContent; createdBy: string; createdAt: string;
                  linear: { issueId: string; identifier: string; url: string } | null; externalEdit: boolean };
type Approval = { id: string; kind: "ticket" | "pr"; target: string; status: "accepted" | "refused";
                  reason: string | null; by: PersonRef; surface: "slack" | "ui"; at: string };
type Build = { id: string; status: "queued" | "running" | "passed" | "failed" | "stopped" | "waiting_budget";
               queuePosition: number | null; branch: string; baseSha: string; headSha: string | null;
               testsPassed: number; testsFailed: number; attempts: number; startedAt: string;
               finishedAt: string | null; stopReason: string | null;
               tokens: { input: number; output: number }; costUsd: number; report: BuildReport | null };
// Added 18 Oct 2026 (W10); written by flow/build.py build_ui_report, read by frontend/lib/build-report.ts.
type BuildReport = { tests: { name: string; status: "pass" | "fail" | "skip"; output?: string }[];
                     constraints: { text: string; status: "holds" | "broken" | "unverified";
                                    proof: { kind: "test" | "evidence"; label: string } | null }[];
                     filesChanged: { path: string; additions: number; deletions: number }[];
                     procedures: { title: string; testCommand: string }[];
                     testsAdded: string[]; notes: string; pi: object | null /* Pi's REPORT.json */ };
type Pr = { number: number; url: string; headSha: string; state: "open" | "merged" | "closed"; targetBranch: string };
type RequestSummary = { id: string; title: string; kind: Kind; state: State; label: Label | null;
                        requester: PersonRef; source: "slack" | "ui"; createdAt: string; updatedAt: string;
                        lastEvent: { type: string; sentence: string; at: string } | null;
                        pipelineStep: 1 | 2 | 3 | 4 | 5 | 6; needsYou: boolean };
type RequestDetail = RequestSummary & {
  text: string; headline: string; purpose: string;
  slack: { channel: string; threadTs: string; permalink: string | null } | null;
  findings: SharedQuery | null;           // PROMPT appendix D
  evidence: Evidence[]; questions: Question[];
  revisions: Revision[]; currentRevision: { n: number; hash: string } | null;
  approvals: Approval[]; builds: Build[]; pr: Pr | null;
  investigation: { mode: "agent" | "pipeline"; toolCalls: number; tokens: { input: number; output: number };
                   costUsd: number; stub: boolean } | null;
  outcome: "approved" | "answered" | "cancelled" | "closed" | null;
  answer: { text: string; citations: Evidence[] } | null;          // Q&A
  allowedActions: ("answer" | "edit_ticket" | "approve_ticket" | "pr_feedback" | "approve_pr" | "close_pr"
                   | "retry" | "cancel")[] };
type Evidence = { evidenceId: string; role: "conflict" | "constraint" | "impact" | "similar_work" | "owner" | "test";
                  nodeId: string; nodeType: string; title: string; quote: string | null;
                  source: { type: string; id: string; url: string | null; author: string | null; at: string | null };
                  confidence: number; tier: "HIGH" | "MEDIUM" | "POSSIBLE"; path: string[] };
type GraphNode = { id: string; type: string; label: string; group: "code" | "github" | "slack" | "linear" | "core";
                   count?: number; props?: Record<string, unknown> };
type GraphLink = { from: string; to: string; type: string; method: string | null; confidence: number | null; count?: number };
type Subgraph = { mode: "aggregated" | "expanded"; nodes: GraphNode[]; links: GraphLink[]; truncated: boolean };
type ConnectionView = { id: string; provider: "github" | "code" | "slack" | "linear" | "slack_export";
                        status: "connected" | "error" | "disconnected"; config: Record<string, unknown>;
                        secretLast4: string | null; createdAt: string; updatedAt: string;
                        sync: { state: "NOT CONNECTED" | "BACKFILLING" | "SYNCING" | "PARTIAL" | "FAILED" | "UP TO DATE";
                                lastSyncedAt: string | null; reason: string | null; perMinute: number;
                                counts: Record<string, number> } };
type Run = { id: string; source: string; mode: "backfill" | "incremental"; status: "running" | "done" | "partial" | "failed";
             startedAt: string; finishedAt: string | null; items: Record<string, number>;
             errors: { action: string; error: string; url?: string; at: string }[] };
```

**Routes** (request → response; status codes beyond 200 listed)
| Route | Request | Response |
|---|---|---|
| `GET /api/auth/slack/start` | `?next=` | 302 to Slack OIDC; 404 when Slack sign-in is not configured |
| `GET /api/auth/slack/callback` | `?code&state` | 302 to `next` with session and CSRF cookies; 302 `/app/signin?error=slack` on failure |
| `POST /api/auth/dev-login` (dev only) | `{name: str}` | `{user: PersonRef, workspace: {id, name}}` + cookies; 404 in prod |
| `POST /api/auth/logout` | — | 204 |
| `GET /api/me` | — | `{user: PersonRef & {email, slackUserId}, workspace: {id, name, role}, csrfToken: str, env: "dev"\|"prod", devFixtures: bool}`; 401 |
| `GET /api/connectors` | — | `{providers: [{provider, title, label, oauth: {enabled, url}?, fields: FormField[], guide: GuideStep[]}]}` (C12 field shape) |
| `POST /api/connectors/{provider}/validate` | `{values: {...}}` | `{ok: bool, found: str, details: object, errors: [{field, message}]}`; 422 |
| `GET /api/connectors/{provider}/options` | `?field=&...values` | `{options: [{value, label, note?, default?: bool, protected?: bool}]}` |
| `GET /api/connectors/{provider}/checks` | — | `{checks: [{id, ok: bool \| null, message, troubleshooting?: str}]}` |
| `GET /api/connections` | — | `{connections: ConnectionView[]}` |
| `POST /api/connections` | `{provider, config, secret?: {...}}` or multipart (`provider=slack_export`, `archive`, `events?`) | 201 `{connection: ConnectionView, runId: str}`; 409 `already_connected`; 422 |
| `PATCH /api/connections/{id}` | `{config: partial}` | `{connection}`; changing `workingBranch` returns `{connection, reingest: true}` |
| `DELETE /api/connections/{id}` | — | 204 |
| `POST /api/connections/{id}/sync` | — | 202 `{triggered: true}` |
| `POST /api/connections/{id}/reset-cursor` | — | `{connection}` |
| `GET /api/ingestion/status` | — | `{sources: [{provider, state, counts, perMinute, lastSyncedAt, reason, runId}], linking: {referencesResolved, pending, decisions, identities, linksKept, linksDropped}, memoryPercent: number, totals: {nodes, links}}` |
| `GET /api/ingestion/runs` | `?source=&limit=` | `{runs: Run[]}` |
| `POST /api/requests` (and `POST /api/ask` with `kindHint=question`) | `{text: str (3..4000), kindHint?: Kind}` | 201 `{request: RequestDetail}` |
| `GET /api/requests` | `?group=needs_you\|running\|done&limit=` | `{requests: RequestSummary[], counts: {needsYou, running, done}}` |
| `GET /api/requests/{id}` | — | `{request: RequestDetail}`; 404 |
| `GET /api/requests/{id}/events` | SSE, `Last-Event-ID` | `id: seq`, `event: type`, `data: EventEnvelope` |
| `GET /api/requests/{id}/replay` | — | `{request: RequestDetail, events: EventEnvelope[]}`; 409 `not_finished` |
| `GET /api/public/replays/{id}` | — | redacted replay; 404 when public replays are off |
| `POST /api/requests/{id}/answers` | `{questionId, value}` | `{result: ActionResult}`; 409 |
| `POST /api/requests/{id}/ticket/revisions` | `{content: TicketContent}` | `{result, revision: Revision}`; 409 |
| `GET /api/requests/{id}/ticket/revisions` | — | `{revisions: Revision[], diffs: [{from, to, changes: [{field, before, after}]}]}` |
| `POST /api/requests/{id}/approvals` | `{kind: "ticket"\|"pr", revisionHash?, headSha?}` | 200 `{result}` accepted; 202 `{result: {status: "pending"}}`; 409 `{error: {code: "stale_revision"\|"stale_head"\|"external_edit"\|"invalid_transition"\|"not_an_approver"}}`; 403 |
| `POST /api/requests/{id}/feedback` | `{text, headSha}` | `{result}`; 409 |
| `POST /api/requests/{id}/cancel` | `{reason?}` | `{result}`; 409 |
| `POST /api/requests/{id}/retry` | — | `{result}`; 409 |
| `POST /api/requests/{id}/close-pr` | `{reason?}` | `{result}`; 409 |
| `GET /api/requests/{id}/pr/diff` | — | `{files: [{path, status, additions, deletions, patch}], headSha}` |
| `GET /api/requests/{id}/builds/{buildId}/log` | — | `text/plain` |
| `GET /api/graph/subgraph` | `?requestId=&mode=aggregated\|expanded` | `Subgraph` |
| `GET /api/graph/nodes/{id}` | — | `{node: GraphNode & {props}, sources: [{type, url}], incoming: GraphLink[], outgoing: GraphLink[]}` |
| `GET /api/graph/nodes/{id}/neighbours` | `?types=&limit=` (≤ 100) | `Subgraph` |
| `GET /api/graph/search` | `?q=&types=&limit=` | `{results: [{id, type, label, snippet, score}]}` |
| `GET /api/graph/path` | `?from=&to=&maxHops=` | `{found: bool, nodes: GraphNode[], links: GraphLink[]}` |
| `GET /api/graph/sample` | `?limit=` (≤ 3000) | `Subgraph` |
| `GET /api/graph/stats` | — | `{nodeTypes: number, nodes: number, links: number, byType: [{type, group, count}], ontology: {types: number, relationships: number}}` |
| `GET /api/graph/quick/{tool}` | `?ids=&depth=` (`callers`, `owners`, `decisions_for`, `shortest_path`, `tests_for`) | the MCP tool's output (B.C4) |
| `GET /api/stream` | SSE, `Last-Event-ID` | `id: events.id`, workspace events |
| `GET /api/notifications` | `?unread=1` | `{notifications: [{id, kind, title, body, requestId, tab, readAt, createdAt}], unread: number}` |
| `POST /api/notifications/{id}/read` | — | 204 |
| `GET /api/settings` | — | `{settings: {approvers: str[], modelPrices: {...}, allowPublicReplays: bool, thresholds: {conflict: number, possibleConflict: number, linkKeep: number}, models: {decision, writing, agent, coding}, jobs: [{job, primitive, provider: "jev"\|"llm"\|"stub", status: "live"\|"stub"}], botIdentity: {name, email}, budget: {capUsd, spentTodayUsd}, schedules: {code, github, linear, slack}}}` |
| `PUT /api/settings` | partial settings | `{settings}`; 422 |
| `POST /api/settings/budget` | `{capUsd}` | `{settings}` |
| `GET /api/health` | — | A1 shape; 503 when a store is down |
| `GET /api/slack/install`, `GET /api/slack/oauth/callback` | B11a | 302 |
| `POST /webhooks/github` | GitHub payload, signed | 204; 401 bad signature |
| `POST /slack/events`, `/slack/commands`, `/slack/interactions` | Slack payloads, signed | 200 within 3 s; 401 bad signature |

`ActionResult = {status: "accepted" | "refused" | "pending" | "duplicate", reason: str | null, eventId: int | null, state: State}`.

---

## B1. Request service, journal and live updates

**Interfaces** (`actron/flow/service.py`, the only way to change a request):
```python
async def create_request(ws: str, *, text: str, actor: Actor, source: Literal["slack","ui"],
                         slack: SlackRef | None = None, kind_hint: str | None = None) -> RequestView: ...
async def answer(ws, request_id, question_id, value, actor, idempotency_key) -> ActionResult: ...
async def edit_ticket(ws, request_id, content, actor, idempotency_key) -> ActionResult: ...
async def approve(ws, request_id, kind: Literal["ticket","pr"], target: str, actor, idempotency_key) -> ActionResult: ...
async def feedback(ws, request_id, text, head_sha, actor, idempotency_key) -> ActionResult: ...
async def cancel(ws, request_id, reason, actor, idempotency_key) -> ActionResult: ...
async def retry(ws, request_id, actor, idempotency_key) -> ActionResult: ...
async def close_pr(ws, request_id, reason, actor, idempotency_key) -> ActionResult: ...
async def raise_budget(ws, cap_usd, actor, idempotency_key) -> ActionResult: ...   # workspace-level; signals waiting builds
async def emit(ws, request_id, type, payload, actor="actron", surface="system") -> Event: ...   # used by activities
```
- **Who writes what (single authority):** the service records the *user's action*; the workflow decides the *outcome*.
  - Service, inside each action: idempotency check (Redis `SET idem:<key> NX EX 86400`; on hit return the stored result) → validate the actor is a member of the workspace (and, for approvals, an allowed approver, B12a) → quick pre-check against the workflow's `state()` query (only to return a fast, friendly 409 for obviously invalid actions) → PostgreSQL transaction inserting one action event (`answer.received`, `approval.requested`, `review.feedback`, `request.cancel_requested`, ...) with the next `seq` (`SELECT … FOR UPDATE` on the request row) and `signal_status = 'pending'` → signal the workflow with the `idempotencyKey` → set `signal_status = 'sent'` → publish the event on Redis (`req:<id>`, `ws:<ws>:requests`).
  - Workflow (through activities): validates the action against its own state (the authority), then writes the `approvals` row (`accepted` or `refused` with reason), the outcome events (`approval.recorded` / `approval.refused`, `request.state_changed`), the `requests.state` mirror and the `Request` node in FalkorDB, and publishes them.
  - API response for approvals: the service waits up to 3 seconds for the workflow's outcome event (Redis subscription) and returns it (200 accepted, 409 with reason); if the outcome is not back in time, it returns 202 and the client follows the SSE stream.
- If signalling fails after commit, `signal_status` stays `pending` and a reconciler activity (every 30 s) re-sends; the workflow deduplicates signals by `idempotencyKey`.
- **Ids:** requests use `req_<ulid>` in the API, events, URLs, Slack action ids and Appendix D's `requestId`; the graph node id is `actron:request:<req_ulid>`.
- **Workspace stream resume:** `GET /api/stream` sends `id: <events.id>` (the global bigserial) and replays `events.id > Last-Event-ID` for that workspace; request streams use `seq`.
- `create_request` starts `RequestWorkflow` with id `request:<request_id>`; `kind` from J7 unless `kind_hint` is given.

**SSE** (`GET /api/requests/{id}/events`): on connect, replay events with `seq > Last-Event-ID` (or all) from PostgreSQL, then subscribe to Redis `req:<id>`; each message `id: <seq>`, `event: <type>`, `data: <json envelope>`; heartbeat comment every 15 s; workspace stream `GET /api/stream` for Home, inbox, ingestion and footer.

**Acceptance criteria**
- B-AC-1: `create_request` creates a row, a `request.created` event (seq 1), a `Request` node, and a running workflow; Slack and UI sources both work.
- B-AC-2: The same idempotency key used twice for any action returns the same result and creates one event.
- B-AC-3: A non-member actor is refused with 403 and a `approval.refused`/no event as appropriate.
- B-AC-4: SSE replay after reconnect with `Last-Event-ID: 5` delivers events 6.. in order with no duplicates and then live events.
- B-AC-5: A signal failure after commit is retried by the reconciler and applied once.
- B-AC-6: Event `seq` is gap-free per request under concurrent actions (Slack and UI at the same time).

Tests: `tests/unit/flow/test_service.py`, `tests/integration/test_sse.py`, `tests/integration/test_idempotency.py`, `tests/integration/test_reconciler.py`.

---

## B2. RequestWorkflow (Temporal)

**Freshness gate (no work on stale code).** Before the investigation and again before the build, an activity `ensure_fresh(ws)` compares the graph's `CodeRepository.headSha` with the ingested repository's current **working-branch** head (`git ls-remote origin refs/heads/<workingBranch>`). If they differ, it triggers the code and GitHub syncs and waits for them to finish (child workflow, timeout 10 minutes; on timeout the request moves to `Needs attention` with reason `memory_stale`). It emits `memory.refreshing {fromSha, toSha}` and `memory.refreshed {sha, functionsChanged}`. The build's `baseSha` is always the head the graph was refreshed to, and the context pack is built from that same snapshot, so Pi never works from code that differs from the graph. If GitHub is unreachable, the gate records `memory.unverified` and continues with the graph's head (visible in the UI).

**Workflow** (`workflows/request.py`, deterministic):
```
activity ensure_fresh(ws)
state = Investigating
findings = activity investigate(ws, request_id)            # agent or pipeline; emits events; timeout 10 min
if kind == question: activity write_answer(...); state = Done; return
questions = findings.questions
if questions: state = Needs your input; await all required answers (signal `answer`), remind via activity after 24 h (timer)
ticket = activity draft_ticket(ws, request_id, findings, answers); revision = activity save_revision(...)
activity sync_ticket_to_linear(...) (skipped with a recorded reason when Linear is not connected); state = Awaiting approval
loop:
    await signal approve_ticket | edit_ticket | cancel
    edit_ticket → new revision, sync, continue
    approve_ticket with hash == current → break; else record refusal (activity) and continue
state = Building
activity ensure_fresh(ws, target_branch)   # working branch synced into the graph; target branch head re-read (ls-remote) and its differing files recomputed; deleted target → missing_branch
result = child BuildWorkflow(BuildInput) with handoff event first
start merge watch for the PR (A11) once it is opened
if result.status != passed: state = Needs attention; await retry | edit_ticket | cancel
state = PR ready for review
loop:
    await approve_pr | pr_feedback | cancel
    approve_pr with headSha == current head (activity read_pr_head) → break; else refuse
    pr_feedback → J10 (activity) → new build (Changes requested → PR ready for review) | Needs attention | answer
activity writeback(...) ; state = Done
```
- Every state change calls an activity `set_state(ws, request_id, state)` which writes the event and mirrors (activities are the only I/O).
- `cancel` at any await → cancel child workflow (if any), `set_state(Cancelled)`.
- Workflow uses `workflow.now()` for time; no randomness.

**Acceptance criteria**
- B-AC-7: Time-skipping tests cover every transition in appendix F, including each refusal (`stale_revision`, `stale_head`, invalid state), with events recorded.
- B-AC-8: Two `approve_ticket` signals arriving together (from Slack and UI) produce exactly one accepted approval and one build.
- B-AC-9: `edit_ticket` while `Awaiting approval` voids the earlier approval target; approving the old hash is refused with `stale_revision`.
- B-AC-10: A 24-hour timer sends one reminder notification while waiting for answers or approval (time skipping).
- B-AC-11: `cancel` during `Building` cancels the build child and its running Pi activity (activity receives cancellation).
- B-AC-12: Worker restart in the middle of waiting for approval loses nothing (integration against the real Temporal server: stop worker, start worker, send signal, workflow continues).
- B-AC-13: Q&A requests end in `Done` with an `answer.ready` event and no ticket.
- B-AC-79: A feature or bug request that does not name a branch always receives the target-branch question with the working branch first and preselected, recent branches (protected marked) and "new branch"; a request naming an existing branch skips it; the answer is stored in `ticket.targetBranch` and shown in Slack, the UI and Linear.
- B-AC-80: A build for a non-default target branch checks out that branch's head, includes the differing files in the context pack, marks them in code-tool responses, and opens the PR against that branch.
- B-AC-81: The freshness gate refreshes the target branch's head and differences before the build; a deleted target branch moves the request to `Needs attention` with `missing_branch`.
- B-AC-77: When the repository's head is ahead of the graph (a merged PR not yet ingested), the freshness gate syncs before investigating and before building; the build's `baseSha` equals the refreshed head and the context pack contains the merged code (integration test: merge a change into the test repository, start a new request touching the same function, verify Pi's context shows the merged version).
- B-AC-78: A sync that does not finish within the timeout moves the request to `Needs attention` with reason `memory_stale`; an unreachable GitHub records `memory.unverified` and the UI shows it.

Tests: `tests/workflows/test_request_workflow.py`, `tests/integration/test_request_workflow_real.py`.

---

## B3. Shared query and algorithms

**Named queries** (`graph/queries.py`; each returns typed rows; each has a test with expected output on `tests/fixtures/graph_small.cypher`, a hand-written fixture graph with ~120 nodes covering every relationship used):
- `seeds_fulltext(text, types, limit)`: calls `db.idx.fulltext.queryNodes(label, text)` per type, merges by score.
- `decisions_constraining(ids)`: `MATCH (d:Decision)-[c:CONSTRAINS]->(t) WHERE t.id IN $ids AND coalesce(d.deleted,false)=false OPTIONAL MATCH (d)-[e:EXTRACTED_FROM]->(src) OPTIONAL MATCH (d)-[:APPROVED_IN]->(ap) RETURN …`.
- `related_work(ids)`: PRs via `PR_TOUCHED` and `COMMENT_ON_FUNCTION`; tickets via `IMPLEMENTED_BY`; issues and messages via `MENTIONS`.
- `callers(id, depth)`: backwards variable-length match `MATCH (f {id:$id})<-[:CALLS*1..3]-(c:CodeFunction)` returning distinct callers with their minimum depth. **Do not use `algo.BFS` for callers:** it follows outgoing relationships only and has no direction argument (verified on v4.22.1, 17 Oct 2026; see `docs/falkordb.md`).
- `callees(id, depth)`: forward variable-length match `-[:CALLS*1..3]->` (or `algo.BFS(node, depth, 'CALLS')`, which yields outgoing `nodes`).
- `impact(ids, depth)`: everything that could break = callers (backwards over `CALLS` and `INSTANTIATES`, depth ≤ 3) plus their files and covering tests (`TESTS` backwards).
- `criticality(ids)`: stored properties.
- `shortest_path(a, b, max)`: `MATCH (a {id:$a}), (b {id:$b}) CALL algo.SPpaths({sourceNode: a, targetNode: b, relDirection: 'both', maxLen: $max}) YIELD path RETURN path` (verified: finds paths across mixed directions without a weight property). Do **not** use Cypher `shortestPath` here: FalkorDB allows it only inside `WITH`/`RETURN` and only for directed patterns.
- `owners(ids)`: `KNOWS_ABOUT`, `OWNS`, `BLAME_OWNS` via `IS_GIT_AUTHOR`.
- `subgraph_for_request(request_id, mode)`: the request node, its `ABOUT` seeds, everything in its latest `Investigation` `FOUND` set, and paths between them; aggregated mode groups by type when more than 300 nodes.
- `shared_query(request_id, seed_ids)`: composes the above into B.C3.
- **Every lookup by id includes the node label**, derived with `ids.parse_id(id)` (for example `MATCH (f:CodeFunction {id: $id})`), because FalkorDB indexes are per label and an unlabelled `MATCH (n {id: $id})` scans every node. Tools and queries that accept "any node" resolve the label first. The same rule applies to `GraphStore.get_node`.
- Every query sets an explicit `LIMIT` and runs with `read_only=True`; timeouts are 2 s for tools and 10 s for the shared query.

**Acceptance criteria**
- B-AC-14: Each named query returns the expected rows on the fixture graph (one test per query, including tombstoned nodes excluded).
- B-AC-15: `shared_query` output validates against the B.C3 JSON schema and matches a snapshot for the fixture request.
- B-AC-16: Depth limits, row limits and timeouts are enforced (a query on a synthetic 50,000-edge graph returns within its timeout and within its limit).
- B-AC-17: Algorithm wrappers use the FalkorDB procedure when available and the fallback otherwise; both give the same answer on the fixture graph.

Tests: `tests/integration/graph/test_queries.py`, `tests/integration/graph/test_shared_query.py`, `tests/integration/graph/test_algos.py`.

---

## B4. MCP graph server

**Rules:** tools exactly as B.C4; JSON schemas generated from Pydantic models; descriptions written so an agent knows when to use each tool (one sentence each, with an example); errors return `{error: {code, message}}` instead of raising; every call logged as events with `by`.

**Acceptance criteria**
- B-AC-18: An MCP client (the SDK's client) lists exactly the tools in B.C4 with their schemas.
- B-AC-19: Each tool returns the documented shape on the fixture graph, respects limits and timeouts, and never returns secrets or full bodies above 4,000 characters.
- B-AC-20: A run token for workspace A cannot read workspace B (calls return an authorisation error).
- B-AC-21: Every call emits `tool.called` and `tool.result` with node ids (verified through the event store).
- B-AC-22: The HTTP transport is reachable from a container on the internal network and not from the host's public interface (compose config test).

Tests: `tests/integration/mcp/test_tools.py`, `tests/integration/mcp/test_transport.py`.

---

## B5. Investigator agent and fallback pipeline

**Agent** (`flow/investigator_agent.py`):
- Model: `MODEL_AGENT` via LiteLLM with tool calling. Tools: the MCP tools converted to function schemas.
- System prompt (in `models/prompts/investigator.md`): role "You investigate a software change request against the team's history graph"; goals: find the exact code the request touches, the decisions that constrain it, earlier related work, the impact (callers, tests, criticality), the owners; rules: use tools rather than guessing; never state a fact without a node id; stop when you can fill the findings schema; at most 12 tool calls; prefer `search` → `get_node` → `decisions_for`/`callers`/`impact`/`related_work`/`tests_for`/`owners`.
- Loop: up to 12 tool calls or 3 minutes; each call via the MCP client (events emitted by the server); after the loop, the agent returns a JSON object `{seedIds, decisionIds, relatedWorkIds, notes}`; Actron then calls `shared_query(request_id, seedIds)` to build the canonical findings (so the output shape never depends on the model), runs J6 on each decision and J8, and writes questions with `write_questions`.
- Seeds are also scored with J5 when more than 5 are proposed.
- Writes `Investigation` node, `HAS_INVESTIGATION`, `FOUND` links with role, rank and path, and `ABOUT` links to seeds.

**Fallback pipeline** (`flow/investigate.py`, used when no `MODEL_AGENT` key, or the agent fails twice): `seeds_fulltext` (top 20) → J5 rank (or full-text score when stubbed) → `shared_query` → J6 per decision → label → J8 → `write_questions` (template-based when the LLM is stubbed: "Should <constraint> still hold for <request objective>?").

**Label rule:** `conflict` if any decision has J6 `restricts` ≥ 0.8; `possible_conflict` if any has 0.5–0.8, or a seed's criticality percentile ≥ 90 with no decision; `nothing_found` if no seeds above threshold and no decisions; else `clear`. The four-value label is stored on the request (events, `requests` row, API). `Investigation.conflictLabel` in the graph uses the ontology's values: `conflict`, `possible_conflict`, and `none` for both `nothing_found` and `clear`.

**Acceptance criteria**
- B-AC-23: With a scripted fake LLM that issues a known sequence of tool calls, the agent emits matching `tool.called`/`tool.result` events, stops at the budget, and produces findings equal to the expected shared-query snapshot.
- B-AC-24: The agent never includes an id in findings that no tool returned (filtering test).
- B-AC-25: The fallback pipeline produces valid findings on the fixture graph with stubs only.
- B-AC-26: The label rule produces each label on four fixture requests (conflict, possible conflict, nothing found, clear).
- B-AC-27: Agent failure twice switches to the pipeline and records `investigation.started {mode: "pipeline"}` with the reason.
- B-AC-28: `Investigation`, `FOUND`, `ABOUT` are written with roles, ranks and paths.
- B-AC-29: On the evaluation fixtures `tests/fixtures/eval/requests.yaml` (at least one request per label, built on the fixture graph), each request yields its expected label (eval test, records results with stub or live label). Do not use `data/sample/`.

Tests: `tests/unit/flow/test_investigator_agent.py`, `tests/unit/flow/test_pipeline.py`, `tests/unit/flow/test_label_rule.py`, `tests/eval/test_investigation_sample.py`.

---

## B6. Questions and answers

- `write_questions(findings)` returns at most 3 questions, each `{questionId, text, kind: "choice"|"text", options?: [{value, label}], evidenceIds, required: true}`. Prefer choices. Example: "Should invoice exports stay Finance-only after this change?" with options "Yes, keep Finance-only" / "No, project admins too".
- Answers can come from Slack buttons (`action_id = answer:<requestId>:<questionId>:<value>`), a Slack thread reply parsed when it starts with the question number (text questions), or the UI.
- **Target branch question (always asked before the ticket, for feature and bug requests).** Unless the request text names a branch that exists ("on release-2.3", "into develop", matched against the repository's branches), Actron adds a required question with `questionId = "target_branch"`: "Which branch should this change go into?" Options, in order: the **working branch** (first, preselected, marked "tracked by Actron's memory"), up to 5 most recently updated other branches (protected ones marked "protected"; each marked "not tracked: Actron reads its differing files directly"), and "A new branch from <working branch>". If the user picks a branch other than the working branch, the next message states plainly that Actron's memory tracks the working branch and that the build will read the other branch's differing files from the checkout. A text answer naming any existing branch is accepted. The answer becomes `ticket.targetBranch`. A request that only had the branch question still goes through `Needs your input` for that one question.

**Acceptance criteria**
- B-AC-30: Questions are tied to evidence ids that exist in the findings; at most 3; choices preferred when the decision has a clear yes/no.
- B-AC-31: Answers from Slack and UI both record `answer.received` with surface; a second answer to the same question replaces the first only before the ticket is drafted.

Tests: `tests/unit/flow/test_questions.py`, `tests/integration/test_answers.py`.

---

## B7. Tickets

- `draft_ticket` uses `write_ticket` (LLM, JSON schema = B.C5) with the findings and answers; when stubbed, a deterministic template fills the schema from findings (objective = request title; constraints = approved decisions' statements; affected functions = seeds; test plan = covering tests).
- `save_revision` canonicalises, hashes, inserts `ticket_revisions` (n = previous + 1), emits `ticket.revised`.
- `sync_ticket_to_linear` creates or updates the issue (spec A A10 writes), stores `linear_issue_id`, emits `ticket.synced`, writes `TRACKED_BY` in the graph.
- External edit detection runs before any approval is accepted (read the issue, compare the hash).

**Acceptance criteria**
- B-AC-32: The canonical hash is stable under key order and whitespace changes and changes when any content field changes (property test).
- B-AC-33: Revisions increment; the Linear description contains the marker and JSON block; parsing it back yields the same hash.
- B-AC-34: An external edit in Linear before approval causes the approval to be refused with `external_edit` and a new revision to be required.
- B-AC-35: With Linear not connected, the ticket is stored and shown in the UI and Slack; the approval flow still works; the event records "Linear not connected".

Tests: `tests/unit/flow/test_ticket_canonical.py`, `tests/integration/test_ticket_sync.py`.

---

## B8. Approvals

- `approve(kind="ticket", target=<hash>)` and `approve(kind="pr", target=<headSha>)` go through B1 (the service records `approval.requested`); the workflow validates and its activity writes the `approvals` row with `accepted`/`refused` and reason, as defined in B1 "Who writes what".
- UI and Slack both display exactly what is approved (revision number and short hash; PR number and short SHA).

**Acceptance criteria**
- B-AC-36: Approving the current revision from Slack moves to `Building`; the UI updates within one second through SSE.
- B-AC-37: Approving a stale revision or head is refused with the reason shown in both surfaces (`approval.refused`).
- B-AC-38: Simultaneous approvals from both surfaces produce one accepted row and one no-op (same response, no second build).

Tests: `tests/integration/test_approvals.py`.

---

## B9. Build with Pi (BuildWorkflow)

**Steps (each an activity on the `build` task queue)**
1. `prepare_checkout(build)`: using the effective values (spec A, A11 step 3), clone or fetch the **ingested repository** into `<ACTRON_BUILD_HOST_DIR>/<buildId>/repo`, check out the current head of `ticket.targetBranch` (that head is `baseSha`, the same commit the freshness gate refreshed the graph to), create branch `actron/<requestId>-r<revision>`, and add the effective push target as the push remote. Fail with `missing_fork` if the effective push target is empty or equals the upstream, and with `missing_branch` if the target branch no longer exists (request → `Needs attention`).
   **Paths and Docker:** the worker starts containers through the mounted Docker socket, so bind-mount paths must be host paths. Build directories live under `ACTRON_BUILD_HOST_DIR` (default `/var/lib/actron/builds`), mounted into the worker at the **same path**, so the same path works for `docker run -v`. The `actron-build` Docker network is defined in compose with the worker attached (so Pi reaches `worker:8765`); `make up` builds the `actron-pi` and `actron-test-runner` images.
   **Target branch different from the working branch (the ingested one):** compute `git diff --name-status <working-branch head>...<baseSha>`; the context pack includes, for every differing file that touches the ticket's affected code, the file's full content from the checkout (marked "differs on <targetBranch>"); code tools receive the list of differing paths for this run and add `"differsOnTarget": true` with a note to read those files from disk.
2. `write_build_context(build)`: write the context folder (mounted read-only at `/context`, except `notes.md`) with: `ticket.json`, `evidence.json`, `procedures.json`, `TASK.md` (rendered instructions, below), **`code.md` (the context pack)**, `notes.md` (writable; Pi's working notes), and for revisions after review feedback `previous-build.md` (the earlier build's notes, diff summary, test results and the reviewer's feedback).
   **Context pack (`code.md`)**, built from the graph so Pi does not need to explore: for each affected function and class in the ticket, the full line-numbered source; for each, its direct callers and callees (signature, path, call-site lines with ±2 lines of context), the tests that cover it (name, path, full source when under 120 lines), the outline of every touched file (classes and functions with line ranges), the decisions that constrain it (statement and quote), and the procedure for its area (test command, files that usually change together). Size limit 60,000 characters; if larger, include full source for the affected symbols and outlines for the rest, and say which tool to call for more.
3. `run_pi(build)`: `docker run --rm --name actron-pi-<buildId> --network actron-build --cpus 2 --memory 4g --pids-limit 512 --read-only --tmpfs /tmp -v <repo>:/work -v <context>:/context:ro -e <ONE model key env> -e ACTRON_MCP_URL=http://worker:8765/mcp -e ACTRON_RUN_TOKEN=<token> actron-pi:latest <pi command>`; `actron-build` network allows only the model provider and the MCP server (egress policy via a proxy container or Docker network rules; if egress filtering is not feasible, document the limitation). Pi command **[VERIFY in the image]**: print/JSON mode with the task file as the prompt, the model from `MODEL_CODING`, MCP server configured. Stream Pi's JSON output; map each step to a `build.step` event (`text` in plain language, `file`, `detail`). Heartbeat every 10 s. Timeout `ACTRON_BUILD_TIMEOUT_SECONDS`.
4. `check_diff(build)`: compute the diff against base. Reject (status `stopped`, reason `tests_weakened`) if any existing test file has deleted test functions, removed or loosened assertions (`assert` lines removed, `expect(`/`assert.` calls removed, Clojure `(deftest` or `(is` forms removed, `pytest.skip`/`xfail`/`.skip(`/`.only(`/`it.skip`/`describe.skip`/`^:skip` added), or deleted test files. Files outside `affectedFunctions`' files trigger J9; probability ≥ 0.7 → stop with `scope_change`.
5. `run_tests(build)`, in two steps:
   - **5a. Prepare dependencies (networked):** in an `actron-test-runner` container *with* network but **without any credentials**, install dependencies into a per-repository cache volume keyed by the lockfile hash (`npm ci` or `pnpm install --frozen-lockfile` from `package-lock.json`/`pnpm-lock.yaml`; Clojure deps via `npx shadow-cljs` / `clojure -P` when `shadow-cljs.edn` or `deps.edn` exists; `uv sync` or `pip install` for Python). Skipped when the cache for that lockfile already exists.
   - **5b. Run tests (offline):** a second `actron-test-runner` container with `--network none`, the repo and the dependency cache mounted, running the test command. Test command resolution: the ticket's test plan command → the area's procedure → the repository default: `package.json` `scripts.test` (or `scripts["unit-test"]` when present) for Node and TypeScript repositories, `pytest -q` for Python repositories, `clojure -M:test` / the project's documented test alias for Clojure-only repositories. Record which source the command came from.
   - The `actron-test-runner` image (`infra/docker/test-runner.Dockerfile`) contains Node 22, a JDK 17+ (ClojureScript builds), Python 3.12, and a headless VS Code test host's system libraries only if the repository's unit tests need them (record the decision).
   - Result parsers: pytest JUnit XML (`--junitxml`), Mocha JSON reporter (`--reporter json`; verified 17 Oct 2026: Calva's `package.json` has `"unit-test": "npx mocha --exit --require ts-node/register 'src/extension-test/unit/**/*-test.ts'"`, so the default command is `npm run unit-test -- --reporter json`), Jest and Vitest JSON reporters, and a fallback that reads the exit code and the last 200 lines of output when no reporter is available. Emit `tests.result`.
6. Repair loop: on failures, write the failing output into `/context/failures.md` and run Pi again (attempt + 1) up to `ACTRON_MAX_REPAIRS`; emit `build.repair`. **Memory across attempts:** the repair continues the same Pi session (session resume or RPC session kept alive, whichever Pi supports **[VERIFY]**), so Pi keeps what it already read and tried; if resuming is not possible, the new run gets `notes.md`, a summary of its previous attempt (files changed, commands run, the failure) and the same context pack. Pi is instructed to keep `notes.md` current: what it learned about the code, what it changed and why, what remains.
7. `commit_and_push(build)`: `git -c user.name=$ACTRON_BOT_NAME -c user.email=$ACTRON_BOT_EMAIL commit -m "<ticket objective>\n\nActron request <id>, ticket revision <n> (<hash short>)"`; push to the fork with a credential helper script reading `GITHUB_TOKEN` from the activity's environment (never in arguments or remote URL). Fail with `missing_identity` if the bot identity is empty.
8. `open_or_update_pr(build)`: `POST /repos/{fork}/pulls` (base = `ticket.targetBranch`, head = the build branch) or update the existing one; body template below (it names the target branch); emit `pr.opened`/`pr.updated`.

**Making Pi follow the instructions (enforcement, not only instructions).** Instructions alone are not enough; the orchestrator checks Pi's behaviour from its JSON event stream and its outputs:
1. **Delivery:** the work protocol is delivered as Pi's system or context prompt (through Pi's supported mechanism: a system-prompt flag, an `AGENTS.md`-style context file, or a prompt template **[VERIFY which Pi supports]**) *and* as `/context/TASK.md`; the first user message is "Follow /context/TASK.md exactly. Start with step 1."
2. **Exploration watch:** every Pi tool event is classified. Direct file reads of paths that are not in the ticket's "Where to work" list and not already edited by Pi, directory listings, and grep or find commands over the repository count as exploration. After 3 exploration events, the orchestrator sends a steering message (RPC mode) or, in print mode, records it and appends the reminder to the next attempt: "Use the graph tools (get_code, file_outline, find_symbol, references, search_code) instead of exploring the repository." After 10, the attempt is stopped and retried once with the reminder at the top of TASK.md. Counts are emitted as `build.step` details and shown in the Build tab.
3. **Graph-first check:** before Pi edits any function that has callers, the event stream must show `callers`, `references` or `impact` for it (or the information must be in code.md). If not, a reminder is sent; the count is reported.
4. **Required outputs:** a plan at the top of `notes.md` within the first 5 tool events (else a reminder); `REPORT.json` present and valid against its schema at the end; the test command run at least once after the last edit. Missing any of these → the attempt counts as failed and a repair attempt starts with the missing item named first.
5. **Hard guards (unchanged):** the diff check for weakened tests, the scope check (J9), the time and token budgets, and STOP.md handling.
6. **Reporting:** every reminder and guard result appears in the Build tab and `BUILD-REPORT.md` so the team can see how well Pi followed the protocol.

**TASK.md for Pi** (rendered; this exact structure, filled from the ticket, evidence and procedures):
```
# Task
<objective>
## Acceptance criteria
- …
## Constraints you must preserve (each with its evidence)
- <constraint> — evidence: <quote> (<source>)
## Where to work
<affected functions with file paths and line ranges>
## How changes are validated here
<procedure test command and co-changed paths>
## Work protocol (follow every step, in order)
1. Read /context/code.md completely. It already contains the exact source of the code you must change (from the team's graph, every line as it is at the base commit), its callers and callees, the tests that cover it, the outlines of the files involved, the decisions you must preserve and how changes are tested here.
2. Read /context/notes.md (and /context/previous-build.md and /context/failures.md if they exist). Continue from them; do not redo work already recorded.
3. Write a short plan at the top of /context/notes.md: which functions you will change, which tests you will add or update, and which constraint each change must preserve.
4. If you need code that is not in code.md, ask the graph through the MCP tools. Do not list directories, grep the repository or open files to look around.
   - Exact code of a function, class or file: get_code
   - A range of lines: get_code_range
   - What a file contains: file_outline
   - Where something is defined: find_symbol
   - Who calls it, with the call lines: references, callers
   - What a change could break: impact
   - Which tests cover it: tests_for
   - Which decisions constrain it: decisions_for
   - Text search over the code: search_code
   The graph shows the code before your edits. After you edit a file, re-read only that file from disk to see your change.
5. Make the smallest change that meets every acceptance criterion. Open a file directly only to edit it.
6. Add or update tests for the new behaviour. Never delete a test, never remove or loosen an assertion, never add skip, xfail or only markers.
7. Run the test command from "How changes are validated here". If tests fail, fix your change, not the tests.
8. If the work needs anything outside the acceptance criteria or the files listed in "Where to work", stop: write the reason in /context/STOP.md and finish without making that change.
9. Update /context/notes.md: what you changed and why, the tests you ran and their result, what remains.
10. Finish by writing /context/REPORT.json exactly in this shape:
    {"filesChanged": ["path", ...], "testsAdded": ["test id", ...], "testCommand": "...", "testsPassed": true|false,
     "constraintsPreserved": [{"constraint": "...", "how": "..."}], "stopped": false, "notes": "one paragraph"}
## Rules (non-negotiable)
- Do not delete or weaken existing tests.
- Stay within the acceptance criteria and the listed files.
- Read code through the graph tools, not by exploring the file tree.
- Use callers, impact and tests_for before changing any function that other code calls.
- Run the tests before finishing. Always write REPORT.json.
```

**PR body template**
```
## What and why
<objective> (Actron request <id>, ticket <identifier> v<n>)
## Evidence from the team's history
- <quote> — <source link>
## Constraints preserved
- [x] <constraint> — proved by <test name or evidence>
## Tests
<passed>/<total> passed on <head sha short>. Command: `<command>`
## Graph impact
<n> callers checked; criticality of changed functions: <percentiles>
```

**Acceptance criteria**
- B-AC-39: With the labelled fake Pi (a script applying a known patch and printing JSON steps), a build passes, emits steps, tests and `build.passed`, commits as the bot identity, pushes to a local bare repo standing in for the fork, and opens a PR on the fake GitHub.
- B-AC-40: Fake Pi that breaks a test, then fixes it on the repair attempt: one `build.repair`, final `passed`.
- B-AC-41: Fake Pi that deletes a test or adds `pytest.skip`: `stopped` with `tests_weakened`.
- B-AC-42: Fake Pi touching files outside scope with J9 ≥ 0.7: `stopped` with `scope_change`, request → `Needs attention`.
- B-AC-43: Timeout: a fake Pi that hangs is killed at the timeout; status `failed` with reason `timeout`; container removed.
- B-AC-44: Missing fork or bot identity stops with the documented reason before any container runs.
- B-AC-45: Credential isolation: the docker run arguments and environment contain exactly one model key and no `GITHUB_TOKEN`, `SLACK_*`, `LINEAR_*`, `DATABASE_URL`, `ACTRON_SECRET_KEY`; the push never exposes the token in process arguments or the remote URL.
- B-AC-46: The test-run container has no network and the prepare container has no credentials (`docker inspect`); results are parsed for pytest, Mocha and Vitest fixtures and for the exit-code fallback; the test command source (ticket, procedure, or repository default from `package.json`) is recorded.
- B-AC-47: Queue: with one build slot, a second approved request shows `build.queued {position: 1}` and starts after the first finishes.
- B-AC-69: The context pack for a fixture ticket contains the full source of every affected symbol, its callers and callees with call-site snippets, covering tests, file outlines, constraints and the procedure, and respects the size limit with the documented fallback.
- B-AC-70: The code tools (`get_code`, `get_code_range`, `file_outline`, `find_symbol`, `references`, `search_code`) return the documented shapes from the graph snapshot with the `snapshot` sha, and respect limits.
- B-AC-71: A repair attempt keeps Pi's memory (same session, or `notes.md` plus previous-attempt summary when resuming is not possible); a revision after review feedback receives `previous-build.md`.
- B-AC-72: In a scripted fake-Pi run, the number of direct file reads outside the files it edits is zero when the context pack covers the task (measures that the pack removes exploration).
- B-AC-82: `history` returns the commits touching a function newest first, including those from before a rename (via `RENAMED_TO`), and `get_code_at` returns the exact earlier source at a given commit (checked against `git show`), or `found: false` when the function did not exist then.
- B-AC-73: With a scripted fake Pi that explores (lists directories, greps, opens unrelated files), the orchestrator sends a reminder after 3 exploration events, stops and retries after 10, and reports the counts.
- B-AC-74: A fake Pi run without a plan in `notes.md`, without `REPORT.json`, or without running tests after its last edit is treated as a failed attempt; the repair attempt names the missing item first.
- B-AC-75: A fake Pi that edits a function with callers without calling `callers`/`references`/`impact` (and without the callers in code.md) receives a graph-first reminder; the event is reported.
- B-AC-76: `REPORT.json` is validated against its schema, and its contents appear in the Build tab and the PR body.
- B-AC-48: The real `actron-pi` image builds; `pi --version` (or equivalent) runs; a trivial prompt completes when a model key exists; the verified command line is recorded in `docs/runbook.md`.

Tests: `tests/workflows/test_build_workflow.py`, `tests/integration/build/test_build_fake_pi.py`, `tests/integration/build/test_isolation.py`, `tests/integration/build/test_test_runner.py`, `tests/live/test_pi_live.py`; fake Pi in `tests/fakes/fake_pi/`.

---

## B10. Write-back

- After `approve_pr` (or when the PR merges, if observed), run `WritebackWorkflow`: ingest the PR (spec A A8 for one PR), its commits (fetch the fork branch into the clone as a remote ref and run A7 for those commits), `BUILD_TOUCHED` (build → functions from the diff), `DELIVERED_BY`, `PRODUCED`, `HANDED_TO`, `USED_PROCEDURE`, `LEARNED_FROM_BUILD` (increment `successCount`), and emit `writeback.done`.

**Acceptance criteria**
- B-AC-49: After a fake build and approval, the graph contains the PR, its links to the request, ticket, build and touched functions, and the procedure's `successCount` increased.
- B-AC-50: Running write-back twice creates nothing new.

Tests: `tests/integration/test_writeback.py`.

---

## B11. Slack bot

- Bolt for Python async app (`integrations/slack_bot.py`). Transport choice per connection: if the Slack connection has an app-level token (from the token form, or `SLACK_APP_TOKEN` in `.env` as fallback), run Socket Mode with it (works without a public URL); otherwise use HTTP mode mounted in FastAPI at `/slack/events`, `/slack/commands`, `/slack/interactions` with signature verification against `SLACK_SIGNING_SECRET`. The bot token comes from the connection (token form or OAuth install).
- Handlers: `/actron <text>` (and `/actron ask <text>`), `app_mention` (text after the mention), `block_actions` (`answer:…`, `approve_ticket:<requestId>:<hash>`, `approve_pr:<requestId>:<headSha>`, `request_changes:<requestId>`, `close_pr:<requestId>`, `retry:<requestId>`, `open:<requestId>`), `view_submission` for the request-changes modal (text field), `message` events in allowed channels (feed ingestion, A9), thread replies to a request's thread (answers to text questions or PR feedback when they start with "feedback:").
- Every handler: `ack()` within 3 s, then hand off to an async task that calls `flow/service.py`; Redis idempotency on Slack's `event_id` / interaction `trigger_id` + action id.
- Status message: `slack_blocks.status_message(request_view)` returns blocks per spec C's Slack blueprints; first post in the thread stores `slack_status_ts`; later updates use `chat.update`. Notifications: thread reply for "needs you" + DM to the specific person (via `conversations.open`) only when a person must act.
- Identity: the Slack user id maps to a `users` row (created on first contact) and to the `Person` via identity.

**Acceptance criteria**
- B-AC-51: Fake Slack: `/actron` acks within 3 s (measured), creates a request, posts the acknowledgement in a thread, and stores the status ts.
- B-AC-52: The status message is updated (not re-posted) on each state change; blocks snapshot-tested for every state.
- B-AC-53: Button clicks for answers and approvals call the service with the right arguments; duplicate deliveries do nothing twice.
- B-AC-54: The request-changes modal submits feedback; thread replies starting with the question number answer text questions.
- B-AC-55: HTTP mode rejects requests with a bad signature or a timestamp older than 5 minutes.
- B-AC-56: DMs are sent only to the person who must act, never for informational events.

Tests: `tests/integration/slack/test_bot_commands.py`, `test_bot_actions.py`, `test_bot_signatures.py`; `tests/unit/slack/test_blocks.py`.

---

## B12. API and auth

- FastAPI app with routers per PRD 14. Pydantic request and response models; OpenAPI at `/api/openapi.json`; TypeScript types generated by `scripts/gen_types.sh` (openapi-typescript).
- Auth: Slack OpenID Connect (`https://slack.com/openid/connect/authorize`, scopes `openid profile email`, token exchange at `openid.connect.token`, user info from the ID token) **[VERIFY endpoints]**; on success create or update `users`, create a session (Redis, 7 days, cookie `actron_session` HttpOnly, SameSite=Lax, Secure in prod). Dev login (`POST /api/auth/dev-login {name}`) only when `ACTRON_ENV=dev` (route not registered otherwise).
- CSRF: double-submit token (`actron_csrf` cookie + `X-CSRF-Token` header) on all state-changing routes.
- Errors: JSON `{error: {code, message, details?}}`; 409 for refused approvals and invalid transitions with the reason code; 422 validation; 401/403 auth.
- Rate limiting: 60 writes per minute per user (Redis counter).

**Acceptance criteria**
- B-AC-57: Every route in PRD 14 has a test for success, auth failure, validation failure and (where relevant) 409.
- B-AC-58: The dev login route does not exist in prod (404) and works in dev.
- B-AC-59: CSRF missing or wrong → 403 on every state-changing route.
- B-AC-60: Responses never contain secrets (scan all JSON responses in tests for setting values and encrypted fields).
- B-AC-61: OpenAPI generation and TypeScript type generation run without errors and the frontend type check passes against them.

Tests: `tests/api/test_routes_*.py`, `tests/api/test_auth.py`, `tests/api/test_csrf.py`, `tests/api/test_no_secrets.py`.

---

## B11a. Slack OAuth install ("Add to Slack")

**Purpose:** connect a Slack workspace without copying tokens. Uses Slack's OAuth v2 install flow with Bolt for Python's built-in OAuth support.

**Configuration (`.env`, app-level):** `SLACK_CLIENT_ID`, `SLACK_CLIENT_SECRET`, `SLACK_SIGNING_SECRET`, `ACTRON_PUBLIC_URL` (for example `https://actron.example.com`). OAuth is enabled only when the first two are set; otherwise the token path is the only one shown.

**Routes**
- `GET /api/slack/install` (authenticated Actron user, workspace owner or member): creates a `state` (random 32 bytes, stored in Redis for 10 minutes with the Actron user id and workspace id), then redirects to `https://slack.com/oauth/v2/authorize?client_id=…&scope=<bot scopes>&user_scope=&redirect_uri=<ACTRON_PUBLIC_URL>/api/slack/oauth/callback&state=…`.
- `GET /api/slack/oauth/callback?code=…&state=…` (or `?error=…`): validates and deletes `state` (single use; mismatch or expiry → redirect to `/app/connect?slack_error=expired`); `error=access_denied` → `/app/connect?slack_error=cancelled`; exchanges the code with `POST https://slack.com/api/oauth.v2.access` (`client_id`, `client_secret`, `code`, `redirect_uri`); on success stores the installation and redirects to `/app/connect?slack=connected`.
- Bot scopes requested: exactly the bot scopes in the Slack manifest (B12a). No user scopes for the install (Sign in with Slack is separate).

**Installation storage:** a custom Bolt installation store backed by PostgreSQL (`connections` row with `provider = 'slack'`, `config` = `{teamId, teamName, botUserId, scopes, installedBy, enterpriseId}`, `secret_encrypted` = the bot token, `secret_last4`), implementing the installation-store interface Bolt expects (save, find installation, find bot, delete) **[VERIFY the exact interface in `slack_sdk.oauth.installation_store` for the installed version]**. The Slack team id is matched to the Actron workspace (the one created at sign-in from the same team). A workspace with no `slack_team_id` yet (for example the `dev` workspace from the dev login) adopts the team of its first Slack connection, whether OAuth or token form; after that, any Slack connection (OAuth or token, checked with `auth.test`) must belong to the same team, and a different team is refused with a clear message.

**Bot token resolution:** the Bolt app is created with an `authorize` function (or the OAuth installation store) that returns the bot token for the incoming event's team id, so one Actron deployment can serve the connected workspace without a `SLACK_BOT_TOKEN` in `.env`. `SLACK_BOT_TOKEN` in `.env` remains a development fallback.

**Uninstall and revocation:** handle the `app_uninstalled` and `tokens_revoked` events: mark the connection `disconnected`, pause the Slack schedule, notify the owner in the UI.

**Redirect URL constraint:** the redirect URL must be registered in the Slack app (the manifest's `oauth_config.redirect_urls`). Slack requires HTTPS redirect URLs for distribution **[VERIFY whether `http://localhost` is accepted for development]**; if not accepted, local development uses the token path, and OAuth is exercised on the deployed HTTPS URL and in tests with a fake Slack OAuth server.

**Acceptance criteria**
- B-AC-88: `GET /api/slack/install` redirects to Slack's authorize URL with the client id, the manifest's bot scopes, the registered redirect URI and a single-use state stored in Redis.
- B-AC-89: The callback with a valid state and code (fake `oauth.v2.access`) stores an encrypted installation matched to the user's workspace and redirects with `slack=connected`; a reused, missing or expired state, an `error=access_denied`, or a different Slack team each redirect with the documented error and store nothing.
- B-AC-90: Incoming events and interactions resolve the bot token from the stored installation by team id (no `SLACK_BOT_TOKEN` set).
- B-AC-91: `app_uninstalled` and `tokens_revoked` events disconnect the source and pause its schedule.

Tests: `tests/api/test_slack_oauth.py`, `tests/integration/slack/test_installation_store.py`; fake OAuth server in `tests/fakes/slack.py`.

## B12a. Workspaces, approvers, spending cap, Slack manifest

- **Workspace creation:** on Slack OIDC sign-in, the ID token's team id (`https://slack.com/team_id` claim **[VERIFY claim name]**) finds or creates the workspace (`id` = slug of the team name, unique; `graph_name` = `actron_<slug>`); the first user becomes `owner`, later users from the same team become `member`. Dev login creates or joins workspace `dev`.
- **Approvers:** `settings.approvers` = list of Slack user ids. `approve()` accepts the requester, the workspace owner, or anyone on the list; anyone else gets 403 with reason `not_an_approver` (and `approval.refused`). Settings UI to manage the list.
- **Spending cap:** `ACTRON_DAILY_MODEL_BUDGET_USD` (default 20) and a price table (`settings.model_prices`: per model, USD per million input and output tokens; defaults filled for configured models, editable). `models/usage.py` computes today's estimated spend from `model_calls` plus build token counts. At or above the cap: investigations switch to the pipeline with stubs (event `budget.reached`), `BuildWorkflow` waits on a durable timer until the next UTC day or until the cap is raised (signal `budget_raised`), the footer and request headers show "Daily model budget reached". Per-build and per-investigation tokens and estimated cost are exposed by the API.
- **Slack manifest:** `infra/slack/manifest.yaml` (HTTP mode: request URLs for events, commands, interactivity; `oauth_config.redirect_urls` containing both `<ACTRON_PUBLIC_URL>/api/slack/oauth/callback` for "Add to Slack" and the Sign in with Slack callback; `settings.org_deploy_enabled: false`) and `infra/slack/manifest.dev.yaml` (Socket Mode). Scopes: `app_mentions:read`, `channels:history`, `channels:read`, `chat:write`, `commands`, `groups:history`, `groups:read`, `im:write`, `reactions:read`, `team:read` (for `team.info`), `users:read`, `users:read.email`; user scopes for OIDC `openid`, `profile`, `email`; events `app_mention`, `message.channels`, `message.groups`, `member_joined_channel`, `channel_rename`, `app_uninstalled`, `tokens_revoked`; slash command `/actron`. **[VERIFY]** the manifest against Slack's manifest schema (the Slack docs' validation).
- **Backups:** a `backup` service in compose runs `pg_dump` nightly for `actron` and `temporal` into a volume, keeping 7 days; restore documented in `docs/runbook.md`.

**Acceptance criteria**
- B-AC-83: First sign-in from a Slack team creates a workspace with the signer as owner; a second user from the same team joins as member; a user from another team gets a separate workspace.
- B-AC-84: Approval by the requester, the owner or a listed approver is accepted; anyone else is refused with `not_an_approver`.
- B-AC-85: When estimated spend reaches the cap, investigations use the pipeline and builds wait with the visible reason; raising the cap resumes waiting builds (time-skipping workflow test).
- B-AC-86: The Slack manifests parse as YAML, contain every listed scope, event and command, and match the routes the backend exposes.
- B-AC-87: The backup job produces a restorable dump (integration test restores it into a scratch database).

Tests: `tests/api/test_workspaces.py`, `tests/integration/test_approvers.py`, `tests/workflows/test_budget.py`, `tests/unit/test_slack_manifest.py`, `tests/integration/test_backup.py`.

## B13. Notifications

- Created by `emit` for: `question.asked` (to the requester), `ticket.synced` when approval is needed (to the requester and configured approvers), `build.failed`/`Needs attention` (to the requester), `pr.opened` (to the requester and reviewers). Stored in `notifications`, pushed on the workspace stream, and sent to Slack per B11.

**Acceptance criteria**
- B-AC-62: Exactly these events create notifications; informational events do not.
- B-AC-63: Marking read works and updates the inbox count live.

Tests: `tests/integration/test_notifications.py`.

---

## B14. Bonus (after the Track 01 path is green)

- **Q&A mode:** `classify_request` → `question` → the investigator runs in "answer" mode (same tools), then `write_answer` composes an answer with quotes and links; Slack posts it in the thread; UI shows it on the request page. Acceptance B-AC-64: on `tests/fixtures/eval/qa.yaml`, answers cite the expected sources.
- **Tenancy:** one graph per workspace; Slack team id → workspace; B-AC-65: two workspaces' requests and graphs never mix (API and MCP tests).
- **Procedural memory visible:** procedures shown in the Build tab and used in `TASK.md`. B-AC-66: the Build tab lists the procedures used, and `TASK.md` contains the area's procedure (test command and co-changed paths).
- **Handoff visible:** `handoff.created` rendered as a distinct step. B-AC-67: the Request timeline shows the handoff as a distinct, wider item with the number of evidence items handed to the build.
- **Load test:** `scripts/load_test.py` runs N concurrent readers (shared query, tools) and writers (ingestion batches) for 60 s and reports throughput and p95 latency; B-AC-68: results written to `BUILD-REPORT.md`.

---

## Spec B coverage summary
Acceptance criteria B-AC-1 to B-AC-91. Living docs updated by this spec: `docs/agents.md`, `docs/workflow.md`, `docs/queries.md`, `docs/models-and-jev.md`, `docs/runbook.md`, `docs/testing.md`.
