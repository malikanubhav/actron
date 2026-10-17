# Implementation plan

Baseline: `daf8490` on `main`. User authorized all 17 ticket drafts and a commit.
This document records implementation choices, rather than earlier product agreements.

1. Establish Python 3.12, repeatable FalkorDB startup, shared provider contracts,
   and connector-backed synthetic sources (tickets 01–03).
2. Implement provenance, explicit scoped decision mapping, revision/update ingestion,
   coherent repository snapshots and evidence retrieval (01–04, 13–14).
3. Implement durable Slack request, clarification, immutable ticket revisions,
   approval and recovery gates (04–06, 15).
4. Implement bounded isolated coding, real checks, repair and PR/review handling
   with current-head merge authorization and operation reconciliation (07–12, 16).
5. Add reproducible demo sources, public-ingress integration tests against real
   FalkorDB/repositories, provider live-smoke commands and comparison tooling (17).
6. Run types and focused tests throughout; full suite at completion. Review against
   baseline on standards and spec in parallel; address findings and commit.

Confirmed test seam: Slack command/interaction ingress and externally visible
messages, graph evidence, provider state, and actual disposable repository checks.
Narrow concurrency/provider security tests only where ingress cannot expose a race.

Modules: contracts.py; graph.py/ingestion.py/connectors.py; workflow.py/ingress.py;
worker.py/github.py; cli.py; demo/; tests/; docs/.

Risks: live credentials/model may be absent; provider success must remain unverified
until a live smoke succeeds. Unknown writes must reconcile. Current scope/head and
fresh check/review requirements are fail-closed. Explicit demo identity binding is
not a general role system. No merge of this Actron repository is authorized here.

Rollback: stop local runtime, revert implementation commit; graph volumes and
dedicated external demo resources are independent and retain their audit history.

Progress: all six implementation steps completed locally. Types and focused
tests passed throughout; standards/spec reviews completed and their findings
resolved. Real container replacement exposed and verified fixes to persistence
configuration and query replay. Final Python 3.12 validation (62 passing tests) is recorded
in the implementation review before commit. The user deferred credentialed live
acceptance until later UI configuration; no live provider/model result is claimed.
