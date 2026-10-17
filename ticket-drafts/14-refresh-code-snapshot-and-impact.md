# 14: Refresh code impact after a repository change

**What to build:** A later Slack investigation uses new code/test relationships after a repository change and does not mix incompatible commit snapshots.

**Blocked by:** 03: Show shared code impact and relevant tests from GitHub.

**Status:** Draft — awaiting breakdown approval and project tracker setup.

## Acceptance criteria

- [ ] Ingest a second synthetic commit containing a meaningful helper or test relationship change through the GitHub connector.
- [ ] Use one coherent snapshot for current impact/check selection and preserve older evidence as history.
- [ ] Refresh or pause requests with invalidated base/evidence snapshots and explain the state before continuing execution.
- [ ] Keep dynamic/unresolved call coverage and curated test mappings explicit.
- [ ] Boundary checks show changed impact/anchors after refresh and reject a deliberately mixed-snapshot evidence result.
