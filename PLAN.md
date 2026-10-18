# Actron: live plan

The base for the build. `PRD.md` says what we build; `PROMPT.md` says how the coding agent builds it; this file says where we are. The coding agent ticks boxes and appends to the decisions log as work lands.

**Deadline:** 18 October 2026, 11:59 PM IST. No new features in the last 6 hours.
**Rules:** no commits or pushes unless the user asks; no secrets in tracked files; PRs only to the fork; only public, synthetic or own data in the graph.

Legend: [x] done · [~] in progress · [ ] not started · [!] blocked on the user (see `NEEDS-FROM-USER.md`)

## Done before the build (17 Oct 2026)
- [x] Project folder `~/Desktop/actron`, local git repo (no commits), `.gitignore`
- [x] PRD v2 (consolidated), `PROMPT.md` v2 (unattended, spec-driven, subagent-ready, large test suite)
- [x] FalkorDB runs in Docker (upgraded to v4.22.1, see below) with persistence; limits raised (15 s default timeout, queue of 2000)
- [x] Python dependencies resolve with uv
- [x] Eight design skills installed in `.claude/skills/`; Impeccable hooks off
- [x] `.claude/settings.json` allows every command and tool; denies commits, pushes, remote and git config changes, `gh`, `sudo` and the fabric folder (run in automatic mode)
- [x] `.env.example` with every variable
- [x] Ontology: `slack.json` and `linear.json` exported from fabric (Slack names prefixed), `github.json`, `code.json`, `core.json` written; cross-checked (96 node types; core expands to 287 links after the run 1 and run 2 fixes)
- [x] `prompts/ONTOLOGY-SAMPLE-DATA-PROMPT.md` rewritten for real data (user chose option A, 17 Oct 2026): real `BetterThanTomorrow/calva` code and GitHub history (MIT), real `#calva` Slack history from the public Clojurians archive (polite collection, pseudonymised authors, converted to Slack export format), synthetic Linear and fork PRs grounded in them; ground-truth labels; 30+ competency questions. Pants' archive was rejected because it blocks scripts with a bot challenge.
- [x] Slack export import added as a product feature (spec A, A9a; A-AC-89 to 91)
- [x] Multi-language parsing: tier 1 Python, TypeScript, TSX, JavaScript, Go, Java, Rust; tier 2 Kotlin, Ruby, PHP, C, C++, Scala, Swift, Clojure (`tree-sitter-language-pack`, grammars verified)
- [x] Hardening run 1 (17 Oct 2026, `data/sample/`, built from the earlier Flask version of the prompt: real Flask GitHub data, synthetic Slack and Linear). Results: all 1,403 labelled links representable (0 misses, 0 guessed types); loaded into FalkorDB (910 nodes, 1,389 relationships); 23 of 34 competency questions fully connected, 4 depend only on code-parsing links, the other 7 explained by check method or by non-link label files, with one real gap (review comments on moved code). Seven ontology fixes applied from the data agent's notes and this run: link tombstones (`deleted`, `deletedAt`), partial supersession (`active`, `supersededBy` on CONSTRAINS), `LinearIssue.attachmentUrls`, `GitCommit.inClone` for commits from the API, `FORK_OF`, mapping review comments through renames, Linear previous versions. Spec A criteria A-AC-101 to 104.
- [x] FalkorDB behaviour verified against the docs (three reads) and live: shortestPath only in WITH/RETURN and only directed; undirected paths via `algo.SPpaths` with `relDirection: 'both'`; `algo.BFS` outgoing only, so callers use backwards variable-length matches; `algo.pageRank('Label','REL')`; full-text indexes per label. Recorded in `docs/falkordb.md` (kept current by the build).
- [x] FalkorDB upgraded from v4.12.0 to v4.22.1 (the current `latest`, which the hackathon page recommends), pinned; same limits re-tested; persistence bug not reproduced; running container recreated with our settings.
- [x] Hardening run 2 (17 Oct 2026, `data/sample-calva/`: real Calva code and 80 PRs, 1,023 real pseudonymised `#calva` Slack messages, synthetic Linear and fork PRs; its own 9 validation checks passed). Results: 596 of 643 labelled links representable directly; the other 47 attach to accounts where the ontology routes through `Person`/`Identity` by design (every account gets a Person, A12.1), so not gaps. 21 of 35 competency questions fully connected; 3 need code-parsing links; the other 11 are covered by existing design or fixed. Five additive ontology fixes: `Reference.kind` value `slack_message`, `SlackChannel.aliases`, `SlackMessage.botId`, `LEARNED_FROM_TEXT` (Procedure → any text), `DECISION_IMPLEMENTED_BY` (Decision → commit or PR, via new node group `ChangeRecord`). Spec A rules and A-AC-106 added. Run 1 still passes 1,403 of 1,403.
- [x] Both sample datasets deleted after the checks (17 Oct 2026).
- [ ] (superseded) Hardening run 2: user runs the Calva version of the prompt in a fresh session; dataset lands in `data/sample-calva/`; then the same checks
- [ ] Delete `data/sample/` and `data/sample-calva/` only after run 2 is checked (all of `data/` is git-ignored; the build agent ignores it)
- [ ] Later: identity across platforms when names and emails differ (GitHub login, Linear name, Slack display name, email case). Current design: lowercased email match, then `config/identity_map.yaml`, never names alone; ambiguous accounts stay unresolved. Planned follow-up: a "People" screen in Settings that suggests matches for a person to confirm.
- [ ] [!] User review and freeze of the ontology files
- [x] Three major specs written before the build run: `specs/A-graph-and-ingestion.md` (106 acceptance criteria), `specs/B-agents-and-workflow.md` (91), `specs/C-experience.md` (57)
- [x] Ontology gaps found while writing spec A and fixed: Slack message author (`POSTED_BY`), message versions (`PREVIOUS_VERSION`), Linear creator and sub-issues, missing properties on fabric nodes (tagged `addedBy: actron`), `Decision.scope`/`statementHistory`, link `flag`

## Build phases (from `PROMPT.md` section 7)
- [x] 0 Layout and housekeeping (move to `backend/`, `frontend/`, `infra/`; Makefile; logs)
- [x] 1 Specs and contracts (every spec in PRD 17; shared query, API, events, design system frozen)
- [x] 2 Platform: compose with PostgreSQL, Redis and Temporal, config, logging, migrations, graph store, ontology loader, indexes, persistence test
- [x] 3 Models: Jev, LiteLLM, stubs, cache, usage
- [x] 4 Code ingestion with tree-sitter (tier 1 and tier 2 languages; Calva: TypeScript and Clojure), chunks, tests links, docs, metrics
- [x] 5 Git history, touched functions, blame, CODEOWNERS
- [x] 6 GitHub connector
- [x] 7 Slack connector and bot
- [x] 8 Linear connector
- [x] 9 Connect flow and incremental sync
- [x] 10 Linking: identity, references (pending resolution), meaning links, decisions, link checks
- [x] 11 Request flow, MCP graph server, investigator agent and fallback, tickets, approvals
- [x] 12 Build with Pi, write-back
- [x] 13 API, auth, SSE, worker, CLI
- [x] 14 Frontend: design system, every screen, review loops
- [x] 15 End-to-end and hardening (green three times)
- [x] 16 Bonus tracks 02 and 03
- [x] 17 Docs, deployment configuration, build report

## Track 01 checklist (required)
- [x] Multi-hop reasoning in one query
- [x] Graph queries and algorithms as agent tools (BFS, PageRank, shortest path)
- [x] Tool selection through MCP, visible in the UI
- [x] Actions based on the graph (questions, ticket, code change, PR)
- [x] Explainable results (path and quote for every finding)

## Waiting on the user
See `NEEDS-FROM-USER.md` (created by the build). Known: ontology review; Slack app, tokens and channels; GitHub token and fork; bot identity for commits; Linear key and team; model keys per job; Jev key (`TYPESAFE_API_KEY`); demo repo confirmation; deployment target; visual direction confirmation.

## Decisions log
- 2026-10-17: FalkorDB for the graph; PostgreSQL for app and workflow state (confirmed by the user); Redis for SSE fan-out, idempotency, sessions and cache (queues, locks and retries are Temporal's).
- 2026-10-17: Ontology defined in advance as files, never generated at runtime. Fabric's Slack and Linear ontologies used as is (Slack names prefixed); GitHub, code and core are ours.
- 2026-10-17: Python tree-sitter, no Rust. Function ids from qualified names, not line numbers.
- 2026-10-17: Pi in Docker is the coding agent; graph tools over MCP; the investigator is also an MCP-tool agent with a deterministic fallback.
- 2026-10-17: Jev (TypeSafe, `typesafe-sdk`, pinned `jev-1.13.0`) for judgments; LiteLLM for text; stubs when no key.
- 2026-10-17: Fresh connector code; fabric read for patterns only.
- 2026-10-17: Incremental sync is core: connect starts backfill, cursors per source, order-independent linking with pending references.
- 2026-10-17: Track 01 is the goal; Tracks 02 and 03 are bonus.
- 2026-10-17: Frontend: Next.js, TanStack Query, Zustand, "Evidence console" design direction (PRD 13.2), JetBrains Mono for data only.
- 2026-10-17: Spec-driven build with acceptance ids mapped to tests; targets of 500+ backend, 200+ frontend unit and 30+ end-to-end tests.
- 2026-10-17: FalkorDB image defaults (1 s timeout, queue of 25) overridden; parameter-prefix persistence caveat tested first.
- 2026-10-17: Unattended run in tmux, reachable over SSH from a phone.
- 2026-10-17: Merged code reaches the graph immediately: GitHub webhook on merge and push, a merge watch for local runs, and a freshness gate before every investigation and build. The ingested repo is the one the team merges into (the fork for the demo); upstream is history only.
- 2026-10-17: Working branch chosen when the repository is connected (for example `dev`); it is the ingested code snapshot, the default target for requests, and the branch watched for merges and freshness. Actron still confirms the target branch before every ticket, working branch first. PRs merged into other branches are recorded but do not change code memory. Changeable in Settings (re-ingests).
- 2026-10-17: Implementation's real repository is Calva (`BetterThanTomorrow/calva`, MIT), the same repo as the ontology check; the sample data itself is never used by the build.
- 2026-10-17: Unattended run in automatic mode (user's choice): `.claude/settings.json` allows every command and tool; deny list only for commits, pushes, remotes, git config, `gh`, `sudo` and the fabric folder. Started in tmux under `systemd-inhibit` so the laptop stays awake.
- 2026-10-17: Final gap review added: onboarding checklist, workspace creation from Slack team, approvers list, daily model budget cap, replay fallback, Slack app manifests, nightly Postgres backup, blog post draft, and production SaaS polish (logo, favicons, Open Graph images, page titles, 404/500 pages, formatting rules, forms, navigation state, responsive landing, cost per build) plus an independent fresh-eyes AI-look audit (PRD 13.9b, 16; spec B B12a; spec C C11).
- 2026-10-17: One build run builds the whole product (specs A, B and C) for consistency and speed. Afterwards Anubhav owns live testing with real keys and fixes for spec B (request flow, Linear tickets, investigator, Pi build, PRs); the user owns spec A (ontology, ingestion, connectors, Slack bot) and the frontend review.
- 2026-10-17: Temporal (self-hosted, free) runs ingestion and the request flow; Pi is one activity inside `BuildWorkflow`. One PostgreSQL container holds the `actron` and `temporal` databases. Redis keeps SSE fan-out, idempotency, sessions and cache.
- 2026-10-17: Deployment: one server, one Compose stack, `make deploy`, Caddy with automatic HTTPS; no managed services required.
- 2026-10-17: ORM is SQLAlchemy 2 with Alembic (Prisma rejected: TypeScript-only, and data rules must live in one backend).
- 2026-10-17: Frontend storytelling is a hard requirement: live system map, visible MCP tool calls, Pi build theatre, real brand logos, custom animated glyphs, public landing page, 3D hero, replay mode, Lighthouse targets enforced in tests.
