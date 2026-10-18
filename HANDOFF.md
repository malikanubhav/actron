# Handoff: where Actron stands (18 October 2026)

For whoever continues the work. Read this first, then `BUILD-REPORT.md`, the last 80 lines of `BUILD-LOG.md` and `NEEDS-FROM-USER.md`. No secret is in this repository.

## State in one paragraph

Actron is built and runs locally with one command (`make up`). Real services are connected: Slack, Linear, GitHub, Jev, DeepSeek, FalkorDB, PostgreSQL, Redis, Temporal and Pi. A real request on the Calva demo repository has gone end to end through Slack mention, graph investigation, questions, ticket, Linear issue, approval, Pi build, tests (1,701 passed) and a pull request on the fork (PR #1, request state Done). The code is published on `dev` and `prod`. Deployment, the demo video and the blog post are not done.

## Branches

- `dev`: work in progress. `prod`: what is deployed and submitted. Changes go to `dev` first, then into `prod` by pull request. `main` holds only an earlier prototype and is not used. The first two commits in the history are Anubhav's; the rest are the current project.
- Set `prod` as the default branch on GitHub if it is not yet.

## Run it

```bash
cp .env.example .env     # then fill in; secrets are shared outside git, never committed
make up                  # whole stack; open http://localhost:3000 (Dev login)
./scripts/live_smoke.sh  # live checks per provider
./scripts/test_all.sh    # every test level (about 11 minutes); do not run two at once
```

`.env` is not in the repository. Ask the owner for the values over a private channel. Variables are listed in `.env.example`. Several keys were pasted into a chat during development: **treat them as exposed and replace them** (Gemini, Jev, DeepSeek, GitHub token, Linear key, Slack secrets) before deploying.

## Accounts and names

Slack app "Actron" (bot `actron`, Socket Mode) in the workspace "Heaven", channel `#arctron-demo` (the name has a typo, keep it). Linear team VIK. Demo repository `BetterThanTomorrow/calva` ingested from the fork `vikram-choudhary03/calva` (working branch `published`). Commit author for builds: "Actron Bot". Models: `deepseek/deepseek-v4-pro` for the build, `deepseek/deepseek-flash` for the rest, Gemini as fallback (its free tier is 20 requests a day).

## Open work, in priority order

1. **Deployment** to `actron.anubhavmalik.com`: needs a server (Ubuntu, 4 vCPU, 8 GB) and a DNS A record. Plan and checks: `prompts/DEPLOY-PROMPT.md`. In production the dev login is off, so Sign in with Slack must work first; add the production redirect URLs in the Slack app.
2. **Demo video**: script and production prompt in `prompts/VIDEO-PROMPT.md`, narration in `prompts/READ-ALOUD-SCRIPT.md` (own voice). Needs the app frozen.
3. **Blog post** for the side prize: outline and research in `docs/blog-research.md`, draft in `docs/blog-post.md`.
4. **Repository polish**: default branch, description and topics, confirm both authors agree on the MIT license.
5. **Known problems from the live runs** (details in `BUILD-LOG.md`, last entries):
   - `build_runs.cost_usd` stays 0, so the daily model budget cannot see Pi's cost.
   - The build container has open network access.
   - A rebuild after an edited ticket used to push to a new branch while the PR stayed on the old one; fixed in code, not yet checked with a live rebuild.
   - An override answer leaves the old decision "approved"; nothing supersedes it.
   - PR feedback answers ignore Pi's build report.
   - The conflict threshold (0.8) over-calls on the small test set; a change to 0.9 is proposed, not applied.
6. **Not yet seen live**: Jev call sites J2, J6b, J9, and the GitHub webhook (the route exists, no webhook is configured on the fork).

## Rules that still apply

- FalkorDB v4.22.1: never delete a graph that has unique constraints and do not restart the FalkorDB container casually (`docs/falkordb.md`, limitation 12).
- Never force-push or rewrite history on `dev`, `prod` or `main`; the commit dates are the proof that the work happened inside the hackathon window (15 to 18 October 2026).
- Use public, synthetic or own data only (hackathon rule). The Calva data is public; the Slack content is our own.
- Disclose AI assistance (README "AI use disclosure" does).
- Submission closes 18 October 2026, 11:59 PM IST: public repo, README with the graph model and the key queries, a demo video, a live deployment (preferred) or full local setup steps, and the tracks entered (01 main, 02 and 03 as well).

## Prompts

`prompts/` holds the working prompts used so far (UI review, live setup, publishing, deployment, video, read-aloud). They can be given to a coding agent as they are; each says what it needs from a human.
