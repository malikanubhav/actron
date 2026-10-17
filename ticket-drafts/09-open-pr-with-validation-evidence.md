# 09: Open a PR with ticket, evidence, and real CI results

**What to build:** A successful implementation produces a real GitHub PR linked to the approved ticket and evidence, with its actual current-head CI status reported in Slack.

**Blocked by:** 07: Implement an approved change and report actual checks.

**Status:** Draft — awaiting breakdown approval and project tracker setup.

## Acceptance criteria

- [ ] The PR branch/head corresponds to worker output and the exact approved ticket revision.
- [ ] Describe the requested behavior, preserved invoice constraint, source evidence, and actual validation in the PR.
- [ ] Distinguish pending, failed, missing, and successful checks and associate them with the correct head.
- [ ] Report a confirmed PR URL and head; do not present fake or unconfirmed provider responses as a live PR.
- [ ] Boundary checks verify the ticket-to-commit-to-checks-to-PR chain, including a CI failure.
- [ ] A dedicated live-repository smoke run verifies real PR creation and check retrieval.
