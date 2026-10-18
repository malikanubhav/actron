# PROMPT: build Actron end to end, unattended

You are the lead engineer for Actron. Build the whole product described in `PRD.md`, from this nearly empty repository to a working, tested, production-grade application, and keep working without stopping until the definition of done (section 15) is met or every remaining item is blocked on an input only the user can give. The user is away and cannot answer questions. Read this entire file before writing any code. Then read `PRD.md` in full. `PRD.md` is the source of truth for *what*; this file is the source of truth for *how*.

---

## 0. For the user: how to start this run

1. Plug the laptop into power. In a terminal (the VS Code terminal works), stop any old test session if it is no longer needed (`tmux ls`, then `tmux kill-session -t <name>`), start a fresh session for the build and go to the project:
   ```
   tmux new -s actron
   cd /home/vikram/Desktop/actron
   ```
2. Put any keys you already have into `/home/vikram/Desktop/actron/.env` (copy `.env.example`; git-ignored). Start Claude Code in automatic mode inside tmux, keeping the laptop awake:
   ```
   systemd-inhibit --what=sleep:idle:handle-lid-switch --why="Actron build run" claude
   ```
   `.claude/settings.json` allows every command and tool, except commits, pushes, remote and git config changes, `gh`, `sudo`, and the fabric folder.
3. Paste: `Read /home/vikram/Desktop/actron/PROMPT.md and execute it completely. Do not stop until section 15 is satisfied.`
4. Detach with `Ctrl-b d` (the run keeps going). From the phone (Termius): connect and run `tmux attach -t actron`; detach again with `Ctrl-b d`. Closing VS Code or its terminal does not stop the run; reattach with `tmux attach -t actron`. Product approvals (tickets, PRs) also work from Slack's mobile app once Slack is connected.

---

## 1. Mission

Actron checks what a team already decided and built before an AI writes code, then carries a change from a Slack request to a tested pull request, showing the exact graph path behind every step. FalkorDB holds the knowledge graph; PostgreSQL holds app and workflow state; Temporal runs ingestion and the request flow as durable workflows; Redis handles live fan-out to the UI, idempotency, sessions and caching. Slack and a Next.js web UI are two windows on the same request. Track 01 of the FalkorDB Graph Hacks hackathon is the main goal (PRD section 2).

---

## 2. Non-negotiable rules

**Never stop, never ask**
- Do not ask the user anything and do not wait for input. When you need something only the user can give (a key, an account, a choice, a permission), add an entry to `NEEDS-FROM-USER.md` (template in appendix A), then continue with a fake, stub, fixture or sensible default, and build everything around the gap.
- If a tool call is denied by a permission rule, record it in `BUILD-LOG.md` and `NEEDS-FROM-USER.md`, choose another legitimate way that respects the rule's intent, or skip that step and continue. Never try to bypass a safety rule.
- If something fails, debug it. Read the error, form a hypothesis, test it, fix it. Do not give up on a phase because one test is hard; time-box (about 30 minutes per stubborn problem), record it in `BUILD-LOG.md` under "Unresolved", and move on to the next item. Come back to unresolved items before finishing.
- Keep going through all phases. Finishing early with untested or unbuilt parts is a failure; spend remaining time on tests, polish and the bonus tracks.

**Safety**
- Never run `git commit`, `git push`, `git remote add`, `gh` write commands, or anything that publishes. Leave all changes uncommitted. The user commits later under their own identity.
- Never write secrets into tracked files. Secrets live in `.env` (git-ignored). Never print secrets in logs or reports.
- Keys come from `.env` (the application reads it). Never ask the user to paste a key into the chat. A missing key goes into `NEEDS-FROM-USER.md`, and you continue with stubs or fakes.
- Never open a PR against an upstream repository. The product's build step (the orchestrator around Pi, not you) pushes only to the **effective push target**: the GitHub connection's `fork` field, else `GITHUB_FORK`. If it is empty or equals the connection's `upstream`, the PR step stops with `missing_fork`. You yourself never push anything.
- Pi and code it writes run only inside Docker. The Pi container gets one model key and the checkout; no GitHub, Slack or Linear credentials.
- Work only inside `/home/vikram/Desktop/actron` (plus the scratchpad for temporary files). Do not read or modify `/home/vikram/Desktop/fabric` or any other project. Do not copy files from fabric.

**Data honesty**
- No invented or demo data in the product. Production mode shows real data or an explicit empty state.
- Test fixtures live under `backend/tests/fixtures/` and `frontend/tests/fixtures/`, clearly named. The UI may run on development fixtures only when `NEXT_PUBLIC_ACTRON_DEV_FIXTURES=1`, and then shows a visible "DEV FIXTURES" badge on every screen.
- Real public data needs no key: cloning `BetterThanTomorrow/calva`, `git log`, `git blame`, the public GitHub API at low limits. Use them for real runs and `@pytest.mark.live` tests.
- Only public, synthetic or the team's own data enters the graph.
- Report real results. A failing test is reported with its output. A stubbed feature is labelled as stubbed. Never claim a live integration works without running it against the live service.

**Quality**
- Python 3.12, type hints everywhere, `ruff` and `mypy --strict` on `backend/actron` clean. TypeScript strict, ESLint clean, no unexplained `any`, zero console errors.
- Idempotent writes (`MERGE` on `id`). Every external call has a timeout, retries with backoff and a typed error.
- Small modules with plain names. Comments only where the reason is not obvious.
- Everything a user reads follows the voice in PRD 13.4.

---

## 2a. The roles you play (think like each one when its work is in front of you)

You are one agent (or a lead with subagents) playing a full product team. Before each phase, name the roles it needs, then work through that role's questions. When you brief a subagent, give it its role text from this section.

### Product manager
- **Owns:** that every feature serves the one sentence in PRD 1.1 and the Track 01 points; scope discipline (PRD 4).
- **Mindset:** "What does the developer in Slack need at this moment, and what proves it worked?"
- **Asks before building:** Which user moment is this for? What is the observable outcome? Which acceptance id proves it? What is the cheapest version that is still excellent? Does this help Track 01, or is it bonus?
- **Refuses:** features without an acceptance id; bonus work before the Track 01 path is green; vague copy.

### UX researcher and product designer
- **Owns:** the user journey (PRD 11, 13.5), information hierarchy, headline copy for every state, the "Evidence console" direction (PRD 13.2).
- **Mindset:** "Can a judge understand this screen in two seconds, and can a developer act on it in ten?"
- **Asks:** What is the one thing this screen must say? What is the main action? What does the user need to trust the answer (source, quote, confidence, path)? What happens when it is empty, loading, partial, stale, failed?
- **Refuses:** screens without an eyebrow, a situation headline and a purpose line; decoration without meaning; any banned pattern (8.4).

### Visual and motion designer
- **Owns:** tokens, type, colour, spacing, iconography, motion (PRD 13.3, 13.7), `DESIGN.md`.
- **Mindset:** restraint, with one unforgettable signature (the evidence path).
- **Asks:** Does colour carry meaning here, or is it decoration? Is the type hierarchy obvious at a glance? Does each motion explain a change of state? Is it beautiful at 1440 and 1920?
- **Uses:** `impeccable`, `interface-design`, `12-principles-of-animation`, `better-ui`, `ui-skills-root`.

### Principal SaaS product designer (independent reviewer)
- **Owns:** the AI-look audit (spec C, C11): a fresh-eyes review of screenshots only, with no knowledge of the code or of the effort spent.
- **Mindset:** "Would a design lead at a top SaaS company ship this today? What gives away that a machine made it?"
- **Asks:** Is every screen's purpose obvious? Is the hierarchy clear at a glance? Is anything generic, templated, decorative or vague? Is spacing, casing, alignment and iconography consistent everywhere? Are empty, loading, error and partial states designed?
- **Refuses:** anything in the C11 list of tells. Run as a separate subagent so its judgement is not anchored on the builder's.

### Design engineer
- **Owns:** turning the design into production code with craft: the token system in code, component APIs, micro-interactions, motion implementation, optical alignment, the graph canvas look and feel, the in-app setup guides, and the final pixel-level finish of every screen.
- **Mindset:** "The details are the product." Sits between the designer and the frontend engineer: designs in the browser, implements with the precision of a designer and the discipline of an engineer.
- **Asks:** Does every state (hover, focus, pressed, disabled, loading, empty, error, success) look intentional? Do motions use the token durations and easings and feel physical, not decorative? Are icons optically centred with text baselines aligned? Is spacing exactly on the scale? Does it hold at 1440, 1920 and on the landing page at 375? Does it stay at 60 fps? Would this pass a design review at a top SaaS company?
- **Uses:** `better-ui`, `12-principles-of-animation`, `interaction-design`, `frontend-design`, `impeccable` (polish), `vercel-react-best-practices`.
- **Refuses:** any default-looking component, inconsistent radius or shadow, an unstyled state, motion without purpose, copy that has not been written for this screen.

### Frontend engineer
- **Owns:** `frontend/`: structure, performance, accessibility, data flow (PRD 13.8).
- **Mindset:** fast, correct, accessible, no layout shift, no waterfalls.
- **Asks:** Is this a server or client component and why? Is the canvas code split? Are queries keyed and invalidated correctly? Does the SSE stream resume? Does every mutation handle 409?
- **Uses:** `frontend-design`, `frontend-ui-engineering`, `vercel-react-best-practices`, `interaction-design`.

### Backend and platform engineer
- **Owns:** FastAPI, PostgreSQL schema and migrations, Redis, workflows and jobs, configuration, health.
- **Mindset:** every operation idempotent, every external call bounded, every state change journaled.
- **Asks:** What happens if this runs twice? If it crashes halfway? If the provider times out? Where is the source of truth?

### Graph and data engineer
- **Owns:** the ontology loader, the graph store, ingestion mappings, linking, Cypher queries and algorithms (PRD 7, 8).
- **Mindset:** the graph must do real work; every node and link carries provenance and confidence.
- **Asks:** Which ontology type and property does this field map to? Is the id stable? Is the link explicit or inferred, and with what confidence? Which query will read this, and is it indexed? Is the query bounded?

### ML and LLM engineer
- **Owns:** the model layer, Jev questions (PRD 10.2a), the investigator agent loop, thresholds, labelled evaluation.
- **Mindset:** narrow judgments with probabilities; text generation only where text is the product; measure, do not assume.
- **Asks:** Is this a judgment (Jev) or a text (LLM)? Is the question narrow and self-contained? What is the fallback? What do the labelled fixtures say about precision and recall?

### Security engineer
- **Owns:** secrets, sessions, signatures, isolation of Pi, tenancy (PRD 15).
- **Asks:** Can a secret leak into a log, a response, the browser, the Pi container? Can a stale or forged approval pass? Can one workspace read another's graph?

### QA and test engineer
- **Owns:** the test suite (section 9), spec coverage, flake hunting.
- **Mindset:** every acceptance criterion has a test that would fail if the feature broke.
- **Asks:** What is the edge case nobody wrote down? Does this test check behaviour or implementation? Would it catch a regression? Is it deterministic?

### DevOps and SRE
- **Owns:** compose files, Dockerfiles, Caddy, health checks, the runbook, the live-deploy path.
- **Asks:** Does `make up` work from a clean machine? Are volumes, restarts and health checks right? Does SSE survive the proxy?

### Technical writer
- **Owns:** the living docs (PRD 17a), README, DEMO, BUILD-REPORT.
- **Mindset:** a judge or new teammate understands where and how each thing is used, with real examples and real numbers.

### Demo storyteller
- **Owns:** the 3-minute story (PRD 19) and making sure the product delivers each beat of it on screen.
- **Asks:** Does the hook land in 15 seconds? Is the evidence path visible and beautiful in the recording? Does every beat show a result, not an explanation?

---

## 3. How you work (spec-driven, test-first, logged)

### 3.1 The loop (three major specs, tests first)
The work is specified in three major specs (PRD 17): `specs/A-graph-and-ingestion.md`, `specs/B-agents-and-workflow.md`, `specs/C-experience.md`. If a spec file already exists, read it and extend it; do not replace the user's or lead's content.
1. **Spec.** Write or complete the spec using appendix B: purpose, interfaces, data written, numbered acceptance criteria (`A-AC-n`, `B-AC-n`, `C-AC-n`), edge cases, test files. Each spec is long and complete; group criteria by area inside the spec.
2. **Tests first.** For the spec's area you are about to build, write the tests for its acceptance criteria before the code. Each test name or docstring includes its acceptance id.
3. **Code.** Implement until those tests pass.
4. **Verify.** Run that area's tests, then `scripts/check.sh`. Fix everything. At the end of each major spec, run all of its tests as a gate. The whole suite runs at the end of the build and three times in a row before done.
5. **Document.** Update the living docs for what you just built (PRD 17a): where it is used, how it works, what was verified.
6. **Record.** Tick the item in `PLAN.md`, append to `BUILD-LOG.md` (appendix C), update `NEEDS-FROM-USER.md` if needed.

### 3.2 Contracts first
Before parallel work starts, write and freeze these contracts as named sections of the major specs (they are what lets workstreams run independently):
- `ontology/*.json` (already written; read-only unless the PRD allows an addition); the loader contract in spec A.
- Shared query output shape (appendix D) with fixtures, in spec B.
- API: every route in PRD section 14 with request and response schemas, in spec B; generate OpenAPI from FastAPI and TypeScript types from it.
- Events and state transitions (appendices E and F), in spec B.
- Design system: tokens, type, spacing, motion, components (PRD 13), in spec C.
- Jev question catalog (PRD 10.2a) with exact `state` and `questions` JSON for each call site, in spec A.

### 3.3 Logging so work survives context limits
- `BUILD-LOG.md`: append a short entry after every completed task, decision or failure. Before starting any phase, read the last entries.
- `PLAN.md`: tick boxes as items land.
- If your context is compacted or you restart, re-read `PROMPT.md` sections 2, 3 and 15, `PLAN.md` and the tail of `BUILD-LOG.md`, then continue where the log says.

### 3.4 Time budget (guidance, not a reason to stop)
Infrastructure and contracts first (fast), then ingestion and the Track 01 flow, then the frontend, then end-to-end tests and hardening, then bonus tracks. Keep the app runnable at all times: after each phase, `make up` must start everything and existing tests must pass.

---

## 4. Orchestration with subagents

You may work alone or spawn subagents; choose by what is faster and safer. If you use subagents:
- **You are the lead.** You write the contracts (3.2), assign workstreams, review every result, integrate, and run the full suite. A subagent's report is a claim; verify it by running the tests yourself.
- **Clear ownership.** Give each subagent a workstream with the exact directories it may edit, the specs it implements, the contracts it must honour, and the tests that define done. Two subagents never edit the same files at the same time.
- **Brief them fully.** Each brief includes: the relevant PRD sections, the spec files, the rules in section 2 of this file (copy them), the test commands, and "do not commit, do not ask questions, record blockers in NEEDS-FROM-USER.md".
- **Gates.** After each workstream reports, run its tests and `scripts/check.sh`, read the diff, and fix integration problems before starting dependent work.

**Model per subagent (to make the usage limit last the whole run):** the lead runs on Opus. When spawning subagents, pass `model: "opus"` for work where judgement and quality matter most (the investigator agent and build orchestration in spec B, the frontend design system and screens, the design engineer's polish, the independent AI-look reviewer, final integration and debugging), and `model: "sonnet"` for routine, well-specified work (connector clients and mappings, fake provider servers, large batches of unit and contract tests, docs). If a usage limit is reached, record it in `BUILD-LOG.md`, finish the current step cleanly, and continue when it resets.

Suggested workstreams and dependencies:

| Workstream | Owns | Depends on |
|---|---|---|
| W1 Platform | `infra/`, `backend/actron/{config,logging,db,graph}/`, `scripts/` | — |
| W2 Code ingestion | `backend/actron/connectors/code/` | W1 store and ontology loader |
| W3 Source connectors | `backend/actron/connectors/{github,slack,linear,common}.py`, `integrations/*_client.py` | W1 |
| W4 Models and linking | `backend/actron/models/`, `backend/actron/linking/` | W1, ontology |
| W5 Flow, agent, build | `backend/actron/flow/`, `mcp_graph/`, `integrations/slack_bot.py`, `slack_blocks.py`, `infra/docker/pi.Dockerfile` | W1, W4 interfaces, shared-query contract |
| W6 API and auth | `backend/actron/api/`, `worker.py`, `cli.py` | W1, events and API contracts |
| W7 Frontend | `frontend/` | API contract and generated types (use MSW fixtures until the backend is ready) |
| Temporal ownership | W3 writes `workflows/source_sync.py` and ingestion activities; W4 writes `workflows/linking.py` and linking activities; W5 writes `workflows/request.py`, `workflows/build.py`, `workflows/writeback.py` and their activities; W1 writes `workflows/schedules.py`, worker entry points and the Temporal compose services | W1 |
| W8 Quality | `backend/tests/e2e/`, `frontend/tests/e2e/`, `scripts/test_all.sh`, `scripts/spec_coverage.py`, load test | all |

---

## 5. Read first

1. `PRD.md` (all of it).
2. The three major specs, already written in detail: `specs/A-graph-and-ingestion.md` (106 acceptance criteria), `specs/B-agents-and-workflow.md` (91), `specs/C-experience.md` (57). They are the most precise description of what to build: exact interfaces, mappings, Jev question JSON, tool schemas, tokens, components and tests. Follow them; extend them only where they are silent, and record what you added.
3. `PLAN.md` and `BUILD-LOG.md` (if present).
4. `ontology/slack.json`, `linear.json`, `github.json`, `code.json`, `core.json`. Rules (full detail in PRD 7 and spec A, A3):
   - These files are the source of truth for every node type, property and relationship. Nothing creates or renames types at runtime.
   - `slack.json` and `linear.json` are fabric's connector ontologies: keep their names; Slack node names carry a `Slack` prefix; properties tagged `"addedBy": "actron"` are our additions. Relationships in those two files that point at undefined node types are skipped by the loader.
   - `github.json`, `code.json` and `core.json` are ours. `core.json` defines shared node and link metadata and `node_groups` that the loader expands into one relationship per member pair.
   - **The files may receive additive updates during your run** (a second ontology check runs in parallel; fixes only add properties, relationships or node types, never rename or remove). Re-read them at the start of every phase; the loader creates indexes for anything new; record each change you picked up in `BUILD-LOG.md`. Do not edit the ontology files yourself except to add properties PRD 7.2 allows; any other change you need goes into `NEEDS-FROM-USER.md`.
5. Each `SKILL.md` in `.claude/skills/` before frontend work, and the user-level `vercel-react-best-practices` skill. Use them as PRD 13.9 describes.
6. Current docs when you integrate a tool: FalkorDB (https://docs.falkordb.com), TypeSafe Jev (https://docs.typesafe.ai/llms.txt, then `/api.md`, `/sdk/python.md`, the primitive pages), Pi (https://pi.dev and the repository it links), Slack Bolt for Python, Linear GraphQL, GitHub REST.

---

## 6. Verified facts about this machine and tools (17 Oct 2026)

- Repo `/home/vikram/Desktop/actron`: git initialised, no commits. Files: `PRD.md`, `PLAN.md`, `PROMPT.md`, `compose.yaml` (FalkorDB only, to be moved to `infra/` and extended), `pyproject.toml` and `uv.lock` (to be moved to `backend/`), `.env.example`, `.gitignore`, `ontology/` (five files), `.claude/skills/` (eight skills), `.claude/settings.json`, `skills-lock.json`.
- Tools present: `uv`, `docker` with compose, `git`, `node`/`npm` (check versions; install Node 22.19+ via the official tarball into `~/.local` if older), `gh` (logged in as a different account; do not use it to write anything).
- **Read `docs/falkordb.md` before writing any Cypher.** It lists every FalkorDB limitation found so far, the verified syntax, and the workaround used. Add to it whenever you hit a new limitation (what failed, the error text, what the docs say, the workaround, the test that proves it). Check the FalkorDB docs at least twice before deciding a workaround.
- FalkorDB v4.22.1 image: defaults `TIMEOUT 1000` and `MAX_QUEUED_QUERIES 25` break bulk work; keep the overrides in PRD 9.1. Procedures available: `algo.pageRank`, `algo.BFS`, `algo.SPpaths`, `algo.SSpaths`, `algo.WCC`, `algo.betweenness`, `algo.labelPropagation`, `db.idx.fulltext.createNodeIndex`, `db.idx.fulltext.queryNodes`, `db.idx.vector.queryNodes`. Verify call syntax yourself.
- Python client `falkordb` 1.8.0: `FalkorDB(host, port)`, `select_graph`, `Graph.query(q, params, timeout)`, `ro_query`, index and constraint helpers.
- Cypher: no regex operator, one label per node, 10,000-row default result cap.
- **Persistence caveat (re-tested on v4.22.1 on 17 Oct 2026 and not reproduced: 51 tricky values written with parameters survived a restart; use normal parameters, keep the test as a regression guard):** a previous project on v4.12.0 found that parameter-prefixed writes (`CYPHER name=value ...`) were truncated when this image replayed its append-only file after a restart. Test it first (phase 2) and switch to safe single-pass literal binding if it reproduces (validate parameter names; accept only JSON scalars and lists; never re-scan substituted text). Keep the test permanently.
- Temporal (confirmed by the user): self-hosted in compose, Python SDK `temporalio`, task queues `ingest`, `link`, `request`, `build`, workflows and schedules as in PRD 9.4. Workflows must be deterministic (no I/O, `datetime.now`, randomness or network in workflow code; use `workflow.now()` and activities). Use `WorkflowEnvironment.start_time_skipping()` for workflow tests.
- Jev: `typesafe-sdk`, `TYPESAFE_API_KEY`, `POST https://api.typesafe.ai/v1/systemone`, `noul`/`choice`/`score`, pin `jev-1.13.0`, retry 429 and 529 (PRD 10.2).
- Pi: `npm install -g --ignore-scripts @earendil-works/pi-coding-agent`; modes: interactive, print/JSON (`pi -p`, `--mode json`), RPC, SDK; MCP built in; no sandbox. Verify every flag inside the image.

---

## 7. Phases (do them in order; each ends with a gate)

### Phase 0: layout and housekeeping
- Add the dependencies the specs need to `backend/pyproject.toml` (re-lock with `uv lock`): `temporalio`, `sqlalchemy`, `alembic`, `psycopg[binary]`, `redis`, `pydantic-settings`, `cryptography`, `slack-bolt`, `slack-sdk`, `mcp`, `typesafe-sdk` (or plain `httpx` if the SDK is unavailable), `litellm`, `falkordb`, `tree-sitter`, `tree-sitter-language-pack`, `fastapi`, `uvicorn[standard]`, `httpx`, `pyyaml`; dev: `pytest`, `pytest-asyncio`, `hypothesis`, `respx`, `ruff`, `mypy`. The frontend's `package.json` is created in phase 14.
- Create the structure in PRD 6.1. Move `pyproject.toml`/`uv.lock` into `backend/` and `compose.yaml` into `infra/` (keep a root `Makefile` with `up`, `down`, `test`, `check`, `e2e`, `fmt`, `logs`). Keep the FalkorDB settings identical.
- Create `BUILD-LOG.md`, `NEEDS-FROM-USER.md` (with the known items from PRD 20), `specs/README.md`.
- Gate: `make up` starts FalkorDB; `uv run --project backend python -c "import falkordb"` works.

### Phase 1: specs and contracts
- The three major specs already exist and are detailed (A, B, C). Read them completely. Extend them only where they are silent, recording every addition in `BUILD-LOG.md`; never rewrite or remove existing criteria. Freeze the contracts in 3.2; the API request and response schemas are not yet written, so add them to spec B as a contract section. Create the living docs skeleton (PRD 17a) with a heading per section.
- Everything under `data/` (for example `data/sample/`, `data/sample-calva/`) is a temporary ontology-hardening dataset that is deleted before the build. If any of it still exists, ignore it completely: do not read it, test against it or copy from it. Build your own fixtures under `backend/tests/fixtures/` and `frontend/tests/fixtures/`.
- Write `scripts/spec_coverage.py` (scans specs for `-AC-` ids and tests for references; fails on gaps; prints a table).
- Gate: all specs exist; spec coverage runs (it will report gaps until tests exist).

### Phase 2: platform (W1)
- Compose: FalkorDB (as now), PostgreSQL 16 with volume and health check (one container; databases `actron`, `temporal`, `temporal_visibility` created by an init script), Redis 7 with `appendonly yes`, Temporal server (`temporalio/auto-setup`, namespace `actron`) and Temporal UI (internal port), plus backend, worker and frontend services. Look up and pin current image tags and Temporal environment variables from Temporal's docs; record them in `docs/runbook.md`. `.env.example` extended (section 13).
- A Temporal smoke workflow and activity with a test in the time-skipping environment and one against the real server, to prove the wiring before real workflows are written.
- `config.py` validates settings at startup and reports which integrations are live or stubbed. Structured logging.
- PostgreSQL models and Alembic migrations for PRD 9.2 tables. Encrypted secret field (Fernet with `ACTRON_SECRET_KEY`).
- `graph/store.py` (safe binding, typed upserts, `UNWIND` batches of ~500, timeouts, typed errors), `graph/ontology.py` (load five files, expand node groups, validate upserts, create unique constraints, range indexes and full-text indexes), `graph/ids.py`.
- Persistence test: write tricky values through the real client, restart the FalkorDB container, read back identical. Fix the store if it fails.
- Gate: platform unit and integration tests pass; persistence test passes; indexes visible.

### Phase 3: models (W4, first part)
- `models/jev.py` (SDK or HTTP; batch independent questions in one request; backoff on 429 and 529; parse `noul`, `choice`, `score` with probabilities and confidence), `models/llm.py` (LiteLLM per-job models, fallback chain), `models/stubs.py`, `models/cache.py` (Redis), `models/usage.py` (`model_calls`).
- Every job function from PRD 10.1 with a typed result.
- Gate: tests against fake Jev and fake LLM servers cover success, 429, 529, timeout, malformed output, fallback and stub. No test needs a key.

### Phase 4: code ingestion (W2)
- Clone, walk, skip rules, tree-sitter parsing for tier 1 languages (A6.3, A6.4, A6.4a: Python, TypeScript, TSX, JavaScript, Go, Java, Rust) then tier 2 including Clojure (A6.4b), updates on new commits without duplicate nodes (A6.10), bodies, chunks covering every line, imports, external packages, components from manifests, call resolution tiers with unresolved counts, tests linking, markdown documents with explicit mentions, CODEOWNERS.
- Metrics: caller counts, transitive callers (depth 3), PageRank (`algo.pageRank` or fallback), criticality percentile.
- CLI: `actron ingest code --repo BetterThanTomorrow/calva`.
- Gate: on a real Calva clone, counts per type printed; hand-checked counts match for three files; every line of every stored file covered (test); second run creates no duplicates; synthetic test repos (built during tests) cover every language feature listed in PRD 18.

### Phase 5: git history (W2)
- `git log` with numstat and hunks; commits, authors, file changes, parents; hunk-to-function mapping for `TOUCHED`/`TOUCHED_CLASS`; `git blame` aggregated to `BLAME_OWNS`; branches and tags; history depth setting.
- Gate: for a named Calva function, its five latest touching commits and authors come back from one query; synthetic repos test add, modify, rename and delete.

### Phase 6: GitHub connector (W3)
- REST client: auth header, timeouts, paging, `Retry-After`, ETags, `since`, volume caps. Fabric bulk order then Actron additions (PRD 8.3). Map onto `github.json`. Explicit references in titles, bodies and branch names.
- Gate: fake-server contract tests; a `live` test pulls a few Calva PRs; a PR with review comments yields `GithubReviewComment` → `COMMENT_ON_FUNCTION`.

### Phase 7: Slack connector and bot (W3, W5)
- Ingestion: channels, users, history with `oldest`, thread replies, edits as versions, deletes as tombstones, onto `slack.json` names (add the `SlackMessage` properties PRD 7.2 allows).
- Bot (Bolt): Socket Mode in dev, HTTP mode with signature verification in prod; `/actron`, mentions, `block_actions`; `ack()` within 3 s then background job; Redis idempotency on every delivery; one status message per request edited in place; Block Kit per PRD 13.10; live `message` events feed incremental ingestion.
- Without keys the bot does not start and the UI shows "Slack not connected" with setup steps.
- Also in this phase: Slack export import (A9a), Slack OAuth install "Add to Slack" (B11a), PR approval button in Slack (B11).
- Gate: fake Slack API server tests for paging, edits, deletes, ack timing, duplicate delivery, signed and unsigned requests, message updates, button clicks.

### Phase 8: Linear connector (W3)
- GraphQL client: teams, projects, states, labels, users, issues with comments; `endCursor` paging; `updatedAt` incremental; create and update with deterministic ids; canonical ticket JSON and hash in the description; external-edit detection.
- Gate: fake Linear tests: create, retry after timeout without duplicates, update, external edit detection, paging.

### Phase 9: connect flow and incremental sync (W1, W3, W6)
- Connections API with encrypted secrets; saving starts `SourceSyncWorkflow` in backfill mode and creates the source's Temporal Schedule for incremental runs (PRD 9.4); cursors and run records in PostgreSQL; "Sync now" triggers the schedule; code incremental by commit diff; progress events for the UI.
- Also in this phase: connector form definitions and validation, options and checks endpoints (spec C, C12 and C13 backend parts), GitHub webhook and merge watch (A11 event-driven sync), working-branch choice and change (A11 step 0), upstream history (A8), Linear attachments and versions (A10).
- Gate: tests for connect → backfill → incremental after changes (fake servers and a synthetic git repo with new commits) with no duplicates and correct tombstones.

### Phase 10: linking (W4)
- Identity, explicit references with pending `Reference` resolution when the target arrives later (test: Slack message mentioning `ENG-17` ingested before Linear, then Linear connected → link appears), meaning links via Jev, decision extraction with exact quotes and spans, link checks; batch runner with progress and caps.
- Labelled fixtures `link_labels.yaml` (≥ 40 cases) and `conflict_labels.yaml` (≥ 30 cases); report precision and recall (marked "stub" without keys).
- Gate: tests for each step; ambiguous identities stay unresolved and are listed.

### Phase 11: request flow and investigator (W5, W6)
- `workflows/request.py`: `RequestWorkflow` per PRD 9.4 (investigation activity, waits on `answer`, `approve_ticket`, `pr_feedback`, `approve_pr`, `cancel` signals, child `BuildWorkflow`, write-back), with queries for current state. Workflow code is deterministic: no I/O, clock, randomness or network inside workflows; everything else in activities.
- `flow/states.py` transitions table (appendix F) used by both the workflow and the API; `flow/service.py` as the only entry point for actions from Slack and the UI (validate actor → PostgreSQL transaction writing the event → signal the workflow → graph mirror → Redis publish for SSE); approvals bound to revision hash and head SHA with 409 reasons; idempotency keys in Redis; cancel everywhere.
- `mcp_graph/server.py`: read-only MCP server with the 20 tools in spec B, B.C4; each tool runs a named query and returns small JSON.
- Also in this phase: the freshness gate (B2), the target-branch question (B6), approvers and the spending cap (B12a), notifications (B13).
- `flow/investigator_agent.py`: an agent loop with `MODEL_AGENT` and the MCP tools, a step budget, every tool call emitted as an event with its inputs, outputs and the nodes touched; produces findings in the shared-query shape. `flow/investigate.py`: the deterministic fallback pipeline.
- Questions, ticket drafting (canonical JSON, SHA-256, revisions, Linear sync), Q&A answers (bonus).
- Gate: every transition tested; stale approvals refused; concurrent Slack and UI approvals produce one approval; duplicate deliveries do nothing twice; nothing-found path; agent and fallback both produce valid shared-query output on a fixture graph.

### Phase 12: build with Pi (W5)
- Build `infra/docker/pi.Dockerfile`; verify Pi's headless mode, provider configuration and MCP configuration inside it and write what you confirmed into `docs/runbook.md`.
- Orchestrator per PRD 12: checkout of the fork at a recorded base, container with one model key and the MCP address only, rules (no test weakening, bounded repairs, time and token budget, scope-change stop), tests in a second container without network or keys where possible, commit as the bot identity via a credential helper, push to the fork, PR via API, plain-language build events, queue position from the `build` task queue (one worker slot by default), write-back. Implement as `BuildWorkflow` (child of `RequestWorkflow`) with each step an activity; the Pi activity heartbeats and has a start-to-close timeout of `ACTRON_BUILD_TIMEOUT_SECONDS`.
- Gate: labelled fake Pi tests (success, fail-then-repair, weakened-test rejection, timeout, scope stop, missing identity, missing fork); credential isolation test on the container command and environment; the real image starts and Pi answers a trivial prompt, or the reason it cannot is recorded.

### Phase 13: API, auth, SSE, worker (W6)
- All routes in PRD 14; Slack OIDC sign-in; sessions in Redis; CSRF; dev login only in dev; SSE with `Last-Event-ID` replay from the journal and Redis live events; health endpoint (including Temporal); Temporal worker entry points per task queue; CLI.
- Gate: API tests for every route (auth, validation, 409s, idempotency), SSE replay test, health test.

### Phase 14: frontend (W7) — see section 8
- Gate: section 8.6.

### Phase 15: end to end and hardening (W8)
- Playwright e2e scenarios in section 9.6 against the full stack with fakes; run each three times; fix flakiness.
- `scripts/test_all.sh` runs everything: backend unit, property, integration, contract, flow, build, security; frontend unit, e2e, accessibility; spec coverage; performance checks.
- Gate: all green three times in a row.

### Phase 16: bonus tracks (only after phase 15 is green)
- Track 02 and 03 points from PRD 2: procedures, visible handoff, per-workspace graphs with an isolation test, load test with numbers, `KNOWS_ABOUT` and "Who knows this?", Q&A mode in Slack and UI. Each with specs and tests.

### Phase 17: docs, deployment, report
- `README.md` (PRD 19), `DEMO.md` (3-minute script), `DESIGN.md`, `DESIGN-DIRECTIONS.md`.
- Complete and review every living doc in PRD 17a (they were written phase by phase; now check each is accurate against the code, with real examples and real measured numbers). `docs/models-and-jev.md` must list every Jev call site with its exact question JSON, its fallback, measured accuracy and cost.
- `infra/compose.prod.yaml` with Caddy configured for SSE, health checks, restart policies.
- Slack app manifests (`infra/slack/manifest.yaml`, `manifest.dev.yaml`) and the nightly backup service (B12a), `make deploy`, `docs/blog-post.md`, `docs/falkordb.md` final review.
- `BUILD-REPORT.md` and final `NEEDS-FROM-USER.md` (section 15).

---

## 8. Frontend instructions (phase 14)

### 8.0 Intent (read this before designing anything)
The UI exists to make one idea undeniable: **Actron's decisions come from the graph, and you can see exactly how.** Three people use it:
- **The requester** (developer or lead) wants to know, fast, whether their request is safe, what it touches, and what they must decide. They act from Slack or the UI and trust the answer only if they can see the source.
- **The reviewer** wants to check the build: what changed, which tests ran, which constraints still hold.
- **The judge** (hackathon) has two minutes. They must see live graph reasoning, the agent acting, and the evidence behind it, and feel that this is a real product, not a demo.

Design consequences:
1. **The headline tells the truth of the moment** in plain words. Everything else on the screen supports it.
2. **Evidence is first-class.** Quotes are typeset with care, sources are always one click away, confidence is shown honestly (and "possible" is a real visual state, not hidden).
3. **The graph is not decoration.** It shows the agent's actual path, step by step, synced with the timeline. Aggregated by default, expanded on demand. Never a hairball.
4. **Live means live.** Things arrive as they happen: tool calls, evidence, test results. The UI never pretends.
5. **Calm by default, loud only when a person must act.** One accent, used sparingly, makes the important thing obvious.
6. **Every surface agrees with Slack.** Same state names, same colours, same words.

### 8.1 Brief
Build the "Evidence console" direction from PRD 13.2–13.7: monochrome surfaces with colour reserved for meaning, the live grammar of the reference (eyebrows, chips, streaming timeline, numbered pipeline, footer status bar, delivery toasts), editorial display type for headlines and evidence quotes, JetBrains Mono for data. The signature is the evidence path tracing hop by hop on the canvas with typeset quote cards. Every screen has an eyebrow, a plain-language headline and a one-line purpose. Every panel has a mono label and a display title.

### 8.2 Process per screen (use the skills for a reason, in this order)
1. **Shape** with `impeccable` and `interface-design`: write the screen's purpose, user, main action, headline copy for each state, and the information hierarchy into `specs/screen-<name>.md`. For the first screen, also run Impeccable's init and record tokens, type, spacing, motion and voice in `DESIGN.md`.
2. **Build** with `frontend-design`, `frontend-ui-engineering` and `vercel-react-best-practices`: semantic structure, accessible components, server components where useful, dynamic import for the canvas, no waterfalls.
3. **States and interaction** with `interaction-design`: loading, empty, error, partial, offline, optimistic, stale; toasts, modals, focus.
4. **Motion** with `12-principles-of-animation`: only the motions in PRD 13.7, with token durations and easings and reduced-motion variants.
5. **Polish** with `better-ui`: radius, optical alignment, shadows, icon states.
6. **Guardrails** with `ui-skills-root`.
7. **Review loop:** run the app, take Playwright screenshots at 1440 and 1920, open and look at them, run Impeccable critique and audit (and its detector if it works offline after the first download), list every problem, fix, repeat. At least two full rounds for the Request page and the Connect page, one for every other screen. Record the rounds in `BUILD-LOG.md`.
8. **AI-look audit (fresh eyes):** after the review loops, run the independent reviewer from section 2a as a separate subagent on the screenshots only, with the brief and the list of tells in spec C, C11. Fix every material finding and repeat until a round returns none. Record both rounds.
9. **Production SaaS completeness:** implement every item in PRD 13.9b (onboarding checklist, workspace creation, logo and wordmark, favicons and Open Graph images, page titles and meta, designed 404 and 500 pages, formatting rules, form behaviour, navigation state, responsive landing, cost visibility, replay fallback).
10. **In-app setup guides:** build the Slack, GitHub and Linear guides in spec C, C13 (numbered steps with exact clicks, copy buttons, deep links, scope tables with reasons, live checks per step, troubleshooting mapped from provider errors). The design engineer owns their finish; a user must be able to connect every source without leaving Actron to search for help.

### 8.3 Typeface choice
Choose the display and UI faces through Impeccable's font guidance and its font index. Constraints: distinctive, excellent at large sizes for headlines and at reading sizes for quotes, available through `next/font`, not Inter, Roboto, Arial, Space Grotesk or system defaults. JetBrains Mono for data. Record the choice and the reason in `DESIGN.md`.

### 8.4 Banned
Purple or blue gradients, glassmorphism, emoji as icons, identical rounded-card grids, stock hero sections, lorem ipsum, fake charts, colour side-stripe borders on cards, "AI beige", default component-library looks, decorative motion, hype copy.

### 8.5 Data flow
Generated types from OpenAPI; TanStack Query keys `requests`, `request`, `events`, `subgraph`, `ingestion`, `notifications`, `connections`, `settings`; one `EventSource` per open request writing into the cache with reconnect and `Last-Event-ID`; optimistic mutations with rollback and 409 reasons; Zustand only for UI state; MSW fixtures during development behind the DEV FIXTURES flag.

### 8.6 Frontend gate
- Every screen in PRD 13.5 implemented with all states in 13.6 and motion in 13.7.
- Type check, lint and build pass; first-load JS under 250 KB gzipped on non-graph routes; no console errors.
- Vitest unit tests for every component and hook; Playwright e2e flows; axe on every screen with zero serious violations; screenshots saved in `frontend/tests/screenshots/` and referenced in the README.
- Review loop completed (8.2 step 7), AI-look audit passed with no material findings (8.2 step 8), PRD 13.9b items complete (8.2 step 9).

### 8.7 App shell (all signed-in screens)
- **Layout:** a 12-column grid at 1440 width, max content width 1600, 24 px gutters. A slim left rail (64 px, icons with tooltips and labels on hover) for Home, Inbox, Graph, System (the live system map), Connect, Settings, with the workspace switcher at the top and the user menu at the bottom. A top bar is not used; each screen's eyebrow, headline and purpose open the page.
- **Footer status bar** (32 px, mono, small): ingestion state per source (dot + label: `GITHUB · SYNCED 2M AGO`), connected sources count, model status (`JEV LIVE` / `JEV STUB`), environment (`DEV`), DEV FIXTURES badge when on, a live connection indicator for SSE.
- **Command palette** (Cmd/Ctrl+K): jump to any request, node (search), screen; actions: new request, sync now, approve current (when available). Fuzzy matching, keyboard only, recent items first.
- **Toasts** bottom-right, stacked, max three, auto-dismiss 6 s except errors and "needs you" (persist until dismissed), each with an action ("Open") and, for cross-surface events, delivery status ("Approved in Slack by <name>. Build started.").
- **Keyboard:** `g h` home, `g i` inbox, `g g` graph, `n` new request, `a` approve (with confirmation showing the hash or SHA), `?` shortcut sheet.

### 8.8 Screen blueprints
Each blueprint lists purpose, layout, components, states (with headline copy), interactions, data and acceptance checks. Copy below is the default; keep its voice if you refine it.

**A. Sign in (`/app/signin`)**
- Purpose: start a session with Slack identity.
- Layout: centred column on the near-black surface; the evidence-path glyph as a quiet animated mark (draws once, then rests); eyebrow `ACTRON`; headline "Sign in to see what your team already decided."; purpose line "Actron reads your code, PRs, tickets and Slack, and checks them before an AI writes code."; one primary button "Sign in with Slack"; in dev, a secondary "Dev login" with a `DEV` badge.
- States: error ("Slack did not complete the sign-in. Try again.").
- Checks: keyboard focus on the button at load; dev login absent in prod build.

**B. Connect and memory (`/app/connect`)**
- Purpose: connect sources and watch the graph being built.
- Layout: eyebrow `MEMORY`; headline reflects state ("Your memory is 62% built." / "Connect a repository to start." / "Memory is up to date. Last sync 2 minutes ago."); purpose line "Each source you connect is read into one graph. Linking runs as data arrives."
  - Left (5 columns): three source cards in order Repository (code, git and GitHub data, from one form), Slack, Linear, plus an optional Slack export card. Each card: mono label (`SOURCE 01 · CODE`), title, state chip (`NOT CONNECTED`, `BACKFILLING`, `SYNCING`, `PARTIAL`, `FAILED`, `UP TO DATE`), counts by type (mono numbers that tick), items per minute, last synced, reason for partial or failed in plain words, actions ("Connect", "Sync now", "Disconnect"). Not connected cards show the exact setup steps (what token, which scopes, where to paste) and a form. The repository card's form has a required **working branch** selector, filled after the repository is validated: branches listed with the default first (marked "default"), then by most recent commit, protected ones marked, with the helper text "Actron reads and keeps this branch in memory. Choose the branch your team builds on." The connected card shows the working branch as a chip (`BRANCH · dev`).
  - Right (7 columns): the live graph canvas filling as nodes arrive (aggregated by type clusters: code, GitHub, Slack, Linear, core), a legend, and a per-type count strip beneath. Linking progress (references resolved, decisions found, identities matched, pending references waiting for a source).
- States: first run (empty canvas with a calm prompt to connect), backfilling, partial (reason), failed (retry), up to date.
- Interactions: connect forms validate tokens with a live test call and show the result; secrets never shown again (last four characters only).
- Data: `connections`, `ingestion` queries; SSE stream for ingestion events.
- Checks: counts update without layout shift; partial reasons visible; canvas stays at 60 fps with 1,000 aggregated nodes.

**C. Home (`/app`)**
- Purpose: see what needs you, what is running, what is done; start a request.
- Layout: eyebrow `REQUESTS`; headline summary ("2 requests need you. 1 is building." / "Nothing needs you right now."); purpose line "Ask in Slack with /actron or start here."
  - A request composer at the top (multi-line input, kind auto-detected and shown as a chip `FEATURE` / `BUG` / `QUESTION` that the user can change; submit with Cmd+Enter).
  - Three groups: **Needs you** (sorted oldest first), **Running**, **Done** (last 20). Each row: title, state chip, last event in plain words with relative time, requester avatar and name, a mini numbered pipeline (01 Investigate · 02 Clarify · 03 Ticket · 04 Approve · 05 Build · 06 Review) showing progress, and "Open".
- States: empty workspace (teach: connect a repo, then ask), no requests yet, loading skeletons matching rows.
- Checks: new requests from Slack appear live; keyboard navigation through rows; `n` focuses the composer.

**D. Request (`/app/requests/[id]`), the hero screen**
- Purpose: see what Actron found, decide, approve, follow the build, review the PR.
- Header: eyebrow `REQUEST · <ID> · FEATURE`; headline is the situation sentence for the current state (examples: "Investigating. 4 graph queries so far." / "Two earlier decisions affect this request." / "Nothing in your history touches this. Safe to continue." / "Ticket v2 is ready for your approval." / "Building. 3 of 14 tests passed." / "The build failed twice. Here is why." / "PR #18 is ready for review." / "Done. Merged scope recorded in memory."); purpose line naming the main action; the numbered pipeline with the current step highlighted; actions on the right (Approve, Answer, Cancel) depending on state.
- Body: three columns.
  - **Left, timeline (3 columns):** events in plain language with mono timestamps: request created (from Slack, by whom), each tool call as a compact card (`TOOL · callers(activate, depth 3)` → "Found 12 callers in 5 files"), evidence found, questions asked and answered (with surface: Slack or UI), ticket revisions, approvals (who, surface, hash), handoff to the build (a distinct, visually marked step), build steps, tests, PR, write-back ("Memory updated: 1 PR, 3 functions"). Hovering an event highlights its nodes on the canvas; clicking pins them.
  - **Centre, graph canvas (6 columns):** the request node at the left edge; the agent's path unfolding to the right (request → decisions, tickets, PRs → files → functions → callers, tests). Aggregated mode groups by type with counts; expanded mode shows every node. Node shapes and colours encode type; link styles encode method (solid explicit, dashed inferred) and confidence (opacity). The **evidence path**: when "show path" is pressed on an evidence card, the path traces hop by hop with the accent colour and each hop shows a small typeset quote card with its source chip. Controls: aggregated/expanded toggle, fit, zoom, "list view" (accessible alternative showing the same selection as a list).
  - **Right, tabs (3 columns):**
    - **Evidence:** the label banner (`CONFLICT` / `POSSIBLE CONFLICT` / `NOTHING FOUND`) with one sentence; evidence cards sorted by role (conflict, constraint, impact, similar work, owner, test): role label, quote set in the display face, source chip (Slack, PR, review, ticket, code) with author and date, confidence tier (`HIGH`, `MEDIUM`, `POSSIBLE`), "show path", "open source". Impact summary: callers count, criticality percentile of each seed, tests covering.
    - **Questions** (only when present): each question tied to its evidence, answer buttons or a short text field, answered state showing who answered and where.
    - **Ticket:** current revision (objective, acceptance criteria, constraints to preserve, affected functions as links to nodes, test plan), revision selector with a diff view, edit form (creates a new revision), approval card showing `REVISION v2 · SHA-256 3f2a…c91e`, approver and surface when approved, and a clear stale state ("You approved v1. This is v2. Approve again to build.").
    - **Build:** queue position or running state, steps in plain language with elapsed times, files touched (with links to function nodes), test results streaming (pass/fail counts as tickers, failing test names with output folded), repair attempts, scope-change stop with reason, raw logs folded.
    - **PR:** PR link and number, diff viewer (file list, unified diff with syntax colouring), test results on the head, the constraints checklist (each preserved constraint with the test or evidence that proves it still holds), head SHA, actions: Approve (bound to head SHA), Request changes (text box), Close.
- States: all request states in PRD 11.1; loading skeletons for each column; SSE reconnecting banner; cancelled view.
- Data: `request`, `events` (SSE), `subgraph` (mode), mutations for answers, revisions, approvals, feedback, cancel.
- Checks: timeline and canvas stay in sync; show path animates in under 1.5 s and respects reduced motion; approve shows the hash and handles 409 with the server's reason; screen readers can follow the timeline (`aria-live` polite).

**E. Graph explorer (`/app/graph`)**
- Purpose: explore the memory directly.
- Layout: eyebrow `GRAPH`; headline ("96 node types, 41,203 nodes, 188,911 links." with real numbers); purpose line "Search anything. Expand neighbours. Every link shows where it came from."; a search bar (full-text over names, text and code); filters by type and source; the canvas (focused subgraph, node budget 300, expand on double-click); a right inspector showing the selected node's properties, sources (links out), incoming and outgoing links grouped by type with method and confidence, and quick queries ("callers", "who knows this", "decisions on this", "shortest path to…").
- Checks: never renders more than the budget without asking; inspector shows provenance for every link.

**F. Inbox (`/app/inbox`)**
- Purpose: everything that needs you, in one list.
- Layout: eyebrow `INBOX`; headline ("3 things need you."); groups: Needs your input, Build failed or blocked, PR ready; each item opens the request at the right tab; mark read; keyboard `j/k` and `enter`.

**G. Settings (`/app/settings`)**
- Purpose: control connections, sync schedules, models per job, thresholds, bot identity.
- Layout: eyebrow `SETTINGS`; sections with clear labels; model settings show which jobs use Jev and which use the LLM (from PRD 10.2a), with live/stub status; thresholds with explanations of what they change; bot identity fields; working branch (changing it shows a confirmation naming the old and new branch and that code memory will be rebuilt, then re-ingests); danger zone (disconnect, reset a source's cursor).

### 8.8a Story, live illustration, icons, landing, replay, performance (required; read PRD 13.9a)
The user's instruction: judges remember the frontend, so the frontend must tell the story from start to end and show everything that happens behind the scenes. Treat this section as a core requirement, not polish.

1. **Live system map.** Build a component that shows the actors (Slack, Actron, FalkorDB, Jev, LLM, Pi container, GitHub, Linear) as nodes with their real logos, connected by edges. Map every event type (appendix E) to an actor pair and a one-line caption. When an event arrives, animate a pulse along the edge and update the active actor's caption ("FalkorDB · impact(activate, depth 3) · 27 functions"). Place it as a collapsible strip on the Request page above the canvas and as a full-screen System view (`/app/system`). It must reflect real events only. Reduced motion: no travelling pulses, captions still update.
2. **MCP tool calls made visible.** Each MCP tool call by the investigator or Pi appears in three places at once: a tool-call card on the timeline (tool glyph, tool name, arguments in mono, result summary, duration), a pulse on the system map (agent → FalkorDB), and the touched nodes highlighting on the graph canvas. The user must be able to see the agent *choosing* tools (Track 01).
3. **Pi at work.** While Pi runs, show a "build theatre" in the Build tab and the system map: current step in plain words, the file being edited (path with a language icon), a live diff preview for the latest change, tests streaming as pass and fail counters, repair attempts, and the MCP tools Pi called.
4. **Brand logos.** Download official brand assets or Simple Icons SVGs (Simple Icons is available on npm as `simple-icons`) for Slack, GitHub, Linear, Python, TypeScript, Docker; get FalkorDB, TypeSafe/Jev and Pi marks from their official sites or press kits. Save them in `frontend/public/brands/` with `LICENSES.md` (source URL, trademark owner, usage note). Use them unmodified apart from allowed monochrome or colour variants. If an official mark cannot be obtained, use a clean text wordmark and record it in `NEEDS-FROM-USER.md`.
5. **Custom glyph set.** Draw the Actron concept glyphs listed in PRD 13.9a as SVG React components on a 24-px grid with one stroke weight and an animated state each (for example: the impact glyph ripples outward, the shortest-path glyph traces its route, a test-pass glyph ticks, a handoff glyph slides from one hand to the next). Show them all on a hidden `/app/dev/glyphs` page used in visual tests. No "AI sparkle", robot, magic-wand or brain icons anywhere.
6. **Landing page (`/`).** One scroll that tells the story: problem sentence; one-sentence product; the five-step journey, each step with a real screenshot or a live embedded component from the app; the graph model (rendered from the ontology); the stack with real logos (FalkorDB, Jev, Pi, MCP, Slack, GitHub, Linear); "Watch a replay" and "Open the app". The app lives under `/app/*`. Capture screenshots from the running app with Playwright; never use mockups.
7. **Hero visual.** React Three Fiber scene of the real memory graph (sampled to a few thousand nodes), slow orbit, shader glow along an evidence path. Lazy-load after first paint, pause when off-screen, static image fallback for reduced motion, low-power devices and no-WebGL. It must not reduce the Lighthouse Performance score below target.
8. **Replay mode.** `/app/requests/[id]/replay`: play back a finished request's recorded events in order, with play, pause, speed (0.5× to 4×) and step controls; the timeline, system map, canvas and evidence path animate together; a caption bar explains each step in one sentence. Link to it from Home, the Request page and the landing page.
9. **Lighthouse and Core Web Vitals.** Add Lighthouse CI (`@lhci/cli`) to `scripts/test_all.sh` for `/`, `/app`, `/app/requests/<fixture id>`, `/app/connect` against a production build. Targets (desktop preset): Performance ≥ 90, Accessibility ≥ 95, Best Practices ≥ 95, SEO ≥ 90 (landing); plus a mobile run of the landing page with Performance ≥ 85 (spec C, C-AC-45); LCP < 2.5 s, CLS < 0.05, INP < 200 ms. Fail the run below target; record scores in `BUILD-REPORT.md`.
10. **Each screen explains itself.** Re-check every screen against this question: could someone who has never seen Actron tell, in five seconds and without reading paragraphs, what this screen is for and what is happening right now? If not, fix the headline, the purpose line, the illustration or the hierarchy.

### 8.9 Slack message blueprints (Block Kit)
- **Acknowledgement (within 3 s):** "On it. Investigating your request." + context line `REQUEST <ID> · INVESTIGATING` + button "Open in Actron".
- **Status message (one per request, edited in place):** header with the request title; context line `STATE · <state name> · <elapsed>`; a section with the headline sentence of the current state (same as the UI headline); for findings: up to three evidence blocks, each a quote in a blockquote with source link and author; the conflict label; actions depending on state: answer buttons, "Approve ticket v2" (action id carries request id and hash), "Request changes", "Open in Actron".
- **Approval confirmation:** the status message updates to "Approved by <name> in Slack. Build started." and the button disappears; the UI shows the same.
- **Needs you DM:** sent only to the person who must act: one sentence and a link to the thread.
- **Build finished:** "PR #18 is ready for review. 14 of 14 tests passed." + "Approve PR #18 (head 3f2a1c9)" (action id `approve_pr:<requestId>:<headSha>`, opens a confirmation naming the head) + "Request changes" (opens a modal) + "Review in Actron" + "Open PR".
- **Failure:** "The build failed twice. <one-line reason>." + "Open in Actron".
- No emoji as status, no exclamation marks, same state names as the UI.

---

## 9. Test suite (aim high: hundreds of tests)

Targets: **at least 500 backend tests, 200 frontend unit tests, 30 end-to-end scenarios**, backend line coverage ≥ 85%, frontend component coverage ≥ 80%, every acceptance id covered, zero flaky tests. More is better where each test checks something real.

### 9.1 Backend unit
ids; ontology loading, group expansion, validation errors; safe binding (quotes, newlines, unicode, `$x` text, large strings, lists, rejected types); every tree-sitter feature in Python and TypeScript (functions, methods, nested, lambdas ignored or handled, decorators, async, classes, inheritance, imports in every form, relative imports, `__all__`, type annotations); call resolution tiers; chunk coverage; markdown splitting; manifest parsing; CODEOWNERS matching (last rule wins); hunk parsing and mapping; blame aggregation; reference regexes with true and false positives for every format; identity matching; thresholds; canonical JSON and hashing; state machine pairs; Slack block builders; Jev request building and parsing for each primitive; LiteLLM fallback; stub markings; config validation.

### 9.2 Property-based (Hypothesis)
Every line covered exactly once by the function/class/chunk partition; ids stable when unrelated lines shift; canonical hash invariant to key order; no action sequence drives the state machine into an invalid state; idempotent upsert under repeated batches.

### 9.3 Integration (real FalkorDB, PostgreSQL, Redis)
Temporal workflows in the time-skipping environment (every signal, timeout, retry, cancel, stale approval, continue-as-new) and against the real server (one end-to-end request and one source sync); schedules created and triggered; store and indexes; persistence across container restart; ingestion of synthetic repos built during tests; re-run idempotency; incremental runs after add, modify, rename, delete commits; shared query and algorithms on a fixture graph with expected outputs; per-workspace isolation; pending references resolving after a later source run; migrations up and down.

### 9.4 Contract tests with fake servers
Slack, GitHub, Linear, Jev, LLM provider: paging, 429 with `Retry-After`, 529, ETag 304, timeouts, malformed responses, partial runs recorded, edits, deletes, external Linear edits.

### 9.5 Flow, build and security
Every transition and refusal; stale ticket and PR approvals; concurrent approvals; duplicate deliveries; cancel at every state; nothing-found; conflict thresholds on labelled data; investigator agent with a scripted fake model choosing tools; fake Pi scenarios; container credential isolation; Slack signatures; CSRF; dev login blocked in prod; secret redaction; tokens never returned by the API.

### 9.6 End to end (Playwright against the full stack with fakes)
At least: sign in (dev login); connect GitHub, Slack, Linear (fakes); watch ingestion progress to done; partial ingestion shown with reason; Sync now; Slack command creates a request and the UI shows it live; investigation with tool calls on the timeline and the evidence path on the canvas; "show path" from an evidence card; question answered in the UI updates the Slack status message (fake Slack records the update); question answered in Slack updates the UI; ticket revision edit voids approval; approve in Slack and in the UI at once, only one counts; build streams steps; failing build shows real failure then repair; PR page with diff, tests and constraints; request changes triggers a new build; approve PR; write-back visible in the graph explorer; cancel at each stage; nothing-found request; graph explorer search and expand; inbox items open the right tab; command palette navigation; keyboard-only flow; reduced-motion flow; SSE reconnect resumes without losing events; error states (backend down, Linear timeout); dev fixtures badge visible only with the flag; Q&A (bonus).

### 9.7 Frontend unit
Every component in PRD 13.6, the SSE reducer, query-key logic, optimistic rollback, stale approval logic, format helpers, palette commands, keyboard shortcuts.

### 9.8 Accessibility and performance
axe on every screen; keyboard traps; focus order; contrast tokens test. Ingestion time for Calva, shared-query p95, canvas frame time, bundle sizes recorded in `BUILD-REPORT.md`; load test (bonus).

### 9.9 Live smoke (opt-in)
`scripts/live_smoke.sh` runs `@pytest.mark.live` tests when keys exist: real Calva ingestion, real GitHub PRs, Slack auth test, Linear viewer query, one Jev call, Pi trivial prompt. Report which ran.

---

## 10. Models (phase 3 detail)
Follow PRD 10. Jev questions are narrow and self-contained (the question id is not sent to the model). State is named JSON (`request`, `candidate`, `decision`). Ask independent questions together in one request. Store the probability and model name on every model-made link. Calibrate thresholds on the labelled fixtures and record the chosen values and the measured precision and recall.

## 11. Pi (phase 12 detail)
Follow PRD 12. Pi has no sandbox: the container is the boundary. Mount only the checkout; network only to the model provider and the MCP server where possible. Record the exact Pi command line and configuration that worked in `docs/runbook.md`.

## 12. Slack (phase 7 detail)
Follow PRD 13.10 and 8.3. Same state names as the UI. One status message per request, edited in place. DMs only when a specific person must act. Buttons carry ids and hashes.

---

## 13. Environment variables (`.env.example`, names only)

```
ACTRON_ENV=dev                      # dev or prod
ACTRON_SECRET_KEY=                  # Fernet key for encrypted connector secrets
SESSION_SECRET=
DATABASE_URL=postgresql+psycopg://actron:actron@127.0.0.1:5433/actron
REDIS_URL=redis://127.0.0.1:6380/0
FALKORDB_URL=redis://127.0.0.1:6389
FALKORDB_GRAPH_PREFIX=actron
TEMPORAL_ADDRESS=127.0.0.1:7233  TEMPORAL_NAMESPACE=actron  TEMPORAL_UI_PORT=8233
SLACK_BOT_TOKEN=  SLACK_SIGNING_SECRET=  SLACK_APP_TOKEN=  SLACK_CHANNELS=
SLACK_CLIENT_ID=  SLACK_CLIENT_SECRET=  ACTRON_PUBLIC_URL=
# One Slack app: SLACK_CLIENT_ID/SECRET serve both "Add to Slack" (OAuth install, spec B B11a) and Sign in with Slack. SLACK_BOT_TOKEN and SLACK_CHANNELS are development fallbacks only.
GITHUB_TOKEN=  GITHUB_REPOSITORY=  GITHUB_FORK=  GITHUB_UPSTREAM=  GITHUB_WEBHOOK_SECRET=
# GITHUB_REPOSITORY = the repo the team merges into and Actron ingests (the fork for the demo); GITHUB_UPSTREAM = history only
LINEAR_API_KEY=  LINEAR_TEAM_ID=
TYPESAFE_API_KEY=  JEV_MODEL=jev-1.13.0
ANTHROPIC_API_KEY=  OPENROUTER_API_KEY=  GEMINI_API_KEY=  GROQ_API_KEY=
MODEL_DECISION=  MODEL_WRITING=  MODEL_AGENT=  MODEL_CODING=
ACTRON_BOT_NAME=  ACTRON_BOT_EMAIL=
ACTRON_MAX_CONCURRENT_BUILDS=1  ACTRON_BUILD_TIMEOUT_SECONDS=1800  ACTRON_MAX_REPAIRS=2  ACTRON_DAILY_MODEL_BUDGET_USD=20
ACTRON_CLONE_DIR=.actron/clones  ACTRON_BACKFILL_DAYS=90  ACTRON_GIT_HISTORY_DEPTH=2000
ACTRON_BUILD_HOST_DIR=/var/lib/actron/builds  ACTRON_HOST=127.0.0.1  ACTRON_PORT=8080  FALKORDB_PORT=6389
LITELLM_FALLBACKS=  LINK_KEEP_THRESHOLD=0.6
API_INTERNAL_URL=http://backend:8080  NEXT_PUBLIC_ACTRON_DEV_FIXTURES=0
# SESSION_SECRET signs the session and CSRF cookies; ACTRON_SECRET_KEY (Fernet) encrypts connector secrets.
# The browser calls same-origin /api; Next.js proxies to API_INTERNAL_URL (spec C, C4). NEXT_PUBLIC_API_URL is not used.
# .env.example in the repo is the authoritative list; keep it in sync with config.py.
```
Use non-default host ports to avoid collisions (PostgreSQL 5433, Redis 6380, FalkorDB 6389). Every variable may be empty; empty means stub or "not connected", never a crash. Write each line on its own line in the real file.

---

## 14. Hackathon checklist (must be true at the end)
- FalkorDB does real work: the investigator and builder depend on graph queries and algorithms.
- Public repo ready (the user pushes it): README with setup, graph data model, key Cypher queries and algorithms, AI-use disclosure, tracks entered (Track 01, plus 02 and 03 only if real).
- Demo script in `DEMO.md`; deployment configuration ready; screenshots captured.
- Only public, synthetic or own data in the graph.

---

## 15. Definition of done and final report

Stop only when every item below is true, or every unchecked item is blocked on user input recorded in `NEEDS-FROM-USER.md`:
1. `make up` starts FalkorDB, PostgreSQL, Redis, the Temporal server and UI, backend, worker, frontend and the backup service, and builds the `actron-pi` and `actron-test-runner` images; health is green (integrations without keys report "not connected").
2. Calva is ingested from a real clone; counts, coverage and idempotency verified.
3. All connectors, incremental sync and linking pass their tests; live ones verified where keys existed.
4. The full request flow works end to end through the API, the Slack handlers (fake) and the UI, including approvals from both surfaces.
5. Pi build orchestration passes with the fake Pi; the real image was built and Pi started (or the reason is recorded).
6. Every screen is built to section 8 and passed the review loop.
7. `scripts/test_all.sh` is green three times in a row; targets in section 9 met or the shortfall explained; spec coverage has no gaps.
8. README, docs, DEMO, DESIGN files, deployment configuration, Slack app manifests (`infra/slack/`), nightly backup job, and the blog post draft (`docs/blog-post.md`) written.
9. Track 01 points all implemented and visible; bonus points done or listed as not done.
10. Nothing committed or pushed.

Then write `BUILD-REPORT.md`: what was built per phase; test counts per level and the real output summary; coverage numbers; what ran live versus fakes or stubs; precision and recall (stub or real); performance numbers; screenshots list; unresolved items; and how to run everything. Finish with a short summary message: what works, what is stubbed, what the user must do next (point to `NEEDS-FROM-USER.md`).

---

## Appendix A: NEEDS-FROM-USER.md entry
```
### <short title>
- Needed for: <feature and phase>
- What: <exact key, account, choice or permission>
- Where it goes: <env var / file / UI screen>
- Current workaround: <stub, fake or default in use>
- How to verify after providing it: <command>
```

## Appendix B: major spec template (`specs/A-…md`, `B-…md`, `C-…md`)
```
# Spec <A|B|C>: <title>
Scope: <PRD sections covered>
Contracts: <frozen interfaces in this spec: schemas, events, query shapes, question catalog>

## <Area 1, for example "Code ingestion">
Purpose: <what and why, linked to PRD>
Interfaces: <functions with signatures, routes, events, CLI>
Data written: <node types, relationships, tables>
Acceptance criteria:
- A-AC-1: <observable behaviour>
- A-AC-2: ...
Edge cases: <list>
Tests: <test files and test names mapped to AC ids>

## <Area 2> ...
```

## Appendix C: BUILD-LOG.md entry
```
## <time> <phase/workstream> <done|decision|failure>
<what happened, files touched, commands run, result>
```

## Appendix D: shared-query output shape
```json
{
  "requestId": "actron:request:…",
  "seeds": [{"id": "code:fn:…", "type": "CodeFunction", "score": 0.91}],
  "decisions": [{"id": "actron:decision:…", "statement": "…", "status": "approved|proposed|superseded",
                 "quote": "…", "source": {"id": "…", "type": "SlackMessage", "url": "…"},
                 "conflict": {"label": "conflict|possible_conflict|none", "probability": 0.84}, "path": ["…"]}],
  "relatedWork": [{"id": "github:pr:…", "type": "GithubPullRequest", "title": "…", "state": "merged", "url": "…", "path": ["…"]}],
  "impact": {"callers": [{"id": "code:fn:…", "depth": 1}], "tests": [{"id": "code:fn:…"}],
             "criticality": [{"id": "code:fn:…", "percentile": 97.5}]},
  "owners": [{"personId": "actron:person:…", "name": "…", "basis": ["blame", "reviews"], "score": 0.7}],
  "procedures": [{"id": "actron:procedure:…", "testCommand": "…"}],
  "label": "conflict|possible_conflict|nothing_found|clear",
  "graph": {"nodes": [{"id": "…", "type": "…", "label": "…"}], "edges": [{"from": "…", "to": "…", "type": "…"}]}
}
```

## Appendix E: event types
`request.created`, `investigation.started`, `tool.called`, `tool.result`, `evidence.found`, `investigation.completed`, `question.asked`, `answer.received`, `ticket.revised`, `ticket.synced`, `approval.recorded`, `approval.refused`, `handoff.created`, `build.queued`, `build.started`, `build.step`, `tests.result`, `build.repair`, `build.failed`, `build.passed`, `pr.opened`, `pr.updated`, `review.feedback`, `pr.approved`, `writeback.done`, `notification.sent`, `request.cancelled`, `request.done`, `answer.ready` (Q&A), `memory.refreshing`, `memory.refreshed`, `memory.unverified` (freshness gate), `request.state_changed {from, to, reason}` (every transition), `judgment.made {job, provider, count, what}` (Jev or fallback judgments, for the system map), `budget.reached {spentUsd, capUsd}`, and the workspace-level ingestion events from spec A, A.C6 (`ingestion.started`, `ingestion.progress`, `ingestion.partial`, `ingestion.finished`, `linking.progress`, `linking.finished`). Each event: `id` (monotonic per request), `requestId`, `type`, `at`, `actor` (`person`, `actron`, `slack`), `surface` (`slack`, `ui`, `system`), `payload`.

## Appendix F: state transitions
| From | Action | To |
|---|---|---|
| (new) | create | Investigating |
| Investigating | freshness gate timeout (`memory_stale`) or investigation failed twice | Needs attention |
| Investigating | findings with questions (always includes the target-branch question unless the request named a branch) | Needs your input |
| Investigating | findings without questions | Ticket ready |
| Investigating | nothing found (and branch already named) | Ticket ready |
| Investigating (question kind) | answer ready | Done (outcome `answered`) |
| Needs your input | all required questions answered | Ticket ready |
| Ticket ready | ticket saved (synced to Linear, or Linear not connected) | Awaiting approval |
| Ticket ready | `edit_ticket` | Awaiting approval (new revision) |
| Awaiting approval | `edit_ticket` | Awaiting approval (new revision, earlier approvals void) |
| Awaiting approval | `approve_ticket` with the current revision hash | Building |
| Awaiting approval | `approve_ticket` with a stale hash, or external edit in Linear | Awaiting approval (refusal recorded: `stale_revision` / `external_edit`) |
| Building | daily model budget reached | Building (waits; resumes on `budget_raised` or the next UTC day) |
| Building | tests pass, PR opened | PR ready for review |
| Building | failure after repairs, `scope_change`, `tests_weakened`, `timeout`, `missing_fork`, `missing_branch`, `missing_identity`, freshness `memory_stale` | Needs attention |
| Needs attention | `edit_ticket` | Awaiting approval (new revision) |
| Needs attention | `retry` | the step that failed: Investigating (if investigation failed) or Building (if the build failed) |
| PR ready for review | `pr_feedback` classified `code_change_within_scope` | Changes requested |
| PR ready for review | `pr_feedback` classified `scope_change` | Needs attention |
| PR ready for review | `pr_feedback` classified `question` | PR ready for review (answer posted) |
| PR ready for review | `approve_pr` with the current head SHA (or `pr_feedback` classified `approval`) | Done (outcome `approved`; write-back runs) |
| PR ready for review | `approve_pr` with a stale head | PR ready for review (refusal recorded: `stale_head`) |
| PR ready for review | `close_pr` | Cancelled (outcome `closed`; the PR is closed on GitHub) |
| Changes requested | revision build passes | PR ready for review |
| Changes requested | revision build fails after repairs or stops | Needs attention |
| any non-final state | `cancel` | Cancelled (outcome `cancelled`) |
Every row is a test (B-AC-7). Any action not listed for a state is refused with `InvalidTransition` and reported in both Slack and the UI.
