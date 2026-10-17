# Actron proof of concept

**Status:** Planning draft, 17 October 2026. This document specifies a demonstration; it does not claim a working implementation.

## Objective

Demonstrate that connected decision history changes an agent's behavior before code is written and remains traceable through the resulting PR.

## Demonstration data and ingestion

Create a fictional company with synthetic people, projects, Slack messages, Linear tickets, decisions, repository history, dependencies, tests, and PR records. Populate dedicated demonstration sources, then ingest their records through connectors.

Store full source content and relevant code snapshots in FalkorDB for this small corpus, along with IDs, revisions, content hashes, timestamps, provenance, and explicit relationships. A coding worker must still materialize files in a checkout to execute code and tests.

Fixture identities and approvals are synthetic. They do not authorize real actions. Keep future clarification answers, approved ticket revisions, golden patches, and expected PR outcomes out of the initial investigator's context. They may live in a separate evaluator graph.

## Main scenario

1. Ingest a Finance-only report-export decision and its supporting history.
2. Ingest the demo repository snapshot and identify the helper shared by reports and invoices.
3. Receive `/build Allow project admins to export reports` in Slack.
4. Retrieve the applicable decision and dependency paths with source evidence.
5. Ask whether report access should expand while invoices remain Finance-only.
6. Record the clarification in a proposed Linear ticket.
7. Obtain approval of that ticket revision.
8. Start an isolated coding worker with the approved ticket, evidence, and recorded base commit.
9. Implement and run feature and regression checks.
10. Open a PR showing the diff, ticket, evidence, and actual results.
11. Process one review revision and rerun checks.
12. Obtain commit-specific final authorization and merge if the selected demo scope includes merge.
13. Record the scoped decision and outcome in the graph.

If the worker broadens the shared helper and breaks an invoice test, show the actual failure and repair. A deliberately supplied vulnerable patch must be labeled as such; it is not evidence that a baseline agent generated it.

## Logical architecture

```text
Slack / Linear / GitHub / other supported sources
                    |
        Connectors and change detection
                    |
     Source versions and ingestion records
                    |
      Ontology mapping and entity resolution
                    |
                 FalkorDB
                    |
      Investigation and evidence retrieval
                    |
         Slack clarification and ticket
                    |
           Ticket revision approval
                    |
         Isolated coding and test worker
                    |
          PR, CI checks, and review
                    |
       Current-commit merge authorization
                    |
        Outcome and knowledge graph updates
```

This diagram assigns responsibilities. It does not decide process boundaries, libraries, deployment platform, or ontology strategy.

## Proposed components

| Component | Responsibility | Decision still needed |
|---|---|---|
| Source connectors | Fetch records, metadata, revisions, and updates | Initial connector inventory; API/MCP capability coverage |
| Ingestion coordinator | Track import progress, retries, duplicates, edits, and deletions | Polling versus events; freshness target |
| Ontology layer | Define and map entities, relationships, and meaning | Manual, generated, or mixed creation approach |
| Entity resolver | Link the same person, project, feature, or ticket across sources | Matching rules and review of uncertain matches |
| Graph service | Persist content, claims, relationships, versions, and evidence | Query contracts, indexes, and state/concurrency design |
| Workflow coordinator | Move requests through clarification, approval, execution, and review | Runtime and durable event handling |
| Slack handler | Receive commands/interactions and route replies to the request thread | App configuration and event transport |
| Linear adapter | Create issues and track immutable approved revisions | Revision snapshots and external-edit detection |
| Coding worker | Materialize code, edit, execute checks, and return commits | Execution environment and coding model/tool |
| GitHub adapter | Manage PRs, checks, reviews, and authorized merge | Authentication and required repository rules |

## Proposed workflow states

`RECEIVED -> INVESTIGATING -> NEEDS_CLARIFICATION -> TICKET_DRAFT -> AWAITING_TICKET_APPROVAL -> IMPLEMENTING -> VALIDATING -> PR_OPEN -> AWAITING_MERGE_AUTHORIZATION -> MERGING -> MERGED`

Requests with sufficient evidence can skip clarification. Other explicit states: `FAILED`, `CANCELLED`, and `NEEDS_SCOPE_REVISION`.

An approved scope change requires a new ticket revision and approval. A code revision requires fresh checks and invalidates final authorization for the old head. Persist external IDs and state transitions; recover uncertain operations before retrying.

## Validation scenarios

- The requested report-export behavior passes while invoice restrictions remain intact.
- Superseded decisions remain visible as history without overriding current scope.
- Similar but unrelated conversations are not declared proven conflicts.
- Source changes refresh graph applicability while preserving necessary provenance.
- A ticket edit invalidates stale scope approval.
- A changed PR head invalidates stale tests and merge authorization.
- Duplicate deliveries do not create duplicate issues, workers, or PRs.
- A restart resumes the persisted phase.
- Missing graph access produces an explicit investigation failure.
- Future scenario answers and fixture approvals are excluded from initial investigation.

## Evaluation

Compare request-only context, flat retrieved history, and graph-based context using the same model, repository, existing tests, tools, and budget. Report observed outcomes even if the baseline succeeds. Do not remove an invoice regression test to manufacture a failure.

Record source/path correctness, useful clarification, preservation of constraints, test results, elapsed time, and model/tool usage. A single scenario supports a concrete demonstration claim, not a general claim of fewer software regressions.

## Implementation stages

1. Confirm flow, boundaries, ontology approach, and demo acceptance criteria.
2. Create synthetic source data and the small repository.
3. Implement ingestion, versioned provenance, ontology mapping, and graph loading.
4. Verify decision, dependency, and test traversals.
5. Connect Slack requests, clarification, Linear tickets, and ticket approval.
6. Connect the coding worker, actual checks, and GitHub PRs.
7. Implement review revision, fresh validation, and final authorization.
8. Validate source updates, duplicate handling, recovery, and evidence isolation.
9. Record evaluation, setup instructions, and a working demo video.

## Proposed team work packages

- Data, ontology, ingestion, and graph queries.
- Slack flow, ticket revisions, and approval state.
- Coding worker, validation, PR integration, and merge policy.
- Integration testing, evaluation, documentation, and video.

For two people, combine the first two and last two packages. These are human work packages; no implementation subagents have been launched.

## Definition of done

A reviewer can populate synthetic sources, ingest them, submit a Slack request, inspect the conflict and dependency evidence, clarify scope, approve a ticket revision, obtain a real tested PR, review a revision, and inspect the complete audit chain. Demonstrate authorized merge only if implemented. Provide repeatable setup and evidence for each claimed behavior.

## Outstanding implementation

The complete synthetic dataset, executable ingestion, ontology implementation, graph loader, agent runtime, live integrations, tests, deployment, and evaluation are not yet built in this folder.
