# 12: Reuse the merged scoped decision on a later request

**What to build:** A later Slack investigation uses the approved report-export exception and its implementation evidence while retaining the independent Finance-only invoice restriction.

**Blocked by:** 11: Authorize and merge only the reviewed current commit.

**Status:** Draft — awaiting breakdown approval and project tracker setup.

## Acceptance criteria

- [ ] Link the resulting decision to the clarification, approved revision, implementation, checks, PR, and confirmed merge.
- [ ] Limit supersession to the relevant export behavior instead of globally replacing the invoice constraint.
- [ ] A fresh investigation retrieves the new applicable scope with provenance rather than treating the obsolete export restriction as current.
- [ ] Retain historical policy and approval evidence and distinguish effective applicability from source recency.
- [ ] Boundary checks perform a second investigation after merge and assert updated export scope and preserved invoice scope.
