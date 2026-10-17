# Reproduce Actron locally

Actron implements the scoped Slack → Linear → isolated worker → GitHub workflow. The
local contract demo uses real FalkorDB, git commits, and subprocess checks; its
Slack, Linear, GitHub, coding patches, and authorizations are labelled simulations.
The live commands use real provider APIs and require your dedicated resources and
credentials. No live deployment or successful model comparison is claimed
by the source tree. A reproducible video replay captures the observed local contract flow. This implementation was produced with AI coding assistance.
The selected implementation track is the local Python/FalkorDB proof of concept;
no external competition track selection has been inferred.

## Fresh local setup

Requires Python 3.12+, uv, git, and Docker with Compose. These commands use only
local synthetic sources and a dedicated graph. Port 6389 avoids a common Redis
port collision; override FALKORDB_PORT and FALKORDB_URL together if needed.

```bash
uv sync --group dev
cp .env.example .env
set -a
source .env
set +a
docker compose up -d --wait
docker compose exec falkordb redis-cli ping
uv run actron populate
uv run actron ingest
uv run actron demo
```

`populate` copies only `demo/repository`, creates a real git baseline, and writes
`.actron/demo/manifest.json` and `sources.json`. Synthetic Slack/Linear histories
then pass through the same FileSources fetch and Ingestor boundary as other source
adapters. Repeating `populate` preserves an existing clean repository; after a
committed source change it produces a fresh immutable snapshot. Repeating `ingest`
deduplicates revisions. The fictional people, current approved Finance rules,
unapproved Linear revisions, PR/review history and curated code map live in
`demo/sources`. Historical approval metadata is fixture evidence and never grants
runtime authorization. Future stimuli and hidden acceptance checks live exclusively
in `demo/evaluator`; neither population nor default ingestion reads that directory.
`actron ingest` rejects paths under an evaluator directory.

Inspect the actual generated base and evidence without copying an example SHA:

```bash
uv run python -c 'import json,subprocess; m=json.load(open(".actron/demo/manifest.json")); subprocess.run(["actron","investigate","--project",m["project"],"--behavior",m["behavior"],"--repo",m["repository"],"--base",m["base"]],check=True)'
```

`actron demo` runs the real graph/disposable-repository workflow contract tests.
They cover investigation/clarification, exact ticket approval, real implementation
and checks, PR revisions, current-head merge gates, duplicate delivery, lost-write
reconciliation, source availability and subsequent scoped decision reuse. The
signed HTTP seam is tested separately in `tests/test_ingress.py`, including durable
acceptance, identity tampering, expiry, nested scope validation, restart dispatch
and an end-to-end signed approval that launches the actual local worker.

Run verification with `scripts/check.sh`. Tests require a reachable FalkorDB;
`ACTRON_REDIS_URL` can override the default test URL `redis://127.0.0.1:6389/0`.
Application configuration uses FALKORDB_URL. These deliberately separate the test
transport URL from the runtime graph name. Test graphs are isolated by random IDs.

## Configure a real model and isolated worker

Build both images before starting work, so validation needs no network access:

```bash
docker pull python:3.12-slim
docker build -f docs/coding.Dockerfile -t actron-coding .
```

Set OPENAI_API_KEY and ACTRON_MODEL in `.env` to your API key and an explicitly
chosen accessible model ID. No model is guessed. The included adapter uses the
[OpenAI Responses API](https://developers.openai.com/api/docs/guides/structured-outputs)
and [input token counting](https://developers.openai.com/api/docs/guides/token-counting)
to bound total input/output usage and return actual usage with a patch. The default
ACTRON_CODING_COMMAND invokes this adapter inside `actron-coding`. A different
real coding CLI can implement the same stdin JSON / stdout JSON contract. Model
credentials are explicitly named in ACTRON_CODING_ENV; provider/workflow credentials
are refused by the worker, apart from the nonsecret ACTRON_MODEL selector.

The coding container mounts only a disposable checkout read-only, gets model
credentials, and can contact the model provider. The validation container has no
network, read-only filesystem/checkout, capped resources, no capabilities, and no
credentials. The coordinator applies validated patches, preserves existing tests
and control files, records exact tested commits/output, and retains artifacts under
ACTRON_ARTIFACTS. Host execution is reserved for explicitly trusted local contract
fixtures. A Docker boundary is required for the connected runtime.

## Connect dedicated live demo sources

Create an empty dedicated GitHub repository, a dedicated Linear team, and a private
Slack demo channel. Configure GITHUB_REPOSITORY and ACTRON_DEDICATED_REPOSITORY to
the same owner/name. Configure LINEAR_TEAM_ID, ACTRON_DEMO_CHANNEL and ACTRON_DEMO_USER
with actual immutable provider IDs. This is one explicit POC identity binding;
there is no role system or inference from job titles.

The Slack app needs a bot with `chat:write`, permission to read the configured
channel/thread (`channels:history` or `groups:history` as applicable), access to
message metadata, slash command `/actron`, and interactivity enabled. Invite the app
to the channel. Thread retrieval may require an appropriate user token/scopes for
the workspace/channel type; an unsupported token fails explicitly instead of
substituting fixtures. Supply SLACK_BOT_TOKEN and SLACK_SIGNING_SECRET. Linear needs
a key that can read/create/update issues in the dedicated team. GitHub needs repo
contents and PR write access, checks/status/review reads, and merge permission.
Preconfigure git authentication for the dedicated remote; tokens never appear in
a command-line remote URL. Configure branch protection and required check names
(the fixture workflow job is `suite`) and at least one approving review as desired.

Read provider identities, then explicitly populate live sources:

```bash
uv run actron live-smoke
uv run actron populate-live --live --channel "$ACTRON_DEMO_CHANNEL" --team "$LINEAR_TEAM_ID" --repository "$ACTRON_DEDICATED_REPOSITORY"
uv run actron ingest --source .actron/live/live-sources.json
```

`populate-live` requires all three explicit resource arguments to match the demo
environment. It pushes only into an empty dedicated repository (or accepts this
exact existing baseline), posts synthetic history to a real Slack thread, creates
and revises a Linear issue, then fetches Slack/Linear/GitHub content through the
live source adapters. `.actron/live/live-writes.json` records confirmed operations.
An uncertain write stops retry: inspect the provider before manually reconciling
the local ledger. This prevents an unacknowledged Slack post being silently repeated.
The workflow's historical PR source example remains explicitly illustrative; live
workflow PRs/reviews/checks are observed from actual GitHub when created.

For an additional isolated write smoke:

```bash
uv run actron live-smoke --live --write --channel "$ACTRON_DEMO_CHANNEL" --team "$LINEAR_TEAM_ID" --operation reviewer-1
```

The smoke creates/reuses its deterministic Linear issue and posts a labelled Slack
message. Each explicit smoke invocation can post another message. It does not
prove an implementation or authorize a merge. Live source population, model calls,
and smoke writes have not been run unless results are recorded separately.

## Start the signed Slack workflow

Set ACTRON_REPOSITORY to `.actron/live/repository`'s absolute path or the authenticated
dedicated GitHub remote. The snapshot's repo identifier for live sources is
GITHUB_REPOSITORY (owner/name), distinct from the worker clone location. Re-load
`.env`, expose the runtime through an HTTPS forwarding proxy, and configure both
the slash command and interaction Request URL to `https://your-host/slack`.

```bash
uv run actron run
curl --fail http://127.0.0.1:8080/health
```

The server validates the [Slack signature over raw bytes and a five-minute timestamp
window](https://docs.slack.dev/authentication/verifying-requests-from-slack/), validates
a bounded command schema, and saves an Inbox record before acknowledging. Graph
failure returns HTTP 503. Root threads use a durable deterministic client_msg_id and request metadata; a bounded, complete
channel-history lookup reconciles uncertain creation. If a prior uncertain message
is still absent, recovery pauses instead of posting again. The operator must
inspect provider visibility before reconciling the journal. A background single consumer dispatches queued work and
drains interrupted entries after restart. No provider credentials or response URLs
are persisted in the inbox. An exact approved ticket produces a durable execution
handoff; the dispatcher starts it automatically, including after restart.

Send commands in the bound channel, substituting owner/name and the full base SHA
from `.actron/live/manifest.json`:

```text
/actron request {"project":"atlas","behavior":"report_export","repo":"owner/dedicated-demo","base":"FULL_SHA","text":"Allow project admins to export reports"}
/actron clarify {"request":"REQUEST_ID","text":"Own project members only; invoices stay Finance-only.","scope":{"membership":"owning-project-only","acceptance":["Allow report exports only if project is in both projects and admin_projects","Preserve Finance exports for their own projects","Deny invoice exports to project admins","Deny cross-project and nonmember exports"]}}
```

Inspect the Linear revision and click **Approve this revision** in Slack. Plain
chat, quoted text, or a slash command cannot approve. Approval binds request,
revision and scope hash. The worker runs and reports actual checks, then opens a PR.
Review through the thread with the actual current PR ID/head:

```text
/actron review {"request":"REQUEST_ID","pr":"PR_ID","head":"CURRENT_HEAD_SHA","text":"Keep the reports exception local; improve the explanation without weakening existing tests."}
/actron status {"request":"REQUEST_ID"}
```

After reviewing the new diff and approving its current commit in GitHub, wait for
required checks and click **Authorize this head**. The separate merge button binds
request, exact ticket revision/hash, PR and head. A stale head or missing/currently
failing checks/reviews blocks merge. A successful merge is confirmed by GitHub
before the scoped decision is ingested. A later investigate/request can retrieve
that decision while invoices retain their independent constraint.

To revise scope, use `/actron revise` with request, optional text, and a scope
object containing objective/acceptance/constraints/unresolved/membership; renewed
approval is required. Check commands, components, provider identity and base cannot
be supplied through scope. `/actron repair` supplies request and optional text for
bounded within-scope repairs; `/actron recover` reconciles existing operations.
`/actron investigate` accepts the same new-request identifiers, or an existing
request ID, for a read-only evidence inspection.

## Refresh, failure and restart checks

- Edit a Slack source or the synthetic Linear issue, then run `actron refresh-live`.
  Source adapters retain explicit mapping/provenance and observe provider revisions.
  To represent confirmed deletion/access loss, create a new source revision with
  availability `unavailable` through the file connector; do not infer absence from
  a timeout. Connector coverage limits remain visible.
- Commit and push a code change, then `actron refresh-live --ref main`; investigate
  with the new exact SHA. Old-base approval cannot execute against new evidence.
- Re-deliver identical signed inputs (within the timestamp window); the immutable
  trigger identity resolves to the same inbox event. Reusing an event with changed
  content cannot grant different workflow authority.
- Stop the runtime after durable acceptance, restart it, and inspect the same request,
  events, Handoff and operations. Provider writes with unknown outcomes reconcile
  by operation identity; unsupported certainty pauses instead of starting new work.
- Stop FalkorDB: readiness returns 503 and acceptance fails. Restore it; queued work
  remains in the persistent volume. Never replace graph evidence with fake answers.
- Try a previously rendered ticket or merge button after revising scope/head; inspect
  the rejection and current revision. No old authorization is transferred.

Exactly one runtime owns a graph. Runtime/request locks intentionally have no TTL.
After an unclean process death, verify all old runtimes/workers are dead and inspect
pending operations before removing only the corresponding stale Redis lock key
`actron:GRAPH:lock:runtime` (or the affected request lock) with redis-cli. Retain
unknown provider/worker operation records; do not erase them to force retry. Normal
shutdown releases ownership. Named Docker volumes survive container recreation;
`docker compose down -v` explicitly destroys that local state.

## Fair context comparison

Populate/ingest first, configure the real model/image, then:

```bash
uv run actron evaluate --manifest .actron/demo/manifest.json --output .actron/evaluations/run-1
```

All three variants use the same explicitly selected model, exact git base, full
preserved suite, tools, time/attempt/token budgets and initial request. Only evidence
changes: request alone, full available source history, or the graph investigation
packet. Comparison builds a fresh graph from historical connector sources, so
merged outcomes in a runtime graph cannot leak future answers. Each variant
receives a new disposable checkout. The evaluator-only acceptance
script runs inside the isolated runner after coding and never enters model context.
It checks requested report behavior, independent invoices, project membership and
cross-project denials. `contexts.json` and `results.json` retain context, every
variant outcome, real check output/commit, elapsed time and reported model usage.
No successful baseline is hidden. Source-path/clarification quality fields remain
unscored until reviewed by a person. A model request for clarification is recorded
as scope_revision, not fabricated as implementation success. No scores are shipped
because a live model comparison has not been observed. Three runs of one synthetic
scenario support only that concrete result, not general regression-prevention claims.

## Inspectable ontology and limits

Ontology `actron-ontology-v1` uses explicit project/behavior IDs, immutable
SourceRevision envelopes, scoped Claim/decision approval provenance, curated
Snapshot/Component/Check mappings, and Request/Clarification/Revision/Approval/
Operation/ValidationRun/PR outcomes. The map's fixed-point traversal follows known
caller/callee edges to expose invoices through the shared helper. Dynamic calls,
unconfigured files, uncertain identities, complete pre-import provider history,
general arbitrary-repository understanding and detailed role permissions remain
outside this POC. Scope mapping is deterministic curated extraction; no model
invented approval is accepted as current policy.

Useful FalkorDB queries (JSON envelopes are in `n.payload`):

```cypher
MATCH (n:Record {kind:'Request'}) RETURN n.key,n.payload;
MATCH (n:Record {kind:'Operation'}) RETURN n.key,n.payload;
MATCH (n:Record {kind:'SourceRevision'}) RETURN n.key,n.payload;
MATCH (c:Record {kind:'Claim'})-[r:SUPPORTED_BY]->(s:Record)
RETURN c.key,s.key,r.provenance;
MATCH (s:Record {kind:'Snapshot'})-[r:CONTAINS]->(c:Record)
RETURN s.key,c.key,r.provenance;
```

The setup, source code and executable contract demo are the reproducible local
handoff. Generate a captured local demonstration video and self-contained HTML
replay with `uv run python scripts/record_demo.py` (requires ffmpeg/drawtext and
DejaVu Sans Mono). It runs `actron demo`, requires the complete passing observed
trace, and renders actual phase, revision, commit and check progression. Outputs
are `.actron/demo.mp4`, `.actron/demo.html`, `.actron/demo.trace.json` and the full
captured stdout. Every frame labels real DB/git/checks and simulated providers/
coding authority. No externally accessible deployment has been produced.
