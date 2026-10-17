# Implementation review

Baseline: `daf8490052feb83976928ade963dcebaec43405c`, the clean starting commit
on `main`. Since the implement workflow requires review before its final commit,
reviewers inspected `git diff <baseline>` including intent-to-add files. There
were no intervening implementation commits. The fixed point was resolved and
the nonempty diff checked before spawning independent reviewers.

Sources: `SPEC.md`, all 17 `ticket-drafts`, `README.md`, and the implementation
plan. This repo has no separate coding standards or configured issue tracker;
the checked-in ticket drafts are the authorized spec source. The Fowler smell
baseline was supplied to the Standards reviewer. No tracker publication occurred.

## Standards

Initial findings, reported separately from the Spec axis:

1. **P1: Uncertain operations could lose ownership.** A new revise/investigate
   event could overwrite a pending worker or merge. This violated the plan's
   requirement that unknown writes reconcile. **Resolved:** pending operations
   reject new mutations; recovery/status remain available. A signed-ingress
   regression confirms the operation and single external issue survive.
2. **P2: Interrupted PR revision could not complete.** Finding the prior PR
   operation at its old head prevented recovery. **Resolved:** recovery revalidates
   scope and completes the same-branch upsert when the existing head predates
   validated worker output. A real-repository regression retains one PR.
3. **P2: Source lifecycle tests bypassed the confirmed observation seam.**
   **Resolved:** source fixture setup still imports through connectors, but
   investigation observations now use signed Slack ingress, real workflow,
   emitted messages and durable graph outputs. Only graph injection safety,
   provider authentication and worker ownership/security use narrow boundaries.

No additional material heuristic smells were reported. JSON payload primitives
are documented by the public contracts; independent boundary gates are intentional.
Final focused review: **no unresolved material Standards findings**.

## Spec

Initial findings, reported separately from the Standards axis:

1. **P1: Pending reconciliation could create duplicate issues.** Ticket 15
   requires one issue and reconciliation before retry. **Resolved:** the same
   pending-operation gate preserves the original journal and provider identity.
2. **P1: Approval details were missing from rendered Slack messages.** Tickets
   06/11 require the exact displayed revision/current PR head. Slack renders
   blocks and uses top-level text as notification fallback. **Resolved:** visible
   section blocks now contain the inspectable scope/hash/head beside the button;
   scope presentation must be confirmed before approval is accepted.
3. **P2: Recovery lost feedback before worker startup.** Ticket 10 requires the
   feedback-to-revision chain. **Resolved:** effective feedback is journaled with
   the worker operation and supplied after restart. The fault-injection regression
   resumes an actual worker with the original feedback and fresh checks.

No scope creep was identified. Final focused review: **no unresolved material
Spec findings**. Live provider/model acceptance is explicitly deferred by the user;
the local video and backend verification do not represent live SaaS results.

## Persistence verification

Actual deployment testing found two additional defects and verified their fixes:
the pinned image ignores arbitrary Compose command arguments, so configuration
now uses `REDIS_ARGS`; and its parameter-prefixed writes were truncated in AOF,
so trusted templates now use single-pass JSON literal binding. Injection tests
preserve quotes, control characters, Unicode and literal parameter-like strings.
The Python 3.12 persistence smoke verified AOF and the mounted data directory,
removed/replaced a dedicated container, and retrieved its identical graph record.

## Validation

- Full suite: **62 passed**, Python **3.12.3**, pytest **9.1.1**; real FalkorDB
  **4.12.0** and actual disposable repository checks. No skipped tests.
- Python 3.12 mypy: all **12** source files pass. Ruff: source, tests and scripts pass.
- Independent deployment persistence smoke: passed across container removal and
  replacement, with effective AOF configuration and mounted data directory verified.
- Actual default Docker worker smoke: baseline and changed-commit suites passed;
  the coding patch was an explicitly labeled controlled stimulus.
- Refreshed local demo: **48** workflow/ingress tests passed; captured trace, raw
  output, self-contained HTML replay and **48-second MP4** under `.actron/demo.*`.
  The artifact is generated locally and excluded from Git; its reproduction
  script is versioned. Provider effects and coding stimuli are visibly labeled.
- `git diff --check` passes. The checked-in Compose deployment also started
  successfully and ingested all eight synthetic source records.

Live Slack/Linear/GitHub writes, real model generation and comparative outcome
measurements were not run; the user explicitly deferred credentials until later
UI integration. See the per-ticket acceptance inventory for those pending checks.

Original findings: Standards 3, Spec 3. Outstanding material findings: Standards
0, Spec 0. Each axis was rechecked independently after corrections.
