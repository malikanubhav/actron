# 16: Reconcile interrupted execution, PR, and merge operations

**What to build:** After restart or a lost provider response during execution, PR creation, or merge, Actron reconciles the existing operation and reports its actual outcome without duplicate work or stale authorization.

**Blocked by:** 11: Authorize and merge only the reviewed current commit; 15: Resume ticket and approval work after retries or restart.

**Status:** Draft — awaiting breakdown approval and project tracker setup.

## Acceptance criteria

- [ ] Persist worker ownership/run identity so redelivery or restart does not give two workers ownership of one request.
- [ ] Rediscover an existing PR after an uncertain creation result instead of creating a duplicate.
- [ ] Reconcile an uncertain merge against actual PR state and commits; do not blindly repeat a completed merge.
- [ ] Never reuse authorization for a changed head or promote unknown validation to success during recovery.
- [ ] Report recovered, failed, or still-unknown state with evidence in the original thread.
- [ ] Boundary checks inject failure around worker handoff, PR creation, and merge and assert external effects are not duplicated.
