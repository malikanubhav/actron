# 11: Authorize and merge only the reviewed current commit

**What to build:** The user authorizes a displayed PR head in Slack, and Actron merges that exact commit only when required checks, reviews, and approved scope agree.

**Blocked by:** 09: Open a PR with ticket, evidence, and real CI results.

**Status:** Draft — awaiting breakdown approval and project tracker setup.

## Acceptance criteria

- [ ] Bind explicit final authorization to the request, approved ticket revision, PR, head commit, and relevant validation records.
- [ ] Refresh scope, head, required checks, and reviews before merge; missing, failed, or stale prerequisites prevent the operation.
- [ ] Invalidate old authorization after a head change and require fresh validation and current-head authorization.
- [ ] Enforce expected-head matching at the provider operation boundary so a concurrent push cannot silently change the authorized code.
- [ ] Record a confirmed merge/resulting commit or an explicit rejected, failed, or unknown outcome in Slack and the graph.
- [ ] Boundary checks cover success, changed-head race, missing check/review, and stale scope; live smoke merges use only the dedicated demo repository.
