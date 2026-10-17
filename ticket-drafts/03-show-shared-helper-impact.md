# 03: Show shared code impact and relevant tests from GitHub

**What to build:** A developer asks about report-export impact in Slack and sees the helper shared by reports and invoices, relevant existing checks, and the repository snapshot supporting the result.

**Blocked by:** 01: Ask Slack about one ingested decision.

**Status:** Draft — awaiting breakdown approval and project tracker setup.

## Acceptance criteria

- [ ] Provide a reproducible synthetic repository containing the shared helper, report and invoice behavior, existing regression tests, CI definitions, and small labeled history including a historical PR/review example.
- [ ] Ingest the selected GitHub snapshot and available history into FalkorDB with repository identity, commit references, content, and versioned provenance.
- [ ] Connect behaviors, symbols, calls, tests, and CI references through a minimal ontology compatible with the initial source-to-graph slice.
- [ ] Return both affected behaviors, relevant check IDs, and source anchors from a coherent repository snapshot in Slack.
- [ ] Distinguish extracted, curated, and unresolved links and disclose bounded or dynamic dependency coverage.
- [ ] Run the existing suite in a real disposable checkout before feature changes and keep the invoice regression test available to all evaluation variants.
- [ ] Verify the workflow boundary with real FalkorDB/repository checks and a live GitHub read smoke run.
