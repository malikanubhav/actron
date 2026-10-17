# 04: Clarify a request using decision and dependency evidence

**What to build:** A request for project-admin report exports joins decision history and code impact, producing a focused scope question in the request thread before coding starts.

**Blocked by:** 02: Connect Linear history to Slack decision evidence; 03: Show shared code impact and relevant tests from GitHub.

**Status:** Draft — awaiting breakdown approval and project tracker setup.

## Acceptance criteria

- [ ] A feature or bug request creates one durable request and dedicated Slack thread linked to the evidence snapshot and repository base commit.
- [ ] Retrieve the approved Finance-only decision, its source provenance, the shared invoice helper, relevant checks, and known gaps from FalkorDB.
- [ ] Ask whether report export should expand while invoices remain Finance-only; unresolved project membership or cross-project semantics remain explicit.
- [ ] Persist the clarification response with its request and evidence references.
- [ ] Do not start coding while consequential product scope is unresolved; compatible requests with sufficient evidence can proceed without unnecessary questions.
- [ ] Boundary checks cover the genuine conflict, similar unrelated evidence, missing critical evidence, and graph/source failures.
