# Architecture

## Components

| Component | What it does | Code |
|---|---|---|
| Frontend | Next.js app. The browser calls same-origin `/api`; Next.js forwards to the backend. | `frontend/` |
| Backend API | FastAPI: requests, approvals, connectors, SSE stream, health. | `backend/actron/api/` |
| Worker | Temporal worker on four task queues: `ingest`, `link`, `request`, `build`. Starts Pi and test containers through the Docker socket. | `backend/actron/worker.py`, `workflows/`, `activities/` |
| FalkorDB | The knowledge graph, one graph per workspace (`actron_<workspace>`). | `graph/store.py`, `graph/ontology.py` |
| PostgreSQL | Application state: users, workspaces, connections with encrypted secrets, sync cursors and runs, requests, ticket revisions, approvals, build runs, the event journal, notifications, model call records. Also holds the Temporal databases. | `db/` |
| Redis | Fan-out for server-sent events, idempotency keys, sessions, rate counters, model cache. | |
| Temporal | Durable workflows: ingestion, linking, the request flow with its waits for answers and approvals, builds, schedules for incremental sync. | `workflows/` |
| Backup | Nightly `pg_dump` of `actron` and `temporal`. | `infra/postgres/backup.sh` |

## Data flow

1. A connector (code, GitHub, Slack, Linear) is connected. A Temporal workflow per source pulls pages in activities and writes them through `GraphStore.upsert_nodes` and `upsert_links` (MERGE on `id`, batches of about 500). Cursors and run records go to PostgreSQL.
2. Linking activities add links between sources (explicit references, identities, meaning links) and decisions. Links carry `method` and `confidence`.
3. A request arrives (UI or Slack). `RequestWorkflow` classifies it, calls the investigator, which reads the graph through query tools and returns findings with evidence. Questions, the ticket draft, approvals, the build and the PR follow. Every step writes an event to the PostgreSQL journal (gap-free `seq` per request, `actron.db.events_seq`) and publishes it on Redis for the browser.
4. Build runs in a Docker container with Pi; the worker reads the result, checks the diff and opens a PR against the configured fork.

## Why each store exists

- **FalkorDB** holds what the agent reasons over: connected facts, paths and graph algorithms (PageRank, shortest path, traversals). It holds no secrets and no workflow state.
- **PostgreSQL** is the system of record for anything that needs transactions or must not be visible to the agent: encrypted connector secrets, approvals, the journal. Temporal also needs it.
- **Redis** is only for short-lived coordination. Losing it loses no data; PostgreSQL has the journal and an idempotency table as fallback.
- **Temporal** keeps long waits and retries out of application code. Waiting is free and survives restarts.

## Platform rules (W1)

- Settings are validated once at start. A bad value stops the process with a message naming the variable. Empty keys mean stub or not connected (`Settings.integrations()`).
- Logs are JSON. A redactor removes configured secrets and known token shapes.
- Secrets at rest use Fernet (`ACTRON_SECRET_KEY`); the API only exposes the last four characters.
- The graph store validates labels and relationship names against the ontology before putting them in Cypher, binds values as parameters (or through the literal binder), halves a batch when it times out (down to 50 rows), and never creates a node when linking (missing endpoints are reported).
- Edits keep history (`graph/versions.py`): the old state is copied to `<id>@v<n>` and linked, newest first. Deletes are tombstones (`deleted`, `deletedAt`); queries filter with `not_deleted()`.
- Ids are built in one place (`graph/ids.py`) and never contain line numbers.
- FalkorDB limits that shape the code are in `docs/falkordb.md`; the graph content is in `docs/graph-model.md`.
