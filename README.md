# Actron

Evidence-backed change delivery from Slack through FalkorDB, Linear, an isolated coding worker, and GitHub. The backend implements the 17 ticket slices in this repository.

Repository: [malikanubhav/actron](https://github.com/malikanubhav/actron).

## Documents

- [docs/setup.md](docs/setup.md): complete local setup, provider configuration, commands, recovery, and demo recording.
- [docs/ticket-status.md](docs/ticket-status.md): implementation and acceptance status for all 17 tickets.
- [docs/graph.md](docs/graph.md): ontology, provenance, source inventory, coherent snapshots, and persistence.
- [docs/worker.md](docs/worker.md): actual coding, isolation, budgets, checks, PRs, and current-head merge gates.
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

The Python backend, synthetic sources, connector adapters, graph ingestion, durable workflow, isolated worker, comparison runner, and local demo are implemented. Integration tests use real FalkorDB and disposable Git repositories. The repeatable suite simulates external provider effects and uses explicitly labeled coding stimuli.

Live Slack/Linear/GitHub acceptance and measured model comparisons await credentials. The user deferred credentials and intends to connect configuration through a UI later; this change supplies the backend and its setup contract. No hosted deployment or live-provider success is claimed.

```bash
uv sync --frozen
docker compose up -d --wait
uv run actron populate
uv run actron ingest
uv run actron demo
```

Run `bash scripts/check.sh` for types, lint, and the full suite. `uv run python scripts/record_demo.py` records the observed local workflow to `.actron/demo.mp4` and an HTML replay. The video visibly distinguishes real graph/repository/check execution from provider and coding fixtures.

Maintain project artifacts as repository files and push to GitHub when authorized. Do not create or update ChatGPT Spaces or Pages.

The original spec and ticket drafts remain the historical scope. Implementation choices and review findings are recorded under `docs/`; these do not create a product role hierarchy or publish an external issue tracker.
