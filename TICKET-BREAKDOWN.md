# Actron ticket breakdown — review draft

**Status:** Proposed breakdown, 17 October 2026. Not approved, not published, and not labeled ready-for-agent.

**Source:** The Actron specification and conversation. The user confirmed the main workflow testing boundary.

There is no existing executable code to prefactor. Each work item adds or strengthens a user-visible path through source data, graph state, workflow, and observable outputs. Use the confirmed Slack command/interaction boundary, real FalkorDB, and real repository checks where applicable. Provider contract fakes do not establish real connectivity; verify each new provider through a dedicated live smoke check.

The first slice establishes only the runtime and minimal ontology mapping needed for one working path. Later slices extend it. Ontology-generation strategy, model/provider, freshness and deletion semantics, and concurrency mechanisms remain choices to record, not prior user decisions. Detailed roles remain deferred.

## Proposed tickets

1. **[Ask Slack about one ingested decision](ticket-drafts/01-ask-about-an-ingested-slack-decision.md)**
   - **Blocked by:** None.
   - **What it delivers:** A developer asks Actron about report-export policy in Slack and receives the applicable synthetic decision with its original source evidence, retrieved from a real FalkorDB graph.

2. **[Connect Linear history to Slack decision evidence](ticket-drafts/02-connect-linear-history-to-slack.md)**
   - **Blocked by:** 01.
   - **What it delivers:** The Slack investigation connects the originating Linear ticket and Slack discussion as one versioned decision while keeping newer unapproved proposals distinct.

3. **[Show shared code impact and relevant tests from GitHub](ticket-drafts/03-show-shared-helper-impact.md)**
   - **Blocked by:** 01.
   - **What it delivers:** A developer asks about report-export impact in Slack and sees the helper shared by reports and invoices, relevant existing checks, and the repository snapshot supporting the result.

4. **[Clarify a request using decision and dependency evidence](ticket-drafts/04-clarify-request-from-joined-evidence.md)**
   - **Blocked by:** 02, 03.
   - **What it delivers:** A request for project-admin report exports joins decision history and code impact, producing a focused scope question in the request thread before coding starts.

5. **[Propose and revise a Linear ticket from the Slack thread](ticket-drafts/05-propose-versioned-linear-ticket.md)**
   - **Blocked by:** 04.
   - **What it delivers:** After clarification, the user reviews a real Linear ticket containing the requested behavior, preserved constraints, evidence, affected code, and validation plan, and can request a scope revision in Slack.

6. **[Approve the exact ticket revision and reject stale approval](ticket-drafts/06-approve-exact-ticket-revision.md)**
   - **Blocked by:** 05.
   - **What it delivers:** A user approves the ticket revision displayed in Slack, and Actron hands work to execution only when current scope matches that approval.

7. **[Implement an approved change and report actual checks](ticket-drafts/07-implement-approved-change-and-test.md)**
   - **Blocked by:** 06.
   - **What it delivers:** An approved request starts an isolated coding worker that makes a real change, runs the repository checks, and reports its resulting commit and actual outcomes in Slack.

8. **[Repair implementation failures or return a scope revision](ticket-drafts/08-repair-within-scope-or-revise.md)**
   - **Blocked by:** 07.
   - **What it delivers:** When checks fail, Actron reports the failure, attempts bounded repairs inside approved criteria, and returns to clarification and ticket approval if product scope must change.

9. **[Open a PR with ticket, evidence, and real CI results](ticket-drafts/09-open-pr-with-validation-evidence.md)**
   - **Blocked by:** 07.
   - **What it delivers:** A successful implementation produces a real GitHub PR linked to the approved ticket and evidence, with its actual current-head CI status reported in Slack.

10. **[Revise a PR from Slack review feedback](ticket-drafts/10-revise-pr-from-slack-feedback.md)**
   - **Blocked by:** 09.
   - **What it delivers:** A reviewer gives feedback in the request thread, Actron revises the PR inside approved scope, and Slack shows the new commit and fresh validation.

11. **[Authorize and merge only the reviewed current commit](ticket-drafts/11-authorize-and-merge-current-head.md)**
   - **Blocked by:** 09.
   - **What it delivers:** The user authorizes a displayed PR head in Slack, and Actron merges that exact commit only when required checks, reviews, and approved scope agree.

12. **[Reuse the merged scoped decision on a later request](ticket-drafts/12-reuse-merged-scoped-decision.md)**
   - **Blocked by:** 11.
   - **What it delivers:** A later Slack investigation uses the approved report-export exception and its implementation evidence while retaining the independent Finance-only invoice restriction.

13. **[Reflect edited, superseded, or unavailable source evidence](ticket-drafts/13-refresh-edited-decision-sources.md)**
   - **Blocked by:** 02.
   - **What it delivers:** When Slack or Linear changes, a new investigation shows current applicability and availability while retaining versioned history and explaining incomplete coverage.

14. **[Refresh code impact after a repository change](ticket-drafts/14-refresh-code-snapshot-and-impact.md)**
   - **Blocked by:** 03.
   - **What it delivers:** A later Slack investigation uses new code/test relationships after a repository change and does not mix incompatible commit snapshots.

15. **[Resume ticket and approval work after retries or restart](ticket-drafts/15-recover-ticket-and-approval-workflow.md)**
   - **Blocked by:** 06.
   - **What it delivers:** After redelivery or restart during ticket creation or approval, Actron resumes the same thread with one issue, the correct revision, and one execution handoff.

16. **[Reconcile interrupted execution, PR, and merge operations](ticket-drafts/16-reconcile-interrupted-execution-and-merge.md)**
   - **Blocked by:** 11, 15.
   - **What it delivers:** After restart or a lost provider response during execution, PR creation, or merge, Actron reconciles the existing operation and reports its actual outcome without duplicate work or stale authorization.

17. **[Reproduce the complete demo and compare context approaches](ticket-drafts/17-reproduce-full-demo-and-evaluate.md)**
   - **Blocked by:** 08, 10, 12, 13, 14, 16.
   - **What it delivers:** A fresh reviewer can populate the synthetic sources, run the complete Actron flow, inspect real results, and reproduce a fair request-only versus flat-history versus graph-context comparison.

## Dependency rationale

- Ticket 01 establishes the first working source-to-graph-to-Slack path.
- Tickets 02 and 03 can proceed independently and join only at ticket 04.
- Tickets 08 and 09 independently extend actual execution: automatic repair does not gate a PR from a successful run.
- Tickets 10 and 11 independently extend a real PR: a feedback-driven code revision is not required before a PR can be reviewed and authorized for merge.
- Tickets 13 and 14 start after their source slices, without waiting for coding or merge.
- Ticket 15 hardens ticket/approval recovery. Ticket 16 combines that with execution, PR, and merge recovery.
- Ticket 17 depends on the remaining terminal capabilities; ancestors are not repeated as redundant blockers.

## External prerequisites

Source workspace/project/repository access, provider credentials, and model/runtime availability are external prerequisites, not fictional completed tickets. Ticket 01 can begin when its Slack/runtime/FalkorDB access is available. Later live-provider slices require their own access.

The full target includes authorized merge. A reviewed-PR-only fallback must be an explicit scope change rather than a claim that the full specification is delivered.

## Review before publication

- Is the granularity appropriate, too coarse, or too fine?
- Are these genuine blocking edges?
- Should any tickets be merged or split?

Full per-ticket drafts are saved for review. They are not a configured local tracker, have not been approved, and do not have ready-for-agent status.

## Publication configuration

No issue tracker or triage-label mapping is configured for this project. Run `/setup-matt-pocock-skills` before publication. Do not infer the tracker from Actron's product integrations.

After breakdown approval and setup, publish one ticket per file or external issue in dependency order. For a real tracker, use native blocking relationships where supported. Apply the configured ready-for-agent label at publication. Do not close or modify any parent issue. Do not create ChatGPT Spaces or Pages.
