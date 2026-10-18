# Handoff: everything about Actron as of 18 October 2026

Written so that whoever continues has the same context as the person who started the work. No secret is in this repository. Read this file first; it points to the detailed files.

Deadline: the FalkorDB Graph Hacks submission closes **18 October 2026, 11:59 PM IST**.

---

## 1. What Actron is, and why

**The problem.** A coding agent can read a repository but not what the team decided. The reason a helper must stay strict is in a Slack thread, the reason a function retries twice is in a review comment, the scope of a feature is in a ticket, who knows the code is in git blame. Nothing connects these, so an agent can satisfy a new request and quietly break an old decision, or change a shared function that many tests depend on. The demo example: "make `docFromTextNotation` accept Windows line endings" touches a helper that 5 functions call and hundreds of tests exercise.

**What Actron does.** A person asks for a change in Slack (`/actron ...` or an `@actron` mention) or in the web app. Actron:
1. **Investigates** a FalkorDB graph of the team's code, git history, GitHub, Slack and Linear, using graph tools (callers, impact, PageRank criticality, shortest path, decisions for a function, owners, tests).
2. **Asks** 1 to 3 questions only where the graph says it must (a conflicting decision, a highly critical function), plus which branch to target.
3. **Writes a versioned ticket** (canonical JSON with a SHA-256), syncs it to Linear, and waits for approval bound to that exact version.
4. **Builds** the change with the Pi coding agent in Docker, with the graph tools and a context pack built from the graph. Tests run in a second container with no network. A repair loop runs up to twice.
5. **Opens a pull request** on the fork. PR approval is bound to the head commit.
6. **Writes back** the PR, commits and touched functions into the graph.

Every finding shows its source quote and the path through the graph. Slack and the web app are two views of one request, kept in sync.

**Why a graph (the hackathon point).** The question is "what is connected to this, by what, how strongly", across four kinds of source. FalkorDB does the traversals (callers, impact), the algorithms (`algo.pageRank`, `algo.SPpaths`) and links Slack message to decision to function to commit. Without it, the central question cannot be answered. See the README sections "Why a graph is the right tool" and "How FalkorDB helped".

**Tracks entered:** 01 Agents That Act on Connected Data (main), plus 02 Agent Memory and Coordination and 03 Company Brain (the README table lists the points implemented).

---

## 2. How it is built

| Part | What | Where |
|---|---|---|
| Frontend | Next.js 16 app (App Router), TanStack Query, Zustand, Tailwind over tokens, d3-force canvas, 3D hero. Dark only, base `#0A0A0A`. Browser calls same-origin `/api`, proxied to the backend | `frontend/` |
| Backend API | FastAPI: requests, approvals, connectors, SSE stream, health, Slack bot and OAuth | `backend/actron/api`, `integrations` |
| Worker | Temporal worker on four queues (`ingest`, `link`, `request`, `build`); starts Pi and test containers through the Docker socket | `backend/actron/worker.py`, `workflows/`, `activities/` |
| Graph | FalkorDB v4.22.1, one graph per workspace; fixed ontology of 96 node types in five JSON files, 275 expanded link types | `ontology/`, `backend/actron/graph/` |
| State | PostgreSQL 16 (state, event journal, encrypted connector secrets; also holds Temporal's databases), Redis 7 (live events, sessions, cache) | `backend/actron/db/` |
| Models | Jev (TypeSafe, `jev-1.13.0`) for 10 judgment call sites; LiteLLM for text and the investigator; stubs when no key | `backend/actron/models/` |
| Agents | Investigator over 20 MCP graph tools; Pi (`@earendil-works/pi-coding-agent`) in the `actron-pi` image | `backend/actron/mcp_graph/`, `flow/` |

Detailed docs: `docs/architecture.md`, `docs/workflow.md`, `docs/agents.md`, `docs/graph-model.md`, `docs/queries.md`, `docs/falkordb.md` (every FalkorDB limit hit, with the workaround), `docs/ingestion.md`, `docs/linking.md`, `docs/models-and-jev.md`, `docs/slack.md`, `docs/runbook.md`, `docs/testing.md`.

**Key decisions already made (do not re-open without a reason):** FalkorDB for the graph, PostgreSQL for state (not Mongo, no Prisma; SQLAlchemy 2 with Alembic), Redis only for short-lived coordination, Temporal for durable workflows and waits, Pi as the coding agent, Jev for judgments, tree-sitter in Python (no Rust), ontology defined in files and never generated at runtime, fresh connector code (an earlier internal product was read for patterns only). `PLAN.md` has the full decisions log; `PRD.md` and `specs/` (A graph and ingestion, B agents and workflow, C experience) are the source of truth for behaviour; `PROMPT.md` is the build prompt used.

---

## 3. How to start it

Requirements: Docker with compose, `uv`, Node 22.19 or newer.

```bash
cp .env.example .env     # fill in; secrets come from the owner over a private channel, never from git
make up                  # FalkorDB, PostgreSQL, Redis, Temporal (+UI), backend, worker, frontend, backup,
                         # and builds the actron-pi and actron-test-runner images
open http://localhost:3000
```

Ports on the host: frontend 3000, backend 8080, Temporal UI 8233, FalkorDB 6389, PostgreSQL 5433, Redis 6380.

Other commands: `make up-deps` (stores and Temporal only, for backend tests), `make down`, `make logs`, `./scripts/live_smoke.sh [provider]` (live checks for models, jev, github, slack, linear, pi), `./scripts/test_all.sh` (every level, about 11 minutes, do not run two at once), `make e2e-stack` (full-stack browser tests against fake providers).

**After editing `.env`:** a plain restart does not reload it. Recreate the containers: `docker compose -f infra/compose.yaml up -d --force-recreate backend worker`. `GET http://127.0.0.1:8080/api/health` shows every integration as `live`, `stub` or `not connected`.

**Signing in.** Locally there is a Dev login button (works only when `ACTRON_ENV` is not `prod`). The dev-login user has no Slack identity, so it is not the requester of a Slack-started request and cannot approve its ticket. To approve, use **Sign in with Slack** (needs `ACTRON_PUBLIC_URL`, the Slack Client ID and Secret and two redirect URLs; see section 5), or be listed as an approver or owner. Approval rule: the requester, the workspace owner, or a Slack user ID in Settings, People, Approvers.

**Using it.** Home has a request box; or type `/actron <what you need>` or mention `@actron` in a channel the bot has joined. The request page shows the timeline of graph tool calls, the graph path, and tabs: Evidence, Questions, Ticket, Build, PR. Answer questions in Slack or the app; approve the ticket; the build starts; review the PR; approve it. Connect (left rail) is where sources are connected with setup guides; Settings holds sync schedules, model jobs, thresholds, the bot identity and approvers.

**Real-data state on the dev machine.** The `dev` workspace has the real Calva graph (about 20,000 nodes and 77,000 links; the code backfill takes about 2 minutes, the GitHub sync is slower). Requests run so far include two that reached a PR on the fork (PR #1 and PR #2 on `vikram-choudhary03/calva`). A fresh server starts with an empty graph and needs the repository connected and backfilled again.

---

## 4. Services, keys and accounts

Variables are listed in `.env.example`. Everything may stay empty; missing keys show "not connected" or a `stub` badge.

- **Models.** `MODEL_CODING=deepseek/deepseek-v4-pro`, `MODEL_AGENT`, `MODEL_WRITING`, `MODEL_DECISION` all `deepseek/deepseek-flash`, `LITELLM_FALLBACKS=gemini/gemini-3.8-flash`. DeepSeek bills per token (about $0.15 input and $0.60 output per million for flash, $0.66 and $1.98 for pro, double at peak hours 01:00 to 04:00 and 06:00 to 10:00 UTC on weekdays). Builds so far cost about $0.05 to $0.43 each; the balance was low (under $1) during the last runs, so top up before more runs. Gemini's free tier is 20 requests a day per model, so it is only a rarely used fallback. OpenRouter could not be paid for. `ACTRON_DAILY_MODEL_BUDGET_USD=3` is the daily cap, but Pi's cost is not recorded (see open problems).
- **Jev:** `TYPESAFE_API_KEY`, model `jev-1.13.0`; all ten call sites are wired.
- **Slack.** App "Actron" (bot `actron`, Socket Mode) in the workspace "Heaven", channel `#arctron-demo` (the name has a typo, keep it). The bot must be invited to every channel it should read (`/invite @actron`). Do not turn on token rotation for the app (it cannot be undone and the code does not refresh tokens). Created from `infra/slack/manifest.dev.yaml`.
- **GitHub.** `GITHUB_REPOSITORY` and `GITHUB_FORK` are the fork `vikram-choudhary03/calva`, `GITHUB_UPSTREAM=BetterThanTomorrow/calva` (history only), working branch `published`. A webhook is optional (see section 7).
- **Linear.** Team VIK. Tickets created so far: VIK-7, VIK-8, VIK-9.
- **Build identity.** `ACTRON_BOT_NAME=Actron Bot`, `ACTRON_BOT_EMAIL=bot@actron.test` (not a real mailbox; only a label on commits). Settings can also hold a per-workspace identity, which takes precedence.
- **Which settings win.** For connectors, a connection saved in the app wins over `.env`, which is only a fallback. Model keys, Jev, the Slack app credentials and the public address belong to whoever runs Actron.
- **Exposed keys.** During development real keys were pasted into a chat. **Replace all of them** (Gemini, Jev, DeepSeek, GitHub, Linear, every Slack secret) before deploying; the new values go only on the server.
- **Local tunnel.** For Slack sign-in from a laptop, VS Code's Ports tab forwards port 3000 as a public HTTPS address; set `ACTRON_PUBLIC_URL` to it (no trailing slash). The address changes if the tunnel is recreated, and then the Slack redirect URLs must be updated.

---

## 5. Deployment (not done yet)

Target: **https://actron.anubhavmalik.com** (the team owns `anubhavmalik.com`; only the `actron` subdomain is used). The hackathon prefers a live deployment; the alternative is complete local setup steps plus a working demo video (the README already has those).

**Full plan, checks and report format: `prompts/DEPLOY-PROMPT.md`.** Give that file to a coding agent. Summary:

- **Platform choice.** One server running the production compose stack (`infra/compose.prod.yaml`, Caddy with automatic HTTPS, `make deploy`). Serverless and managed PaaS do not fit: the stack needs always-on databases and workers, and the worker needs the Docker socket to start build containers.
- **Server:** Ubuntu 24.04, at least 4 vCPU, 8 GB RAM, 80 GB disk, public IPv4, ports 22, 80 and 443 open only. Prices checked on 18 October (vendor pages): DigitalOcean Basic 4 vCPU 8 GB $48 a month ($0.0714 an hour, billed hourly, so a few days cost about $5 to $12; Bangalore exists), AWS Lightsail 4 vCPU 8 GB $84 a month, Vultr about $40 to $48 (third-party listings), Hetzner cheaper but price unverified and no India site. Oracle's free tier is not recommended (allowance disputed, idle reclamation, capacity). Nothing has been rented yet.
- **DNS:** an A record named `actron` pointing to the server's IP, TTL 300 or lower. Check with `dig` before starting Caddy.
- **Production `.env`:** `ACTRON_DOMAIN=actron.anubhavmalik.com`, `ACTRON_PUBLIC_URL=https://actron.anubhavmalik.com`, a strong `POSTGRES_PASSWORD` (the compose default is `actron`), newly generated `ACTRON_SECRET_KEY` and `SESSION_SECRET`, and all the keys above. The dev login is off in production, so **Sign in with Slack is the only way in**: it must work first.
- **Slack settings for production:** redirect URLs `https://actron.anubhavmalik.com/api/auth/slack/callback` and `.../api/slack/oauth/callback`; Socket Mode stays on. GitHub webhook (optional): `https://actron.anubhavmalik.com/webhooks/github`, content type JSON, a secret, events for pushes, PRs, reviews, review comments, issues and issue comments.
- **Cautions:** never delete a FalkorDB graph that has unique constraints and do not restart the FalkorDB container during the demo window (`docs/falkordb.md`, limitation 12); do a trial backup restore and a reboot test; check that server-sent events pass through Caddy unbuffered; keep the daily cost cap.

---

## 6. Demo video (not done yet)

Everything is in **`prompts/VIDEO-PROMPT.md`** (script, shot list, production prompt, pre-flight and day-of checklists) and **`prompts/READ-ALOUD-SCRIPT.md`** (the 12 narration segments to read).

Decisions already taken:
- About 5 minutes. Part 1 (0:00 to 2:30): problem, why it matters, what Actron is, how FalkorDB helped, tracks. Part 2 (2:30 to 5:00): the real product from a Slack message to a PR, with launch-video motion (zooms, callouts, a visible cursor).
- **Narration is the owner's own voice**, recorded after the video draft exists, one file per segment in `video/audio/`. No AI voice.
- **The capture and composition are done by an AI agent, not by hand**: a Playwright driver captures the real app (1920 x 1080, double scale), and the video is composed as code with HyperFrames (free, Apache-2.0), with Remotion as a second choice (its licence for a team like ours was not checked). Slack screens need a one-time manual login in the browser the agent opens; if Slack blocks automation, use four hand-taken screenshots instead. OBS is a manual fallback only.
- The video does not mention how the code was written; the README's "AI use disclosure" covers it. It only claims what ran live, and labels anything sped up.
- Pre-flight: the app is frozen, a real request has reached a PR (done at least twice), numbers in the script are re-read from the live app that day.

---

## 7. Blog post (not done yet)

Side prize: AirPods 5 for the best blog post (one winner). Research on past WeMakeDevs blog winners, what could be learned, and a full 11-section outline: **`docs/blog-research.md`**. Draft with real numbers: `docs/blog-post.md`.

Key points: the Cognee hackathon's best blog and the SigNoz pre-event blog winners both have first-person, specific titles; the organisers say a good report covers the problem, how it was built and how the sponsor tool helped, what broke, and what you would do differently. The winning posts themselves could not be read (Medium blocks automated access), so those conclusions are partly inference and the file says so. Plan: open with the real moment (the "5 functions and 964 tests" question), show three graph queries that only work as traversals, put "what broke" (planner scan 2.3 s to 4 ms, the append-only crash, the tree-sitter crash, live-run failures) at the centre, give numbers with denominators and caveats, end with one blunt lesson. Publish on dev.to or Medium (not LinkedIn alone), re-check every number, no secrets in screenshots.

---

## 8. Repository and publishing

- Public repo `malikanubhav/actron`. Branches: `dev` (work in progress), `prod` (deployed and submitted), `main` (an earlier prototype, unused). Changes go to `dev`, then into `prod` by pull request (base `prod`, compare `dev`). The server deploys `prod`.
- **Set `prod` as the default branch** on GitHub (Settings, Branches) and add a description and topics.
- History: Anubhav's first two commits (17 Oct) are at the bottom; the project commits follow. **Never force-push or rewrite history**: the commit dates are the proof the work happened inside the window (15 to 18 October 2026).
- License: MIT ("The Actron authors"). Both authors should agree (hackathon rule 15 asks teams to agree ownership).
- Git-ignored on purpose: `.claude/` (third-party skills, permissive settings), `skills-lock.json`, `video/`, the root `data/`. The working prompts in `prompts/` and the blog research are published.
- `.claude/settings.json` (local only) allows all tools and denies `git config`, `gh`, `sudo` and the old fabric folder. The git commit, push and remote denies were removed on 18 October so the publishing could run; restore them if you want to stop agents from publishing.
- Before pushing again: scan for secrets (compare the real values in `.env` against every tracked file; token-shaped strings in tests are fixtures), keep `.env` and `infra/.env.prod` out, and keep the README accurate.
- The earlier push missed 22 files (the run-time model prompts and the frontend fixture data) because broad ignore rules matched them; fixed. If a fresh clone ever fails, suspect an ignore rule first.

---

## 9. Hackathon rules that matter

From the rules page (18 Oct 2026): FalkorDB must be the primary graph database and do real work; main coding must start after 15 Oct 12:01 AM IST (ideas, notes and diagrams before are fine); public, synthetic or own data only; submission needs a public repo, a README with setup steps and the graph data model, the Cypher queries and graph algorithms the product depends on, a demo video (length and format not specified), a live deployment (preferred) or complete local setup steps, and the tracks entered; AI assistants are allowed but must be disclosed, and the team must be able to explain the graph model, queries, architecture and decisions. Judging criteria are not published.

---

## 10. Open problems in the product (from the live runs, details in `BUILD-LOG.md`)

1. `build_runs.cost_usd` stays 0.0 because Pi's cost is not recorded, so the daily budget cannot see build spend.
2. The build container has open network egress (known limitation).
3. After an edited ticket the rebuild used to push to a new branch while the PR stayed on the old one; fixed in code (`build_branch()`), not yet verified by a live rebuild. Request 2's record keeps the corrupted branch value.
4. A user's override answer leaves the old decision `approved`; nothing supersedes it.
5. PR-feedback answers ignore Pi's build report.
6. The conflict threshold (0.8) over-calls on a small, optimistic test set (8 false positives of 21); 0.9 is proposed, not applied. Link keep 0.6 looks fine.
7. Not yet seen live: Jev call sites J2, J6b, J9; the GitHub webhook; Slack's own manifest validator for the production manifest.
8. 1,575 of Calva's TypeScript calls stay unresolved (need type information).
9. The Slack ticket message has only an "Open in Actron" button, not an Approve button; the question message shows raw internal ids in one place; "who r u" gets an awkward answer.
10. `NEEDS-FROM-USER.md` lists the remaining owner-only items (Slack and GitHub settings, a vector mark for the Jev logo and a light-on-dark FalkorDB wordmark, deleting the old FalkorDB volume `actron_falkor-data`).

---

## 11. Prompts index (all in `prompts/`)

| File | Use |
|---|---|
| `UI-REVIEW-AND-FIX-PROMPT.md` | the user-perspective UI review and fixes (already run once) |
| `LIVE-SETUP-PROMPT.md` | connect real services and run a real request (already run) |
| `GIT-PUSH-PROMPT.md` | publishing to `dev` and `prod` (already run, by hand and agent) |
| `DEPLOY-PROMPT.md` | deploy to the server and verify (to run) |
| `VIDEO-PROMPT.md` | script, shot list and the video-making agent (to run) |
| `READ-ALOUD-SCRIPT.md` | the narration to record (to do) |
| `ONTOLOGY-SAMPLE-DATA-PROMPT.md` | how the ontology was validated on sample data (done; data deleted) |

## 12. Working practices

- Give agents a prompt file and tell them to read it and not to stop for questions. Use Sonnet for routine work and subagents.
- Never paste keys into chat; put them in `.env` or the server's environment.
- Do not commit or push without the owner saying so; the owner's personal GitHub account and commit identity are used for commits, passed as `GIT_AUTHOR_*` and `GIT_COMMITTER_*` environment variables, never stored in a file or in Git's settings.
- On the owner's machine, pushes to `malikanubhav/actron` used a dedicated SSH key for the personal account; anyone else uses their own credentials.
