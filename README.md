# Actron

Local planning folder for Actron, the FalkorDB hackathon project. The project name was selected on 17 October 2026.

Repository: [malikanubhav/actron](https://github.com/malikanubhav/actron).

## Documents

- [TICKET-BREAKDOWN.md](TICKET-BREAKDOWN.md): proposed dependency-ordered slices with complete unpublished ticket drafts.
- [SPEC.md](SPEC.md): consolidated specification, extensive user stories, confirmed workflow testing boundary, and publication status.
- [POC.md](POC.md): demonstration flow, proposed architecture, implementation stages, and validation.
- [PRD.md](PRD.md): product problem, user experience, scope, and success criteria.
- [REQUIREMENTS.md](REQUIREMENTS.md): ingestion, ontology, graph, integrations, execution, infrastructure, and dataset requirements.

## Current agreement

Ingest information from connected sources, create an ontology, and store the source content and relationships in FalkorDB. Use that graph to investigate requests in Slack, clarify conflicts, propose a Linear ticket, and carry the approved scope through implementation, testing, PR review, and authorized merge.

Synthetic company data will supply the demonstration sources. It should pass through connectors so the POC demonstrates ingestion as well as graph reasoning.

An explicitly approved decision establishes the current rule. A newer unapproved ticket remains a proposal. Detailed roles and approver permissions are deferred at the user's request.

## Status

Drafts saved on 17 October 2026. The flow and detailed architecture remain under discussion. These documents do not claim that the dataset, agent, connectors, tests, or deployment have been built.

Maintain project artifacts as repository files and push to GitHub when authorized. Do not create or update ChatGPT Spaces or Pages.

## Next planning step

Confirm the end-to-end flow, then decide the ingestion and ontology mechanisms. Record proposed choices separately from confirmed decisions.
