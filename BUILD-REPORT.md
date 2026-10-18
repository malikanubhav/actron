# Build report

Built unattended on 17–18 October 2026 from `PRD.md`, `PROMPT.md` and the three specs. Nothing is committed or pushed. This report states what was built, what ran for real, what ran against fakes or stubs, and what is left. The step-by-step record is `BUILD-LOG.md`; anything only you can provide is in `NEEDS-FROM-USER.md`.

## Summary

- The whole product exists and runs locally with one command (`make up`): FalkorDB, PostgreSQL, Redis, Temporal server and UI, backend, worker, frontend, nightly backup, plus the `actron-pi` and `actron-test-runner` images. Health is green; integrations without keys report "not connected" or "stub".
- Real data: Calva (`BetterThanTomorrow/calva` at `b2476a7`) is cloned and ingested into the `dev` workspace graph through the product's own connect flow and Temporal workflow.
- The Track 01 request flow runs end to end on the real stack through the API: request → graph investigation with traced tool calls → evidence → graph-driven questions → ticket with hash → approval (stale hash refused) → handoff to the build. Without your keys the build stops, as designed, at `missing_identity` (no bot identity) and would next stop at `no_model_key`.
- The full flow including Slack, a Pi build, PR, review and write-back runs end to end against fakes (fake Slack, GitHub backed by local git repositories, Linear, Jev, and a fake Pi container) in 40 browser scenarios on the full stack.
- Every acceptance criterion in specs A, B and C (106 + 91 + 57) is referenced by at least one test. `scripts/test_all.sh` passed three times in a row (results below).

## What was built, per phase

| Phase | Result |
|---|---|
| 0 Layout | PRD 6.1 structure; `pyproject.toml` and `uv.lock` in `backend/`, `compose.yaml` in `infra/`; Makefile (`up`, `up-deps`, `down`, `test`, `check`, `e2e`, `e2e-stack`, `test-all`, `fmt`, `logs`, `types`, `deploy`) |
| 1 Specs and contracts | Specs A, B, C read and extended only where silent: API contract B.C7, C13 check ids; `specs/WORKSTREAMS.md` (ownership and cross-team interfaces); `scripts/spec_coverage.py` |
| 2 Platform | Pinned images (FalkorDB 4.22.1, Postgres 16.15, Redis 7.4.11, Temporal auto-setup 1.29.7, UI 2.56.0); settings with fail-fast validation; JSON logs with secret redaction; ontology loader (96 node types, 275 expanded core links, 12 Slack and 78 Linear relationships skipped); graph store with safe binding, batches, timeout halving; PostgreSQL schema and migrations; Fernet secrets; Temporal smoke and schedule helpers; health endpoint |
| 3 Models | Jev client (httpx; batching; 429/529 backoff; typed errors) with the exact J1–J10 question JSON; LiteLLM with fallbacks; conservative marked stubs; Redis cache; usage rows and daily spend |
| 4–5 Code and git | tree-sitter parsing for Python, TypeScript/TSX/JavaScript, Go, Java, Rust (tier 1) and Kotlin, Ruby, PHP, C, C++, Scala, Swift, Clojure (tier 2); chunks covering every line; call resolution tiers; tests linking; docs, manifests, CODEOWNERS; git log, hunks to functions, blame; in-place updates, tombstones and rename detection; PageRank via `algo.pageRank` |
| 6–8 GitHub, Slack, Linear | REST, Web API and GraphQL clients with paging, ETags, `Retry-After`, typed errors; mappings onto the ontology; Slack versions and tombstones; Slack export import; Linear writes with deterministic ids and external-edit detection |
| 9 Connect and sync | Connector forms served from the backend; validate, options and checks endpoints; `SourceSyncWorkflow` with continue-as-new and cursors; Temporal Schedules; GitHub webhook and merge watch; working-branch choice and change |
| 10 Linking | Identity, explicit references with pending resolution, meaning links, decisions with exact quotes, link checks, knowledge and procedures |
| 11 Request flow | `RequestWorkflow` (every appendix F transition), service layer with idempotency and approvers, event journal, SSE with replay, freshness gate, target-branch question, tickets with SHA-256 revisions, notifications, budget cap; 20 MCP graph tools; investigator agent and deterministic pipeline |
| 12 Build with Pi | `actron-pi` image (Pi 1.3.0); `BuildWorkflow`; checkout, context pack from the graph, TASK.md protocol and its enforcement, weakened-test and scope guards, offline test container, repair loop, commit through a credential helper, PR via the API |
| 13 API | Every PRD 14 route (47 OpenAPI paths), Slack OIDC and dev login, Redis sessions, CSRF, rate limits; worker and CLI; Slack bot (Bolt, HTTP and Socket Mode), Block Kit messages, "Add to Slack" OAuth, manifests |
| 14 Frontend | Next.js 16 app: landing with 3D hero, sign in, Home, Connect with setup guides, Request (timeline, graph canvas with evidence-path tracing, tabs, build theatre, PR diff), graph explorer, inbox, system view, settings, replay; command palette, shortcuts, toasts, footer status bar; design system in `DESIGN.md` |
| 15 End to end | 40 full-stack Playwright scenarios against fake providers; 114 scenarios on the fixture build; `scripts/test_all.sh` |
| 16 Bonus | Load test, per-workspace graphs, handoff, procedures, Q&A mode, `KNOWS_ABOUT` (see Tracks) |
| 17 Docs and deploy | README, DEMO, DESIGN, DESIGN-DIRECTIONS, eleven living docs, blog post draft, `compose.prod.yaml` with Caddy, `make deploy`, Slack manifests, backup service |

## Tests

Final three consecutive runs of `scripts/test_all.sh` (same code, see "Three runs" below for each run's summary line):

| Level | Count |
|---|---|
| Backend unit | 741 |
| Backend property-based (Hypothesis) | 23 |
| Backend integration (real FalkorDB, PostgreSQL, Redis, Temporal) | 396+ |
| Backend contract (fake Slack, GitHub, Linear, Jev, LLM) | 82 |
| Backend workflows (Temporal time-skipping) | 65 |
| Backend API | 82 |
| Backend eval | 19 |
| Frontend unit (Vitest) | 813 |
| End to end on the fixture build (Playwright) | 114 |
| End to end on the full stack with fakes (Playwright) | 40 |

Coverage: backend 88% of lines; frontend 82.8% of lines (components and lib; canvas, WebGL and image routes cannot run in jsdom and are covered by the Playwright suites instead).

Targets in PROMPT 9: 500 backend tests (met: 1,400+), 200 frontend unit tests (met: 813), 30 end-to-end scenarios (met: 154), backend coverage ≥ 85% (met), frontend coverage ≥ 80% (met), spec coverage complete (met).

### Three runs
All three consecutive runs of `scripts/test_all.sh` on 18 October 2026 passed with identical counts:

| Run | Started (UTC) | Duration | Result |
|---|---|---|---|
| 1 | 01:49 | 11 min 4 s | PASSED |
| 2 | 02:00 | 10 min 52 s | PASSED |
| 3 | 02:11 | 10 min 34 s | PASSED |

Each run: backend unit 741, property 23, integration 397, contract 82, workflows 65, API 82, eval 19 (1,409 backend tests); backend coverage 88%; frontend typecheck and lint clean; frontend unit 813 (coverage 82.8%); end to end on the fixture build 114; end to end on the full stack 40; Lighthouse desktop Performance 99–100 and Accessibility 98–100 on all four routes; Lighthouse mobile landing Performance 92–94; spec coverage A 106/106, B 91/91, C 57/57. Logs: `.actron/test-all/`.

## What ran live and what ran against fakes or stubs

| Part | Live | Fakes or stubs |
|---|---|---|
| FalkorDB, PostgreSQL, Redis, Temporal | Live in every test run and in the app | — |
| Calva clone, parsing, git history | Live (public clone) | — |
| GitHub | Live without a token: repository validation, branch list, a public-limit sync (12 PRs, 66 users, 14 branches, run marked `partial`, "public rate limit"); live test pulling 5 Calva PRs and a review comment | Full history, pushes and PRs need `GITHUB_TOKEN` and a fork; tested against a fake GitHub backed by local git repositories |
| Slack | Not run (no tokens) | Fake Slack Web API, signed HTTP requests to the bot, OAuth with a fake `oauth.v2.access` |
| Linear | Not run (no key) | Fake Linear GraphQL server; field names follow the docs, not checked against the live schema |
| Jev | Not run (no key) | Fake Jev server; stubs in the app (`JEV STUB` in the footer) |
| LLM (investigator agent, writing) | Not run (no key) | Scripted fake model for the agent loop; deterministic pipeline and templates in the app |
| Pi | Image built; `pi --version`, help, JSON event stream, session resume and MCP connection verified inside the image | A prompt was not completed (no model key); builds in tests use a fake Pi image that applies known patches |

## Link and conflict quality (A-AC-77)

Mode: stub (no Jev or model keys). Explicit references, which need no model: precision 1.00, recall 1.00 over 20 labelled cases (optimistic, because patterns and fixtures were written together). Inferred links and conflict judgments: no positive predictions with stubs, so recall 0.00; these numbers measure the stub, not Jev. The labelled fixtures (`link_labels.yaml`, 44 cases; `conflict_labels.yaml`, 32 cases) and `tests/eval/test_link_quality.py` are ready to measure the real model once `TYPESAFE_API_KEY` is set.

## Performance

| Measure | Result |
|---|---|
| Calva ingestion (code and git, depth 2,000 commits) | 36.4 s on an existing clone; 70.8 s including the clone; 1 min 54 s through the connect flow's Temporal workflow |
| Calva graph size | 19,952 nodes and 76,532 links after ingestion (5,533 functions, 11,754 `CALLS`, 4,150 `TESTS`, 2,000 commits); 19,954 and 76,757 after the test requests added their request, investigation and evidence links |
| Shared query, single call | 0.18–0.5 s (hub functions with 900+ callers included) |
| Load test (60 s, 8 reader + 2 writer processes, 50 most-called functions) | 0 errors; shared query p95 1,747 ms; impact p95 725 ms; callers p95 429 ms; 4,609 node writes per second (500-row batch p95 359 ms) |
| Lighthouse desktop (`/`, `/app`, `/app/connect`, a real request) | Performance 99–100, Accessibility 98–100, Best Practices 96–100, SEO 100 on the landing |
| Lighthouse mobile landing | Performance 89–92 across runs (target 85) |
| First-load JavaScript, largest non-graph route | 232 KB gzipped (budget 250 KB) |

The load test first showed timeouts; the cause was a FalkorDB planner behaviour (docs/falkordb.md 17), fixed by anchoring lookups and walking callers one hop at a time (shared query 4.4 s → 0.5 s on hub functions).

## Screenshots

- Real data (Calva, no fixtures): `frontend/tests/screenshots/real/` — home, connect, graph, system, inbox, settings, and a real request's evidence, ticket and build tabs, each at 1440 and 1920.
- Every screen and state from the development-fixture build: `frontend/tests/screenshots/` — landing, sign in, home (normal, empty, backend down), connect (normal, empty, setup guide), request (investigating, evidence, path traced, stale ticket, building, failed, PR ready, cancelled, answered, nothing found), replay, public replay, inbox, graph, system, settings, command palette, 404, glyphs.

## Design review

Two screenshot review rounds per main screen and seven rounds of an independent "AI-look" audit by a reviewer that saw only screenshots; material findings went 8, 5, 6, 5, 2, 1, 0 (`BUILD-LOG.md`, W7). A later pass on real data found and fixed a canvas that never laid out when data arrived after the first render, and a request graph that drew as a wall of nodes (now clustered).

## Tracks

- Track 01: all five points implemented and visible (README table).
- Track 02: episodic memory (journal, replay), handoff, per-workspace graphs with isolation tests, load test — done. Procedural memory is implemented but learns from merged PRs, which needs real PR history (a GitHub token).
- Track 03: docs, tickets, chats and code in one graph; ownership and `KNOWS_ABOUT`; decisions traced to quotes; incremental sync — done. Q&A mode works; answers are template-written until a model key is set.

## Unresolved and limitations

- No live Slack, Linear, Jev, LLM or Pi prompt runs (keys missing). Linear field names are unverified against the live schema.
- Thresholds (link keep 0.6, conflict 0.8/0.5, approval 0.85, supersession 0.7) are not calibrated; calibration needs real model answers on the labelled fixtures.
- Without keys, approved decisions touching a request show as "possible conflict" (never "conflict"), and PR feedback is classified as a question, so it never starts a rebuild without a person.
- Egress from the build network is not limited to the model provider and the MCP server (plain bridge network); recorded in the runbook.
- Not verified: whether Pi's own file tools edit in place (bind-mounted notes and report files would fail on rename-writes); a private-repository clone through the credential helper against GitHub.
- 1,575 TypeScript calls in Calva stay unresolved (method names shared by several classes need type information). `TOUCHED` does not follow files renamed in history.
- The old FalkorDB volume `actron_falkor-data` was left untouched after a crash (see NEEDS-FROM-USER.md); the stack uses `falkor-data-v2`.
- 17 minor items from the last design audit (label placement in dense graphs, diff line clipping, and similar) are listed in `BUILD-LOG.md`.

## How to run everything

```bash
make up                      # whole stack and images; open http://localhost:3000, Dev login
make up-deps                 # stores and Temporal only (for the backend tests)
./scripts/test_all.sh        # every test level, spec coverage, Lighthouse; prints a summary
make e2e-stack               # full-stack browser tests against fake providers
uv run --project backend python scripts/load_test.py --seconds 60 --readers 8 --writers 2
./scripts/live_smoke.sh      # live provider checks, for each key present in .env
make deploy                  # production stack with Caddy (needs a server and ACTRON_DOMAIN)
```
