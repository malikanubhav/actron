# 15: Resume ticket and approval work after retries or restart

**What to build:** After redelivery or restart during ticket creation or approval, Actron resumes the same thread with one issue, the correct revision, and one execution handoff.

**Blocked by:** 06: Approve the exact ticket revision and reject stale approval.

**Status:** Draft — awaiting breakdown approval and project tracker setup.

## Acceptance criteria

- [ ] Persist request/thread identity, phase, ticket revisions, approvals, external IDs, and deduplication keys in the intended persistent graph-backed workflow design.
- [ ] Reconcile a lost issue-creation response against its operation identity before creating another issue.
- [ ] Prevent duplicate commands, clarification events, and approval interactions from duplicating revisions or execution handoffs.
- [ ] Show current durable state after restart and never obtain approval of an unseen changed revision.
- [ ] Boundary checks interrupt provider writes and approval persistence and assert correct recovered external behavior.
- [ ] Document and validate atomic-transition and concurrency assumptions instead of relying on an untested read-then-write sequence.
