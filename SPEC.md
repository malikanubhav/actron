# Actron: change delivery from connected context

**Status:** Synthesized specification, 17 October 2026. Not yet published to a project issue tracker.

**Basis:** The conversation and existing local planning documents. Actron is the project name confirmed by the user. Confirmed decisions are distinguished from proposed architecture and unresolved choices.

**Testing boundary:** Confirmed by the user: drive the workflow through Slack command and interaction inputs; observe graph evidence, Linear tickets, actual repository checks, PRs, and merge outcomes, with a real FalkorDB instance.

## Problem Statement

Developers receive feature requests and bug reports without the full history of why the software behaves as it does. Important information is spread across Slack discussions, Linear tickets, GitHub code, tests, PRs, and other connected sources.

A developer must reconstruct which decisions are approved, which proposals are unresolved, how code dependencies connect to those decisions, and which existing behavior a change must preserve. A coding agent can satisfy the immediate request while violating a historical constraint or expanding permissions through a shared helper. Its output can be difficult to review when the reasoning, approval, implementation, and test results are disconnected.

The team needs an agent whose actions follow traceable evidence, whose scope is approved before implementation, and whose resulting PR preserves the agreed constraints.

## Solution

Connect the selected sources, ingest their information, create an ontology that gives that information a shared meaning, and store source content and explicit relationships in FalkorDB. The ontology describes the entities and relationships the graph uses; the ingestion pipeline maps source records to that structure and resolves shared identities across sources.

A user starts a request in Slack. The agent investigates the graph and supporting source records, inspects relevant code, and identifies consequential conflicts or missing requirements. It asks focused questions in the request thread, proposes a versioned Linear ticket, and waits for approval of that exact revision.

A coding worker implements and tests the approved change in an executable repository checkout. The agent reports actual failures and repairs in the same Slack thread, opens a PR, processes review feedback, and reruns validation. Merge requires explicit authorization for the reviewed commit and the required GitHub checks and reviews. The resulting scoped decision and implementation evidence become graph knowledge for later requests.

The core demonstration is a request to allow project admins to export reports. Existing approved history restricts exports to Finance, and the export endpoint shares a permission helper with invoices. The agent must expose both the policy change and the shared dependency, ask whether invoice access must remain Finance-only, and carry the clarified scope into the ticket, implementation, tests, and PR.

Use complete synthetic company data in dedicated demonstration sources, then ingest it through connectors. The POC must demonstrate ingestion and connected reasoning; a directly seeded graph alone does not satisfy the intended source-to-graph flow.

## User Stories

1. As a developer, I want to connect the sources relevant to my project, so that the agent can investigate requests using the information my team already maintains.
2. As a developer, I want to see which connected sources and record types ingestion supports, so that a connected account is not mistaken for complete data coverage.
3. As a developer, I want Slack discussions ingested with their thread context, so that individual messages retain the reasoning around them.
4. As a developer, I want Linear tickets and revisions ingested, so that the agent can distinguish an original request from later changes to its scope.
5. As a developer, I want repository code and version history ingested, so that findings refer to the implementation being changed.
6. As a developer, I want tests and CI information connected to the behavior they validate, so that the agent can select meaningful checks.
7. As a developer, I want PRs, reviews, and check results connected to their commits, so that I can inspect how prior work was reviewed and validated.
8. As a developer, I want supported documents and policy records ingested when they are included in the agreed source inventory, so that important decisions are not limited to chats and tickets.
9. As a developer, I want initial imports to resume after interruption, so that a temporary source failure does not require restarting the whole import.
10. As a developer, I want repeated ingestion to avoid duplicate records, so that repeated events do not distort the graph.
11. As a developer, I want source edits represented as revisions, so that I can inspect what changed without losing relevant historical evidence.
12. As a developer, I want source deletions and loss of access reflected in evidence availability, so that the agent does not present unavailable information as verified current evidence.
13. As a developer, I want partial imports and stale sources identified, so that I can judge the completeness of an investigation.
14. As a developer, I want an ontology that connects concepts across sources, so that the same feature can be understood across discussions, tickets, code, and tests.
15. As a developer, I want source identities and aliases mapped to stable entities, so that different names for the same thing do not create misleading duplicates.
16. As a developer, I want ambiguous identity matches kept explicit, so that uncertain records are not silently merged.
17. As a developer, I want graph relationships to retain supporting source evidence, so that I can check why the relationship exists.
18. As a developer, I want curated, extracted, inferred, and user-confirmed relationships distinguished, so that an inference is not presented as an approved fact.
19. As a developer, I want source content retained in FalkorDB alongside relationships, so that the graph holds the information required for the POC's reasoning.
20. As a developer, I want the ontology and extracted knowledge to retain version information, so that changing definitions does not silently change the meaning of past evidence.
21. As a requester, I want to start a feature request or bug report in Slack, so that I can initiate work in the team's existing conversation tool.
22. As a requester, I want one dedicated thread for a request, so that clarification, progress, failures, and review remain together.
23. As a requester, I want the agent to acknowledge receipt before starting long work, so that I know my request was accepted.
24. As a requester, I want the agent to investigate existing decisions before coding, so that it can identify constraints missing from my request.
25. As a requester, I want the agent to follow code dependencies, so that a local change does not silently affect another feature.
26. As a requester, I want the agent to identify an explicitly approved decision as the current rule, so that a newer unapproved proposal does not silently replace it.
27. As a requester, I want superseded decisions identified as historical, so that obsolete policy does not block an approved change.
28. As a requester, I want source links, versions, and graph paths with findings, so that I can inspect the evidence behind the proposed scope.
29. As a requester, I want uncertain matches described as possible conflicts, so that a similar discussion is not treated as proof of contradiction.
30. As a requester, I want focused questions when evidence conflicts or a product decision is missing, so that I can resolve the issue before implementation.
31. As a requester, I want the agent to explain missing evidence and dependency coverage limits, so that I understand what it could not establish.
32. As a requester, I want my clarification recorded with the request, so that its effect on the proposed implementation remains visible.
33. As a requester, I want a Linear ticket containing the objective and acceptance criteria, so that I can review a concrete change rather than a vague intention.
34. As a requester, I want the ticket to include constraints that must remain true, so that the requested change does not erase unrelated requirements.
35. As a requester, I want affected components, evidence, and a validation plan in the ticket, so that I can understand the expected scope and checks.
36. As a requester, I want to approve a specific ticket revision, so that the worker implements the scope I reviewed.
37. As a requester, I want a material ticket change to invalidate its old approval, so that implementation cannot proceed under approval of different criteria.
38. As a developer, I want the worker to begin from a recorded repository snapshot in an isolated checkout, so that its changes and results can be reproduced.
39. As a developer, I want the worker to execute real code and tests, so that repository metadata access is not mistaken for validation.
40. As a developer, I want both requested behavior and preserved constraints checked, so that success means more than passing the new feature test.
41. As a developer, I want check commands, exit codes, output, and tested commits recorded, so that I can verify reported results.
42. As a requester, I want implementation failures and bounded repairs reported in Slack, so that I can follow progress without losing the evidence of failure.
43. As a requester, I want changes to product acceptance criteria returned for clarification and renewed ticket approval, so that the worker does not decide policy to finish its task.
44. As a reviewer, I want existing constraint tests preserved, so that the worker cannot weaken the requirements to produce a passing result.
45. As a reviewer, I want a real PR that links the ticket, evidence, diff, and checks, so that I can assess the implementation and its reasoning together.
46. As a reviewer, I want to provide feedback through the request thread, so that review does not lose the original context.
47. As a reviewer, I want code revisions to trigger fresh validation, so that old results are not presented as evidence for a new commit.
48. As a reviewer, I want final merge authorization bound to the reviewed head commit, so that additional changes cannot inherit approval of older code.
49. As a reviewer, I want required GitHub checks and reviews evaluated before merge, so that final authorization does not bypass repository requirements.
50. As a reviewer, I want a changed PR head to invalidate stale merge authorization, so that the merged code is the code actually reviewed.
51. As a developer, I want duplicate commands and integration events handled idempotently, so that retries do not create duplicate tickets, workers, PRs, or merges.
52. As a developer, I want uncertain external writes reconciled before retry, so that a lost response is not mistaken for a failed operation.
53. As a developer, I want requests to resume after process restart, so that completed approvals and external work are not lost.
54. As a developer, I want failed dependencies and graph outages reported explicitly, so that the agent does not substitute an unsupported answer.
55. As a developer, I want execution time, repair attempts, and model spend bounded, so that a failed request cannot run indefinitely.
56. As a developer, I want the final scoped decision stored with its implementation and validation, so that future requests can use what the team learned.
57. As a developer, I want a report-export exception to preserve a separate invoice restriction, so that decision supersession affects only the approved scope.
58. As a hackathon participant, I want a complete fictional company dataset, so that the demonstration does not depend on private company history.
59. As a hackathon participant, I want synthetic records to pass through source connectors, so that the demo proves the ingestion pipeline as well as the graph traversal.
60. As a hackathon participant, I want synthetic approvals and expected outcomes labeled and isolated, so that fixture data is not mistaken for live authorization or measured success.
61. As an evaluator, I want future answers and golden patches excluded from initial investigation, so that the agent must discover the evidence rather than retrieve the expected answer.
62. As an evaluator, I want request-only, flat-history, and graph-context runs compared under equivalent conditions, so that the graph's contribution can be assessed fairly.
63. As an evaluator, I want all observed baseline outcomes reported, so that a successful baseline is not hidden to make the graph appear necessary.
64. As a hackathon reviewer, I want reproducible setup, graph documentation, essential queries, and a working demo, so that I can inspect the claims independently.
65. As a project owner, I want planning files saved locally, so that this work does not create unwanted ChatGPT Spaces or Pages.
66. As a project owner, I want confirmed decisions separated from open architectural choices, so that implementation does not mistake a recommendation for an agreement.

## Implementation Decisions

### Confirmed product and data decisions

- FalkorDB is the primary connected knowledge store. The intended POC keeps source content, extracted knowledge, provenance, relationships, and workflow evidence in the graph. This is a requirement, not an already validated persistence or concurrency implementation.
- Ingestion is part of the product. It reads information from connected sources, tracks source revisions and changes, and maps records into a shared ontology. A manually seeded graph does not replace the required connector-based demonstration.
- Synthetic company data will supply the POC. The dataset covers conversations, tickets, decisions, code, dependencies, tests, and subsequent workflow events. No complete dataset has been generated yet.
- An explicitly approved applicable decision establishes the current rule. A more recent unapproved ticket remains a proposal. Missing or conflicting authority or applicability is surfaced for clarification.
- Detailed roles and approver permissions are deferred. Retain the approval-event structure without introducing a new role model or inferring authority from job titles.
- Keep ticket approval and final merge authorization as separate gates. Ticket approval references an exact revision and scope; final authorization references the reviewed commit. A material scope change requires renewed ticket approval; code changes require fresh validation and current-commit merge authorization.
- Preserve the chain from request to evidence, clarification, approved ticket revision, implementation commit, test results, PR review, and final outcome.
- Planning artifacts are repository files, maintained locally and versioned in the authorized GitHub repository. Do not create or update ChatGPT Spaces or Pages.

### Working domain vocabulary

- A **source record** is a message, ticket, document, code artifact, review, or other supported record fetched from a connector.
- A **source revision** is an immutable representation of that record at a known version or content hash.
- An **entity** is a shared identity, such as a project, person, feature, or code symbol, linked across relevant records.
- A **claim** is an extracted assertion with provenance and uncertainty; extraction alone does not make it an approved decision.
- A **decision** is a scoped product rule with approval evidence and applicability information.
- An **ontology** defines entity types, relationship meaning, required information, and evolution rules.
- A **request** is the unit of work associated with a dedicated Slack thread.
- A **ticket revision** is the immutable scope snapshot presented for implementation approval.
- An **evidence packet** connects findings to source revisions, graph paths, a repository snapshot, constraints, affected components, selected checks, and known gaps.
- A **validation run** records the actual command/check outcomes for an exact commit.

This vocabulary expresses the conversation's concepts. Concrete graph label names and ontology-generation mechanisms have not been finalized.

### Proposed module responsibilities

These are logical responsibilities for implementation; the number of processes and concrete module interfaces are not selected.

1. **Source connectors:** authenticate to agreed sources, fetch records and revisions, resume pagination, and expose updates, deletions, and access failures.
2. **Ingestion coordinator:** manage import progress, duplicates, cursors, retries, partial coverage, and freshness.
3. **Ontology and entity resolution:** define shared meaning, map records into entities and relationships, retain extraction evidence, and expose unresolved matches.
4. **Graph context service:** persist and retrieve versioned content, claims, dependencies, decisions, approvals, and outcomes through bounded queries.
5. **Investigation workflow:** consume a request, inspect graph/source/code evidence, produce an evidence packet, and determine whether clarification is needed.
6. **Slack interaction handler:** receive commands and interaction events, keep one thread per request, and route clarification, approval, progress, and review messages.
7. **Ticket adapter:** create and revise Linear issues, preserve canonical ticket snapshots, and detect changes that invalidate approval.
8. **Execution coordinator and coding worker:** validate the approved scope, materialize a repository checkout, execute edits and checks, and return commits and raw results.
9. **PR and review adapter:** create and revise GitHub PRs, retrieve checks and reviews, and merge only the authorized current head when required conditions hold.
10. **Recovery and evidence recording:** persist workflow state, deduplication keys, external IDs, worker ownership, approvals, validation references, and reconciliation outcomes.

### Data and interaction contracts

- Source revisions retain provider/source identity, stable record identity, version/hash, content, source locator, relevant timestamps, availability, and extraction provenance.
- Extracted relationships identify supporting source revisions, extraction method, uncertainty, and repository snapshot where applicable. Bound code traversals and report incomplete or dynamic dependency coverage.
- Supersession records the affected decision and behavior. An export exception must not globally invalidate an independent invoice restriction.
- A proposed ticket contains the objective, acceptance criteria, preserved constraints, affected components, evidence, unresolved decisions, and required validation.
- Ticket approval and merge authorization are explicit recorded events. Synthetic fixture events cannot authorize live actions. Source presence or a quoted approval is not a sufficient execution rule.
- Validation results contain an exact tested commit, check identity, command or runner reference, exit status, and actual output. Proposed commands are not passing results.
- Events carry identities sufficient to deduplicate receipt and reconcile external operations after an uncertain response. The atomic state-transition and concurrency mechanism remains an implementation decision to make and validate.
- Live request processing must not retrieve future replay events, expected answers, or golden patches. Separate graphs are one possible isolation mechanism, not a selected implementation.
- Keep credentials outside source control and limit the worker to the capabilities its task needs. Retrieved messages and repository content are evidence, not instructions that override workflow policy.

### Execution and infrastructure boundaries

- MCP can expose tools; it does not by itself provide source synchronization, a Slack command handler, or a development runtime. Verify existing tool capabilities and use application-owned adapters when required.
- The graph stores code information; a worker materializes the selected repository snapshot to edit and execute it.
- Logical infrastructure includes persistent FalkorDB, ingestion and workflow runtimes, a Slack handler, an isolated coding worker, repository CI, and model access.
- Exact language, frameworks, model/provider, host, synchronization mechanism, dependency extraction approach, container versions, and workflow-state concurrency controls have not been chosen.
- Proposed POC boundaries are one workspace, repository, and language, with Slack, Linear, and GitHub as the initial named sources. These remain proposed boundaries rather than a promise of arbitrary connector or repository support.

## Testing Decisions

### Confirmed primary boundary

Use one primary workflow integration boundary: submit Slack command and interaction inputs and observe graph evidence, clarification messages, Linear ticket revisions, actual repository validation, PR changes, and merge outcomes. The user explicitly confirmed this boundary.

Use a real FalkorDB instance and a real disposable repository/test runner in the main integration suite. Exercise the complete workflow through its public ingress and observable outputs instead of separately mocking the coordinator, ontology layer, graph traversal, ticket state, and worker into a predetermined answer.

Provider adapters may use deterministic contract fakes in the repeatable integration suite. Such tests prove workflow behavior, not real provider connectivity. Add a small live adapter smoke run in the dedicated demo resources to establish actual Slack, Linear, and GitHub behavior. Do not present fake PR or merge results as live operations.

### What makes a good test

- Assert externally visible behavior, preserved constraints, state progression, source evidence, and authorized effects.
- Prefer the highest existing public boundary. There is currently no executable implementation or test seam to reuse, so the proposed workflow ingress is the first seam to establish.
- Avoid assertions tied to private helpers, a particular prompt, internal call counts, or exact Cypher formatting unless those details form an explicit external contract.
- Test both requested behavior and existing invariants. Do not weaken or hide existing tests to force a result.
- Identify the exact repository snapshot and tested commit. Distinguish a check that ran from one that was merely selected or proposed.
- Isolate future scenario answers and expected results from the investigator. Test the isolation as observable non-disclosure.
- Use additional narrow tests only where a failure is difficult to establish meaningfully through the main workflow boundary, such as an atomic authorization race. Do not create new seams merely to mirror module internals.

### Behavior covered through the main boundary

| Scenario | Observable result |
|---|---|
| Initial source import | Connected demo records enter FalkorDB with versioned content and provenance |
| Repeated import or duplicate event | One logical record or operation; no duplicate ticket, worker, or PR |
| Source edit, deletion, or access loss | Current applicability and evidence availability change without silently treating stale content as authoritative |
| Ambiguous identity | The uncertainty remains visible and records are not silently merged |
| Approved decision versus newer proposal | The approved applicable rule is retained; the proposal is not silently promoted |
| Scoped supersession | The report-export change does not remove the invoice restriction |
| Similar unrelated discussion | No unsupported claim of a confirmed contradiction |
| Shared permission helper | The investigation surfaces invoice impact before implementation |
| Missing product decision | The workflow asks a focused question and does not begin unresolved-scope implementation |
| Ticket approval | Only the exact approved revision starts execution |
| Ticket changes after approval | Execution rejects stale approval and returns to scope review |
| Feature implementation | Agreed report-export behavior passes and existing invoice restrictions remain intact |
| Implementation failure | Actual output is retained; bounded repair stays within scope or requests a scope revision |
| PR review revision | The updated commit receives fresh checks |
| Changed head after authorization | The stale merge authorization does not merge a different commit |
| Required GitHub check/review absent | The merge does not proceed merely because Slack authorization exists |
| Restart or uncertain external response | The request resumes or reconciles without duplicate external effects |
| Graph outage | Investigation reports insufficient graph access instead of giving a hardcoded supported-looking answer |
| Future fixture or golden answer | Initial investigation cannot retrieve it or use it as approval |
| Subsequent request | The new scoped decision and implementation outcome are retrievable with provenance |

### Modules exercised and prior art

The main boundary exercises connectors, ingestion, ontology mapping, entity resolution, graph retrieval, investigation, Slack interactions, ticket revisions, approval checks, worker execution, PR handling, and recovery as an integrated behavior.

The current project contains planning documents only. There are no existing executable modules, tests, framework conventions, domain glossary file, or ADRs in this project to cite as test prior art. The documented permission scenario supplies the initial acceptance fixture, not an existing tested implementation. Select a framework after the implementation language is selected.

### Evaluation decisions

Compare request-only, flat-history, and graph-context runs with the same model, repository, existing tests, tools, and execution budget. Record evidence/path correctness, clarification quality, preserved behavior, actual check outcome, latency, and model/tool usage.

Report all observed results, including baseline success. A supplied vulnerable patch demonstrates a regression but does not prove that the baseline agent generated it. A single scenario supports a specific demonstrated result rather than a general claim of fewer software defects.

## Out of Scope

- Detailed business-role hierarchy and approver-permission design, explicitly deferred by the user.
- Implementing code, generating the full dataset, populating external demo sources, or executing a merge as part of this specification-writing task.
- Creating or updating ChatGPT Spaces or Pages.
- Claiming arbitrary-codebase understanding, complete dynamic call graphs, universal ingestion support, or production readiness from the POC.
- Treating installed connectors as implemented ingestion pipelines without verified coverage.
- Unattended changes to product policy, automatic acceptance-criteria weakening, or bypassing repository merge requirements.
- Presenting synthetic approvals, scripted answers, replayed outcomes, or proposed tests as live authorization or successful execution.
- Multi-tenant SaaS onboarding and production deployment of the changed application in the initial proposed POC.

## Further Notes

- Team size is 2–4 and the project name is Actron. The one-workspace/repository/language limit and complete initial connector inventory remain proposals.
- The full synthetic dataset remains an outstanding deliverable. It must cover source history, identities, approved/unapproved/superseded decisions, repository dependencies and tests, and isolated future workflow events and evaluator answers.
- The ontology creation approach is unresolved. The conversation discussed manual, generated, and mixed approaches, but the user redirected planning to the flow without selecting one. Do not implement a recommendation as an accepted choice.
- The exact sync method, freshness targets, deletion/retention semantics, entity-resolution rules, coding worker/model, deployment, and transactional execution-state mechanism remain to be selected.
- Project-admin membership and cross-project access semantics are unresolved acceptance details. The demo must make them explicit before treating related permission checks as agreed requirements.
- The intended full flow includes authorized merge. Existing POC planning leaves a reviewed-PR fallback as a possible demonstration boundary; resolve that boundary before claiming the complete flow is delivered.
- The project issue tracker and triage-label configuration are absent. Publication is pending setup. Linear is part of the proposed product workflow; that does not establish it as this project's configured issue tracker.
- The invoked to-spec skill requires running `/setup-matt-pocock-skills` when the issue tracker and triage vocabulary are not configured. Once configured, publish this spec to that tracker with its mapped `ready-for-agent` label; no issue or external label has been created in this task.
- Architecture and acceptance decisions not established in the conversation are explicitly unresolved rather than filled with invented approvals. The primary testing boundary is confirmed.
