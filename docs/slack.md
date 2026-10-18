# Slack

How the Slack side of Actron works and how to set it up. Code: `backend/actron/integrations/slack_bot.py` (handlers), `slack_blocks.py` (messages), `slack_sender.py` (one status message per request, notifications), `slack_oauth.py` ("Add to Slack" and the installation store), `slack_common.py` (scopes, token lookup, service adapter). Manifests: `infra/slack/manifest.yaml` (HTTP mode) and `infra/slack/manifest.dev.yaml` (Socket Mode).

Status: tested against a fake Slack Web API server and, since 18 Oct 2026, against the real workspace "Heaven" (`./scripts/live_smoke.sh slack`: tokens, scopes, Socket Mode, `#arctron-demo` membership and history). With no channel chosen, ingestion reads every channel the bot is a member of. A real `/actron` and the OAuth consent screens still need a person; the live run used correctly signed HTTP requests to `/slack/commands` and `/slack/events`. Note: `x-oauth-scopes` of a call made with the app token describes the app token, not the bot, and is ignored for the scopes check.

## Set up

Pick one transport.

**Deployed Actron (HTTP mode, needs a public HTTPS URL)**
1. Open `infra/slack/manifest.yaml`. Replace every `https://actron.example.com` with your `ACTRON_PUBLIC_URL`.
2. In Slack: api.slack.com/apps, Create New App, From a manifest, paste the YAML.
3. Slack shows the request URLs as "not verified". Open Event Subscriptions and press Retry once Actron is running. The URLs are `/slack/events`, `/slack/commands` and `/slack/interactions`.
4. Copy Client ID, Client Secret and Signing Secret (Basic Information) into `.env` as `SLACK_CLIENT_ID`, `SLACK_CLIENT_SECRET`, `SLACK_SIGNING_SECRET`.
5. In Actron open Connect, Slack, and press "Add to Slack". The install is stored as the workspace's Slack connection. No `SLACK_BOT_TOKEN` is needed.
6. Invite the bot to the channels Actron should read: `/invite @actron`. Try `/actron add a retry to the invoice export`.

**Laptop (Socket Mode, no public URL)**
1. Create the app from `infra/slack/manifest.dev.yaml`. Nothing to replace.
2. Install it to your workspace and copy the Bot User OAuth Token (`xoxb-...`).
3. Basic Information, App-Level Tokens, Generate with scope `connections:write` (`xapp-...`).
4. Enter both on the Connect screen (Slack, token form), or set `SLACK_BOT_TOKEN` and `SLACK_APP_TOKEN` in `.env`.
5. The worker calls `slack_bot.run_socket_mode()`, which starts only when an app-level token exists.

"Add to Slack" and Sign in with Slack need HTTPS redirect URLs, so on a laptop use the token form. Whether Slack accepts `http://localhost` redirect URLs for development was not verified; assume it does not.

## Scopes and why

| Scope | Why Actron needs it |
|---|---|
| `app_mentions:read` | Start a request with `@actron <text>`. |
| `channels:history` | Read messages in chosen public channels for the memory, and see thread replies to requests. |
| `groups:history` | The same for chosen private channels the bot was invited to. |
| `channels:read` | List public channels so you can choose which to read. |
| `groups:read` | List the private channels the bot is in. |
| `chat:write` | Post and edit the status message, questions and answers. |
| `commands` | The `/actron` slash command. |
| `im:write` | Open a direct message with the one person who must act. |
| `reactions:read` | Read reactions on messages used as evidence. |
| `team:read` | Read the workspace name and id (`team.info`) to match it to the Actron workspace. |
| `users:read` | Resolve who wrote a message and who clicked a button. |
| `users:read.email` | Match Slack people to the same people in GitHub and Linear by email. |
| user scopes `openid`, `profile`, `email` | Sign in with Slack only. The install requests no user scopes. |

Events: `app_mention`, `message.channels`, `message.groups`, `member_joined_channel`, `channel_rename`, `app_uninstalled`, `tokens_revoked`. Command: `/actron`. Interactivity is on (buttons and the request-changes modal). `org_deploy_enabled` is false.

The single list of scopes and events lives in `slack_common.py` (`BOT_SCOPES`, `USER_SCOPES`, `BOT_EVENTS`). The install URL, the manifests and this table all follow it; `backend/tests/unit/test_slack_manifest.py` fails if they drift.

## What people can do in Slack

- `/actron <text>` or `@actron <text>` starts a request. `/actron ask <question>` (or `@actron ask ...`) starts Q&A mode.
- Buttons on the status message: answer a question, "Approve ticket v2", "Approve PR #18 (head 3f2a1c9)" (asks for confirmation naming the head), "Request changes" (opens a modal), "Close PR", "Retry", "Open in Actron".
- Reply in the thread: start with the question number to answer a text question ("2 EUR and GBP only"), or start with `feedback:` to send pull request feedback.
- Button ids: `answer:<requestId>:<questionId>:<value>`, `approve_ticket:<requestId>:<hash>`, `approve_pr:<requestId>:<headSha>`, `request_changes:<requestId>`, `close_pr:<requestId>`, `retry:<requestId>`, `open:<requestId>`. Questions with more than five options use a menu (`...:~select`); a value too long for the 255-character limit is sent as `...:#<option index>`.

Approving needs the same rights as in the UI: the requester, the workspace owner or someone on the approvers list. A refused click answers only the person who clicked, in plain words.

## Message blueprints (PROMPT 8.9)

The colour bar and chip text come from one shared map, `backend/actron/flow/states.json` (`frontend/lib/states.json` when that file is missing); a test checks the two agree.

| Message | Content |
|---|---|
| Acknowledgement (first message in the thread) | "On it. Investigating your request." and `REQUEST <ID> · INVESTIGATING`, button "Open in Actron". The id shown is the last eight characters of the request id. |
| Status message (one per request) | Header with the request title. Context line `STATE · <STATE> · <elapsed>`. The headline sentence from `RequestDetail.headline`, the same text as the UI. For findings states: the label (`LABEL · CONFLICT`) and up to three evidence quotes, each with source link and author. Actions depend on the state. |
| Approval confirmation | "Approved by <name> in Slack. Build started." The approve button is gone. While the request is Building the line stays, taken from the recorded approval. |
| Needs-you DM | One sentence and a link to the thread. |
| Build finished (thread reply) | "PR #18 is ready for review. 14 of 14 tests passed." with Approve PR, Request changes, Review in Actron, Open PR. |
| Failure (thread reply) | "The build failed twice. <one-line reason>." with Retry and Open in Actron. |
| Question (thread reply) | "Question 1 of 2." with the question, answer buttons, and a reply hint for text questions. Edited to "Answered: ... by ..." once answered. |
| Answer (Q&A) | The answer, then each citation as a quote with source and author. |

Copy rules: no emoji as status, no exclamation marks. `slack_blocks.lint_copy` checks our own text. Verbatim quotes of other people's messages are exempt because they are evidence and are never rewritten. `slack_blocks.validate_message` checks Slack's size limits (50 blocks, 3000 characters in a section, 150 in a header, 75 on a button, 255 in an action id, 25 elements in an actions block).

## How the status message stays in sync

W6 calls `slack_sender.on_event(ws, envelope)` after every request event is stored and published. It never raises.

1. It does nothing when Slack is not connected, when the request is unknown, or for chatty events (`tool.called`, `tool.result`, `evidence.found`, `build.step`, `judgment.made`).
2. For the events that change what a person sees (state changes, investigation done, questions, tickets, approvals, builds, tests, pull requests, answers) it reads the current request with `flow.service.get_request_view` and builds the status message from that, not from the event. Late or repeated events cannot show stale data.
3. The first message is posted once in the request's thread (the `request.created` event posts the acknowledgement) and its `ts` is saved in `requests.slack_status_ts`. Every later change calls `chat.update` on that `ts`. If Slack says the message is gone, a new one is posted and the new `ts` saved.
4. A per-request lock (in the process and in Redis) means two events never post two messages. A hash of the message (ignoring the elapsed time) stops identical updates being sent.
5. Requests created in the UI have no Slack thread, so they get no status message, but the person who must act still gets the DM when they are linked to a Slack user.

## Who gets interrupted

Only four state changes notify, as a thread reply plus a DM:

| State | DM to | Thread reply |
|---|---|---|
| Needs your input | the requester | the questions (one message each) |
| Awaiting approval | the requester and the approvers | "Ticket v2 for ... is ready for your approval." |
| Needs attention | the requester | the failure message |
| PR ready for review | the requester and the approvers | the build finished message |

Everything else only edits the status message. A DM is sent once per event even if the event is delivered twice.

## Reliability

- Every handler calls `ack()` first and then does its work in an asyncio task. A slash command is acknowledged in milliseconds even when Slack's API is slow (tested with a 1.2 second delay).
- Redis idempotency: `event_id` for events, `trigger_id` plus action id for button clicks, the view id for modal submissions, `trigger_id` for commands. A repeated delivery does nothing. The same keys go to the service as the idempotency key.
- HTTP mode checks Slack's signature on all three routes. A bad signature or a timestamp more than five minutes away from now gets 401 and nothing runs. Without `SLACK_SIGNING_SECRET` the routes answer 503.
- `app_uninstalled` and `tokens_revoked` (bot token) mark the Slack connection disconnected, remove the dead bot token and pause the Slack sync schedule.
- The bot token for an incoming event is looked up by team id from the stored installation. `SLACK_BOT_TOKEN` is only a development fallback.

## Installation storage

"Add to Slack" stores the install as the workspace's `connections` row (provider `slack`): config `{teamId, teamName, botUserId, botId, scopes, installedBy, enterpriseId, appId}`, secret `{"bot_token": ...}` encrypted with `ACTRON_SECRET_KEY` (an `app_token` can sit beside it). A workspace with no Slack team adopts the team of its first connection; after that a different team is refused (`slack_error=different_team`). Callback errors redirect to `/app/connect?slack_error=expired|cancelled|failed|different_team`; success is `?slack=connected`. The OAuth state is random, kept in Redis for 10 minutes and single use.

Token-form connections should call `slack_oauth.ensure_team(ws, team_id)` with the team from `auth.test`, so both paths follow the same team rule.

## What was verified (17 Oct 2026)

- slack-bolt 1.30.0 and slack-sdk 3.45.0, async: `AsyncApp(authorize=...)`, `AsyncSlackRequestHandler` (starlette handler, used for FastAPI), `AsyncSocketModeHandler` (aiohttp), `AsyncInstallationStore` with `async_save`, `async_save_bot`, `async_find_bot`, `async_find_installation`, `async_delete_bot`, `async_delete_installation`, `async_delete_all`.
- Bolt's `authorize` arguments are read from positional-or-keyword parameters only; keyword-only parameters are silently missed.
- Bolt rejects bad signatures and stale timestamps (more than 300 seconds) with 401, and skips authorization for `app_uninstalled` and `tokens_revoked`, so those handlers run after the bot token is dead.
- Manifest keys and limits were checked against docs.slack.dev/reference/app-manifest. Not verified: that Slack's own manifest validator accepts these files (it needs a real app); the request URLs must be verified by hand in Slack.
- Not tested: a real Socket Mode websocket (only that the handler is started with the stored app token), real Slack rate limits, and messages rendering in a real client. Blocks inside `attachments` are used for the colour bar; they are valid Block Kit but were not looked at in Slack.
