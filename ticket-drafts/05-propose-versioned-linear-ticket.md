# 05: Propose and revise a Linear ticket from the Slack thread

**What to build:** After clarification, the user reviews a real Linear ticket containing the requested behavior, preserved constraints, evidence, affected code, and validation plan, and can request a scope revision in Slack.

**Blocked by:** 04: Clarify a request using decision and dependency evidence.

**Status:** Draft — awaiting breakdown approval and project tracker setup.

## Acceptance criteria

- [ ] Include the objective, acceptance criteria, invoice restriction, affected components, source evidence, selected checks, and unresolved decisions in the proposed issue.
- [ ] Link the issue in Slack and retain its immutable canonical scope snapshot, revision identity, and content hash in the graph.
- [ ] A requested edit produces a new inspectable revision rather than silently overwriting previously presented scope.
- [ ] Report creation/update errors honestly and identify an issue as created only after confirmation from the provider.
- [ ] Boundary checks verify the request-to-clarification-to-ticket chain and differences between successive revisions.
- [ ] A dedicated live Linear write smoke check establishes that the demonstration issue exists.
