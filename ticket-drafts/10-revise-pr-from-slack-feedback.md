# 10: Revise a PR from Slack review feedback

**What to build:** A reviewer gives feedback in the request thread, Actron revises the PR inside approved scope, and Slack shows the new commit and fresh validation.

**Blocked by:** 09: Open a PR with ticket, evidence, and real CI results.

**Status:** Draft — awaiting breakdown approval and project tracker setup.

## Acceptance criteria

- [ ] Associate feedback with the correct request, PR, and reviewed commit.
- [ ] Update the PR for an in-scope revision and run fresh relevant checks plus the complete small repository suite.
- [ ] Retain older check records as history without presenting them as validation of the new head.
- [ ] Return product-scope changes to ticket revision and approval before implementing those changes.
- [ ] Persist and report the feedback-to-revision-to-validation chain and updated PR.
- [ ] Boundary checks cover one real code revision and one scope-changing review request without requiring automatic failure-repair behavior.
