# Live setup: connect Actron to real services and run one real request

You are continuing the Actron project. The product is built and its tests pass against fakes. Nothing has run against real Slack, Linear, GitHub pushes, Jev, a model, or Pi with a model. Your job is to make those real, fix what breaks, and report honestly what worked.

Work unattended. Do not stop to ask questions; make a reasonable choice and record it.

## 1. Read first

1. `BUILD-REPORT.md`
2. `NEEDS-FROM-USER.md`
3. The last 80 lines of `BUILD-LOG.md`
4. `docs/runbook.md`, `docs/slack.md`, `docs/models-and-jev.md`, `docs/ingestion.md`

## 2. Rules

- Do not print, log, echo or commit any secret. Never show a value from `.env` in your output; when you check a variable, say only "set" or "empty". If a value appears in a log or an error, say so and redact it.
- No git commits, pushes or remote changes by you. (Actron's own push to the user's fork during a build is the product feature and is expected.)
- Another agent is changing the frontend. Do not edit anything under `frontend/`, `DESIGN.md` or `styles/`. Do not run `scripts/test_all.sh` or `make test-all`; use `./scripts/live_smoke.sh <provider>` and targeted `pytest` runs only.
- Do not reset or delete the `dev` workspace or its graph (Calva). Do not touch the old Docker volume `actron_falkor-data`.
- `.env` is already filled in for everything except `LINEAR_TEAM_ID`, `SLACK_CHANNELS` and any optional `DEEPSEEK_API_KEY`. The user has authorised you to read `.env` and use these credentials for this project only. If a value is missing or rejected, report which variable and why; do not ask for it in chat, and carry on with the other tasks.
- Use Sonnet for every subagent.

## 3. What the user has put in `.env`

Check each variable is set (do not print it). Where it comes from is given so you can diagnose a failure.

| Variable | Where the user got it | Used by |
|---|---|---|
| `GEMINI_API_KEY` | Google AI Studio, aistudio.google.com, "Get API key" | fallback model through LiteLLM (`gemini/<model>`, free tier with daily limits) |
| `OPENROUTER_API_KEY` | not set: the user cannot buy credits. Optional free-account key for fallback only (free models, 50 requests a day) | fallback, if added later |
| `MODEL_CODING` | `deepseek/deepseek-v4-pro` | Pi build |
| `MODEL_AGENT`, `MODEL_WRITING`, `MODEL_DECISION` | `deepseek/deepseek-flash` | investigator, writing, decision extraction |
| `LITELLM_FALLBACKS` | `gemini/gemini-3.8-flash` (the Gemini model name is unverified) | used when the main model fails |
| `TYPESAFE_API_KEY` | TypeSafe dashboard (Jev) | the ten judgment call sites J1 to J10, model `jev-1.13.0` |
| `ACTRON_DAILY_MODEL_BUDGET_USD` | `3` | daily cap on model spend, all models together |
| `ACTRON_BOT_NAME`, `ACTRON_BOT_EMAIL` | `Actron Bot`, `bot@actron.test` (not a real mailbox; only a label on commits) | build commit author |
| `GITHUB_TOKEN` | GitHub, Settings, Developer settings, fine-grained token for the fork only (Contents RW, Pull requests RW, Issues R, Metadata R, Actions R, Checks R) | ingestion beyond the public limit, push, PRs |
| `GITHUB_REPOSITORY`, `GITHUB_FORK` | the user's fork of `BetterThanTomorrow/calva` (`vikram-choudhary03/calva`) | repo ingested as code; repo the build pushes to |
| `GITHUB_UPSTREAM` | `BetterThanTomorrow/calva` | history only |
| `SLACK_BOT_TOKEN` | api.slack.com/apps, the Actron app, Install App, "Bot User OAuth Token" (`xoxb-`) | Slack ingestion and the bot |
| `SLACK_APP_TOKEN` | same app, Basic Information, App-Level Tokens, scope `connections:write` (`xapp-`) | Socket Mode |
| `SLACK_SIGNING_SECRET` | same app, Basic Information, Signing Secret | request verification |
| `SLACK_CHANNELS` | empty on purpose: the user picks channels in Connect, Slack. The demo channel is the public channel `#arctron-demo` (the name has a typo, keep it); the bot is already a member and two messages are posted there | which channels are read |
| `DEEPSEEK_API_KEY` | platform.deepseek.com, API keys; the user topped up $2 (about $0.15 input and $0.60 output per million tokens for `deepseek-flash`; `deepseek-v4-pro` about $0.66 and $1.98) | the four model jobs. It is not in `.env.example` and the settings class may not know it yet: add it |
| `LINEAR_API_KEY` | linear.app, Settings, Security and access, Personal API keys | Linear ingestion and ticket sync |
| `LINEAR_TEAM_ID` | empty; you look it up | tickets are created in this team |

The Slack app was created in the workspace "Heaven" from `infra/slack/manifest.dev.yaml` with `name: Actron` and bot `display_name: actron` (Socket Mode, no public URL). "Add to Slack" is not available on a laptop, so Slack is connected with the token form or these variables.

## 4. Tasks, in order

1. **Apply the environment.** Check which variables above are set. Restart the backend and worker so they read `.env`. Confirm `/api/health` is green and the footer in the app no longer reports Jev or the models as stubs.
2. **Model names.** Make LiteLLM and Pi accept the configured names. If `gemini/gemini-3.8-flash` is not a real model, list the models the key can use, pick the closest current Gemini flash model, tell the user the exact name to put in `.env`, and use it for the rest of the run through a temporary override rather than editing `.env`. Check that Pi accepts the provider/model form it is given (Pi's own names: anthropic, openrouter, google, groq); fix the mapping in code if it does not. If `GEMINI_API_KEY` is rate limited, say so with the limit shown. To list the models, call Google's models list endpoint with the key from `.env` read inside the script, never printed. Keep only models that support `generateContent` and tool calling, and prefer the newest flash model for the four jobs. If a build step later needs a stronger model than flash (the Pi build failing on tool calls or reasoning), try the newest pro model for `MODEL_CODING` and `MODEL_AGENT` only, and say what changed in the report. If `DEEPSEEK_API_KEY` is set, make sure the settings and LiteLLM mapping accept it (`deepseek/deepseek-flash`, `deepseek/deepseek-v4-pro`; check the names in DeepSeek's docs first), add the variable to `.env.example`, and compare it with Gemini on the same real request, reporting cost, speed and whether the build passed.
3. **Provider smoke checks.** Run `./scripts/live_smoke.sh` for `models`, `jev`, `github`, `slack` and `linear`. Fix every failure in the backend. For Jev, run the live test (`backend/tests/live/test_jev_live.py`) and confirm the response field names against the real API (they were taken from the docs only). Record real latency and cost per judgment.
4. **Linear.** Look up the team through the API, write `LINEAR_TEAM_ID` into `.env` (the one allowed edit, and say you did it), and check the query and mutation field names against the live schema (spec A10 [VERIFY]). Fix mismatches. Create one real test issue through the product's ticket sync, then leave it.
5. **Slack.** The user ran `/actron who r u` before the backend was connected and got "the app did not respond"; that is expected and should work after your restart. Verify the Socket Mode connection with the real tokens, that the bot is in `#arctron-demo`, that its history is ingested (connect the channel through the Connect screen's API, since `SLACK_CHANNELS` is empty), and that `/actron <text>` and an `@actron` mention both create a request. Also test what happens with no channel chosen (does ingestion read nothing, does `/actron` still work) and report it. If the bot is not in a channel, report that the user must run `/invite @actron`. Check the setup checks on the Connect screen turn green.
6. **One real request end to end** on the `dev` workspace (Calva), started from Slack, then through questions, ticket (synced to Linear), approval, build with Pi in Docker using the real model, a real PR on the fork, review, and write-back. If the build stops, find out why and fix it in the backend, then retry. Pay attention to the items the build log lists as unverified:
   - whether Pi's own file tools write in place (the bind-mounted `notes.md`, `REPORT.json`, `STOP.md` would fail on rename-writes);
   - cloning and pushing a private or forked repository through the credential helper against real GitHub;
   - egress from the build network.
   Also check which bot identity the build uses: Settings stores a per-workspace bot identity that falls back to `.env`, but `flow/build.py` was seen reading `ACTRON_BOT_NAME` and `ACTRON_BOT_EMAIL` from settings directly. Make the build use the Settings value first, then `.env`, and add a test.
7. **Quality with real models.** Run `tests/eval/test_link_quality.py` with the real Jev key and report precision and recall. Compare the thresholds (link keep 0.6, conflict 0.8/0.5, approval 0.85, supersession 0.7) against the result and propose changes in the report; do not change them silently.
8. **Housekeeping.** Update `NEEDS-FROM-USER.md` (remove what is now done, keep what is left), append a dated entry per task to `BUILD-LOG.md`, and add what you learned about real providers to the relevant doc under `docs/`.

## 5. Done means

- Every live smoke check passes or is listed with the exact reason and what the user must do.
- One real request completed through a PR on the fork, or a precise statement of where it stopped and why.
- Backend tests you touched pass (`ruff`, `mypy --strict` on changed files, targeted `pytest`).
- A final message to the user with: what is now real, what is still a stub, the exact `.env` changes the user must make (variable names only), and any key that was rejected.
- No secrets in any file, log or output. Nothing committed.
