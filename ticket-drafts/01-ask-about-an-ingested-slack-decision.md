# 01: Ask Slack about one ingested decision

**What to build:** A developer asks Actron about report-export policy in Slack and receives the applicable synthetic decision with its original source evidence, retrieved from a real FalkorDB graph.

**Blocked by:** None (can start immediately once external prerequisites are available).

**Status:** Draft — awaiting breakdown approval and project tracker setup.

## Acceptance criteria

- [ ] Populate a dedicated Slack demonstration thread with fictional identities, one report-export decision, and historical approval evidence; ingest those source records rather than inserting an expected graph answer directly.
- [ ] Persist source content, IDs, revisions/hashes, timestamps, approval evidence, and minimal ontology mapping in FalkorDB, linked to the report-export behavior.
- [ ] Acknowledge the request and reply in its Slack thread with the applicable decision, supporting text, source locator/version, and uncertainty.
- [ ] Repeat ingestion without duplicate source revisions; a claim does not become approved merely because it appeared in chat.
- [ ] Document the runtime, minimal ontology-creation/mapping choice, startup, and tested persistence assumptions needed for this slice without representing new choices as prior user decisions.
- [ ] Use the confirmed Slack workflow test boundary and real FalkorDB; verify explicit graph-unavailable behavior and a dedicated live Slack smoke check.
- [ ] Keep future answers, current-task approvals, and golden outcomes out of initial investigation; historical fixture approval evidence cannot authorize live execution.
