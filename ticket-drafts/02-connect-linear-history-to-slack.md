# 02: Connect Linear history to Slack decision evidence

**What to build:** The Slack investigation connects the originating Linear ticket and Slack discussion as one versioned decision while keeping newer unapproved proposals distinct.

**Blocked by:** 01: Ask Slack about one ingested decision.

**Status:** Draft — awaiting breakdown approval and project tracker setup.

## Acceptance criteria

- [ ] Populate synthetic Linear issues and revisions in a dedicated demo project and fetch them through a connector, with a live-read smoke check.
- [ ] Use stable source IDs and explicit references to connect tickets, discussions, project, and behavior rather than merging solely by matching names.
- [ ] Show approved applicable scope, unapproved newer proposals, and superseded historical decisions distinctly in Slack.
- [ ] Preserve supporting source revisions, extraction method, certainty, and minimal ontology mapping for normalized decisions and relationships.
- [ ] Keep ambiguous person or feature matches unresolved and visible rather than silently merging entities.
- [ ] Boundary checks prove that a newer unapproved proposal cannot replace the approved rule, unrelated similar discussion is not a proven conflict, and re-ingestion stays idempotent.
- [ ] Document the supported source record inventory and import coverage limits.
