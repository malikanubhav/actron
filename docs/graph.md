# Graph persistence, source inventory, and ontology

This implementation uses Python 3.12+, redis-py and FalkorDB. This is a concrete
POC implementation choice, not a claim that the original specification selected
these schema names, extraction rules or concurrency semantics. Start the local
FalkorDB service with the repository startup script; set `ACTRON_REDIS_URL` for a
nondefault port. The integration tests use a real server at port 6389 by default.

FalkorDB is the primary durable store. Every entity is a `Record` node with
`kind`, `key` and canonical JSON `payload` properties. Source contents, immutable
source revisions, mapped claims, code snapshots, workflow requests, approvals and
operations all remain in the graph; Redis keys are used only for coordination.
Restart persistence relies on the pinned FalkorDB 4.12.0 container's mounted data
volume and `REDIS_ARGS="--appendonly yes"` configuration. Redis configuration must
be checked at runtime: the image startup script does not apply arbitrary Compose
command arguments as Redis options. `scripts/check_persistence.py` was run with
Python 3.12.3 against a dedicated real container and confirmed AOF enabled, the
configured data directory inside its volume, and the same stored graph record
after removing and replacing the container while retaining that volume. This
does not establish backup recovery or production HA guarantees. Use separate
graph names for tests and replay runs;
never import future events, golden patches or evaluator answers into the live
investigation graph.

Ontology `actron-ontology-v1` uses explicit stable project and behavior IDs:

| Record kind | Identity and meaning |
| --- | --- |
| Source | Provider plus stable source ID; points to current observed revision and availability |
| SourceRevision | Provider, source ID and immutable revision; full content, hash, locator, timestamps and mapping version |
| Claim | Revision-scoped explicit claim ID, behavior, text, certainty, extraction method and approval metadata |
| HistoricalApproval | Source approval evidence; explicitly historical and incapable of approving a live workflow |
| Behavior | Explicit project and behavior identity; names alone never establish equivalence |
| Snapshot | Repository plus immutable commit, explicit component/check map and coverage limits |
| Component / Check | Snapshot-scoped code/test identity and curated or extracted provenance |
| Import | Durable connector cursor, completion status and gaps |
| Outcome | Confirmed merged scoped decision with request, exact revision, PR, head and evidence |

Relationships include `HAS_REVISION`, `REVISES`, `SUPPORTS_BEHAVIOR`, `SUPPORTED_BY`,
`APPLIES_TO`, `APPROVES`, `CONTAINS`, `IMPLEMENTS`, `CALLS` and `VERIFIES`. Edges
retain JSON provenance including source revision, extraction method, mapping
version and commit where relevant. An immutable envelope is rejected if the same
source revision or commit is supplied with different content. Code relationship
keys include their commit; current investigations select one complete snapshot.
Static call traversal is bounded at eight expansion rounds and explicitly does
not resolve dynamic calls. Unknown/missing symbol targets remain unproven edges.

Examples of inspection queries (run using `GRAPH.QUERY actron '<query>'`):

```cypher
MATCH (n:Record {kind:'SourceRevision'}) RETURN n.key,n.payload
MATCH (a:Record {kind:'Claim'})-[r:SUPPORTED_BY]->(s:Record)
RETURN a.key,s.key,r.provenance
MATCH (s:Record {kind:'Snapshot'})-[:CONTAINS]->(c:Record)
RETURN s.key,c.kind,c.key
MATCH (c:Record {kind:'Component'})-[r:CALLS]->(target:Record)
RETURN c.key,target.key,r.provenance
MATCH (n:Record {kind:'Operation'}) RETURN n.key,n.payload
```

Application queries bind data values and validate dynamic relationship names.
Pinned FalkorDB 4.12.0 was observed to corrupt parameter-prefixed write commands
in AOF: a submitted `CYPHER kind=...` command was recorded as `CYPHER kind`, and
replay could not reconstruct its graph nodes. The store therefore binds
JSON-escaped scalar/list literals into trusted query templates with one regex
substitution pass, requiring an exact match between template placeholders and
supplied parameter names. Inserted source content is never scanned again, so a
literal `$payload` inside evidence cannot become another substitution; quote,
backslash, control-character and Unicode injection cases are checked against a
real server. Nonfinite numeric values and non-scalar/list parameter types are
rejected. Full source objects remain canonical JSON string envelopes. The
container replacement check above passes with this binding workaround.

`put` replaces a mutable record envelope; source and snapshot immutability
is enforced by the ingestion boundary. A single FalkorDB instance serializes
writes, including `MERGE`; no distributed multi-primary semantics are claimed.

## Connector inventory and import coverage

`FileSource`/`FileSources` reads a JSON list or `{records:[...]}` and paginates
through the same `Sources.fetch(cursor)` boundary as live adapters. Synthetic
history is source input rather than an expected graph answer. It supports
explicit edited revisions, deletions and access-loss tombstones. An import
checkpoints only after all records in a page are persisted. A failed page can be
replayed idempotently, and partial import status stays visible until completion.
Completed imports restart their connector traversal to discover edits. Replaying
known older revisions does not roll back observed source or repository heads.

`SlackSources` reads one configured thread with pagination, source message IDs,
thread context, author IDs and edit timestamps. `LinearSources` reads configured
issues with observed update timestamps and explicit cross-source claim metadata.
Historical revisions predating the first import are not exhaustively retrieved.
Neither connector invents approval from words such as “approved”, issue status or
a person's display name. Mapping metadata binds stable source IDs to behaviors;
ambiguous identities stay unresolved. Slack deletion is not inferable from an
absent page: an explicit tombstone event is required. Provider access failure
raises `Unavailable`; it is never silently interpreted as successful deletion.

`GitHubSources` resolves a ref once to a commit, reads a recursive tree and up to
200 configured UTF-8 files (one megabyte per artifact), and imports optional
configured historical PR/reviews. Tree truncation is exposed as a gap. Snapshot
component calls and relevant tests are explicitly mapped in the POC; this is not
an arbitrary-repository parser or proof of dependency completeness. CI files can
be included in the configured source paths. Selected checks are distinct from
checks actually run by the isolated worker.

A source record requires `id`, `provider`, `revision`, `project`, `content` and
`locator`. Optional `timestamp`, `behavior`, `availability`, `claims` and
`snapshot` retain provenance. A claim requires `id`, `behavior` and `text`.
`status:approved` is effective only with explicit `approval.actor`,
`approval.source` and `approval.revision`; this models ingested historical
approval evidence, not a general authority verification service. A scoped
approved replacement can explicitly name superseded claim IDs. Unapproved
proposals do not replace approved rules. Explicit `conflicts_with` IDs establish
conflicts; different text or similar names alone do not prove contradiction.

`Investigator.evidence(project, behavior, repo, base)` returns decisions,
proposals, historical rules, independent constraints affected through shared
code, source revisions, graph paths, affected components, selected checks, a
single repository/commit snapshot, fingerprint, coverage gaps and critical gaps.
Access-loss source content remains historical but cannot support current policy.
Missing/stale code, partial imports, unavailable required evidence and missing
approved rules prevent execution. Dynamic-call coverage is disclosed without
being treated as proof that no implementation can proceed. A merged Outcome
supersedes only matching requested-behavior claims, preserving invoice policies
when report-export scope changes. A change to the packet fingerprint invalidates
prior implementation approval through the workflow gate.

## Request serialization and recovery

`FalkorStore.lock(key)` uses atomic Redis `SET NX`, ownership tokens and a
compare-and-delete Lua release. Locks have no expiration. This intentionally
fails closed: a timed-out process cannot continue an external write while a
second holder acquires an expired lease. A busy or unreachable lock raises
`Unavailable` rather than letting execution continue. Imports lock their source
ID; workflow transitions lock their request ID. The same graph must be used by
all handlers for a request. Redis database and graph name are part of lock
namespace configuration.

After a crashed holder, stop/verify termination of the original process, inspect
the request's pending Operation and reconcile any uncertain external writes.
Only then remove its `actron:<graph>:lock:<key>` Redis key and resume the request.
Deleting a lock while the holder might still be alive defeats serialization.
The POC provides safety at the cost of requiring this manual recovery step;
there is no unattended stale-lock stealing. Persisting coordination keys with
FalkorDB prevents a server restart from silently erasing held locks.

Provider contract references: [Linear GraphQL guide](https://linear.app/developers/graphql),
[Linear filtering](https://linear.app/developers/filtering), and the
[official generated SDK schema](https://github.com/linear/linear/blob/master/packages/sdk/src/_generated_documents.ts)
were checked for issue create/update, ID filters and the required UUID-v4 format
for caller-supplied issue IDs. This documentation check does not replace the
credentialed live smoke test. Linear create IDs use deterministic operation
entropy encoded in UUID-v4 format for crash reconciliation.
