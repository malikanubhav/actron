# 08: Repair implementation failures or return a scope revision

**What to build:** When checks fail, Actron reports the failure, attempts bounded repairs inside approved criteria, and returns to clarification and ticket approval if product scope must change.

**Blocked by:** 07: Implement an approved change and report actual checks.

**Status:** Draft — awaiting breakdown approval and project tracker setup.

## Acceptance criteria

- [ ] Use a controlled test stimulus that produces a real failing implementation/check result; label it as a stimulus rather than claiming the baseline agent generated it.
- [ ] Retain failed output and commit, then validate any repaired implementation against the invoice restriction and requested feature.
- [ ] Return changed acceptance criteria or preserved constraints as a new ticket revision that cannot reuse old scope approval.
- [ ] Report repair attempts and exhausted retry, time, or spend limits in the request thread.
- [ ] Do not remove or weaken existing regression assertions simply to obtain passing checks.
- [ ] Boundary checks cover successful in-scope repair, a scope-changing repair requiring renewed approval, and exhausted repair limits.
