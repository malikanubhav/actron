# 06: Approve the exact ticket revision and reject stale approval

**What to build:** A user approves the ticket revision displayed in Slack, and Actron hands work to execution only when current scope matches that approval.

**Blocked by:** 05: Propose and revise a Linear ticket from the Slack thread.

**Status:** Draft — awaiting breakdown approval and project tracker setup.

## Acceptance criteria

- [ ] Record an explicit interaction against the request, ticket revision, canonical scope hash, repository/base snapshot, event identity, and time.
- [ ] Refresh relevant ticket content before execution and reject approval covering a materially changed revision.
- [ ] Do not accept historical fixtures, quoted approval text, or stale interaction references as current execution authorization.
- [ ] Show whether work is approved, awaiting approval, or awaiting approval of a revised scope in the thread.
- [ ] Boundary checks cover matching approval, external ticket edit, an old interaction/revision, and duplicate approval delivery with one execution handoff.
- [ ] Keep detailed roles deferred and label any minimal demo identity binding as a POC mechanism rather than an agreed role hierarchy.
