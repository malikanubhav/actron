# Workstreams, ownership and cross-team interfaces

Written by the lead on 17 Oct 2026 before parallel work started. Every engineer (human or agent) reads this first.
Two workstreams never edit the same file. If you need a change in a file you do not own, write what you need in
`BUILD-LOG.md` (entry type `decision`, prefixed `REQUEST TO <owner>:`) and work around it with an adapter in your own files.

## Rules (from PROMPT.md section 2; non-negotiable)
- Never ask the user anything; never wait for input. Anything only the user can give (a key, an account, a choice)
  goes into `NEEDS-FROM-USER.md` (template in PROMPT.md appendix A); continue with a fake, stub or default.
- Never run `git commit`, `git push`, `git remote ...`, `git config`, `gh`, `sudo`, or anything that publishes. Leave changes uncommitted.
- Never write secrets into tracked files or logs. Keys come from `/home/vikram/Desktop/actron/.env` (git-ignored).
- Work only inside `/home/vikram/Desktop/actron` (and your scratchpad). Never read `/home/vikram/Desktop/fabric`.
  Ignore `/home/vikram/Desktop/actron/data/` completely (do not read, test against or copy from it).
- No invented data in the product. Test fixtures live under `backend/tests/fixtures/` (and `frontend/tests/fixtures/`), clearly named.
- Never claim a live integration works without running it live. Mark stubs as stubs.
- Python 3.12, type hints everywhere; `uv run ruff check actron tests` and `uv run mypy actron` (strict) clean for your files.
  Idempotent writes (`MERGE` on `id`). Every external call has a timeout, retries with backoff and a typed error.
  Small modules with plain names; comments only where the reason is not obvious. User-facing text follows PRD 13.4
  (calm, plain, no hype, no exclamation marks, no emoji).
- Tests first for each area, then code. Every test names its acceptance id in its name or docstring (`"""A-AC-16"""`).
  Run `python3 scripts/spec_coverage.py` to see which ids are still uncovered.
- When stuck, time-box about 30 minutes, record it in `BUILD-LOG.md` under "Unresolved", move on, come back later.
- Append a short entry to `BUILD-LOG.md` after each completed area, decision or failure:
  `## <UTC time> <workstream> <done|decision|failure>` + what happened, files, commands, result.
- Re-read `ontology/*.json` at the start of each area (they may get additive updates). Never edit them.
- Read `docs/falkordb.md` before writing Cypher; add an entry when you hit a new FalkorDB limitation.

## Commands
- Stores and Temporal: `make up-deps` (FalkorDB 127.0.0.1:6389, PostgreSQL 127.0.0.1:5433, Redis 127.0.0.1:6380, Temporal 127.0.0.1:7233, UI :8233). Already running.
- Backend tests: `cd backend && uv run pytest tests/<your dirs> -q`. Lint: `uv run ruff check <files>`; types: `uv run mypy <files>`.
- Shared fixtures in `backend/tests/conftest.py`: `ontology`, `graph` (fresh FalkorDB graph per test, dropped after),
  `indexed_graph`, `db_url`/`db_session` (fresh migrated PostgreSQL DB per session), `redis_client` (db 15), `temporal_address`.
  Add your own fixtures in a `conftest.py` inside your own test directory, never in the root conftest (owned by W1).
- Python deps: if you need a new package, `cd backend && uv add <pkg>` is allowed (pyproject and uv.lock are shared; only add, never remove).

## Ownership (directories and files)
| Workstream | Owns (may edit) |
|---|---|
| Lead | `specs/*`, `PLAN.md`, `Makefile`, `infra/compose.yaml`, `backend/tests/conftest.py`, final integration |
| W1 Platform | `backend/actron/{config.py,logging.py}`, `backend/actron/db/`, `backend/actron/graph/{ids.py,ontology.py,store.py}`, `backend/actron/workflows/{schedules.py,smoke.py}`, `infra/docker/backend.Dockerfile`, `infra/docker/frontend.Dockerfile`, `scripts/{check.sh,test_all.sh,live_smoke.sh,gen_types.sh,deploy.sh}`, `docs/{runbook.md,architecture.md,testing.md,graph-model.md}`, tests: `backend/tests/unit/{test_config,test_log_redaction,test_secrets,test_ids,test_ontology_loader,test_ontology_validation,test_literal_binder}.py`, `backend/tests/property/test_ids_props.py`, `backend/tests/integration/{test_health_stores,test_falkordb_config,test_migrations,test_event_seq,test_persistence,test_store_upserts,test_versions_tombstones,test_workspace_isolation,test_indexes,test_temporal_smoke}.py` |
| W2 Code and git | `backend/actron/connectors/code/`, `backend/actron/graph/algos.py`, `backend/tests/unit/code/`, `backend/tests/unit/git/`, `backend/tests/property/test_chunk_coverage.py`, `backend/tests/integration/{test_ingest_calva,test_ingest_synthetic,test_git_history,test_code_incremental}.py`, `backend/tests/fixtures/code/`, `docs/ingestion.md` (code and git sections) |
| W3 Sources | `backend/actron/integrations/{github_client,slack_client,linear_client}.py`, `backend/actron/connectors/{common,github,slack,linear,slack_export,forms}.py` (+ `forms.json`), `backend/actron/workflows/source_sync.py`, `backend/actron/activities/ingest.py`, `backend/tests/fakes/{github,slack,linear}.py`, `backend/tests/contract/`, `backend/tests/unit/{test_slack_text,test_slack_export_validation}.py`, `backend/tests/integration/{test_github_incremental,test_slack_events,test_slack_export_import,test_linear_writes,test_connect_flow,test_schedules}.py`, `backend/tests/workflows/test_source_sync.py`, `backend/tests/live/test_{github,slack,linear}_live.py`, `docs/ingestion.md` (GitHub, Slack, Linear sections) |
| W4 Models and linking | `backend/actron/models/`, `backend/actron/linking/`, `backend/actron/workflows/linking.py`, `backend/actron/activities/link.py`, `backend/tests/unit/models/`, `backend/tests/unit/linking/`, `backend/tests/fakes/{jev,llm}.py`, `backend/tests/contract/test_jev_fake_server.py`, `backend/tests/integration/test_pending_references.py`, `backend/tests/eval/test_link_quality.py`, `backend/tests/fixtures/{link_labels,conflict_labels}.yaml`, `backend/tests/live/test_jev_live.py`, `config/identity_map.yaml`, `docs/{linking.md,models-and-jev.md}` |
| W5 Graph reasoning | `backend/actron/graph/queries.py`, `backend/actron/mcp_graph/`, `backend/actron/flow/{findings.py,investigate.py,investigator_agent.py,labels.py}`, `backend/tests/fixtures/graph_small.cypher`, `backend/tests/fixtures/eval/`, `backend/tests/integration/graph/`, `backend/tests/integration/mcp/`, `backend/tests/unit/flow/{test_investigator_agent,test_pipeline,test_label_rule}.py`, `backend/tests/eval/test_investigation_sample.py`, `docs/queries.md`, `docs/agents.md` (investigator part) |
| W6 Flow and API | `backend/actron/flow/{states.py,service.py,events.py,questions.py,ticket.py,approvals.py,writeback.py,qa.py,notifications.py,budget.py}`, `backend/actron/workflows/{request.py,writeback.py}`, `backend/actron/activities/request.py`, `backend/actron/api/`, `backend/actron/worker.py`, `backend/actron/cli.py`, `backend/tests/api/`, `backend/tests/workflows/{test_request_workflow,test_budget,test_merge_watch}.py`, `backend/tests/unit/flow/{test_service,test_states,test_questions,test_ticket_canonical}.py`, `backend/tests/property/test_state_machine.py`, `backend/tests/property/test_canonical_hash.py`, `backend/tests/integration/{test_sse,test_idempotency,test_reconciler,test_answers,test_ticket_sync,test_approvals,test_approvers,test_notifications,test_writeback,test_request_workflow_real,test_backup}.py`, `docs/workflow.md` |
| W7 Frontend | `frontend/`, `DESIGN.md`, `DESIGN-DIRECTIONS.md`, `docs/frontend.md` |
| W8 Build with Pi | `backend/actron/flow/{build.py,context_pack.py,test_runner.py,diff_check.py}`, `backend/actron/workflows/build.py`, `backend/actron/activities/build.py`, `infra/docker/{pi.Dockerfile,test-runner.Dockerfile}`, `backend/tests/fakes/fake_pi/`, `backend/tests/integration/build/`, `backend/tests/workflows/test_build_workflow.py`, `backend/tests/live/test_pi_live.py`, `docs/agents.md` (Pi part) |
| W9 Slack bot | `backend/actron/integrations/{slack_bot.py,slack_blocks.py,slack_oauth.py}`, `infra/slack/`, `backend/tests/integration/slack/`, `backend/tests/unit/slack/`, `backend/tests/unit/test_slack_manifest.py`, `backend/tests/api/test_slack_oauth.py` |

## Cross-workstream interfaces (frozen; build against these)

**Graph access (W1, done):** `from actron.graph.store import GraphStore, LinkRow, store_for` — `store_for(ws)` returns the
cached store for workspace `ws` (graph `actron_<ws>`). Methods: `query(cypher, params, read_only=, timeout_ms=)` → list of
dict rows (nodes come back as dicts of properties plus `_label`; edges plus `_type`), `upsert_nodes(label, rows, partial=False)`,
`update_nodes(label, rows)` (MATCH-only SET), `upsert_links(rel, from_label, to_label, [LinkRow(from_id, to_id, props)])` →
`LinkResult(created, missing)` (props must include `method` and `confidence`), `tombstone(label, ids, at)`,
`tombstone_links(...)`, `delete_links(...)`, `get_node(id)`, `count(label)`. Ids: `from actron.graph import ids`
(`ids.code_fn(repo, path, qualname, dup)`, `ids.slack_msg(channel, ts)`, ..., `ids.parse_id`, `ids.label_of`).
Ontology: `from actron.graph.ontology import default_ontology, load_ontology, ensure_indexes, OntologyViolation`.
Settings: `from actron.config import get_settings`. Logging: `from actron.logging import get_logger`.
PostgreSQL: `from actron.db.session import session_scope, async_session`; models in `actron.db.models`; secrets
`actron.db.crypto.encrypt_secret/decrypt_secret/last4`.

**Event sink (W6 implements; everyone else receives it as a parameter):**
```python
class EventSink(Protocol):
    async def __call__(self, type: str, payload: dict[str, Any], *, actor: str = "actron",
                       surface: str = "system") -> None: ...
```
Producers (investigator, build, linking progress) take an `emit: EventSink` argument and never import the event store.
Workspace-level ingestion events use `actron.flow.events.publish_workspace_event(ws, type, payload)` (W6) — until it
exists, producers accept an optional `emit` and tests pass a list-collecting fake.

**Models (W4):** `from actron.models import Judgment, classify_message, is_approval, judge_link, judge_links, check_link,
rank_candidates, judge_conflict, classify_request, needs_question, is_scope_change, feedback_kind, extract_decision,
write_questions, write_ticket, write_answer, summarize_findings, agent_completion` exactly as spec A, A13
(`agent_completion(messages, tools) -> AgentTurn` is the tool-calling LLM call used by the investigator; returns
`AgentTurn(tool_calls=[{id, name, arguments}], content, tokens, stub)`; with no model key it raises `ModelUnavailable`).
Every job accepts optional keyword `ws: str | None` and `request_id: str | None` for usage rows.

**Findings (W5):** `from actron.flow.findings import Findings` — Pydantic model of PROMPT appendix D (B.C3), with
`Evidence`, `Question` helpers. `async def investigate(ws: str, request_id: str, text: str, kind: str, *, emit: EventSink,
mode: Literal["auto","agent","pipeline"]="auto") -> InvestigationResult` in `actron.flow.investigate` returns
`InvestigationResult(findings: Findings, label, summary, mode, tool_calls, tokens, cost_usd, stub)`.
Graph tools: `from actron.mcp_graph.tools import ToolContext, call_tool, TOOL_NAMES` — plain async functions behind the MCP
server, used by the API quick queries and the context pack.

**Build (W8):** `BuildInput`/`BuildResult` per spec B, B.C6 in `actron.flow.build`. `BuildWorkflow` in `actron.workflows.build`
(task queue `build`), started by `RequestWorkflow` as a child.

**Temporal registration:** each workflow module exports its workflow class; each activities module exports
`ACTIVITIES: list[Callable[..., Any]]`. Task queues: `ingest` (`actron.workflows.source_sync`, `actron.activities.ingest`),
`link` (`actron.workflows.linking`, `actron.activities.link`), `request` (`actron.workflows.request`,
`actron.workflows.writeback`, `actron.activities.request`), `build` (`actron.workflows.build`, `actron.activities.build`).
`actron/worker.py` (W6) imports exactly these names. Workflow code is deterministic: no I/O, `datetime.now`, randomness or
network inside workflows; use `workflow.now()` and activities. Import activity modules inside
`workflow.unsafe.imports_passed_through()`. Test with `WorkflowEnvironment.start_time_skipping()`.

**Code ingestion entry point (W2):** `actron.connectors.code.pipeline.ingest_code(ws, repo: str, *, url: str | None,
branch: str | None, clone_dir: Path, depth: int, token: str | None, emit: EventSink | None) -> CodeIngestReport`
(full or incremental, decided by the stored cursor passed in `since_sha`), plus the per-step functions the source-sync
workflow calls. CLI: W6 wires `actron ingest code --repo owner/name` to it.

**Connectors (W3):** `actron.connectors.<source>.STEPS` (ordered step names) and
`async def fetch_page(ws, step, cursor, page_token, config) -> Batch` / `def write_batch(ws, step, batch) -> WriteResult`
per spec A11; `actron.connectors.forms.load_forms()` returns the connector form definitions (spec C, C12) for
`GET /api/connectors`; `validate(provider, values)`, `options(provider, field, values)`, `checks(provider, ws)`.

**Slack sender (W9):** `actron.integrations.slack_sender.on_event(ws: str, envelope: dict) -> Awaitable[None]` consumes every
request event after it is stored and published (W6's `emit` and `set_state` call it best-effort; errors are logged, never
raised). It keeps one status message per request (post once, then `chat.update`), posts questions and approval buttons,
and sends DMs only to the person who must act (B11, B13). It is a no-op when Slack is not connected.
Slack inbound handlers (W9) call only `actron.flow.service` functions (W6): `create_request`, `answer`, `approve`,
`feedback`, `cancel`, `retry`, `close_pr`. W6 mounts W9's HTTP handlers at `/slack/events`, `/slack/commands`,
`/slack/interactions` via `actron.integrations.slack_bot.mount(app)` and the OAuth routes via
`actron.integrations.slack_oauth.router` (FastAPI `APIRouter`). Socket Mode runs inside the worker process via
`actron.integrations.slack_bot.run_socket_mode()` when an app-level token exists.

**Request data the Slack blocks need:** `actron.flow.service.get_request_view(ws, request_id) -> RequestDetail` (B.C7 shape as
a dict) is the single read model for the API and Slack.
