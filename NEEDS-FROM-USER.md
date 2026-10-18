# Needs from the user

Everything here blocks a live integration or a decision only the user can make. Keys go into `/home/vikram/Desktop/actron/.env` (git-ignored); never paste them into chat. Updated 18 Oct 2026 after the live setup run (see `BUILD-LOG.md`).

### Review and merge PR #1 on the fork (optional)
- PR https://github.com/vikram-choudhary03/calva/pull/1 (tests only, 1,701 tests pass in Actron's runner) was opened by the first full end-to-end run. Actron approved it in the app; it is not merged. Merge or close it as you like.

### Decisions for you
- Pi's cost is not recorded (`cost_usd` stays 0), so `ACTRON_DAILY_MODEL_BUDGET_USD` does not cover builds. Say if you want it counted.
- The build container still has open internet access. Say if you want it limited to the model provider and the graph server.

### Gemini quota
- `gemini/gemini-3.8-flash` is a real model, but the free tier allows 20 requests per day per model (quota `GenerateRequestsPerDayPerProjectPerModel-FreeTier`) and it is used up. It works only as a rarely used fallback. Options: leave it, or enable billing on the Google AI project.

### Slack: things only you can do
- Add the redirect URLs `https://cr65g885-3000.inc1.devtunnels.ms/api/auth/slack/callback` and `.../api/slack/oauth/callback` in the Slack app (OAuth & Permissions, Redirect URLs). Then click "Sign in with Slack" and "Add to Slack" once in a browser; the consent screens cannot be run from here.
- Run a real `/actron <text>` and an `@actron` mention once in `#arctron-demo`. The live run sent correctly signed requests to the bot instead, because only a person can type a slash command.
- The Connect screen shows "Waiting for the first /actron command" until a real command arrives.
- The dev manifest uses Socket Mode. With `ACTRON_PUBLIC_URL` set, the Connect check says Slack sends events to the HTTPS address and skips the Socket Mode check; events still arrive over Socket Mode because the worker keeps the connection.

### Deployment target
- Needed for: `make deploy`, a permanent HTTPS address (the dev tunnel address changes)
- What: a server (4 vCPU, 8 GB RAM recommended; see `docs/runbook.md`) with Docker, a domain name pointing at it, and `ACTRON_PUBLIC_URL`
- How to verify: `make deploy` then `curl https://<domain>/api/health`

### Ontology review and freeze
- Needed for: everything that writes to the graph
- What: review `ontology/*.json` and confirm they are frozen
- How to verify: `uv run --project backend pytest backend/tests/unit/test_ontology_loader.py -q`

### Visual direction confirmation
- What: confirm the "Evidence console" direction in `DESIGN.md` or pick an alternative from `DESIGN-DIRECTIONS.md`

### Old FalkorDB volume `actron_falkor-data`
- What: decide whether to delete the old Docker volume `actron_falkor-data` (FalkorDB 4.22.1 crashed replaying its append-only file). The stack uses `falkor-data-v2`. A repaired copy is in the earlier session's scratchpad.
- How to verify: `docker volume ls | grep falkor`

### TypeSafe (Jev) vector mark
- What: an official SVG of the TypeSafe/Jev mark, or permission and a press-kit link. Goes in `frontend/public/brands/typesafe.svg`. Workaround: the official 400 px PNG.

### FalkorDB light-on-dark wordmark
- What: an official wordmark for dark backgrounds, in `frontend/public/brands/falkordb-wordmark.svg`. Workaround: the icon with the name set in Actron's type.

### License for the public repository
- Done: `LICENSE` (MIT, "The Actron authors") and the README "License" section are in place.
- Still for the team: both authors agree that MIT is the license (hackathon rule 15 encourages agreeing ownership before submitting). To change it, replace `LICENSE` and the README line.

## Publishing

### Git identity not exported
- The four variables `GIT_AUTHOR_NAME`, `GIT_AUTHOR_EMAIL`, `GIT_COMMITTER_NAME`, `GIT_COMMITTER_EMAIL` are not set in the agent's shell. Export them for the GitHub account you want to publish with, then run `prompts/GIT-PUSH-PROMPT.md` again.

### Blocked git command
- The permission check blocked the step that points `dev` at `origin/main` and runs `git reset` (nothing ran). Allow it, or run these three commands yourself in the repo: `git update-ref refs/heads/dev origin/main`, `git symbolic-ref HEAD refs/heads/dev`, `git reset`.

### Done so far
- Pre-push checks passed (no secrets, MIT `LICENSE` present, no file over 5 MB). `origin` was added and fetched. `.gitignore` now excludes `.claude/`, `skills-lock.json`, `prompts/`, `docs/blog-research.md` and `video/`; remove those lines to publish any of them. The README "Timeline" section is added.
- Still to do after the commands above: copy `docs/implementation-review.md` from `origin/main`, make the six commits, push `dev` and `prod`, verify from a clean clone.

### Done in the live setup run (for reference)
- Slack tokens, GitHub token and fork, Linear key and team (`LINEAR_TEAM_ID` was written by the run), Jev key, DeepSeek and Gemini keys, bot identity, demo repository: set and checked by `./scripts/live_smoke.sh` (models, github, slack, linear, jev, pi all pass).
