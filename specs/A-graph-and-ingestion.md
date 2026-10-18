# Spec A: Graph and ingestion

**Scope:** PRD sections 5, 6.1, 7, 8, 9, 10. Platform and configuration, PostgreSQL schema, ontology loader, graph store, ids, code and git ingestion, GitHub, Slack and Linear connectors, connect flow and incremental sync (Temporal), linking, the model layer (Jev and LiteLLM).

**How to read this spec.** Each area has: purpose, interfaces (exact signatures), data written, rules, acceptance criteria (`A-AC-n`), edge cases, and the test files that prove the criteria. Where this spec says **[VERIFY]**, confirm the behaviour against the live tool or its current docs before relying on it, and record what you found in `docs/runbook.md`. Where a choice is not specified, choose the simplest option that satisfies the PRD and record it in `BUILD-LOG.md`.

**Conventions used below**
- `ws` = workspace id (slug, `[a-z0-9-]{3,40}`). Graph name = `actron_<ws with - replaced by _>`.
- All times are timezone-aware UTC (`datetime` with `tzinfo=UTC`); stored in FalkorDB as ISO 8601 strings with `Z`, in PostgreSQL as `timestamptz`.
- "Upsert" = `MERGE` on `id`, then `SET` properties; never `CREATE` for source records.
- Python package root: `backend/actron/`. Tests root: `backend/tests/`.

---

## Contracts (frozen before parallel work)

### A.C1 Ontology loader contract
```python
# backend/actron/graph/ontology.py
@dataclass(frozen=True)
class PropertyDef: name: str; type: str; required: bool; indexed: bool; unique: bool; full_text: bool
@dataclass(frozen=True)
class NodeDef: name: str; primary_key: str; display_name: str; properties: dict[str, PropertyDef]; source_file: str
@dataclass(frozen=True)
class RelDef: name: str; from_node: str; to_node: str; cardinality: str; temporal: bool; source_file: str

class Ontology:
    version: str                       # built from each file's own "version" field, e.g. "slack:1.0-fallback|linear:1.0|github:1.0|code:1.0|core:1.0"
    nodes: dict[str, NodeDef]
    relationships: dict[tuple[str, str, str], RelDef]   # (name, from, to) after group expansion
    common_node_properties: dict[str, PropertyDef]
    common_relationship_properties: dict[str, PropertyDef]
    def node(self, name: str) -> NodeDef: ...            # raises UnknownNodeType
    def rel(self, name: str, from_node: str, to_node: str) -> RelDef: ...  # raises UnknownRelationship
    def validate_node(self, name: str, props: Mapping[str, Any]) -> None: ...  # raises OntologyViolation
    def validate_rel(self, name: str, from_node: str, to_node: str, props: Mapping[str, Any]) -> None: ...
    def full_text_fields(self) -> dict[str, list[str]]: ...   # node -> fields

def load_ontology(directory: Path) -> Ontology: ...
def ensure_indexes(graph: GraphStore, ontology: Ontology) -> IndexReport: ...
```
- `full_text` is true when the property `description` contains "full-text indexed".
- Relationships in fabric files whose `from_node` or `to_node` is not a defined node type are skipped at load time and listed in `IndexReport.skipped_relationships`.
- Type mapping for validation: `string` → `str`; `integer` → `int` (not `bool`); `float` → `int|float`; `boolean` → `bool`; `datetime` → ISO 8601 string or `datetime`; `array` → `list` of JSON scalars; `object` → stored as a JSON string. Unknown property names on a node are allowed only if they are in `common_node_properties`; otherwise `OntologyViolation`.
- **Relationship properties:** allowed names are the `common_relationship_properties` in `core.json` plus the names listed after "Properties:" in that relationship's `description` (for example `TOUCHED` allows `linesChanged`, `changeType`; `CALLS` allows `resolution`, `confidence`, `callSiteLines`, `count`; `FOUND` allows `role`, `rank`, `path`; `KNOWS_ABOUT` allows `score`, `signals`; `OWNS` allows `basis`; `SUPERSEDES` allows `scope`). The loader parses these lists at load time; any other property name raises `OntologyViolation`. Fabric relationships allow only the common properties.
- **Enumerated values:** where a property's description lists its allowed values ("one of …", "a, b or c"), the loader extracts them and validation rejects other values.

### A.C2 Graph store contract
```python
# backend/actron/graph/store.py
class GraphStore:
    def __init__(self, url: str, graph_name: str, ontology: Ontology, *, timeout_ms: int = 15000): ...
    def query(self, cypher: str, params: Mapping[str, Any] | None = None, *, read_only: bool = False,
              timeout_ms: int | None = None) -> list[dict[str, Any]]: ...
    def upsert_nodes(self, label: str, rows: Sequence[Mapping[str, Any]], *, batch_size: int = 500) -> int: ...
    def upsert_links(self, rel: str, from_label: str, to_label: str,
                     rows: Sequence[LinkRow], *, batch_size: int = 500) -> int: ...
    def tombstone(self, label: str, ids: Sequence[str], at: datetime) -> int: ...
    def delete_links(self, rel: str, from_label: str, to_label: str, pairs: Sequence[tuple[str, str]]) -> int: ...
    def get_node(self, node_id: str) -> dict[str, Any] | None: ...
    def drop(self) -> None: ...           # tests only

@dataclass(frozen=True)
class LinkRow: from_id: str; to_id: str; props: Mapping[str, Any]   # props must include method, confidence
```
- Every upsert adds `source`, `workspaceId`, `ontologyVersion`, `refreshedAt`, and `ingestedAt` (only on create, via `ON CREATE SET`).
- `upsert_links` uses `MATCH (a:From {id}), (b:To {id}) MERGE (a)-[r:REL]->(b) SET r += props`; rows whose endpoints do not exist are returned as missing (not created) and logged.
- Labels and relationship names are validated against the ontology before they are interpolated into Cypher (they cannot be parameters). Values are always bound, never interpolated, except through the safe literal binder (A4).

### A.C3 Id formats (complete list)
| Node | Id | Example |
|---|---|---|
| CodeRepository | `code:repo:<owner/name>` | `code:repo:betterthantomorrow/calva` |
| CodeComponent | `code:component:<repo>:<path>` | `code:component:betterthantomorrow/calva:.` |
| CodeDependency | `code:dep:<ecosystem>:<name lowercased>` | `code:dep:npm:mocha` |
| CodeFile | `code:file:<repo>:<path>` | `code:file:betterthantomorrow/calva:src/extension.ts` |
| CodeClass | `code:class:<repo>:<path>::<QualifiedName>[~n]` | `code:class:betterthantomorrow/calva:src/<path>.ts::<ClassName>` |
| CodeFunction | `code:fn:<repo>:<path>::<QualifiedName>[~n]` | `code:fn:betterthantomorrow/calva:src/extension.ts::activate` |
| CodeChunk | `code:chunk:<repo>:<path>#L<start>-L<end>` | `code:chunk:betterthantomorrow/calva:src/extension.ts#L1-L54` |
| CodeDocument | `code:doc:<repo>:<path>#<slug>[~n]` | `code:doc:betterthantomorrow/calva:README.md#<heading-slug>` |
| CodeOwnerRule | `code:owners:<repo>:<line>` | |
| GitCommit | `git:commit:<repo>:<sha>` | |
| GitAuthor | `git:author:<email lowercased>` | |
| GitBranch | `git:branch:<repo>:<name>` | |
| GitTag | `git:tag:<repo>:<name>` | |
| GitFileChange | `git:change:<repo>:<sha>:<path>` | |
| GithubRepository | `github:repo:<numeric id>` | |
| GithubOrganization | `github:org:<numeric id>` | |
| GithubUser | `github:user:<numeric id>` | |
| GithubPullRequest | `github:pr:<owner/name>#<number>` | `github:pr:betterthantomorrow/calva#<number>` |
| GithubPullRequestFile | `github:prfile:<owner/name>#<number>:<path>` | |
| GithubReview | `github:review:<numeric id>` | |
| GithubReviewComment | `github:reviewcomment:<numeric id>` | |
| GithubIssue | `github:issue:<owner/name>#<number>` | |
| GithubIssueComment | `github:issuecomment:<numeric id>` | |
| GithubLabel | `github:label:<owner/name>:<name>` | |
| GithubMilestone | `github:milestone:<owner/name>#<number>` | |
| GithubRelease | `github:release:<numeric id>` | |
| GithubBranch | `github:branch:<owner/name>:<name>` | |
| GithubWorkflowRun | `github:run:<numeric id>` | |
| GithubCheckRun | `github:check:<numeric id>` | |
| SlackWorkspace | `slack:workspace:<team id>` | `slack:workspace:T0123` |
| SlackChannel | `slack:channel:<channel id>` | |
| SlackUser | `slack:user:<user id>` | |
| SlackMessage | `slack:msg:<channel id>:<ts>` | `slack:msg:C0456:1712345678.000100` |
| SlackMessage (previous version) | `slack:msg:<channel id>:<ts>@v<n>` | |
| SlackUserGroup | `slack:usergroup:<id>` | |
| SlackFile | `slack:file:<id>` | |
| SlackReaction | `slack:reaction:<channel id>:<ts>:<name>` | |
| LinearTeam | `linear:team:<uuid>` | |
| LinearUser | `linear:user:<uuid>` | |
| LinearIssue | `linear:issue:<uuid>` (property `identifier` holds `ENG-12`) | |
| LinearComment | `linear:comment:<uuid>` | |
| LinearState, LinearLabel, LinearProject | `linear:state:<uuid>`, `linear:label:<uuid>`, `linear:project:<uuid>` | |
| Core nodes | `actron:<type>:<id>` as in `core.json` | |

Rules: `<repo>` is `owner/name` lowercased. `<path>` is POSIX, relative to the repo root, case preserved. `<QualifiedName>` is dotted (`Outer.inner`, `Class.method`). `~n` (n ≥ 2) is appended in source order to the second and later definitions with the same qualified name in one file (for example conditional definitions). `slug` is the lowercased heading text with non-alphanumerics replaced by `-`, collapsed and trimmed.

### A.C4 Jev question catalog (exact JSON)
All calls use `model = settings.JEV_MODEL` (default `jev-1.13.0`). The question id is for code only. Questions over the same state are sent together.

**J1 classify_message**
```json
{"state": {"text": "<text>", "source": "slack|github_pr|github_review_comment|github_issue|linear_issue|linear_comment",
           "thread_parent_text": "<text or null>"},
 "questions": {"kind": {"type": "choice",
   "instructions": "What is this text mainly doing in a software team's conversation?",
   "criteria": {"decision": "States how the software should or should not behave, or settles a choice",
                "proposal": "Suggests a way the software should behave, without settling it",
                "question": "Asks for information",
                "request": "Asks for a feature or change to be built",
                "bug_report": "Reports something broken",
                "status_update": "Reports progress or what someone did",
                "chatter": "Social talk, thanks, jokes or anything off-topic"}}}}
```
**J2 is_approval**
```json
{"state": {"decision": "<decision text>", "reply": "<reply text>", "reply_author_is_decision_author": false},
 "questions": {"approves": {"type": "noul",
   "instructions": "Does the reply explicitly approve or agree to adopt the decision in `decision`? Polite acknowledgement without agreement is not approval.",
   "criteria": {"true": "The reply clearly agrees the decision should be adopted", "false": "Anything else"}}}}
```
**J3 judge_link**
```json
{"state": {"text": "<message text>", "candidate": {"kind": "function|class|file|feature", "name": "<qualified name or feature name>",
           "path": "<path or null>", "signature": "<signature or null>", "docstring": "<first 400 chars or null>"}},
 "questions": {"refers": {"type": "noul",
   "instructions": "Does `text` talk about the code or feature described in `candidate`, even if it does not name it?"}}}
```
**J4 check_link**
```json
{"state": {"quote": "<exact quote>", "claim": "<plain sentence describing the link, e.g. 'This message is about activate in src/extension.ts'>"},
 "questions": {"supported": {"type": "noul", "instructions": "Does `quote` support `claim` exactly as stated?"}}}
```
**J5 rank_candidates** (one request, one question per candidate, ids `c0`..`c19`)
```json
{"state": {"request": "<request text>", "candidates": [{"id": "c0", "summary": "<kind, name, path, docstring excerpt>"}]},
 "questions": {"c0": {"type": "score",
   "instructions": "How relevant is candidate c0 in `candidates` to `request`?",
   "criteria": ["unrelated", "same area of the code", "directly involved in the change", "the exact place to change"]}}}
```
**J6 judge_conflict**
```json
{"state": {"request": "<request text>", "decision": {"statement": "...", "quote": "...", "status": "approved|proposed|superseded"}},
 "questions": {"relation": {"type": "choice",
   "instructions": "How does `decision` relate to what `request` asks for?",
   "criteria": {"restricts": "Doing the request as written would break or contradict the decision",
                "supports": "The decision agrees with or enables the request",
                "unrelated": "The decision does not affect the request",
                "superseded_by_request": "The request explicitly replaces the decision"}}}}
```
**J7 classify_request**: `choice` with criteria `feature` ("asks for new behaviour"), `bug` ("reports broken behaviour to fix"), `question` ("asks for an explanation or information, not a change").
**J8 needs_question**: `noul` "Is a product decision from a person needed before this can be implemented safely?" with state `{findings_summary, conflicts:[...], max_criticality_percentile}`.
**J9 is_scope_change**: `noul` "Does the proposed change go beyond the approved acceptance criteria in `ticket`?" with state `{ticket, diff_summary, files_outside_affected_list}`.
**J10 feedback_kind**: `choice` with criteria `code_change_within_scope`, `scope_change`, `question`, `approval`; state `{feedback, ticket}`.

Response handling: `noul` answers are a probability in `answers[id].noul`; `choice` answers use `answers[id].choice`, `.probabilities`, `.confidence`; `score` answers use `.score` (0-based level index, may be fractional), `.probabilities`, `.confidence`. **[VERIFY]** field names with one live call when `TYPESAFE_API_KEY` is set.

### A.C5 Sync cursor and run record (PostgreSQL)
```
sync_cursors(workspace_id, source, cursor jsonb, updated_at)   PK(workspace_id, source)
sync_runs(id uuid, workspace_id, source, mode backfill|incremental, status running|done|partial|failed,
          started_at, finished_at, items jsonb {type: count}, errors jsonb [ {action, error, url, at} ],
          temporal_workflow_id, temporal_run_id)
```
Cursor shapes: code `{"last_sha": "..."}`; github, keyed per repository (ingested and upstream, A8) `{"<owner/name>": {"pulls_updated": "<iso>", "issues_since": "<iso>", "review_comments_since": "<iso>", "issue_comments_since": "<iso>", "etags": {"<url>": "<etag>"}}`; slack `{"channels": {"C…": {"oldest": "<ts>"}}}`; linear `{"issues_updated": "<iso>", "comments_updated": "<iso>"}`.

### A.C6 Progress events (published on Redis `ws:<ws>:ingestion`, stored in `events` with `request_id = null`)
`ingestion.started {source, mode, runId}`, `ingestion.progress {source, runId, counts: {type: n}, perMinute, phase}`, `ingestion.partial {source, runId, reason}`, `ingestion.finished {source, runId, status, counts, durationMs}`, `linking.progress {runId, step, done, total}`, `linking.finished {runId, counts: {references_resolved, pending, decisions, identities, links_kept, links_dropped}}`.

---

## A1. Platform and configuration

**Purpose.** One command starts every dependency; settings are validated once at startup; health is visible.

**Compose services (`infra/compose.yaml`)**
| Service | Image | Host port | Notes |
|---|---|---|---|
| falkordb | `falkordb/falkordb:v4.22.1` | 6389→6379 | `REDIS_ARGS=--appendonly yes`; `FALKORDB_ARGS=THREAD_COUNT 8 TIMEOUT_MAX 60000 TIMEOUT_DEFAULT 15000 MAX_QUEUED_QUERIES 2000 RESULTSET_SIZE 10000`; volume `falkor-data` |
| postgres | `postgres:16` (pin a minor) | 5433→5432 | init script creates databases `actron`, `temporal`, `temporal_visibility` and user `actron`; volume `pg-data` |
| redis | `redis:7` (pin a minor) | 6380→6379 | `--appendonly yes`; volume `redis-data` |
| temporal | `temporalio/auto-setup` (pin) | 7233 | Postgres-backed; namespace `actron` created at start **[VERIFY env names]** |
| temporal-ui | `temporalio/ui` (pin) | 8233→8080 | internal use |
| backend | build `infra/docker/backend.Dockerfile` | 8080 | `uvicorn actron.api.app:app` |
| worker | same image | — | `python -m actron.worker` (all task queues in dev); mounts `/var/run/docker.sock` for builds |
| frontend | build `infra/docker/frontend.Dockerfile` | 3000 | Next.js standalone; proxies `/api`, `/slack`, `/webhooks` to `API_INTERNAL_URL` |
| backup | `postgres:16` (same tag) | — | nightly `pg_dump` of `actron` and `temporal` into volume `pg-backups`, keeping 7 days (spec B, B12a) |

Networks: the default network for all services, plus `actron-build` (worker attached) used by Pi containers to reach the MCP server at `worker:8765`. Volumes: `falkor-data`, `pg-data`, `redis-data`, `pg-backups`, and the host directory `ACTRON_BUILD_HOST_DIR` mounted into the worker at the same path. The worker also mounts `/var/run/docker.sock`. `make up` additionally builds the `actron-pi` and `actron-test-runner` images.

**Interfaces**
```python
# backend/actron/config.py
class Settings(BaseSettings):  # every field from .env.example, typed; empty strings become None
    def integrations(self) -> dict[str, Literal["live", "stub", "not_connected"]]: ...
def get_settings() -> Settings: ...   # cached
```
`GET /api/health` returns `{"falkordb": "ok|error", "postgres": ..., "redis": ..., "temporal": ..., "integrations": {...}, "version": "<git sha or dev>"}` with HTTP 200 if all stores are ok, 503 otherwise.

**Acceptance criteria**
- A-AC-1: `make up` starts every service; `make health` (curl `/api/health`) reports all stores `ok` within 90 seconds on a clean machine.
- A-AC-2: Starting the backend with an invalid setting (for example `ACTRON_ENV=staging`, a malformed `DATABASE_URL`) fails fast with a message naming the setting.
- A-AC-3: With every key empty, the backend and worker start; `integrations()` reports `stub` for models and `not_connected` for Slack, GitHub writes and Linear; nothing crashes.
- A-AC-4: Logs are JSON lines with `level`, `msg`, `ts`, `request_id` or `workflow_id` where available; secrets (any setting ending in `KEY`, `TOKEN`, `SECRET`, and connector secrets) never appear in logs (test with a capturing handler).
- A-AC-5: FalkorDB runtime config equals the values in the table (`GRAPH.CONFIG GET`).

Tests: `tests/unit/test_config.py`, `tests/integration/test_health.py`, `tests/integration/test_falkordb_config.py`, `tests/unit/test_log_redaction.py`.

---

## A2. PostgreSQL schema

**Tables (SQLAlchemy 2 typed models in `actron/db/models.py`; Alembic migration `0001_initial`)**
- `users(id uuid pk, slack_user_id text unique null, email text null, name text, avatar_url text, created_at)`
- `workspaces(id text pk, name text, slack_team_id text unique null, graph_name text unique, created_at)`
- `memberships(user_id fk, workspace_id fk, role text default 'member', pk(user_id, workspace_id))`
- `connections(id uuid pk, workspace_id fk, provider text check in ('github','slack','linear','code','slack_export'), status text check in ('connected','error','disconnected'), config jsonb, secret_encrypted bytea null, secret_last4 text null, created_at, updated_at, unique(workspace_id, provider))`
- `sync_cursors`, `sync_runs` (A.C5)
- `requests(id text pk 'req_<ulid>', workspace_id fk, kind text, title text, text text, state text, requester_user_id fk null, slack_channel text null, slack_thread_ts text null, slack_status_ts text null, linear_issue_id text null, pr_number int null, temporal_workflow_id text, created_at, updated_at, closed_at null)`
- `ticket_revisions(id uuid pk, request_id fk, n int, content jsonb, content_hash text, created_by text, created_at, unique(request_id, n))`
- `approvals(id uuid pk, request_id fk, kind text check in ('ticket','pr'), target text, actor_user_id fk null, actor_slack_id text null, surface text check in ('slack','ui'), status text check in ('accepted','refused'), reason text null, created_at)`
- `build_runs(id text pk, request_id fk, status text, branch text, base_sha text, head_sha text null, tests_passed int, tests_failed int, attempts int, started_at, finished_at null, log_path text)`
- `events(id bigserial pk, workspace_id fk, request_id fk null, seq int null, type text, at timestamptz, actor text, surface text, payload jsonb, signal_status text null check in ('pending','sent'))`; unique `(request_id, seq)` where `request_id` is not null.
- `notifications(id uuid pk, workspace_id fk, user_id fk null, request_id fk null, kind text, title text, body text, read_at null, created_at)`
- `drafts(id uuid pk, user_id fk, key text, value jsonb, updated_at, unique(user_id, key))`
- `idempotency_keys(key text pk, created_at, response jsonb)` (fallback when Redis is unavailable)
- `model_calls(id bigserial pk, workspace_id, job text, provider text, model text, input_tokens int, output_tokens int, latency_ms int, cached bool, stub bool, ok bool, error text null, created_at)`

Secrets: `secret_encrypted = Fernet(ACTRON_SECRET_KEY).encrypt(json.dumps(secret))`; `secret_last4` = last four characters of the main token.

**Acceptance criteria**
- A-AC-6: `alembic upgrade head` then `alembic downgrade base` then `upgrade head` succeeds on an empty database.
- A-AC-7: A connection's secret is unreadable in the database dump and decrypts to the original with the key; with a different key, decryption fails with a typed error.
- A-AC-8: The API never returns `secret_encrypted`; it returns `secret_last4` only.
- A-AC-9: `events.seq` is gap-free and strictly increasing per request under 50 concurrent writers (test).

Tests: `tests/integration/test_migrations.py`, `tests/unit/test_secrets.py`, `tests/integration/test_event_seq.py`.

---

## A3. Ontology loader

**Rules**
1. Load the five files from `ontology/` in the order slack, linear, github, code, core.
2. Expand `node_groups` in `core.json`: a relationship whose `from_node` or `to_node` is a group becomes one `RelDef` per (from member, to member) pair.
3. Fail on: duplicate node names across files; a relationship in `github.json`, `code.json` or `core.json` with an undefined endpoint; a group member that is not a node; two `RelDef`s with the same `(name, from, to)`.
4. Skip and report fabric relationships with undefined endpoints.
5. Index creation (idempotent): for each node type, a unique constraint on `id` (create a range index on `id` first if FalkorDB requires it **[VERIFY]**); range indexes on properties with `indexed: true`; one full-text index per node type over its full-text fields (`db.idx.fulltext.createNodeIndex(label, field1, field2, ...)`).

**Acceptance criteria**
- A-AC-10: Loading the real five files succeeds; node count and expanded relationship count equal the values computed from the files at test time by the validator (at the time of writing: 96 node types; core's 56 relationships expand to 287 links, plus all relationships of the other files with valid endpoints).
- A-AC-11: Each failure in rule 3 raises `OntologyError` naming the file, the item and the reason (one test per rule with a temporary fixture directory).
- A-AC-12: `validate_node` rejects a wrong type for every type kind, a missing required property, and an unknown property; accepts common properties on any node.
- A-AC-13: `ensure_indexes` run twice creates nothing the second time and reports existing indexes; `db.indexes()` lists the expected indexes and full-text indexes after the first run.
- A-AC-14: `IndexReport.skipped_relationships` lists exactly the fabric relationships with undefined endpoints (the test computes the expected list from the files; 12 in Slack and 78 in Linear at the time of writing).

Tests: `tests/unit/test_ontology_loader.py`, `tests/unit/test_ontology_validation.py`, `tests/integration/test_indexes.py`.

---

## A4. Graph store

**Safe binding.** First, run the persistence test (A-AC-15) using the client's normal parameters. If values come back corrupted after a FalkorDB restart, switch `query()` to the literal binder:
- Parameter names must match `[A-Za-z_][A-Za-z0-9_]*`; the set of `$names` in the template must equal the set of supplied names.
- Values: `None`, `bool`, `int`, finite `float`, `str`, and lists of these (nested lists allowed); anything else raises `ValueError`. Strings are encoded as JSON string literals (`json.dumps(value, ensure_ascii=True)`).
- Substitution is a single pass over the template with a regex callback; substituted text is never scanned again.
Record which mode is active in `docs/runbook.md` and in `/api/health` (`"falkordb_binding": "params|literal"`).

**Batching.** `upsert_nodes` uses `UNWIND $rows AS row MERGE (n:Label {id: row.id}) ON CREATE SET n.ingestedAt = row.ingestedAt SET n += row.props`. Batch size 500 by default; on a query timeout, halve the batch and retry once, down to 50.

**Versions and tombstones.** Slack edits: before overwriting `SlackMessage.text`, copy the current node to `slack:msg:<c>:<ts>@v<n>` (same label, `version = n`), link `PREVIOUS_VERSION`, then update the main node with `version = n+1`, `edited = true`, `editedAt`. Other sources keep only the latest text plus `refreshedAt` (their history lives in their own APIs). Tombstones set `deleted = true`, `deletedAt`; links from tombstoned nodes keep existing but queries filter `coalesce(n.deleted, false) = false` unless asked for history.

**Workspace graphs.** `GraphStore` is created per workspace; there is no cross-graph query API. A request scoped to workspace A cannot reach graph B (A-AC-20).

**Acceptance criteria**
- A-AC-15: Persistence: values with double and single quotes, backslashes, newlines, tabs, emoji, CJK, a literal `$param`, a literal `CYPHER x=1`, and a 50 KB string, written through `upsert_nodes`, read back identical after `docker compose restart falkordb`.
- A-AC-16: Upserting the same 1,000 rows twice leaves 1,000 nodes and updates `refreshedAt` while `ingestedAt` stays from the first write.
- A-AC-17: `upsert_links` with 10 rows where 2 endpoints do not exist creates 8 links and reports the 2 missing.
- A-AC-18: A Slack edit creates a `@v1` node with the old text and `PREVIOUS_VERSION`, and the main node shows the new text with `version = 2`; a second edit creates `@v2`.
- A-AC-19: `tombstone` marks nodes; the shared query helpers exclude them by default and include them with `include_deleted=True`.
- A-AC-20: Two workspaces' stores write the same ids without interference; a query through store A never returns B's nodes.
- A-AC-21: An invalid label or relationship name (not in the ontology, or containing a backtick or space) is rejected before any query is sent.
- A-AC-22: A forced timeout on a large batch triggers halving and the batch eventually succeeds (fault injection via a tiny `timeout_ms`).

Tests: `tests/integration/test_persistence.py`, `tests/integration/test_store_upserts.py`, `tests/unit/test_literal_binder.py`, `tests/integration/test_versions_tombstones.py`, `tests/integration/test_workspace_isolation.py`.

---

## A5. Ids

`actron/graph/ids.py` exposes one builder per row of A.C3 (`code_fn(repo, path, qualname, dup=1)`, `slack_msg(channel, ts)`, …) and `parse_id(id) -> ParsedId`.

**Acceptance criteria**
- A-AC-23: Every builder produces the documented format; `parse_id(build(x)) == x` for all builders (property-based with Hypothesis).
- A-AC-24: Repo names are lowercased; paths keep case; qualified names keep case; `~n` suffix only for n ≥ 2.
- A-AC-25: Function ids do not change when lines are inserted above the function (tested through the parser in A6).

Tests: `tests/unit/test_ids.py`, `tests/property/test_ids_props.py`.

---

## A6. Code ingestion

### A6.1 Clone
- `activities/ingest_code.py::clone_or_fetch(ws, repo_url, branch, depth=ACTRON_GIT_HISTORY_DEPTH) -> CloneInfo(path, head_sha, branch)`; `branch` is always the connection's `workingBranch`.
- First time: `git clone --filter=blob:none --no-tags --depth <depth> <url> <dir>`; later: `git fetch --depth <depth> origin <branch>` then `git reset --hard origin/<branch>`. Directory: `ACTRON_CLONE_DIR/<ws>/<owner>__<name>`.
- Private repos: authenticate with `GIT_ASKPASS` script reading the token from the environment of the subprocess; never put the token in the URL or command line.

### A6.2 Walk and skip
Include every tracked file (`git ls-files`). Skip text storage (create `CodeFile` with `isSkipped=true`) when:
- binary (NUL byte in the first 8 KB, or extension in an image, font, archive, binary list) → `skipReason=binary`;
- lock files (`*.lock`, `package-lock.json`, `pnpm-lock.yaml`, `poetry.lock`, `uv.lock`, `Cargo.lock`) → `lockfile`;
- minified (`*.min.js`, `*.min.css`, or a line longer than 1,000 characters in a `.js`/`.css` file) → `minified`;
- generated (path contains `/dist/`, `/build/`, `/node_modules/`, `/vendor/`, `/__generated__/`, or a first line containing `@generated` or `DO NOT EDIT`) → `generated`;
- size over 1 MB → `too_large`.
Grammars come from `tree-sitter-language-pack` (`get_parser(<name>)`). Language by extension:
- Tier 1 (full rules, A6.3, A6.4, A6.4a): `.py`/`.pyi` python, `.ts`/`.mts`/`.cts` typescript, `.tsx` tsx, `.js`/`.mjs`/`.cjs`/`.jsx` javascript, `.go` go, `.java` java, `.rs` rust.
- Tier 2 (generic rules, A6.4b): `.kt`/`.kts` kotlin, `.rb` ruby, `.php` php, `.c`/`.h` c, `.cc`/`.cpp`/`.cxx`/`.hpp` cpp, `.scala` scala, `.swift` swift, `.clj`/`.cljs`/`.cljc`/`.edn` clojure.
- Documents: `.md`/`.mdx` markdown, `.rst` rst.
- Everything else (`.toml`, `.json`, `.yaml`, `.yml`, `.cfg`, `.ini`, `.txt`, `.sql`, `.sh`, `.html`, `.css`, ...) is stored as text and covered by chunks.

### A6.3 Python parsing (tree-sitter-python)
Extract with exact line ranges (1-based, inclusive):
- `class_definition` → `CodeClass` (name, bases as written from `argument_list`, decorators from the enclosing `decorated_definition`, docstring = first statement string, body = source text from the decorator start to the class end).
- `function_definition` (also `async`): kind `method` if directly inside a class body, `constructor` if named `__init__`, `property` if decorated with `@property` or `@<name>.setter`, `nested` if inside another function, else `function`. Parameters from `parameters` (names only, including `*args`, `**kwargs`), return type from `return_type`, decorators as written, `isAsync`, `isPublic` = name does not start with `_` (dunder names count as public), `isTest` per A6.7.
- Qualified name: join enclosing class and function names with `.`.
- Imports: `import a.b as c`, `from a.b import x as y`, `from . import x`, `from ..pkg import *`. Record module, symbols and aliases per file for resolution.
- Call sites: every `call` node inside a function body (not inside a nested function, which owns its own calls); record the callee expression text (`foo`, `self.bar`, `mod.baz`, `Class.method`, `super().x`), line, and enclosing function.
- `__all__` lists in a module define its exported names.

### A6.4 TypeScript and TSX parsing (tree-sitter-typescript)
- `class_declaration`, `abstract_class_declaration`, `interface_declaration` (as `CodeClass` with `bases` from `extends`/`implements`), `type_alias_declaration` (not a class; stored as a chunk), `function_declaration`, `method_definition`, arrow functions and function expressions assigned to `const`/`let`/exported names (`const handler = async () => {}` gets the variable name), `export default function`.
- Imports: `import x from 'm'`, `import {a as b} from 'm'`, `import * as ns from 'm'`, `export ... from`, dynamic `import()` (recorded, low confidence), `require()` (low confidence). Resolve relative specifiers with extensions `.ts`, `.tsx`, `.js`, `/index.ts`, `/index.tsx`; read `tsconfig.json` `paths` and `baseUrl` for aliases.
- Calls: `call_expression` and `new_expression` (the latter → `INSTANTIATES`).
- `isPublic` = exported.

### A6.4a Go, Java and Rust (tier 1)
- **Go:** `function_declaration` (function), `method_declaration` (method; qualified name `Receiver.Method` with the receiver type without `*`), `type_declaration` with `struct_type` or `interface_type` → `CodeClass`; imports from `import_declaration` (path and alias) resolved to packages inside the module using `go.mod`'s module path; calls from `call_expression` (`pkg.Func`, `recv.Method`); tests: files `*_test.go`, functions `Test*`, `Benchmark*`, `Example*`; `isPublic` = name starts with an upper-case letter.
- **Java:** `class_declaration`, `interface_declaration`, `enum_declaration`, `record_declaration` → `CodeClass` (qualified by package and outer classes); `method_declaration` and `constructor_declaration` → `CodeFunction` (overloads get `~n` in source order); imports from `import_declaration` (single and wildcard) resolved by package path under `src/main/java` and `src/test/java`; calls from `method_invocation` and `object_creation_expression` (→ `INSTANTIATES`); tests: classes under `src/test` or named `*Test`/`*Tests`, methods annotated `@Test`; `isPublic` from the `public` modifier.
- **Rust:** `function_item` (function), functions inside `impl_item` (method; qualified `Type::method`, and `Trait for Type` recorded in `bases`), `struct_item`, `enum_item`, `trait_item` → `CodeClass`; modules from `mod_item` and file layout (`mod.rs`, `lib.rs`, `main.rs`); `use_declaration` resolved within the crate (`crate::`, `super::`, `self::`); calls from `call_expression` and `macro_invocation` (macros recorded with `resolution=name_only`); tests: functions with `#[test]` or inside `#[cfg(test)] mod tests`; `isPublic` from `pub`.

### A6.4b Tier 2 languages (generic extraction)
For Kotlin, Ruby, PHP, C, C++, Scala, Swift and Clojure, a per-language map in `connectors/code/lang_maps.py` lists the tree-sitter node types for classes, functions and methods, the child field that holds the name, and the node type for calls. Example entries: Kotlin `class_declaration`, `function_declaration`, `call_expression`; Ruby `class`, `module`, `method`, `singleton_method`, `call`; PHP `class_declaration`, `function_definition`, `method_declaration`, `function_call_expression`, `member_call_expression`; C `function_definition` (name from the declarator), `struct_specifier`, `call_expression`; C++ adds `class_specifier` and qualified names from `namespace_definition`; Scala `class_definition`, `object_definition`, `trait_definition`, `function_definition`, `call_expression`; Swift `class_declaration`, `protocol_declaration`, `function_declaration`, `call_expression`; Clojure lists whose first symbol is `defn`, `defn-`, `defmacro`, `defmulti`, `defmethod` (functions) and `defprotocol`, `defrecord`, `deftype` (classes), namespaces from `ns` forms, calls = list forms whose first symbol resolves to a known function. **[VERIFY]** each node type name against the grammar by parsing a small sample file per language and print the node types; adjust the map and record it. Tier 2 resolution uses only `local` and `name_only` tiers (confidence ≤ 0.6); imports are recorded but not resolved across files except Clojure `ns :require` aliases. Test detection by common path conventions (`spec/`, `test/`, `*_test.*`, `*Test.*`, `*_spec.*`).

### A6.5 Chunks (every line covered)
For each stored text file: let `covered` be the union of line ranges of top-level classes and top-level functions (methods and nested functions are inside their class or function). The remaining lines are grouped into maximal runs; each run is split into chunks of at most 80 lines with 10 lines of overlap; each chunk gets `kind` = `module_level` (code files), `config` (toml, json, yaml, cfg, ini), `data` (csv and similar), `other`. Files with no classes or functions become chunks entirely. Markdown and rst files are covered by `CodeDocument` sections instead of chunks.

### A6.6 Resolution
Build a symbol table for the snapshot: module path → defined names (top-level functions and classes, `__all__`), class → methods. Resolve each call site in this order and set `resolution` and `confidence`:
1. `local`: a function defined in the same scope chain (nested or same module top level) → 1.0.
2. `self`/`cls` method: `self.x()` inside a class resolves to `Class.x` or an inherited method (walk `INHERITS_FROM` within the repo) → 0.95.
3. `import`: the callee root is an imported name or alias that maps to a module or symbol in the repo → 0.95.
4. `project`: a unique qualified name match anywhere in the repo for `a.b()` patterns → 0.7.
5. `name_only`: a unique function name in the repo → 0.4; if several match, create no edge and count as unresolved.
Calls to external packages create no `CALLS` edge; the file gets `IMPORTS_PACKAGE`. `super().x()` resolves through base classes. Unresolved calls increment `CodeFunction.unresolvedCalls` and `CodeRepository.unresolvedCallCount`. Repeated calls from the same caller to the same callee aggregate into one edge with `count` and `callSiteLines`.

### A6.7 Tests
- Test files: Python `test_*.py`, `*_test.py`, `tests/**`, `conftest.py` (fixtures, not tests); TypeScript and JavaScript `*.test.ts(x)`, `*.spec.ts(x)`, `*-test.ts` (Calva's Mocha convention under `src/extension-test/unit/`), `*.test.js`, `__tests__/**`, `test/**`, `src/**/test/**`; Clojure `*_test.clj[sc]` and `test/**`.
- Test functions: Python functions named `test*` in test files or methods of classes named `Test*`; TypeScript and JavaScript callbacks passed to `it(...)`, `test(...)` (BDD) and Mocha TDD `test(...)` inside `suite(...)` (named by the first string argument, qualified by enclosing `describe` or `suite` strings joined with ` > `); Clojure `(deftest name ...)` forms in `*_test.clj`, `*_test.cljs`, `*_test.cljc` files or under `test/` (calls inside them via `(is ...)` and direct invocations count for `TESTS`); Go `Test*`, Java `@Test`, Rust `#[test]` as in A6.4a. Test files also include paths matching `src/extension-test/**`, `**/test/**` and `**/tests/**` for TypeScript repositories.
- `TESTS`: for each call from a test function that resolves to a non-test function, an edge with `method=calls`, confidence = the call's confidence. If a test imports a module and its name matches a function or class (`test_make_response` ↔ `make_response`), add `method=naming`, confidence 0.6 when no call edge exists.
- `TEST_FILE_FOR`: test file → source file when the test file name matches (`test_app.py` ↔ `app.py`) or when more than half its `TESTS` targets are in that file.

### A6.8 Documents, manifests, CODEOWNERS
- Markdown: split by headings (ATX `#` and Setext); rst: split by section underlines. Each section → `CodeDocument` (title, level, text, line range), `SUBSECTION_OF` its parent. Explicit mentions: backticked identifiers and paths that resolve to a file, class or function in the snapshot → `DOC_MENTIONS_*` (method `explicit`, confidence 1.0; a name-only match with several candidates is skipped).
- Manifests: `pyproject.toml` (`[project] name`, `dependencies`, `[project.optional-dependencies]`, `[tool.poetry]`), `setup.cfg`, `requirements*.txt`, `package.json` (name, `dependencies`, `devDependencies`, `workspaces`), `pnpm-workspace.yaml`. Each manifest directory → `CodeComponent`; files under it (nearest manifest wins) → `FILE_IN_COMPONENT`; declared deps → `CodeDependency` + `USES_PACKAGE`; workspace dependencies between components → `COMPONENT_DEPENDS_ON`. A repo with no manifest gets one component at the root.
- CODEOWNERS: look in `.github/CODEOWNERS`, `CODEOWNERS`, `docs/CODEOWNERS`; parse patterns with gitignore semantics; the last matching rule wins; `MATCHES_OWNER_RULE` per file.

### A6.10 Updates when new commits land (no duplicate nodes)
The graph holds exactly one node per function, class and file of the working branch's **current** code. History lives in commit nodes and links, never in duplicate code nodes.
- **Changed, same qualified name:** update the existing node in place (`body`, `startLine`, `endLine`, `loc`, `signature`, `docstring`, `contentHash`, `lastCommitSha`, `lastChangedAt`, `refreshedAt`). Its id does not change, so every link to it (decisions, PRs, review comments, tests, mentions) stays valid. Only update when `contentHash` or the line range actually changed.
- **New:** create the node; the commit gets `TOUCHED {changeType: "added"}`.
- **Deleted:** tombstone the node (`deleted = true`, `deletedAt`); keep its links; normal queries exclude it; the commit gets `TOUCHED {changeType: "deleted"}`.
- **Renamed or moved:** for each deleted symbol in a commit, compare its body with symbols added in the same commit (same `contentHash` → similarity 1.0; else token Jaccard similarity of bodies ≥ 0.8 and same kind). The best match above the threshold gets `RENAMED_TO {commitSha, similarity}` (or `CLASS_RENAMED_TO`) from the old (tombstoned) node to the new one. Files use git's rename detection (`-M`) → `FILE_RENAMED_TO`. Queries that look up decisions, PRs, review comments, owners and history for a node also follow `RENAMED_TO` backwards (up to 5 hops), so earlier knowledge carries over to the new name.
- **Unchanged files** are skipped by `contentHash`.
- **Calls and metrics:** `CALLS`, `INSTANTIATES` and `TESTS` edges from changed or deleted functions are recomputed; edges from unchanged callers to a renamed function are re-pointed to the new node; caller counts, PageRank and criticality are recomputed after the run.
- **Earlier versions of code** are not stored as nodes. They are read from git on demand (`git show <sha>:<path>` sliced to the symbol's line range at that commit, located by re-parsing that file version) through the `get_code_at` and `history` tools (spec B, B.C4).

### A6.9 Metrics (after code and git runs)
- `callerCount` = number of distinct callers via `CALLS`; `transitiveCallerCount` = distinct callers within 3 hops via a backwards variable-length match `(f)<-[:CALLS*1..3]-(c)` (not `algo.BFS`, which only follows outgoing links).
- `pageRank` via `CALL algo.pageRank('CodeFunction', 'CALLS') YIELD node, score` (verified on v4.22.1: heavily called functions rank highest); fallback: power iteration in Python over the exported edge list (damping 0.85, 30 iterations, tolerance 1e-6).
- `criticalityPercentile` = percentile rank of `0.6 * pageRank_norm + 0.4 * log1p(transitiveCallerCount)_norm` across non-test functions.

**Acceptance criteria**
- A-AC-26: Synthetic Python repos built in tests cover: top-level functions, async functions, methods, `__init__`, properties and setters, nested functions, decorators with arguments, classes with multiple bases, inheritance inside the repo, conditional duplicate definitions (`~2`), lambdas (not functions), `__all__`, every import form, relative imports. Each produces the expected nodes, qualified names, line ranges and links.
- A-AC-27: Synthetic TypeScript repos cover: classes, abstract classes, interfaces, methods, exported and non-exported functions, arrow functions assigned to consts, default exports, every import form, tsconfig path aliases, `new` expressions, `describe`/`it` tests.
- A-AC-87: Synthetic Go, Java and Rust repos (built in tests) produce the expected classes, functions, methods (with receiver or impl qualified names), imports, calls and tests per A6.4a, including Java overloads (`~n`), Go exported names and Rust `#[cfg(test)]` modules.
- A-AC-88: For each tier 2 language, a sample file parses, its functions and classes are extracted with correct names and line ranges, and its calls create `name_only` or `local` edges with confidence ≤ 0.6; the verified node-type map is recorded in `docs/ingestion.md`.
- A-AC-28: For every stored text file in the Calva snapshot, the union of function, class, chunk and document line ranges covers every line (property test on synthetic files; full check on Calva in an integration test).
- A-AC-29: Call resolution assigns the documented tier and confidence for one case of each tier; ambiguous name-only calls create no edge and increase the unresolved count.
- A-AC-30: Test detection and `TESTS` links match expected results on the synthetic repos (calls and naming methods).
- A-AC-31: Skip rules classify one example of each skip reason correctly and still create a `CodeFile`.
- A-AC-32: Markdown and rst splitting produce the expected sections, slugs (with `~n` for duplicates), hierarchy and explicit mentions.
- A-AC-33: Manifests produce components, dependencies and component dependencies for a synthetic monorepo with two packages.
- A-AC-34: CODEOWNERS last-rule-wins semantics on a fixture with overlapping patterns.
- A-AC-35: Metrics: on a synthetic call graph with a known structure, caller counts, transitive counts and the PageRank ordering match the expected values (procedure and fallback both tested).
- A-AC-36: Ingesting real Calva at a pinned SHA prints counts per node type and unresolved calls; a second run creates no new nodes or links; three hand-checked files have exactly the expected functions and classes (written as a fixture after inspecting them).
- A-AC-37: Function and class ids are unchanged after inserting blank lines and comments above them in a synthetic repo and re-ingesting.
- A-AC-98: After a commit that modifies two functions in place, the graph has the same node ids with updated bodies, line ranges, hashes and `lastCommitSha`; node counts are unchanged; existing links to them (a decision, a review comment) still resolve.
- A-AC-99: A commit that renames a function (same body) and another that moves a function to another file (body 90% similar) produce `RENAMED_TO` from the tombstoned old node to the new node with the commit SHA and similarity; a decision that constrained the old function is returned for the new function by the shared query; callers are re-pointed.
- A-AC-100: A deleted function is tombstoned (not removed), excluded from normal queries, and its history remains queryable; unchanged files are not rewritten (no `refreshedAt` change).
- A-AC-105: With an upstream set, upstream PRs, reviews and review comments are ingested with a per-repository cursor and linked to functions in the ingested working-branch snapshot; the ingested repository's own PRs are ingested too; a re-run creates nothing new.
- A-AC-106: (ontology hardening run 2) A Slack permalink using a channel's original id resolves through `SlackChannel.aliases` to the right `SlackMessage` (`Reference.kind = slack_message`); bot messages carry `botId` and produce no decisions; a procedure stated in a Slack message is linked with `LEARNED_FROM_TEXT`; a decision restated after the commit that carried it out is linked with `DECISION_IMPLEMENTED_BY`.
- A-AC-101: A PR commit absent from the clone becomes a `GitCommit` with `inClone = false`, so `INCLUDES_COMMIT` and `MERGED_AS` resolve; when the commit later arrives in the clone, its file changes are added and `inClone` becomes true.
- A-AC-102: A review comment made on a file before it was moved (fixture: `src/old/name.ts` renamed to `src/new/name.ts`) links to today's function through the rename chain with confidence 0.7.
- A-AC-103: Deleting a Slack message tombstones its outgoing reference and mention links; a partial supersession deactivates only the `CONSTRAINS` links inside its scope.
- A-AC-104: An edited Linear description and an edited Linear comment produce previous-version nodes and links, and decision extraction re-runs on the new text; Linear attachments that are PR URLs yield `IMPLEMENTED_BY`.
- A-AC-38: Private repo cloning never exposes the token in process arguments (inspect the subprocess call) or in the remote URL (`git remote -v`).

Tests: `tests/unit/code/test_parse_python.py`, `test_parse_typescript.py`, `test_chunks.py`, `test_resolve.py`, `test_tests_link.py`, `test_skip_rules.py`, `test_docs.py`, `test_manifests.py`, `test_codeowners.py`, `test_metrics.py`; `tests/property/test_chunk_coverage.py`; `tests/integration/test_ingest_calva.py` (marked `slow`), `tests/integration/test_ingest_synthetic.py`, `tests/unit/code/test_clone_auth.py`.

---

## A7. Git history

**Interfaces**
```python
def read_log(repo_dir: Path, since_sha: str | None, depth: int) -> Iterator[CommitRecord]: ...
def map_hunks_to_symbols(file_symbols_at_commit: list[SymbolRange], hunks: list[tuple[int, int]]) -> list[TouchedSymbol]: ...
def read_blame(repo_dir: Path, path: str) -> list[BlameLine]: ...
```
- Log: `git log --format=<NUL-separated fields: sha, parents, author name, author email, author date ISO, committer date ISO, subject, body> --numstat -M <since>..HEAD` (or `--max-count=<depth>` on first run). Merge commits are recorded with `isMerge` and no file changes from `numstat` (use `-m --first-parent` for merges **[decide and record]**).
- Hunks: `git show --unified=0 --format= <sha> -- <path>` for changed text files; parse `@@ -a,b +c,d @@` into new-file ranges `[c, c+d-1]` (pure deletions map to the line before the deletion).
- Symbols at commit: parse the file content at that commit (`git show <sha>:<path>`) with the same parser as A6, cached per (sha, path). Map hunks to the innermost function containing each changed line; lines in a class but outside methods map to the class.
- `TOUCHED.changeType`: `added` if the function did not exist at the parent commit, `deleted` if it does not exist at this commit (link to the function only if it exists in the current snapshot; otherwise record on the `GitFileChange` only), else `modified`. `linesChanged` = number of changed lines inside the function.
- Blame: `git blame --line-porcelain <path>` on the current snapshot for stored text files; aggregate lines per author per function and per file; `lineShare` = lines / function `loc`.
- Authors: `GitAuthor` per lowercased email; `commitCount`, first and last commit dates updated incrementally.
- Branches and tags: `git for-each-ref refs/remotes refs/tags`.
- Incremental: from `cursor.last_sha` to the new head; if `last_sha` is not an ancestor (force push), re-read the last `depth` commits and record a partial reason "history rewritten".

**Acceptance criteria**
- A-AC-39: A synthetic repo with scripted commits (add function, modify body, rename file, delete function, move function to another file, merge) yields the expected `GitCommit`, `GitFileChange` (status and `oldPath`), `TOUCHED` with `changeType`, and `AUTHORED_BY` links.
- A-AC-40: Hunk parsing handles additions, deletions, multiple hunks, no-newline-at-end markers and binary files.
- A-AC-41: Blame aggregation gives correct `lines` and `lineShare` per author on a synthetic two-author file.
- A-AC-42: Incremental run after two new commits processes only those commits; after a force push it re-reads and records the partial reason.
- A-AC-43: On Calva, one query returns the five most recent commits touching a chosen function with authors and dates, matching `git log -L` for that function (spot check recorded in the test fixture).

Tests: `tests/unit/git/test_log_parse.py`, `test_hunks.py`, `test_blame.py`; `tests/integration/test_git_history.py`.

---

## A8. GitHub connector

**Client** (`integrations/github_client.py`): `httpx.AsyncClient` with base `https://api.github.com`, headers `Accept: application/vnd.github+json`, `X-GitHub-Api-Version: 2022-11-28`, `Authorization: Bearer <token>` when set, timeout 30 s. Paging via the `Link` header (`rel="next"`). On 403/429 with `x-ratelimit-remaining: 0` or `Retry-After`, raise `RetryableProviderError(retry_after=s)` so the Temporal activity retries after that delay. Conditional requests: send `If-None-Match` with the stored ETag; a 304 means no change. Record `x-ratelimit-remaining` in the run record.

**Pulls (in this order; each step is one activity per page)**
| Step | Endpoint | Params | Maps to |
|---|---|---|---|
| repo | `GET /repos/{o}/{r}` | — | `GithubRepository`; `HOSTED_AS` from `CodeRepository` |
| org | `GET /orgs/{org}` when the owner is an organisation | — | `GithubOrganization`, `BELONGS_TO_ORG` |
| contributors | `GET /repos/{o}/{r}/collaborators` (needs push access; on 403 fall back to `GET /repos/{o}/{r}/contributors`) | `per_page=100` | `GithubUser`, `COLLABORATES_ON` |
| pulls | `GET /repos/{o}/{r}/pulls` | `state=all&sort=updated&direction=desc&per_page=100`; stop when `updated_at` < cursor | `GithubPullRequest`, `OPENED_BY`, `MERGED_BY` (from `merged_by` when present via the single PR endpoint), `PR_ASSIGNED_TO`, `REVIEW_REQUESTED_FROM`, `PR_HAS_LABEL`, `PR_IN_MILESTONE`, `FROM_BRANCH`, `INTO_BRANCH` |
| pr files | `GET /repos/{o}/{r}/pulls/{n}/files` for each changed PR | `per_page=100` | `GithubPullRequestFile` (`hunks` parsed from `patch`), `CHANGES_FILE` |
| pr commits | `GET /repos/{o}/{r}/pulls/{n}/commits` | `per_page=100` | `INCLUDES_COMMIT` to `GitCommit` by SHA (create the link only if the commit exists in the clone; otherwise record a pending reference of kind `commit`) |
| reviews | `GET /repos/{o}/{r}/pulls/{n}/reviews` | `per_page=100` | `GithubReview`, `HAS_REVIEW`, `REVIEWED_BY` |
| review comments | `GET /repos/{o}/{r}/pulls/comments` | `sort=updated&direction=asc&since=<cursor>&per_page=100` | `GithubReviewComment`, `COMMENTS_ON_PR`, `PART_OF_REVIEW` (`pull_request_review_id`), `REPLIES_TO` (`in_reply_to_id`), `REVIEW_COMMENT_BY`, `COMMENTS_ON_FILE` |
| issues | `GET /repos/{o}/{r}/issues` | `state=all&since=<cursor>&per_page=100`; skip items with `pull_request` | `GithubIssue`, `ISSUE_OPENED_BY`, `ISSUE_ASSIGNED_TO`, `ISSUE_HAS_LABEL`, `ISSUE_IN_MILESTONE` |
| issue comments | `GET /repos/{o}/{r}/issues/comments` | `sort=updated&direction=asc&since=<cursor>&per_page=100` | `GithubIssueComment`, `COMMENT_BY`, and `ISSUE_DISCUSSED_IN` or `PR_DISCUSSED_IN` (decide by `issue_url` number being a PR) |
| labels | `GET /repos/{o}/{r}/labels` | | `GithubLabel`, `LABEL_IN_REPO` |
| milestones | `GET /repos/{o}/{r}/milestones` | `state=all` | `GithubMilestone`, `MILESTONE_IN_REPO` |
| releases | `GET /repos/{o}/{r}/releases` | `per_page=30` | `GithubRelease`, `RELEASE_IN_REPO`, `RELEASED_BY`, `RELEASES_COMMIT` (resolve `target_commitish`) |
| branches | `GET /repos/{o}/{r}/branches` | `per_page=100` (cap 300) | `GithubBranch`, `BRANCH_IN_REPO`, `GITHUB_BRANCH_AT` |
| check runs | `GET /repos/{o}/{r}/commits/{sha}/check-runs` for heads of PRs updated in this run (cap 50) | | `GithubCheckRun`, `CHECK_FOR_PR`, `CHECK_ON_COMMIT` |
| workflow runs | `GET /repos/{o}/{r}/actions/runs` | `per_page=50&created=>=<cursor date>` | `GithubWorkflowRun`, `RUN_IN_REPO`, `RUN_FOR_PR` (from `pull_requests`), `CHECK_PART_OF_RUN` (by `check_suite_id`) |

**Field mapping (GitHub REST → ontology)**: `id`→numeric part of id; `number`; `title`; `body`; `state`; `draft`→`isDraft`; `merged_at` not null → `merged=true`; `merged_at`→`mergedAt`; `closed_at`; `created_at`; `updated_at`; `head.ref`→`headRef`; `head.sha`→`headSha`; `base.ref`; `base.sha`; `merge_commit_sha`; `additions`, `deletions`, `changed_files` (from the single-PR endpoint when needed); `html_url`→`url` and `sourceUrl`; review `state`, `body`, `commit_id`→`commitSha`, `submitted_at`; review comment `body`, `path`, `line`, `start_line`, `side`, `diff_hunk`, `commit_id`, `created_at`, `updated_at`, `html_url`; file `filename`→`path`, `previous_filename`→`previousPath`, `status`, `additions`, `deletions`, `patch`→`hunks`.

**Upstream history:** when an upstream repository is set (A11 step 3), run the pulls, PR files, PR commits, reviews, review comments, issues, issue comments and check-run steps for **both** the ingested repository and the upstream (labels, milestones, releases, branches and workflow runs for the ingested repository only). The GitHub cursor is keyed per repository: `{"<owner/name>": {"pulls_updated", "issues_since", "review_comments_since", "issue_comments_since", "etags"}}`. Upstream PRs and review comments are mapped onto the ingested working-branch snapshot by path (and through renames, below) for `PR_TOUCHED`, `PR_FILE_IS`, `COMMENT_ON_CODE_FILE` and `COMMENT_ON_FUNCTION`. Webhooks are configured on the ingested repository only; the upstream is refreshed by its schedule. A fork has little history of its own, so for the demo most PR and review history comes from the upstream.

**Commits not in the clone (found in ontology hardening):** PR commits from `GET /pulls/{n}/commits` (and `merge_commit_sha`) whose SHA is not in the local clone (PRs not merged into the working branch, or PRs on another fork) are created as `GitCommit` nodes from the API data (`sha`, `subject`, `message`, author name and email, `authoredAt`) with `inClone = false`, no `GitFileChange` and no `TOUCHED`; `INCLUDES_COMMIT` and `MERGED_AS` then always have a target. If the commit later appears in the clone, the code ingestion fills in its file changes and sets `inClone = true`.

**Forks:** when the repository JSON has `fork: true`, create `FORK_OF` to the `parent` repository (upserting a minimal `GithubRepository` for the parent).

**Cross-source links created here** (method `structural`, confidence 1.0 unless noted): `PR_FILE_IS` (prfile → `CodeFile` by path in the current snapshot), `PR_TOUCHED` (PR → functions overlapping the file hunks, mapped on the current snapshot; confidence 0.9 because the PR's base may differ), `COMMENT_ON_CODE_FILE` and `COMMENT_ON_FUNCTION` (review comment → file and function, found by parsing the file **as it was at the comment's `commit_id`** (`git show <commit_id>:<path>`, fetching the commit if needed), taking the innermost function containing `line`, then following `FILE_RENAMED_TO` and `RENAMED_TO` (and git's rename history for the path, `git log --follow --name-status`) to the node in the current snapshot; confidence 0.8 when no rename was followed, 0.7 when renames were followed; if the function no longer exists, link to the tombstoned node and record it; if the commit cannot be fetched, skip and record. This keeps comments on old PRs, for example on a file that was later moved, attached to today's function), `MERGED_AS` (PR → `GitCommit` by `merge_commit_sha` when present in the clone).

**Explicit references** found in titles, bodies, branch names and comments go to linking (A12.2).

**Acceptance criteria**
- A-AC-44: Against a fake GitHub server: paging over three pages; ETag 304 short-circuits; 429 with `Retry-After` raises a retryable error with that delay; 403 rate limit likewise; 404 on a deleted PR records a partial reason and continues.
- A-AC-45: The mapping produces the documented nodes, properties and links for a fixture PR with files, commits, two reviews, five review comments (one reply chain) and two conversation comments.
- A-AC-46: Incremental run with a cursor fetches only PRs and comments updated after it; the cursor advances to the newest `updated_at` seen; re-running with the same cursor creates nothing new.
- A-AC-47: Without a token, the connector runs with lower limits, caps volume, and marks the run `partial` with reason "public rate limit" if it stops early.
- A-AC-48: `PR_TOUCHED` and `COMMENT_ON_FUNCTION` are created for a fixture whose hunks and lines fall inside known functions, with the documented confidences.
- A-AC-49: Live (`@pytest.mark.live`): pulling 5 recent Calva PRs with reviews and comments succeeds and produces at least one `GithubReviewComment`.

Tests: `tests/contract/test_github_client.py`, `tests/contract/test_github_mapping.py`, `tests/integration/test_github_incremental.py`, `tests/live/test_github_live.py`; fake server in `tests/fakes/github.py`.

---

## A9. Slack connector

**Client** (`integrations/slack_client.py` using `slack_sdk.web.async_client.AsyncWebClient`): bot token; handle `ratelimited` errors with `Retry-After`; cursor paging via `response_metadata.next_cursor`.

**Backfill and incremental**
| Step | Method | Params | Maps to |
|---|---|---|---|
| workspace | `auth.test`, `team.info` | — | `SlackWorkspace` (`id`, `name`, `domain`) |
| users | `users.list` | `limit=200` | `SlackUser` (`id`, `name`, `realName`, `displayName`, `email` (needs `users:read.email`), `title`, `isBot`, `isDeleted`, `avatarUrl`), `SlackUser -RELATED_TO-> SlackWorkspace` |
| channels | `conversations.list` | `types=public_channel,private_channel&exclude_archived=false&limit=200` | `SlackChannel` (`id`, `name`, `isPrivate`, `isArchived`, `topic.value`, `purpose.value`, `num_members`); only channels in `SLACK_CHANNELS` or where the bot is a member are read |
| members | `conversations.members` per channel | `limit=200` | `SlackUser -RELATED_TO_CHANNEL-> SlackChannel` |
| history | `conversations.history` per channel | `oldest=<cursor or now − ACTRON_BACKFILL_DAYS>&limit=200&inclusive=false` | `SlackMessage` (properties from PRD 7.2 additions), `SlackMessage -RELATED_TO_CHANNEL-> SlackChannel`, `-RELATED_TO-> SlackWorkspace`, `POSTED_BY` |
| replies | `conversations.replies` for each parent with `reply_count > 0` whose `latest_reply` > cursor | `ts=<parent ts>&limit=200` | reply `SlackMessage` + `THREAD_OF` parent |
| permalinks | `chat.getPermalink` for messages that become evidence (lazy, on demand), else construct `https://<domain>.slack.com/archives/<channel>/p<ts without dot>` | | `permalink` |
| reactions | from message `reactions` field | | `SlackReaction` (`id` per A.C3), `SlackMessage -RELATED_TO_REACTION-> SlackReaction` |
| files | from message `files` (metadata only: id, name, mimetype) | | `SlackFile`, `SlackMessage -RELATED_TO_FILE-> SlackFile` |

- `name` (fabric's property) on `SlackMessage` is set to the first 80 characters of the text; on channels and users to their names.
- Slack mrkdwn in text is kept raw in `text`; a normalised plain version (user mentions `<@U1>` → `@name`, links `<url|label>` → `label (url)`, channels `<#C1|name>` → `#name`) is used for linking and display.
- Live events (bot, Socket Mode or HTTP): `message` (new) → upsert and enqueue linking for that id; `message_changed` → version per A4 then re-link; `message_deleted` → tombstone and remove its `MENTIONS`/`CONTAINS_REFERENCE` links (record them in the event payload for audit); `channel_rename`, `member_joined_channel` → update channel and membership.
- Incremental catch-up (schedule every 10 minutes): `conversations.history` with `oldest = cursor.channels[C].oldest`; replies for parents whose `latest_reply` advanced; edits are detected by `edited.ts` > stored `editedAt`.
- Bot messages: `botId` (from the message's `bot_id`) is stored on `SlackMessage`; they are stored with `subtype=bot_message` and excluded from decision extraction; Actron's own messages are stored and tagged (`userId` = the bot user) so they are not treated as human statements.

**Acceptance criteria**
- A-AC-50: Fake Slack server: users, channels, members, history over two pages, replies, reactions and files map to the documented nodes and links.
- A-AC-51: A `message_changed` event creates a previous version node and updates text; a `message_deleted` event tombstones the message and removes its outgoing reference links.
- A-AC-52: Incremental catch-up after new messages and an edit processes only those; the per-channel `oldest` cursor advances.
- A-AC-53: Rate limiting (`ratelimited` with `Retry-After: 3`) raises a retryable error with 3 s.
- A-AC-54: Text normalisation converts user, channel and link markup exactly as specified (table-driven test with 15 cases).
- A-AC-55: Only allowed channels are read; channels the bot is not in are skipped and listed in the run record.
- A-AC-56: Bot and Actron messages never produce `Decision` nodes.

Tests: `tests/contract/test_slack_client.py`, `tests/contract/test_slack_mapping.py`, `tests/unit/test_slack_text.py`, `tests/integration/test_slack_events.py`; fake server `tests/fakes/slack.py`.

### A9a. Slack export import
- **Purpose:** ingest Slack history from a workspace export (Slack's official export format: `users.json`, `channels.json`, one folder per channel with `YYYY-MM-DD.json` day files) instead of the live API. Used for teams that have an export, for public archives converted to the format, and for the ontology-hardening dataset.
- **Interface:** connection provider `slack_export` with config `{path}` (a directory or a `.zip` uploaded through the Connect screen and stored under `ACTRON_CLONE_DIR/<ws>/slack_export/`); CLI `actron ingest slack-export <path>`; optional `events.jsonl` in Events API shape applied after the import, in order (`message`, `message_changed`, `message_deleted`).
- **Mapping:** identical to A9 (same node types, ids, properties, links, versions and tombstones). When the export (or a converted archive) records a channel's original id that differs from its id in the export (for example in permalinks inside messages), store the original in `SlackChannel.aliases` so `slack_message` references to old permalinks resolve. `users.json` entries without email stay identity-unresolved. The `SlackWorkspace` id comes from the export's `team` field when present, else `slack:workspace:export-<hash of path>`.
- **Incremental:** re-importing the same export creates nothing new; a later export with more days imports only new or changed messages.
- **Acceptance criteria**
  - A-AC-89: A fixture export with two channels, threads, reactions, files and a deleted-message subtype imports into the documented nodes and links; a re-import creates nothing.
  - A-AC-90: An `events.jsonl` with edits and deletions produces previous-version nodes and tombstones exactly as live events would.
  - A-AC-91: A `.zip` upload through `POST /api/connections` (provider `slack_export`) is validated (structure, sizes, path traversal rejected) and imported by `SourceSyncWorkflow`.
- Tests: `tests/integration/test_slack_export_import.py`, `tests/unit/test_slack_export_validation.py`.

---

## A10. Linear connector

**Client** (`integrations/linear_client.py`): `POST https://api.linear.app/graphql`, header `Authorization: <api key>` (personal keys use the raw key, no `Bearer`), timeout 30 s. Errors: GraphQL `errors` with `extensions.code == "RATELIMITED"` (or HTTP 429) → retryable with backoff (use any reset header if provided **[VERIFY]**); other errors → typed failure with the message.

**Queries** (page size 50, `pageInfo { hasNextPage endCursor }`):
- `teams { nodes { id name key description createdAt updatedAt } }`
- `users { nodes { id name displayName email active admin avatarUrl lastSeen } }`
- `workflowStates(filter: {team: {id: {eq: $team}}}) { nodes { id name type color position team { id } } }`
- `issueLabels(filter: {team: {id: {eq: $team}}}) { nodes { id name color team { id } parent { id } } }`
- `projects { nodes { id name description state lead { id } startDate targetDate createdAt updatedAt teams { nodes { id } } } }`
- `issues(filter: {team: {id: {eq: $team}}, updatedAt: {gt: $since}}, orderBy: updatedAt, first: 50, after: $after) { nodes { id identifier number title description priority estimate url branchName createdAt updatedAt completedAt canceledAt dueDate state { id name type } assignee { id } creator { id } team { id } project { id } parent { id } labels { nodes { id } } comments(first: 50) { nodes { id body url createdAt updatedAt editedAt user { id } parent { id } } pageInfo { hasNextPage endCursor } } } pageInfo { hasNextPage endCursor } }` (paginate comments per issue when `hasNextPage`).
**[VERIFY]** every field name against Linear's current schema with one introspection or live query; drop unavailable fields and record them.

**Mapping** onto `linear.json` names: `LinearTeam`, `LinearUser`, `LinearState` (+ `LinearTeam -DEFINES_WORKFLOW-> LinearState`), `LinearLabel` (+ `USES_LABEL`), `LinearProject`, `LinearIssue` (all properties incl. Actron additions; `stateId`, `assigneeId`, `teamId`, `projectId`, `labelIds`, `creatorId`, `parentId`) with `ASSIGNED_TO`, `BELONGS_TO_TEAM`, `HAS_STATE`, `HAS_LABEL`, `BELONGS_TO_PROJECT`, `CONTAINS_ISSUE`, `ISSUE_CREATED_BY`, `SUBISSUE_OF`; `LinearComment` with `HAS_COMMENT`, `CREATED_BY`, `REPLIES_TO`, `MENTIONS_USER` (from `@` mentions resolved to users).

**Attachments and edit history (found in ontology hardening):** also query `attachments { nodes { url title sourceType } }` on issues **[VERIFY field names]**; store the URLs in `LinearIssue.attachmentUrls`; linking treats each URL as an explicit reference (a GitHub PR URL yields `IMPLEMENTED_BY`). When an issue's title or description, or a comment's body, changes between pulls, copy the previous version to `linear:issue:<uuid>@v<n>` / `linear:comment:<uuid>@v<n>` (same label, `version = n`), link `ISSUE_PREVIOUS_VERSION` / `COMMENT_PREVIOUS_VERSION`, and update the main node (`version = n+1`), exactly as for Slack edits. Re-run decision extraction for edited text.

**Writes** (used by spec B): `issueCreate(input: {id, teamId, title, description, priority, labelIds, assigneeId})` with a deterministic UUID v4-formatted id derived from `sha256(ws + request_id)`; `issueUpdate(id, input: {title, description})`; `commentCreate(input: {issueId, body})`. The description contains the rendered ticket and a fenced JSON block with the canonical ticket and its SHA-256 (spec B defines the format). A read that finds the description changed outside Actron marks the revision `external_edit` and voids approval.

**Acceptance criteria**
- A-AC-57: Fake Linear server: teams, users, states, labels, projects and issues with paginated comments map to the documented nodes and links.
- A-AC-58: Incremental pull filters by `updatedAt` > cursor and advances the cursor.
- A-AC-59: `RATELIMITED` errors produce retryable failures; other GraphQL errors produce typed failures naming the field.
- A-AC-60: `issueCreate` retried after a timeout with the same deterministic id does not create a duplicate (fake server enforces id uniqueness).
- A-AC-61: An externally edited description is detected (hash mismatch) and reported.
- A-AC-62: `branchName` is stored and later used by linking to connect PRs whose `headRef` equals it (see A12.2).

Tests: `tests/contract/test_linear_client.py`, `tests/contract/test_linear_mapping.py`, `tests/integration/test_linear_writes.py`; fake server `tests/fakes/linear.py`.

---

## A11. Connect flow and incremental sync (Temporal)

**Flow**
0. **Working branch (asked when the repository is connected).** The Connect form for the repository lists its branches (`GET /repos/{o}/{r}/branches`, default branch first and marked, then by most recent commit, protected ones marked) and requires the user to choose the **working branch**: the branch the team builds on (for example `dev`). It is stored in `connections.config.workingBranch` for both the `code` and `github` connections. The code snapshot in the graph is always this branch; `CodeRepository.defaultBranch` holds it (its description is "Branch that was ingested"). Changing the working branch later (Settings) re-runs code ingestion from that branch's head and replaces the snapshot (functions that no longer exist are tombstoned), after a confirmation that names what will change.
1. `POST /api/connections` with `{provider, config, secret}` → validate by a live test call (`auth.test`, GitHub `GET /repos/{o}/{r}`, Linear `viewer`, code `git ls-remote` including that `workingBranch` exists) → store encrypted → start `SourceSyncWorkflow(ws, source, mode="backfill")` with workflow id `sync:<ws>:<source>:backfill:<ulid>` → create or update the Temporal Schedule `sync:<ws>:<source>` for incremental runs.
2. The repository is connected through **one form** (spec C, C12 "GitHub"). Saving it creates two connection rows from the same values: `code` (clone, parse, git history) and `github` (PRs, reviews, issues, checks), both with `config = {repository, workingBranch, fork, upstream, historyDays}` and the token and webhook secret encrypted once and referenced by both. Each has its own schedule and run records. Disconnecting the repository removes both.
3. **Effective values (used everywhere: ingestion, webhooks, builds):** repository = `connection.config.repository`, else `GITHUB_REPOSITORY`; push target = `config.fork` (defaults to the repository), else `GITHUB_FORK`; upstream = `config.upstream`, else `GITHUB_UPSTREAM`; token = the connection's token, else `GITHUB_TOKEN`; webhook secret = the connection's generated secret, else `GITHUB_WEBHOOK_SECRET`. A saved connection always wins; `.env` values are development fallbacks.

**SourceSyncWorkflow(ws, source, mode)** (deterministic):
```
cursor = activity load_cursor(ws, source)
run_id = activity start_run(ws, source, mode)
for step in STEPS[source]:                      # ordered list, e.g. github: repo, org, contributors, pulls, ...
    page_token = None
    loop:
        batch = activity fetch_page(ws, source, step, cursor, page_token)    # retry policy, rate-limit aware
        activity write_batch(ws, source, step, batch)                         # idempotent upserts + changed ids
        cursor = merge(cursor, batch.cursor_update)
        activity save_cursor(ws, source, cursor)
        activity publish_progress(ws, run_id, counts)
        page_token = batch.next_page_token; break if None
        if pages_this_run >= 200: continue_as_new(ws, source, mode, resume={step, page_token})
activity finish_run(ws, run_id, status)
start child LinkingWorkflow(ws, changed_ids) (parent close policy ABANDON)
```
- Activity retry policy: initial 2 s, backoff 2.0, maximum interval 5 min, maximum attempts 8; non-retryable error types: `AuthError`, `ValidationError`, `OntologyViolation`. Rate-limit errors carry `retry_after` and the activity sleeps through `activity.heartbeat` before raising, or uses `ApplicationError(next_retry_delay=...)` **[VERIFY the SDK feature]**.
- Code source steps: `clone_or_fetch`, `walk_and_parse` (batches of 200 files), `resolve`, `link_tests`, `documents`, `manifests`, `codeowners`, `git_log` (batches of 500 commits), `hunks` (batches), `blame` (batches of 100 files), `metrics`.
- Schedules (overlap policy SKIP): code every 15 min, GitHub every 5 min, Linear every 5 min, Slack catch-up every 10 min. "Sync now" = `schedule.trigger()`.
- Disconnecting a source pauses its schedule and marks the connection `disconnected`; data stays in the graph (marked by `refreshedAt` age).

**Event-driven sync (so merged code reaches the graph immediately)**
- **Which repository is ingested:** `GITHUB_REPOSITORY` is the repository the team merges into. For the demo that is the fork (`GITHUB_FORK`), so PRs opened and merged by Actron land in the ingested branch. The ingested branch is the connection's **working branch** (step 0). `GITHUB_UPSTREAM` (optional) is read for history only (PRs, reviews, issues), never as the code snapshot. PRs merged into other branches are still ingested as GitHub records (with their files and discussion) but do not change the code snapshot; the UI says so on such PRs ("Merged into <branch>; Actron's memory tracks <working branch>").
- **GitHub webhook:** `POST /webhooks/github` verifies `X-Hub-Signature-256` with `GITHUB_WEBHOOK_SECRET` (HMAC-SHA256 over the raw body; constant-time compare; reject otherwise) and deduplicates by `X-GitHub-Delivery` in Redis. Handled events: `push` to the working branch → trigger the `code` schedule and the `github` schedule now; `pull_request` with `action=closed`, `merged=true` and base = the working branch → trigger both (merged into another branch → GitHub sync only) and also re-ingest that PR (files, reviews, comments) directly; `pull_request` `opened`/`synchronize`/`reopened`, `pull_request_review`, `pull_request_review_comment`, `issues`, `issue_comment` → trigger the `github` schedule (debounced 30 s). Unknown events → 204.
- **Merge watch without a public URL (local development):** after Actron opens a PR, `RequestWorkflow` polls that PR every 2 minutes (activity, durable timer) until it is merged or closed, then triggers the code and GitHub syncs. When webhooks are configured, the watch still runs but finds the work already done.
- **Actron's own approvals:** `approve_pr` (and an observed merge) always triggers the code and GitHub syncs before write-back completes.
- Triggers use `schedule.trigger()` with overlap SKIP plus a follow-up trigger when a run is already in progress, so a merge during a running sync is never missed.

**Acceptance criteria (event-driven sync)**
- A-AC-92: A signed `pull_request` closed+merged webhook triggers code and GitHub syncs and re-ingests that PR; the new commit becomes `CodeRepository.headSha` and its touched functions are updated. An unsigned or wrongly signed request is rejected with 401 and triggers nothing; a repeated delivery id is ignored.
- A-AC-93: A `push` to the working branch triggers the code sync; a push to another branch does not; a PR merged into another branch triggers only the GitHub sync.
- A-AC-96: Connecting a repository requires choosing a working branch from the listed branches (default first); ingestion clones and snapshots that branch; `CodeRepository.defaultBranch` equals it.
- A-AC-97: Changing the working branch in Settings re-ingests from the new branch's head, tombstones functions that no longer exist, and updates the schedules and webhook filtering.
- A-AC-94: Without webhooks, the merge watch detects a merged PR within one polling interval (time-skipping workflow test) and triggers the syncs.
- A-AC-95: A merge that arrives while a code sync is running causes one follow-up sync after it, and the final `headSha` equals the merged commit.
- Tests: `tests/api/test_github_webhook.py`, `tests/workflows/test_merge_watch.py`, `tests/integration/test_merge_triggered_sync.py`.

**Acceptance criteria**
- A-AC-63: Workflow test (time-skipping): a source with three pages processes all pages, saves the cursor after each, finishes the run `done`, and starts linking with the changed ids.
- A-AC-64: An activity failing twice with a retryable error then succeeding produces exactly one write of that page (idempotency) and a `done` run.
- A-AC-65: A non-retryable `AuthError` ends the run `failed` with the reason and pauses the schedule; the UI-facing run record shows the reason.
- A-AC-66: `continue_as_new` resumes at the right step and page token (test with a low page threshold).
- A-AC-67: Creating a connection creates the schedule; "Sync now" triggers an immediate run; two triggers while a run is in progress result in one run (overlap SKIP).
- A-AC-68: Integration against the real Temporal server: connecting a synthetic repo (provider `code`) backfills it; adding a commit and triggering sync ingests only the change.
- A-AC-69: Progress events are published at least once per page with counts and appear in `events`.

Tests: `tests/workflows/test_source_sync.py`, `tests/integration/test_connect_flow.py`, `tests/integration/test_schedules.py`.

---

## A12. Linking

### A12.1 Identity
- Inputs: new or changed `SlackUser`, `GithubUser`, `LinearUser`, `GitAuthor`.
- Match order: (1) exact lowercased email across sources; (2) entries in `config/identity_map.yaml` (`- person: <name>; accounts: [slack:U…, github:login, linear:<uuid>, git:email]`); (3) nothing else. Never match on display name alone.
- For each match group: one `Person` (`actron:person:<uuid5(ws, primary key)>`), one `Identity` per account (`matchMethod`, `matchConfidence` 1.0 for email and mapping), `HAS_IDENTITY`, `IS_*_USER`/`IS_GIT_AUTHOR`.
- Accounts with no match get their own `Person` with `matchMethod=unresolved`, confidence 0.0, so they still appear in ownership; they merge later if an email or mapping appears (merge moves links and deletes the extra `Person`).
- GitHub noreply emails (`<id>+<login>@users.noreply.github.com`) map to the GitHub user id.

### A12.2 Explicit references
Patterns (applied to normalised text; each match yields a `Reference` with `kind` and `key`):
| Kind | Pattern | Key |
|---|---|---|
| linear_issue | `\b([A-Z][A-Z0-9]{1,9})-(\d{1,6})\b` where the prefix is a known Linear team key (or any, if no team known yet, stored pending) | `ENG-12` |
| linear_url | `https://linear\.app/[^/\s]+/issue/([A-Z][A-Z0-9]+-\d+)` | `ENG-12` |
| github_pr_or_issue | `(?<![\w/])#(\d{1,7})\b` (resolved against the repo of the context) and `\b([\w.-]+/[\w.-]+)#(\d{1,7})\b` | `owner/name#123` |
| github_url | `https://github\.com/([\w.-]+)/([\w.-]+)/(pull|issues)/(\d+)` | `owner/name#123` |
| commit | `\b[0-9a-f]{7,40}\b` only when the context is code-ish (inside backticks, after "commit", or in a GitHub URL `/commit/<sha>`), matched by prefix against known commits (unique prefix ≥ 7) | full sha |
| file | backticked or plain tokens containing `/` and an extension that match a `CodeFile.path` suffix uniquely | path |
| symbol | backticked dotted names or `name()` that match a `CodeFunction`/`CodeClass` qualified name or unique name | qualified id |
| slack_permalink | `https://[\w-]+\.slack\.com/archives/(C\w+)/p(\d{10})(\d{6})` | `C…:<ts>` |
| branch | PR `headRef` equal to a `LinearIssue.branchName`, or containing a Linear key | `ENG-12` |
- **Stored `Reference.kind` values** are exactly the ones in `core.json` (`linear_issue`, `github_pr`, `github_issue`, `commit`, `file`, `symbol`, `slack_message`, `url`). Pattern names above map onto them: `linear_url` → `linear_issue`; `github_pr_or_issue` and `github_url` → `github_pr` or `github_issue` (decided by the target; `github_pr` while still pending); `slack_permalink` → `slack_message` (key `channel:ts`, resolved against `SlackChannel.id` or any id in `SlackChannel.aliases`); `branch` → `linear_issue`.
- Each match: upsert `Reference` (`status=pending` or `resolved`), `CONTAINS_REFERENCE` from the text node; if the target exists → `RESOLVES_TO` and a `MENTIONS` link (method `explicit`, confidence 1.0, `quote` = the matched span with ±60 characters of context). PR → Linear by key or branch also creates `IMPLEMENTED_BY` (Linear issue → PR).
- **Pending resolution:** after every source run, `resolve_pending(ws)` looks up all `Reference{status:'pending'}` whose `kind` matches the source just ingested and resolves those whose target now exists, creating the same links. Ambiguous (several targets) → `status=ambiguous`, `RESOLVES_TO` to each, no `MENTIONS`.
- False positives to avoid (tests): `HTTP-200`, `UTF-8`, `ISO-8601`, `SHA-256` are not Linear keys unless the prefix is a known team key; `#1` inside code blocks of Python comments is ignored; hex colour codes `#fff` are not issue refs; version strings `v1.2.3` are not commits.

### A12.3 Meaning links
- For each text node classified (J1) as `decision`, `proposal`, `request`, `bug_report` or `question`: candidates = top 10 full-text matches over `CodeFunction`, `CodeClass`, `CodeFile`, `Feature` using the normalised text (stop words removed), plus the code nodes within 1 hop of anything the text explicitly mentions. Drop candidates already linked explicitly.
- Judge each candidate with J3 (batched per text). Keep probability ≥ `LINK_KEEP_THRESHOLD` (0.6): `MENTIONS` (method `inferred`, confidence = probability, `model`). Features: when ≥ 3 texts in a cluster discuss the same concept without code names, the extraction step may propose a `Feature` (name, description, aliases) via `MODEL_DECISION` with a JSON schema; features are linked to code with J3 and `IMPLEMENTED_IN`.

### A12.4 Decisions
- Input: text nodes classified `decision` or `proposal` (J1 probability ≥ 0.5).
- Extraction via `MODEL_DECISION` with a strict JSON schema: `{"is_decision": bool, "statement": str, "quote": str, "scope": str, "status_hint": "decided|proposed"}`; reject the result if `quote` is not an exact substring of the source text (retry once with a reminder; then drop and count).
- Status: `approved` only if (a) the text itself states an explicit decision by a participant ("we decided", "going with", "approved") with J1 `decision` ≥ 0.7, or (b) a reply judged by J2 ≥ 0.85 approves it (then `APPROVED_IN` → reply, `DECIDED_BY` → the replier's Person); otherwise `proposed`.
- `CONSTRAINS`: from the decision to the code and features its source text mentions (explicit) or that J3 links at ≥ 0.6.
- `DECISION_IMPLEMENTED_BY` (found in ontology hardening run 2): link a decision to the commit or PR that carried it out, when (a) the decision's source text references a commit SHA or PR that implements it, (b) a merged PR's description or a commit message states the decision (then extraction runs on that text and links both `EXTRACTED_FROM` and `DECISION_IMPLEMENTED_BY`), or (c) a commit touching the constrained code is explicitly named in a later message restating the decision. The commit may precede any text that restates the decision.
- `SUPERSEDES`: when a new approved decision's statement is judged (J6-style choice with state `{earlier, later}`) as replacing an earlier one in the same scope (`restricts`/`superseded_by_request` reused as "replaces"), link with `scope`.
- Edited sources: re-run extraction; if the statement changes, update the decision, append the old statement to `statementHistory` (defined on `Decision` in `core.json`), and link the new message version.

### A12.4a Link tombstones and partial supersession (found in ontology hardening)
- When a source text is deleted, or edited so that a reference or mention is gone, its outgoing `MENTIONS`, `CONTAINS_REFERENCE`, `DISCUSSED_IN`, `EXTRACTED_FROM` and `APPROVED_IN` links that no longer hold get `deleted = true` and `deletedAt` (not removed). Decisions whose only `EXTRACTED_FROM` source is deleted keep their node with status unchanged but are shown as "source deleted". Normal queries filter `coalesce(r.deleted, false) = false`.
- When a new decision supersedes an earlier one for only part of what it constrains (`SUPERSEDES {scope}`), set `active = false` and `supersededBy = <new decision id>` on the earlier decision's `CONSTRAINS` links to the targets inside that scope; links to other targets stay `active`. Conflict checks use only active constraints.
- Label vocabulary mapping for evaluations: labelled `explicit` matches link methods `explicit` and `structural`; labelled `inferred` matches `extracted` and `inferred`.

### A12.5 Link checks
For every `inferred` or `extracted` link created in this run: J4 with the link's quote and a plain claim. `< 0.5` → delete the link and count; `0.5–0.7` → keep, set `flag = "possible"`; `≥ 0.7` → keep.

### A12.6 Knowledge and procedures (bonus)
- `KNOWS_ABOUT.score` per (Person, code or feature) = `1 - exp(-(0.4·commits + 0.3·blameShare·10 + 0.2·reviews + 0.1·messages)/5)` with signals counted over the last 365 days; keep the top 10 people per node with score ≥ 0.2; `signals` lists the counts.
- `OWNS`: from CODEOWNERS rules (basis `codeowners`) and from blame share ≥ 0.5 (basis `blame`).
- `LEARNED_FROM_TEXT` (found in ontology hardening run 2): procedures are also learned from text that states how changes are made: Slack messages (for example step-by-step build or release instructions), PR templates (`.github/pull_request_template.md` and similar, ingested as `CodeDocument`) and PR descriptions; J1 classifies candidate texts as `status_update` or `request`, and an LLM extraction (`MODEL_DECISION`, JSON schema `{area, steps[], testCommand?}`) produces or updates the `Procedure`, linked with `LEARNED_FROM_TEXT` to its sources.
- `Procedure` per component or top-level directory: `testCommand` from CI workflow files and PR descriptions (most common command), `coChangedPaths` = path pairs changed together in ≥ 30% of the area's merged PRs, `steps` summarised by `MODEL_WRITING`; `LEARNED_FROM_PR` to the source PRs.

**Acceptance criteria**
- A-AC-70: Identity: email matches across four sources produce one `Person` with four `Identity` nodes; same display name with different emails produces two people; noreply emails map correctly; a later mapping-file entry merges two people and moves their links.
- A-AC-71: Reference patterns: a table of at least 60 cases (true and false positives for every kind) behaves as specified.
- A-AC-72: Pending: a Slack message mentioning `ENG-40` ingested before Linear creates a pending `Reference`; after a Linear run containing `ENG-40`, `RESOLVES_TO` and `MENTIONS` exist and the reference is `resolved`.
- A-AC-73: PR ↔ Linear: a PR whose `headRef` equals an issue's `branchName`, or whose title contains its key, yields `IMPLEMENTED_BY`.
- A-AC-74: Meaning links: with a fake Jev returning fixed probabilities, links above threshold are kept with the probability as confidence and those below are not created.
- A-AC-75: Decisions: extraction rejects non-substring quotes; approval via reply sets `approved`, `APPROVED_IN` and `DECIDED_BY`; no approval leaves `proposed`; bot messages never yield decisions; supersession links with scope.
- A-AC-76: Link checks delete, flag or keep links by the documented thresholds.
- A-AC-77: On the labelled fixtures (`link_labels.yaml` ≥ 40 cases, `conflict_labels.yaml` ≥ 30 cases; never `data/sample/`), precision and recall are computed and written to `BUILD-REPORT.md`; with stubs, the report says so.
- A-AC-78: (bonus) `KNOWS_ABOUT` and `OWNS` match expected values on a synthetic dataset; procedures extract the expected test command and co-changed paths.

Tests: `tests/unit/linking/test_identity.py`, `test_reference_patterns.py`, `test_meaning.py`, `test_decisions.py`, `test_link_checks.py`, `test_knowledge.py`, `test_procedures.py`; `tests/integration/test_pending_references.py`; `tests/eval/test_link_quality.py`.

---

## A13. Model layer

**Interfaces**
```python
# backend/actron/models/__init__.py
class Judgment(BaseModel):
    job: str; answer: Any; probability: float | None; probabilities: dict[str, float] | None
    confidence: float | None; model: str; provider: Literal["jev", "llm", "stub"]; cached: bool; stub: bool
async def classify_message(text: str, source: str, thread_parent_text: str | None) -> Judgment: ...
async def is_approval(decision: str, reply: str, same_author: bool) -> Judgment: ...
async def judge_link(text: str, candidate: Candidate) -> Judgment: ...
async def judge_links(text: str, candidates: list[Candidate]) -> list[Judgment]: ...   # one Jev request
async def check_link(quote: str, claim: str) -> Judgment: ...
async def rank_candidates(request: str, candidates: list[CandidateSummary]) -> list[Judgment]: ...
async def judge_conflict(request: str, decision: DecisionView) -> Judgment: ...
async def classify_request(text: str) -> Judgment: ...
async def needs_question(summary: str, conflicts: list[str], max_criticality: float) -> Judgment: ...
async def is_scope_change(ticket: dict, diff_summary: str, outside_files: list[str]) -> Judgment: ...
async def feedback_kind(feedback: str, ticket: dict) -> Judgment: ...
async def extract_decision(text: str) -> DecisionExtraction | None: ...                 # LLM, JSON schema
async def write_questions(findings: Findings) -> list[Question]: ...                     # LLM
async def write_ticket(request: str, findings: Findings, answers: list[Answer]) -> Ticket: ...  # LLM
async def write_answer(question: str, evidence: list[EvidenceItem]) -> Answer: ...      # LLM (Q&A)
async def summarize_findings(findings: Findings) -> str: ...                             # LLM
```
- Jev transport: the `typesafe-sdk` async client if installed and working; otherwise `httpx` to `POST https://api.typesafe.ai/v1/systemone`. Timeout 20 s. Retries: 429 and 529 with exponential backoff (0.5, 1, 2, 4 s; max 4 attempts); 400/401/413/415/422 not retried (typed errors).
- Fallback order per job: Jev → LiteLLM model for that job (prompted to answer with the same options and a probability in JSON; parse and validate) → stub. Stub answers: the most conservative option (`classify_message` → `chatter` with probability 0.0; `judge_link` → 0.0; `judge_conflict` → `unrelated` with 0.0; `needs_question` → 1.0 (ask when unsure); `is_scope_change` → 1.0 (stop when unsure); `classify_request` → `feature`), each marked `stub: true`.
- Cache: Redis key `model:<job>:<sha256(model + canonical(state) + canonical(questions))>`, TTL 7 days; never cache stubs or errors.
- Usage: every call writes a `model_calls` row.
- LiteLLM: `litellm.acompletion(model=<setting>, messages=..., response_format={"type": "json_object"} or json_schema where supported, timeout=60, num_retries=2)`; per-job model from settings; fallback list `LITELLM_FALLBACKS` (comma list) optional.
- Text-generation prompts live in `actron/models/prompts/*.md`, versioned, with the voice rules from PRD 13.4 for anything shown to users.

**Acceptance criteria**
- A-AC-79: Each Jev job builds exactly the JSON in A.C4 (snapshot tests) and parses `noul`, `choice` and `score` responses from fixtures into `Judgment`.
- A-AC-80: Fake Jev returning 429 twice then 200 succeeds after backoff; 529 likewise; 422 raises a typed error and falls back to the LLM.
- A-AC-81: With no Jev key and a fake LLM, each judgment job falls back and validates the LLM's JSON (invalid JSON → one retry → stub).
- A-AC-82: With no keys at all, every job returns the documented stub with `stub: true`, and nothing is cached.
- A-AC-83: Cache hits skip the network and are logged with `cached: true`.
- A-AC-84: `extract_decision` rejects quotes that are not exact substrings.
- A-AC-85: `model_calls` rows record provider, model, tokens, latency and stub flags for every path.
- A-AC-86: (live, opt-in) one real Jev call per primitive returns a valid answer; the response field names match A.C4 (record in `docs/models-and-jev.md`).

Tests: `tests/unit/models/test_jev_requests.py`, `test_jev_parse.py`, `test_fallbacks.py`, `test_stubs.py`, `test_cache.py`, `test_usage.py`; `tests/contract/test_jev_fake_server.py`; `tests/live/test_jev_live.py`; fakes `tests/fakes/jev.py`, `tests/fakes/llm.py`.

---

## Spec A coverage summary
Acceptance criteria A-AC-1 to A-AC-106 (A-AC-87 onward were added later and appear next to the area they belong to). Every one must map to at least one test (`scripts/spec_coverage.py`). Living docs updated by this spec: `docs/architecture.md`, `docs/graph-model.md`, `docs/ingestion.md`, `docs/linking.md`, `docs/models-and-jev.md`, `docs/runbook.md`, `docs/testing.md`.
