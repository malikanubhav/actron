# Testing

Everything runs from one script: `scripts/test_all.sh` (or `make test-all`). It needs the compose stack (`make up`):
the stores for the backend tests and the e2e stack, the running frontend and backend for Lighthouse. It prints one
line per level with its counts, exits non-zero when anything fails, and keeps every log in
`.actron/test-all/<UTC time>/`.

## Levels

| Level | Where | Needs | How to run one level |
|---|---|---|---|
| Backend static | `backend/actron`, `backend/tests` | nothing | `cd backend && uv run ruff check actron tests && uv run mypy actron` (strict) |
| Unit | `backend/tests/unit` | nothing | `cd backend && ACTRON_TEST_REDIS_DB=7 uv run pytest tests/unit -q` |
| Property | `backend/tests/property` | nothing | `... pytest tests/property -q` (Hypothesis: ids, chunk coverage, state machine, canonical hash) |
| Integration | `backend/tests/integration` | `make up-deps`, Docker | `... pytest tests/integration -q --timeout 300` (real FalkorDB, PostgreSQL, Redis, Temporal; builds with the fake Pi image) |
| Contract | `backend/tests/contract` | stores | `... pytest tests/contract -q` (connectors against fake Slack, GitHub, Linear, Jev) |
| Workflows | `backend/tests/workflows` | Temporal test server | `... pytest tests/workflows -q` (time-skipping environment) |
| API | `backend/tests/api` | stores | `... pytest tests/api -q` (FastAPI app over httpx and real uvicorn for SSE) |
| Eval | `backend/tests/eval` | nothing | `... pytest tests/eval -q` (link and investigation quality on labelled samples) |
| Live (opt in) | `backend/tests/live` | provider keys | `scripts/live_smoke.sh` (`pytest -m live`; excluded by default) |
| Frontend static | `frontend/` | Node 22 | `cd frontend && npm run typecheck && npm run lint` |
| Frontend unit | `frontend/tests/unit` | Node | `npm test` (Vitest, jsdom); `npm run test:coverage` adds line coverage of `components/` and `lib/` |
| E2E, fixtures | `frontend/tests/e2e` | Node | `npm run build:fixtures && npm run test:e2e` (production build with MSW fixtures on :3100) |
| E2E, full stack | `frontend/tests/e2e-stack` | `make up-deps`, Docker | `make e2e-stack` (or `scripts/e2e_stack.sh start --build-frontend`, `npm run test:e2e-stack`, `scripts/e2e_stack.sh stop`) |
| Lighthouse | `frontend/lighthouserc*.json` | `make up` | run by `scripts/test_all.sh` (Caddy front on :3400, a dev-login session) |
| Spec coverage | `specs/[ABC]-*.md` | Python | `python3 scripts/spec_coverage.py` lists acceptance ids that no test names |

Use a free Redis database per parallel run: `ACTRON_TEST_REDIS_DB` (the compose stack uses db 0, the e2e stack db 8).
Markers: `live`, `slow`, `integration` (`backend/pyproject.toml`); `live` is excluded by default.

## The full-stack e2e stack

`scripts/e2e_stack.sh` starts, from an empty world each time, a separate copy of Actron next to the compose stack:
the real backend (:18080) and worker against fake Slack (:18102), GitHub (:18101, backed by local bare git
repositories `acme/calc` and its fork), Linear (:18103) and a scripted Jev (:18104), the production frontend build
`frontend/.next-e2e` (:3300), and a control API (:18100) that reads what the fakes recorded and injects failures,
delays and a backend restart. It uses its own PostgreSQL database `actron_e2e`, Redis db 8, Temporal namespace
`actron-e2e`, graph prefix `actrone2e` (no unique constraints, so it can be dropped) and dev workspace `e2e`; the
compose stack and the `dev` workspace are never touched. Builds run the fake Pi image `actron-fake-pi:test`
(scenario `fail_then_repair`: the first attempt fails a real test, the repair passes) and the real test runner.
Slack requests are signed with the stack's test signing secret, as Slack sends them. Logs: `.actron/e2e/logs/`.
Code: `backend/tests/e2e_stack/{launch,world,github_git}.py`, specs `frontend/tests/e2e-stack/0N-*.spec.ts` (run in
order in one worker; 01 connects the sources the others use).

Scenarios (PROMPT 9.6), 40 tests: dev login; GitHub, Slack and Linear connected through the forms; a partial run
with its reason; Sync now; ingestion done; setup-guide checks; a Slack command that shows up live on Home; tool calls
on the timeline and the evidence on the canvas; show path; an answer in the UI that edits the Slack status message;
a ticket edit that voids the old approval (the old hash from Slack is refused); simultaneous approval from Slack and
the UI (one counts, one build); streamed build steps with a real failure and repair; the PR tab (diff, tests,
constraints); request changes → a second build on the same PR; approve PR → write-back → found in the graph
explorer; an answer in Slack that updates the open page; cancel while investigating, needing input, awaiting
approval and building, and closing the PR; nothing found; Q&A; a Linear timeout; explorer search, expand and quick
query; inbox tabs; command palette; a keyboard-only journey; reduced motion; SSE resume across a backend restart
with no lost or doubled events; the backend-down error state; no DEV FIXTURES badge on seven screens.

## Lighthouse

`frontend/lighthouserc.json` (desktop: landing, Home, a real finished request in workspace `dev`, Connect) and
`lighthouserc.mobile.json` (landing at 375 px). They measure the compose frontend through `infra/lhci/Caddyfile`
(Caddy on :3400 with `encode zstd gzip`, as production's Caddy does; Next itself serves uncompressed so that
server-sent events are not buffered). `/app` routes need `LHCI_SESSION` (a dev-login session cookie);
`scripts/test_all.sh` gets one and points `CHROME_PATH` at Playwright's Chromium.

## Rules

- Every test names its acceptance id in its name or docstring (`"""A-AC-16"""`, `test('C-AC-31 ...')`).
- Tests first, then code. No retries to hide flakes: a flaky test is a bug in the test or the product.
- Fixtures live in `backend/tests/conftest.py` (`ontology`, `graph`, `indexed_graph`, `db_url`, `db_session`,
  `redis_client`, `temporal_address`) and under `backend/tests/fixtures/` and `frontend/tests/fixtures/`.
- Tests that restart FalkorDB or create unique constraints use a throwaway container
  (`backend/tests/integration/falkor_scratch.py`), never the shared service (`docs/falkordb.md`, limitation 12).
- Workflow tests use `WorkflowEnvironment.start_time_skipping()`; workflow modules import only deterministic code.

## Counts (W10, 18 Oct 2026, `scripts/test_all.sh`, three consecutive green runs)

| Level | Tests | Result |
|---|---|---|
| Backend unit | 741 | pass |
| Backend property | 23 | pass |
| Backend integration | 396 | pass |
| Backend contract | 82 | pass |
| Backend workflows | 65 | pass |
| Backend API | 82 | pass |
| Backend eval | 19 | pass |
| Backend total | 1,408 (3 live tests deselected) | pass |
| Frontend unit | 599 | pass |
| E2E, fixtures | 114 | pass |
| E2E, full stack | 40 | pass |
| Lighthouse | 4 desktop routes, 1 mobile | pass (desktop Performance 99–100, Accessibility 98–100; mobile 89–92) |
| Spec coverage | A 106/106, B 91/91, C 57/57 | no gaps |

One run takes about 10.5 minutes. The three summaries are in `BUILD-LOG.md` (W10, 18 Oct 2026).

Coverage: backend 88% of 22,497 statements (all levels together). Frontend unit tests cover 66% of the lines in
`components/` and `lib/` (2,788 of 4,207); the PROMPT 9 target of 80% is not met. Lowest by folder:
`lib/api` 8% (endpoint wrappers and the server fetch), `components/settings` 24%, `inbox` 27%, `replay` 28%,
`shell` 41%, `lib/hooks` 43%, `graph` 43%; these screens are exercised by the two e2e suites rather than unit tests.
Highest: `core`, `stream`, `format`, `ui` 97–99%, `connect` 86%, `events` 85%.
