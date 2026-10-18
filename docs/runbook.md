# Runbook

How to set up, run, check and recover Actron on one machine. Written by W1 (platform) on 17 Oct 2026.

## Setup

1. Install Docker (with Compose), `uv`, Node 22.19 or newer.
2. `cp .env.example .env`. Generate the two secrets once:
   - `ACTRON_SECRET_KEY`: `python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
   - `SESSION_SECRET`: any long random string.
   Every other value may stay empty. Empty means "stub" or "not connected", never a crash.
3. `make up-deps` starts FalkorDB, PostgreSQL, Redis, Temporal and the Temporal UI. `make up` starts everything, including backend, worker, frontend, backup, and builds the Pi and test-runner images.
4. `make health` calls `/api/health`. Stores report `ok` or `error`; integrations report `live`, `stub` or `not_connected`.
5. Backend tests: `cd backend && uv run pytest -q`. Everything: `scripts/test_all.sh`.

## Pinned images and Temporal settings

| Service | Image | Host port |
|---|---|---|
| falkordb | `falkordb/falkordb:v4.22.1` | 6389 |
| postgres | `postgres:16.15` | 5433 |
| redis | `redis:7.4.11` | 6380 |
| temporal | `temporalio/auto-setup:1.29.7` (newest tag that still ships auto-setup) | 7233 |
| temporal-ui | `temporalio/ui:2.56.0` | 8233 |
| backup | `postgres:16.15` | none |
| backend, worker | `actron-backend:dev` (built from `infra/docker/backend.Dockerfile`) | 8080 |
| frontend | `actron-frontend:dev` (`infra/docker/frontend.Dockerfile`) | 3000 |

Temporal environment names, read from the image's `/etc/temporal/auto-setup.sh`: `DB=postgres12`, `DB_PORT`, `POSTGRES_SEEDS`, `POSTGRES_USER`, `POSTGRES_PWD`, `DBNAME`, `VISIBILITY_DBNAME`, `SKIP_DB_CREATE`, `DEFAULT_NAMESPACE`, `DEFAULT_NAMESPACE_RETENTION`. The databases `temporal` and `temporal_visibility` are created by `infra/postgres/init.sql`, so `SKIP_DB_CREATE=true`. Namespace `actron` is registered at start (retention 168h). Verified live: the namespace exists and a smoke workflow runs on it (`tests/integration/test_temporal_smoke.py`).

FalkorDB settings are in `infra/compose.yaml` (`THREAD_COUNT 8 TIMEOUT_MAX 60000 TIMEOUT_DEFAULT 15000 MAX_QUEUED_QUERIES 2000 RESULTSET_SIZE 10000`, append-only on). `tests/integration/test_falkordb_config.py` checks them with `GRAPH.CONFIG GET`.

## FalkorDB binding mode (A4)

Mode in use: **params** (`FALKORDB_BINDING=params`, reported as `falkordb_binding` in `/api/health`). The persistence regression guard passed on v4.22.1: tricky values written with query parameters survive a restart unchanged, in both modes. To switch, set `FALKORDB_BINDING=literal` and restart backend and worker. Details and the literal binder's escaping rules are in `docs/falkordb.md` (limitation 6).

## Warning: never delete a graph that has unique constraints

On FalkorDB v4.22.1, deleting such a graph makes the server crash on the second restart after that (limitation 12 in `docs/falkordb.md`, with the recovery steps). Unique id constraints are on by default and off when `ACTRON_ENV=test`. Do not run `docker compose restart falkordb` in a shared development stack after test runs from an older checkout; check `docker logs actron-falkordb-1` for `crashed by signal` first.

## Environment variables

Defaults are in `backend/actron/config.py`; `.env.example` is the list to copy. Names only, no values.

| Group | Variables |
|---|---|
| App | `ACTRON_ENV` (dev, prod or test), `ACTRON_SECRET_KEY`, `SESSION_SECRET`, `ACTRON_HOST`, `ACTRON_PORT`, `ACTRON_PUBLIC_URL`, `ACTRON_ONTOLOGY_DIR`, `ACTRON_LOG_LEVEL`, `ACTRON_VERSION` (set by the image build) |
| Stores | `DATABASE_URL`, `REDIS_URL`, `FALKORDB_URL`, `FALKORDB_GRAPH_PREFIX`, `FALKORDB_BINDING`, `FALKORDB_UNIQUE_CONSTRAINTS`, `FALKORDB_PORT`, `POSTGRES_PORT`, `REDIS_PORT` |
| Temporal | `TEMPORAL_ADDRESS`, `TEMPORAL_NAMESPACE`, `TEMPORAL_UI_PORT`, `TEMPORAL_PORT` |
| Slack | `SLACK_BOT_TOKEN`, `SLACK_SIGNING_SECRET`, `SLACK_APP_TOKEN`, `SLACK_CHANNELS`, `SLACK_CLIENT_ID`, `SLACK_CLIENT_SECRET`, `SLACK_API_URL` |
| GitHub | `GITHUB_TOKEN`, `GITHUB_REPOSITORY`, `GITHUB_FORK`, `GITHUB_UPSTREAM`, `GITHUB_WEBHOOK_SECRET`, `GITHUB_API_URL` |
| Linear | `LINEAR_API_KEY`, `LINEAR_TEAM_ID`, `LINEAR_API_URL` |
| Models | `TYPESAFE_API_KEY`, `JEV_MODEL`, `JEV_API_URL`, `ANTHROPIC_API_KEY`, `OPENROUTER_API_KEY`, `GEMINI_API_KEY`, `GROQ_API_KEY`, `MODEL_DECISION`, `MODEL_WRITING`, `MODEL_AGENT`, `MODEL_CODING`, `LITELLM_FALLBACKS`, `LINK_KEEP_THRESHOLD`, `CONFLICT_THRESHOLD`, `POSSIBLE_CONFLICT_THRESHOLD` |
| Build with Pi | `ACTRON_MAX_CONCURRENT_BUILDS`, `ACTRON_BUILD_TIMEOUT_SECONDS`, `ACTRON_MAX_REPAIRS`, `ACTRON_DAILY_MODEL_BUDGET_USD`, `ACTRON_BUILD_HOST_DIR`, `ACTRON_PI_IMAGE`, `ACTRON_TEST_RUNNER_IMAGE`, `ACTRON_MCP_URL`, `ACTRON_MCP_PORT`, `ACTRON_BOT_NAME`, `ACTRON_BOT_EMAIL` |
| Ingestion | `ACTRON_CLONE_DIR`, `ACTRON_BACKFILL_DAYS`, `ACTRON_GIT_HISTORY_DEPTH` |
| Frontend | `API_INTERNAL_URL`, `NEXT_PUBLIC_ACTRON_DEV_FIXTURES`, `FRONTEND_PORT` |
| Tests only | `ACTRON_TEST_REDIS_DB` (Redis database for a test run, default 15) |

An invalid value stops the backend at start with a message that names the variable (A-AC-2).

`API_INTERNAL_URL` is read when the frontend image is built (Next.js bakes the `/api` rewrites in), so it is a build argument of `frontend.Dockerfile` (default `http://backend:8080`).

## Images

- Backend image: `docker build -f infra/docker/backend.Dockerfile -t actron-backend:dev .` from the repository root. Check: `docker run --rm actron-backend:dev python -c "import actron.config"`. It contains `git` and the Docker CLI. It runs as user `actron`, except when `/var/run/docker.sock` is mounted (the worker), which stays root so it can use the socket and write the host build directory.
- Docker here builds without BuildKit, so the Dockerfiles avoid BuildKit-only syntax.
- The repository root `.dockerignore` keeps `.env`, `.git`, `node_modules` and virtual environments out of the build context.

## Operations

- Logs: JSON lines on stdout (`level`, `msg`, `ts`, `request_id` or `workflow_id`). Secrets are replaced by `[REDACTED]`. `make logs` follows all services.
- Schedules (incremental sync): `actron.workflows.schedules` has `ensure_schedule`, `trigger_schedule`, `pause_schedule`, `unpause_schedule`, `delete_schedule`. Schedule id is `sync-<workspace>-<source>`. Overlap policy is SKIP. The Temporal UI is on port 8233.
- Migrations: `cd backend && uv run alembic -c actron/db/alembic.ini upgrade head` (the backend container does this at start). Down to empty and back up is tested.
- Event sequence numbers: `actron.db.events_seq.next_seq` locks the request row, so concurrent writers get 1, 2, 3 with no gaps.
- Settings check without starting anything: `uv run python -c "from actron.config import get_settings; get_settings()"` prints the offending variable or nothing.

## Backups and restore

The `backup` service runs `infra/postgres/backup.sh` every `BACKUP_INTERVAL_SECONDS` (86400), dumps the `actron` and `temporal` databases into volume `pg-backups` and keeps `BACKUP_KEEP_DAYS` (7) days.

- List: `docker compose -f infra/compose.yaml exec backup ls -l /backups`
- Restore `actron`: stop backend and worker, then
  `docker compose -f infra/compose.yaml exec -T postgres psql -U actron -d postgres -c "DROP DATABASE actron WITH (FORCE)" -c "CREATE DATABASE actron"`
  and pipe the dump in: `docker compose -f infra/compose.yaml exec -T backup sh -c 'gunzip -c /backups/<file>' | docker compose -f infra/compose.yaml exec -T postgres psql -U actron -d actron`
  (use `pg_restore` instead if the file is a custom-format dump; check the file name ending). Start the services again.
- FalkorDB: its append-only file lives on volume `falkor-data`. Back it up by copying that volume while the container is stopped. The graph can also be rebuilt by re-running ingestion.
- The restore steps above were not exercised in W1 (the backup service belongs to the lead and W6; `tests/integration/test_backup.py` is W6's).

## Scripts

`scripts/check.sh` (ruff, mypy, frontend typecheck and lint, spec coverage), `scripts/test_all.sh` (all test levels with a summary), `scripts/live_smoke.sh` (live tests for providers whose key is in `.env`), `scripts/gen_types.sh` (OpenAPI to TypeScript types), `scripts/deploy.sh` (build, migrate, start `infra/compose.prod.yaml`, health check; the production compose file is not written yet), `scripts/gen_graph_model.py` (writes `docs/graph-model.md`).

## What was verified live (W1, 17 Oct 2026)

- Against the running stack: health probes for all four stores, `GRAPH.CONFIG GET` values, migrations up/down/up on a fresh database, secrets in a real `pg_dump`, 50 concurrent event writers gap-free, store upserts, versions, tombstones, workspace isolation, indexes.
- Persistence across a restart of a FalkorDB container of the pinned image (a throwaway container, not the shared service).
- A smoke workflow in the time-skipping environment and on the real server (namespace `actron`), and schedule helpers (create, update, trigger, pause, SKIP overlap) on the real server.
- The backend image builds, imports `actron.config`, finds the ontology and runs the migrations against PostgreSQL.
- Not verified: the frontend image (its lock file was out of sync with `package.json` when tried), `scripts/deploy.sh`, `scripts/gen_types.sh` (no backend app yet), `make up` with every service.

## Pi

Section owned by W8. Everything below was run inside the built image on 17 Oct 2026, unless it is marked unverified.

**Image.** `docker build -f infra/docker/pi.Dockerfile -t actron-pi:latest .` from the repository root. Python 3.12.15 base, Node 22.23.3 copied from the official image, git, ripgrep, OpenJDK 17, pytest. Pi is `@earendil-works/pi-coding-agent@1.3.0`, installed with `npm install -g --ignore-scripts`. Pi runs as uid 1000. This Docker has no BuildKit (`docker buildx` is missing), so the Dockerfile does not use heredocs. The entry wrapper is written with `printf`.

**Entry wrapper** (`/usr/local/bin/actron-pi-entry`). It sets `PI_CODING_AGENT_DIR=/tmp/pi-agent` (tmpfs), `PI_SKIP_VERSION_CHECK=1` and `PI_TELEMETRY=0`. When `ACTRON_MCP_URL` is set, it writes `mcp.json` with server `actron`, `url`, header `X-Actron-Run: ${ACTRON_RUN_TOKEN}` and exposure `direct`. Pi reads the token from the environment, so it is never written to disk. When `ACTRON_PI_BASE_URL` is set, it also writes a custom `models.json` provider. That path has not been run. Then it runs `exec pi "$@"`.

**Verified**
- `docker run --rm actron-pi:latest --version` prints `1.3.0`. `--help` lists `--mode <mode>`, `--print`, `--session-dir`, `--session-id`, `--append-system-prompt`, `--no-approve`, `--offline`, `--list-models` and `--tools`.
- Providers are checked with a dummy key and `--offline --list-models <search>`. The LiteLLM prefix maps to the Pi provider and key like this: `anthropic/…` uses `anthropic` and `ANTHROPIC_API_KEY`. `openrouter/…` uses `openrouter` and `OPENROUTER_API_KEY`. `gemini/…` uses `google` and `GEMINI_API_KEY`. `groq/…` uses `groq` and `GROQ_API_KEY`. Pi is called with `--model <provider>/<id>`.
- JSON mode is `--mode json`. The first record is `{"type":"session","id":…}`. After it come `agent_start`, `turn_start`, `message_start/end`, `tool_execution_start/end` (`toolName`, `args`), `turn_end`, `agent_end` and `agent_settled`. Usage is in `message_end.message.usage.{input,output}`.
- `--append-system-prompt /context/TASK.md` reads the file. Its text appears in the system message's `addendum` section. This is how the work protocol reaches Pi.
- Sessions: `--session-dir /session --session-id actron-<buildId>` creates `/session/<time>_actron-<buildId>.jsonl`. It prints the warning "No project session found…; creating" on stderr. A second run with the same id appends to the same file, so the session is resumed. Repair attempts use this.
- MCP over HTTP: a probe streamable-HTTP MCP server (Python `mcp` 2.x `MCPServer`) ran on the host. Running `pi mcp list --json` in the container with `ACTRON_MCP_URL` and `ACTRON_RUN_TOKEN` gave `state: connected`, `exposure: direct` and the probe's tool. The server received `x-actron-run: <token>`. Tools appear to the model as `mcp__actron__<tool>` (Pi docs).
- Pi exits 0 even when every model call fails. Failures show as `message_end` with `stopReason: "error"`, `errorMessage`, and retries (`auto_retry_start/end`). The build treats an attempt with only error turns and no tools as `model_error`.
- The container works with `--read-only --tmpfs /tmp --user 1000:1000`.

**Not verified: a real prompt.** No model key is in `.env`. Pi starts, loads the prompt and session, and fails the model call (`Connection error.` with `--network none`). `tests/live/test_pi_live.py::test_trivial_prompt_with_model_key` runs once `MODEL_CODING` and its key are set.

**Command line used by the build** (`actron.flow.build.pi_docker_command`):
```
docker run --rm --name actron-pi-<buildId> --network actron-build --cpus 2 --memory 4g --pids-limit 512 \
  --read-only --tmpfs /tmp --user <uid>:<gid> -w /work \
  -v <build>/repo:/work -v <build>/context:/context:ro \
  -v <build>/context/notes.md:/context/notes.md -v <build>/context/REPORT.json:/context/REPORT.json \
  -v <build>/context/STOP.md:/context/STOP.md -v <build>/session:/session \
  -e <ONE_MODEL_KEY_NAME> -e ACTRON_MCP_URL=http://worker:8765/mcp -e ACTRON_RUN_TOKEN \
  actron-pi:latest --mode json --no-approve --model <provider>/<id> \
  --session-dir /session --session-id actron-<buildId> --append-system-prompt /context/TASK.md \
  "Follow /context/TASK.md exactly. Start with step 1."
```
Secret values (the model key and the run token) are passed by name only. Their values are set only in the docker CLI's own environment. Additions to the B9 flags:
- `--user`, so files in the bind-mounted checkout keep the worker's owner.
- `-w /work`.
- File bind mounts that make `notes.md`, `REPORT.json` and `STOP.md` writable inside the read-only `/context`.
- `/session`, so repair attempts can resume.

A Pi write that replaces a file by rename would fail on those file mounts. Unverified: Pi's `write` and `edit` tools may rewrite files in place. `--no-approve` ignores project-local `.pi/` settings and extensions in the target repository.

**Egress.** `actron-build` is a normal bridge network (compose). Egress is not filtered to the model provider and the MCP server. This limitation is recorded, not solved.

**Test runner image.** `docker build -f infra/docker/test-runner.Dockerfile -t actron-test-runner:latest .` contains Node 22.23.3, Python 3.12.15, OpenJDK 17.0.20, Clojure CLI 1.12.6.1673, pnpm 9.15.9 and pytest 8.4.2, with user `runner` (uid 1000). It has no headless VS Code libraries: Calva's unit tests run in plain Node.

**Fake Pi for tests.** `backend/tests/fakes/fake_pi/` builds the tiny image `actron-fake-pi:test`, which the test session builds in a few seconds. It is started through exactly the same `docker run` command. The scenario comes from `FAKE_PI_SCENARIO`, set through `BuildEnv.pi_extra_env`, which is for tests only.
