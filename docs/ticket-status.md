# Ticket implementation and acceptance

All 17 ticket slices have backend implementations. This is an acceptance inventory,
not a claim that unconfigured live providers have been exercised. On 17 October
2026 the user explicitly deferred credentials and said configuration will connect
through a UI later. UI implementation is a subsequent step.

The repeatable primary boundary is signed Slack commands/buttons, real FalkorDB,
durable graph state, external provider contract fixtures, and actual disposable
Git repositories and check processes. Controlled coding stimuli are labeled;
the actual model adapter is separate. Existing invoice assertions remain intact.

| Ticket | Implemented path and validation | Pending live acceptance |
|---|---|---|
| 01 | Source connector import, immutable content/provenance, Slack evidence and graph-outage response | Dedicated Slack population/read/write smoke |
| 02 | Explicit cross-source identities, approved rules vs proposals, revision lineage and uncertain coverage | Linear source population/read smoke |
| 03 | Synthetic repository, shared calls, impacted behaviors/checks, exact code snapshot and baseline execution | GitHub source read smoke |
| 04 | Durable request/thread, joined evidence, membership and invoice clarification | Live Slack thread |
| 05 | Confirmed issue creation/update, canonical immutable scope revisions, exact hashes and evidence | Real Linear issue creation/revision |
| 06 | Signed button identity, visible revision/hash, refreshed scope and one durable handoff | Live interaction |
| 07 | Isolated real checkout, bounded actual model adapter, real commands/output/commits, protected regression tests | Credentialed model implementation |
| 08 | Real failing controlled stimulus, failed commit/output retained, bounded in-scope repair and scope-return gate | Live model repair observation |
| 09 | Dedicated-repository PR adapter, approved revision/evidence/check results, current-head CI reads | Real PR write and check retrieval |
| 10 | Head-bound feedback, same-branch new commit/fresh suite, changed scope returns to approval | Live PR revision |
| 11 | Separate explicit head authorization, fresh required checks/reviews, provider expected-SHA merge | Authorized live demo-repository merge |
| 12 | Confirmed merged outcome becomes scoped knowledge; invoice rule survives report supersession | Reuse after a live merge |
| 13 | Source edits, scoped supersession, access-loss/tombstone evidence, resumable/repeated import | Source updates in dedicated services |
| 14 | New coherent code snapshot, immutable history, mixed-commit rejection, stale-request pause | GitHub second-commit import |
| 15 | Graph request/revision/approval/event journal, deterministic issue identity, lost-response recovery and deduplication | Live interrupted-provider validation |
| 16 | Atomic worker ownership, PR upsert/reconciliation, unknown merge reads and changed-head rejection | Live interrupted write reconciliation |
| 17 | Complete local setup, separate evaluator/future fixtures, comparable measured-run tooling, captured local video | Actual three-context model runs and external-source demo |

## Reproducibility and limits

- `uv run actron populate` creates synthetic source files and a real local Git
  baseline. File connectors ingest them; no expected answer is seeded as a graph result.
- `populate-live --live` and `refresh-live` populate and read only explicitly
  configured dedicated resources; they are available for later credentialed acceptance.
- Historical approval metadata never authorizes current work. The POC authorization
  binding is an explicit configured Slack user/channel, not a role model.
- Ontology v1 and code links are curated explicit mappings. Static dependency
  traversal is bounded and dynamic coverage is disclosed. Arbitrary repository
  understanding and production readiness are outside this implementation.
- Source deletion/access loss is represented by explicit versioned tombstones.
  The one-thread Slack connector does not infer deletions from pagination absence.
- No-TTL graph locks fail closed after process death. Operator recovery first
  confirms the old process is dead and reconciles provider effects. This trades
  availability for exclusive ownership; it is not an expiring distributed lease.
- Model comparisons retain every observed result under the same model/base/tests/
  tools/budgets. No quality improvement is asserted without observed runs.
- Source code and model adapter were created with AI assistance. The local video
  is a recorded passing provider-contract demonstration, not live SaaS footage.

See [setup](setup.md), [graph](graph.md), [worker](worker.md), and
[implementation plan](implementation-plan.md) for concrete commands and assumptions.
