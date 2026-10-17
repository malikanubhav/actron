# Actron product requirements document

**Status:** Draft, 17 October 2026. Project name: Actron, confirmed by the user.

## Product in plain language

An AI assistant checks the history before changing software. It connects what people discussed, what they approved, what the code does, and what the tests protect. It asks about important conflicts, then implements and validates the approved change.

## Problem

Developers receive feature requests and bug reports without the full history of why the software behaves as it does. Decisions, discussions, tickets, code dependencies, and tests are spread across tools. A change can satisfy the new request while breaking an existing requirement.

## Intended outcome

Trace each request through connected evidence, resolve consequential contradictions with the user, and preserve that reasoning through a reviewed PR. The graph must change what the agent does: whether it asks a question, what scope it implements, or which checks it runs.

## Confirmed direction

- A team of 2–4 is building the hackathon POC.
- Ingest data from connected sources and create an ontology.
- Keep source information and explicit relationships in FalkorDB for the POC.
- Supply synthetic company data for the demo.
- Treat explicitly approved decisions as current rules. Treat newer unapproved statements as proposals; ask when applicability or authority is unclear.
- Defer detailed roles and approver permissions.
- Establish the flow before finalizing implementation details.
- Save planning files locally; do not create ChatGPT Spaces or Pages.

## Users and initial boundaries

Primary users are developers and technical leads who request or review software changes in Slack.

Slack, Linear, and GitHub are the initial named sources. Supporting every connected tool requires an explicit connector inventory; a connection alone does not guarantee ingestion support. One workspace, one repository, and one programming language are proposed POC limits, not confirmed product-wide limits.

## Working end-to-end flow

1. Connect the source systems.
2. Fetch source content, identities, metadata, and revisions.
3. Establish the ontology, resolve matching entities across sources, and construct the graph.
4. Keep graph knowledge current as source data changes.
5. Receive a `/build` or `/bug` request and start a Slack thread.
6. Investigate relevant decisions, source evidence, code dependencies, and tests.
7. Ask focused questions about conflicting decisions or missing product requirements.
8. Propose a Linear ticket with the agreed scope, acceptance criteria, preserved constraints, affected components, and evidence.
9. Obtain approval of that exact ticket revision.
10. Implement and test the change in an executable repository checkout.
11. Open a PR, show results in Slack, and process review feedback.
12. Obtain final authorization for the reviewed commit, verify required GitHub checks and reviews, and merge.
13. Update the graph with the scoped decision, implementation, validation, and outcome.

This is the current working proposal. The user has not yet confirmed every step or selected the detailed architecture.

## Demonstration scenario

Request: **Allow project admins to export reports.**

The graph connects an approved Finance-only report-export decision to its source discussion and ticket. It also shows that reports and invoices share a permission helper.

The agent asks whether report access should expand while invoice access remains Finance-only. After clarification and ticket approval, it implements that scope, runs both feature and regression checks, and opens a PR explaining the evidence and results.

Project membership, cross-project access, and whether Finance users require project membership are unresolved product details. Do not invent them as accepted requirements.

## Product behavior

- Cite source records and versions when presenting historical decisions.
- Distinguish a possible conflict from a confirmed contradiction.
- Treat code as evidence of current implementation, which can differ from approved policy.
- Ask only questions that affect scope, policy, or implementation correctness.
- Bind ticket approval to the exact ticket revision and canonical content hash.
- Repair implementation failures within approved criteria; return to clarification and ticket approval if criteria must change.
- Never weaken a preserved-constraint test solely to obtain a passing result.
- Show actual check failures, repairs, unresolved questions, and validation limits.
- Bind final merge authorization to the current PR head commit.
- Preserve historical decisions and scope replacements precisely. A report-export exception must not erase a separate invoice restriction.

## Success criteria

| Outcome | Evidence |
|---|---|
| Connected history changes the agent's action | Source-backed conflict or dependency triggers clarification or changes implementation/validation scope |
| Ingestion works | Synthetic records are fetched from demonstration sources into the graph |
| Knowledge is traceable | Findings link to source IDs, versions, supporting text, and repository snapshots |
| Approved scope survives implementation | Ticket criteria, code diff, tests, and PR remain linked |
| Validation is real | Exact tested commit, commands, exit codes, and results can be inspected |
| Approval is current | Ticket revision and final commit match the approvals used |
| Knowledge persists | A later request can retrieve the resulting scoped decision and outcome |

## Proposed non-goals for the POC

Arbitrary-codebase understanding, complete dynamic dependency analysis, multi-tenant SaaS onboarding, production deployment of application changes, and unattended changes to product policy.

## Open product questions

1. Confirm the complete flow and first connector inventory.
2. Decide how the ontology is created and extended.
3. Define how source edits, deletions, missing access, and contradictory evidence affect current knowledge.
4. Confirm exact acceptance criteria for the demonstration request.
5. Select approval-invalidation rules without expanding the deferred discussion of roles.
6. Confirm whether the first complete demonstration includes an actual merge or ends at a reviewed PR.
