# Specs

Actron is specified in three major specs. Each has numbered acceptance criteria; every test names the ids it covers, and `scripts/spec_coverage.py` fails if an id has no test.

| Spec | Covers | Criteria |
|---|---|---|
| `A-graph-and-ingestion.md` | platform, PostgreSQL, ontology loader, graph store, ids, code and git ingestion, GitHub, Slack, Linear, connect flow, incremental sync, linking, models | `A-AC-1` … `A-AC-105` |
| `B-agents-and-workflow.md` | request flow on Temporal, events, shared query, MCP tools, investigator, questions, tickets, approvals, Pi build, write-back, Slack bot, API, auth, notifications, bonus | `B-AC-1` … `B-AC-91` |
| `C-experience.md` | design system, components, screens, data flow, accessibility, performance, Slack presentation, setup guides | `C-AC-1` … `C-AC-57` |

Screen specs written during the frontend phase live in `screen-<name>.md`.

How a test names its criteria: put the id in the test name or docstring, for example `def test_upsert_twice_keeps_ingested_at():  """A-AC-16"""`, or in a Vitest/Playwright title `it('C-AC-11 shows the stale state', ...)`.

Run the coverage check: `make coverage`.
