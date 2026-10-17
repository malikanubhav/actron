# Actron requirements

**Status:** Draft, 17 October 2026. Items below describe target behavior; they are not claims of completed implementation. Detailed roles and approver permissions are deferred.

## Functional requirements

| ID | Requirement | Acceptance evidence |
|---|---|---|
| F01 | Connect the selected sources | Authenticated reads from each required demo source |
| F02 | Perform initial ingestion | Source content and metadata stored in FalkorDB with provenance |
| F03 | Apply source updates | Edits, deletions, and loss of access handled without presenting stale information as current |
| F04 | Create and apply an ontology | Documented types and relationships mapped consistently across sources |
| F05 | Resolve cross-source entities | Relevant conversations, tickets, decisions, and code share stable identities |
| F06 | Receive Slack requests | One request record and dedicated thread per accepted request |
| F07 | Investigate history and code | Bounded graph paths with source versions and repository snapshot references |
| F08 | Clarify consequential conflicts | Persisted question and response before changing unresolved product scope |
| F09 | Create a versioned Linear ticket | Objective, acceptance criteria, preserved constraints, evidence, components, and check plan |
| F10 | Gate implementation on ticket approval | Approval matches the exact revision and canonical content hash |
| F11 | Execute coding and validation | Actual checkout, code change, commit, commands, exit codes, and output |
| F12 | Handle failures and revisions | Failures remain visible; automatic repairs stay inside approved scope |
| F13 | Create and revise a PR | Real PR links to ticket, evidence, current commit, and checks |
| F14 | Gate merge on fresh authorization | Current head, required checks/reviews, and authorization agree |
| F15 | Preserve learned outcomes | Later investigations retrieve the scoped decision and implementation evidence |

## Source and ingestion requirements

- Inventory each connector, supported record types, access needs, pagination, rate limits, and update/deletion capabilities.
- Define initial import boundaries and a resumable watermark or equivalent cursor.
- Make ingestion idempotent and preserve immutable source revisions.
- Distinguish source event time, effective time where applicable, and ingestion time.
- Store full source content required by the POC, source IDs, locators, hashes, versions, and extraction provenance in FalkorDB.
- Keep raw source records separate from extracted claims through explicit graph relationships.
- Preserve supporting text/spans, extraction method, uncertainty, and review state.
- Handle partial failures and retries without claiming complete ingestion.
- Mark deleted or inaccessible evidence appropriately and define retention behavior.
- Ingest all agreed supported sources; do not silently interpret every installed connector as implemented ingestion support.

## Ontology requirements

An ontology defines what graph entities and relationships mean. Its creation method is unresolved; no manual, automatic, or mixed approach has been approved.

Candidate entities: Person, Team, Project, SourceRecordVersion, DecisionVersion, Behavior, TicketRevision, CodeSymbolVersion, TestVersion, CIWorkflowVersion, Request, Clarification, Approval, Commit, TestRun, and PullRequest.

Candidate relationships: AUTHORED, SUPPORTED_BY, CONSTRAINS, SUPERSEDES, TARGETS, IMPLEMENTED_BY, CALLS, VERIFIES, RUNS_IN, PROPOSES, APPROVES, IMPLEMENTS, TESTS, EXECUTES, and HEAD.

- Define required properties, relationship directions, cardinality expectations, and evidence rules.
- Version the ontology and define migration or re-extraction behavior.
- Resolve duplicate names and aliases with source-specific stable IDs and explicit mappings.
- Keep uncertain entity matches unresolved rather than silently merging records.
- Distinguish curated, extracted, inferred, and user-confirmed relationships.
- Do not infer authority solely from job titles or conversation text; detailed authority configuration remains deferred.

## Graph and provenance requirements

- FalkorDB is the primary connected knowledge store. Store source content as well as relationships for the small POC corpus.
- Code content in the graph does not replace an executable checkout for editing and testing.
- Preserve historical decisions and scoped supersession. An export exception must not supersede an independent invoice restriction.
- Approved decisions establish current rules; an unapproved newer statement does not replace them.
- Record approval scope, source event, exact revision/hash, and timestamp.
- Associate code symbols, calls, test mappings, and CI definitions with the correct repository snapshot.
- Return source evidence and uncertainty with findings; connectivity alone does not prove truth or contradiction.
- Bound traversals and disclose unresolved or dynamic dependency coverage.
- Define persistence, atomic state transitions, single/multiple writer behavior, and recovery before using graph records as an execution ledger.
- Store workflow events in the graph as requested, without claiming that an unvalidated concurrency design is sufficient for reliable orchestration.
- Keep evaluator answers and future scenario events inaccessible to the initial investigator, including when they are stored in separate graphs on the same server.

## Integration requirements

| System | Required capabilities |
|---|---|
| Slack | Read agreed history, receive commands/events, create request threads, ask questions, receive clarifications and approval interactions |
| Linear | Read issues, create/update proposed tickets, retain revision snapshots, detect external edits |
| GitHub | Read repository snapshots and history, inspect PRs/reviews/checks, create branches/PRs, process review updates, merge the authorized head |
| FalkorDB | Store and query source content, versioned entities, relationships, evidence, and outcomes |
| Coding worker | Materialize a checkout, install dependencies, make controlled edits, run checks, return commits and output |
| LLM provider | Support the selected investigation/coding tools within configured time and spend limits |

MCP servers can provide tools, but they do not automatically provide source synchronization, a Slack interaction handler, or a running development environment. Verify actual tool capabilities and select direct API adapters where necessary. No server/tool inventory or implementation stack has been finalized.

## Approval and execution requirements

- Keep ticket approval and final merge authorization as separate gates.
- Detect a material ticket revision and require approval of its new scope.
- Revalidate code revisions and bind final authorization to the current PR head.
- Distinguish implementation repair from a product decision that changes acceptance criteria.
- Preserve tests that protect unchanged constraints; flag changes to their assertions for review.
- Bound automatic repair attempts, wall time, and model spend.
- Deduplicate request/events and reconcile uncertain external writes before retrying.
- Keep external credentials out of the coding worker where they are unnecessary.
- Treat retrieved messages and repository text as evidence, not instructions that override approval policy.
- Persist enough information to recover after a crash without duplicate workers, issues, PRs, or merges.
- Define detailed approver permissions later, as requested by the user.

## Infrastructure requirements

Logical resources: FalkorDB with verified persistence, ingestion and workflow runtimes, a Slack interaction handler, an isolated coding worker, repository CI, and a model API.

Proposed starting capacity for a small demo is one Linux machine with 4 vCPU, 8 GB RAM, and about 30 GB free disk. This is an estimate, not a benchmark or selected cloud configuration. No GPU or Kubernetes requirement has been established.

- Use persistent graph storage and verify recovery by restart, not merely by configuring a volume.
- Keep graph database and browser access local or restricted.
- Keep credentials outside source control and document placeholders only.
- Pin tested dependencies and container versions when implementation begins.
- Persist ingestion cursors, workflow state, external IDs, approvals, worker ownership, commits, and validation records.
- Record request/run/tool IDs, durations, failures, check output, and model usage with secret redaction.
- Implement readiness checks, timeouts, bounded retries, and graceful recovery.
- Provide reproducible setup, synthetic source population, graph import, validation, and demo commands.
- Select the actual host, runtime, model, sync mechanism, and state/concurrency implementation after flow decisions.

## Synthetic dataset requirements

The full synthetic dataset remains an outstanding deliverable. It must include:

- Fictional people, teams, projects, and source identities.
- Slack channels, threads, messages, edits, and decision discussions.
- Linear issues, ticket revisions, acceptance criteria, and dependencies.
- Approved, unapproved, superseded, and unrelated decisions with supporting records.
- Source documents or policy records where included in the connector inventory.
- A small repository with report/invoice permissions, shared dependencies, tests, CI, and version history.
- Request and clarification scenarios, approval events, commits, PRs, review comments, and validation outcomes.
- Update, deletion, ambiguous-identity, duplicate-delivery, and stale-approval examples.
- Separate initial-context data and future-event/evaluation data.

Label all identities, IDs, URLs, approvals, and results as synthetic where applicable. Demonstration events are not evidence of live permission or successful execution. Populate demo sources and ingest them through connectors to prove the intended pipeline.

## Validation requirements

Run the complete small repository test suite in addition to selected graph-linked checks. Record exact tested commit, commands, exit codes, and output. Include feature/regression behavior, scoped supersession, source freshness, duplicate events, recovery, ticket revisions, and changed PR heads.

Compare graph context with request-only and flat-history baselines honestly. Keep model, code, existing tests, tools, and budgets comparable. A successful baseline is a valid result; do not hide tests or future answers to manufacture graph superiority.

## Hackathon references and submission

- [Event and tracks](https://www.wemakedevs.org/hackathons/falkordb)
- [Official rules](https://www.wemakedevs.org/hackathons/falkordb/rules)
- [Schedule](https://www.wemakedevs.org/hackathons/falkordb/schedule)

The official pages reviewed in this conversation state that the event ends on 18 October 2026 at 11:59 PM IST. They require FalkorDB to be central, a public repository, setup README and graph model, essential Cypher queries/algorithms, a working demo video, deployment or complete local instructions, selected tracks, and disclosure of AI assistance. Recheck the current submission panel and rules before submission.

Track 01 is the proposed primary fit because graph evidence changes agent actions. Track 03 is a possible additional fit. Track 02 should be claimed only if persistent memory/coordination is implemented and shown. No registration or submission has been performed by these documents.

## Open decisions

1. Confirm the complete end-to-end flow.
2. Confirm supported sources and connector coverage for the first demo.
3. Select ontology creation, review, and evolution behavior.
4. Define ingestion freshness, updates, deletions, and access changes.
5. Decide which dependency and test relationships are extracted or curated.
6. Select coding worker, model, deployment, and workflow persistence/concurrency design.
7. Define exact approval-invalidation rules while deferring detailed roles.
8. Confirm the final demo boundary and evaluation plan.
