# Deploy Actron to actron.anubhavmalik.com

You are an agent deploying Actron, an already built and tested product, to one server on the public internet. Read this whole file before you start. Work unattended. Do not stop to ask questions: when a step needs a human (DNS, a Slack or GitHub console click, a decision), write it to `NEEDS-FROM-USER.md` under "Deployment", skip to the next step that does not depend on it, and keep going.

## 1. Goal and deadline

- Public address: **https://actron.anubhavmalik.com**. The team owns `anubhavmalik.com`; only the `actron` subdomain is used.
- The FalkorDB Graph Hacks submission closes **18 October 2026, 11:59 PM IST**. A live deployment is preferred by the organisers. Work in the priority order in section 5; get the early items working before polishing.
- What Actron is: an engineering team asks for a change in Slack or the web app. Actron investigates a FalkorDB graph of the team's code, GitHub, Slack and Linear, asks clarifying questions, writes a versioned ticket for approval, has the Pi coding agent build the change in Docker, and opens a pull request on a fork.

## 2. Rules

- Do not print, log, echo or commit any secret. When you check a variable say only "set" or "empty". Redact values if they show up in output.
- No git commits, pushes or remote changes by you. The team commits and pushes. Deploy from the checkout that is on the server.
- Do not edit product code unless a deployment step cannot work without it; if you must, make the smallest change, add a test, and list it in the report.
- Never delete a FalkorDB graph that has unique constraints, and do not restart the FalkorDB container casually (see section 7, item 3).
- Use Sonnet for every subagent.

## 3. Read first

1. `BUILD-REPORT.md` and the last 100 lines of `BUILD-LOG.md`
2. `docs/runbook.md` (environment variables, operations, backups), `docs/architecture.md`, `docs/falkordb.md`, `docs/slack.md`
3. `infra/compose.prod.yaml`, `infra/Caddyfile`, `scripts/deploy.sh`, `Makefile`
4. `NEEDS-FROM-USER.md`

## 4. What you need from the human, and what you can do yourself

Only the human can do these. Write each one as a short numbered instruction with exact values:

| Step | Who | Detail |
|---|---|---|
| Have a server | Human | Ubuntu 24.04 LTS, at least 4 vCPU, 8 GB RAM and 80 GB disk (runbook recommendation), a public IPv4 address, SSH access with a key. Ports 22, 80 and 443 open to the internet. Nothing else. |
| DNS record | Human | At the registrar or DNS host of `anubhavmalik.com`: an **A record**, name `actron`, value the server's public IPv4, TTL 300 or lower. If the server has IPv6, an AAAA record too, or none at all. |
| Slack app settings | Human | Redirect URLs and (if used) event URLs, see section 6. |
| GitHub webhook | Human | On the fork, see section 6. |
| Replace exposed keys | Human | See section 7, item 1. |
| License and README | Human | See section 8. |

You can do everything else: check DNS (`dig +short actron.anubhavmalik.com`), install Docker, write the production `.env`, build, migrate, start, verify, harden.

If you are running on the server itself, do the server steps directly. If you are running on a laptop with SSH access, run the commands over SSH. If you have neither, produce the exact commands in `DEPLOY-RUNBOOK.md` for the human to paste, ordered, with the expected output of each.

## 5. Order of work (stop at any point and still have something working)

1. **Server basics.** Update packages. Create a non-root user. SSH keys only, root login off, password login off. Firewall (`ufw`): allow 22, 80, 443; deny the rest. `unattended-upgrades` on. Install Docker Engine and the compose plugin from Docker's repository. Add a 4 GB swap file. Check the clock is synced (`timedatectl`). Confirm the checkout is on branch `prod` and clean.
2. **DNS check.** `dig +short actron.anubhavmalik.com` must return the server's IP before Caddy starts, or the certificate request fails and Let's Encrypt rate-limits repeated failures. If it does not match yet, record it in `NEEDS-FROM-USER.md` and wait; do not retry in a loop.
3. **Production `.env`** (section 6). Never copy the laptop's `.env`: generate new secrets on the server.
4. **Deploy.** `make deploy` (runs `scripts/deploy.sh`: build, start stores and Temporal, migrate, start everything, wait for health). Make sure the `actron-pi` and `actron-test-runner` images exist on the server (`make up` builds them; `deploy.sh` may not). If they are missing, build them with the same commands the Makefile uses and make `deploy.sh` or the Makefile do it, so a clean server works with one command. Check that the worker can reach the Docker socket and that `ACTRON_BUILD_HOST_DIR` is the same host path inside and outside the worker container.
5. **HTTPS and routing.** `curl -I https://actron.anubhavmalik.com` returns 200 with a valid certificate (check issuer and expiry). `/api/health` returns healthy JSON. HTTP redirects to HTTPS. The security headers from the Caddyfile are present.
6. **Sign-in (critical).** In production the dev login is switched off (`ACTRON_ENV=prod`), so **Sign in with Slack is the only way in**. Test the whole flow in a real browser session (Playwright is fine): start, Slack consent, callback, session cookie (check `Secure`, `HttpOnly`, `SameSite`), landing in `/app`. Find out what happens for a person from a Slack team that has no Actron workspace yet (the build creates the workspace from the Slack team; confirm the first user becomes the owner, because only the owner, the requester or a listed approver can approve tickets). If sign-in fails, fix the cause or document it.
7. **Data.** The server starts with an empty graph. Connect the repository through the app or CLI and run the backfill for `BetterThanTomorrow/calva` ingested from the fork (`GITHUB_REPOSITORY`), working branch `published`. Calva takes about two minutes plus the GitHub sync. Then connect Slack (the same Slack app) and the channel `#arctron-demo` (note the typo, keep it). Import the demo Slack export if one exists (`video/` or `data/`; ask in `NEEDS-FROM-USER.md` if not).
8. **Slack.** Section 6.
9. **One real request** end to end from Slack: `/actron make docFromTextNotation in the test utilities accept Windows line endings`. Investigation, questions, ticket, approval by the requester, build with Pi in Docker, a PR on the fork, PR approval, write-back. Report where it stops, if it does.
10. **Real-time stream.** Check that server-sent events pass through Caddy unbuffered (open a request page and watch the timeline update live; `curl -N` on the stream returns data at once). The Caddyfile already has an unbuffered route; the Next.js app has compression off for this reason.
11. **Hardening and operations** (section 7).
12. **Report.** Write `DEPLOY-REPORT.md` (section 9).

## 6. Configuration

### Production `.env` on the server

Based on `.env.example`. Compose sets `ACTRON_ENV=prod`. Set or change:

| Variable | Value |
|---|---|
| `ACTRON_DOMAIN` | `actron.anubhavmalik.com` |
| `ACTRON_PUBLIC_URL` | `https://actron.anubhavmalik.com` (no trailing slash; used for OAuth redirects and webhook links) |
| `POSTGRES_PASSWORD` | a long random password (the compose default is `actron`, which is not acceptable on the internet) |
| `ACTRON_SECRET_KEY` | new Fernet key generated on the server (`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`). Losing it makes stored connector secrets unreadable: back it up outside the server. |
| `SESSION_SECRET` | new long random string |
| `ACTRON_BUILD_HOST_DIR` | an absolute path on the server, mounted at the same path in the worker |
| Slack | `SLACK_CLIENT_ID`, `SLACK_CLIENT_SECRET`, `SLACK_SIGNING_SECRET`, `SLACK_APP_TOKEN` (Socket Mode stays on), `SLACK_BOT_TOKEN`; leave `SLACK_CHANNELS` empty (channels are chosen in Connect) |
| GitHub | `GITHUB_TOKEN`, `GITHUB_REPOSITORY`, `GITHUB_FORK` (both `vikram-choudhary03/calva`), `GITHUB_UPSTREAM=BetterThanTomorrow/calva`, `GITHUB_WEBHOOK_SECRET` (new random string) |
| Linear | `LINEAR_API_KEY`, `LINEAR_TEAM_ID` (team VIK) |
| Models | `TYPESAFE_API_KEY`, `DEEPSEEK_API_KEY`, `GEMINI_API_KEY` (fallback, free tier is small), `MODEL_CODING=deepseek/deepseek-v4-pro`, `MODEL_AGENT`, `MODEL_WRITING`, `MODEL_DECISION` all `deepseek/deepseek-flash`, `LITELLM_FALLBACKS=gemini/gemini-3.8-flash` |
| Bot identity | `ACTRON_BOT_NAME=Actron Bot`, `ACTRON_BOT_EMAIL=bot@actron.test` |
| Budget | `ACTRON_DAILY_MODEL_BUDGET_USD=3` (keep a cap; a stuck build must not spend freely) |

The human puts the actual secret values on the server (for example by writing `/opt/actron/.env` themselves or by `scp`). You check each is set without printing it. `.env` and `infra/.env.prod` must be mode 600 and git-ignored.

### Slack (the app already exists; Socket Mode stays on)

Socket Mode needs no request URLs, so `/actron`, mentions and buttons keep working from the server with no inbound Slack traffic. What changes for production:

1. Slack app, OAuth & Permissions, Redirect URLs. Add and save both:
   - `https://actron.anubhavmalik.com/api/auth/slack/callback` (Sign in with Slack)
   - `https://actron.anubhavmalik.com/api/slack/oauth/callback` (Add to Slack)
   Remove the old tunnel addresses (`*.devtunnels.ms`) once production works.
2. Do not turn on token rotation for this app (it cannot be undone and the code does not refresh tokens).
3. The bot must be invited to each channel to be read (`/invite @actron`); public distribution is not needed while only the owning workspace uses it. Other workspaces installing the app would need Manage Distribution activated: leave for after the hackathon.
4. In the app's Connect, Slack screen the checks should turn green. "Try it" turns green after one real `/actron` command.

### GitHub webhook (optional but wanted for instant updates)

On the fork: Settings, Webhooks, Add webhook.
- Payload URL: `https://actron.anubhavmalik.com/webhooks/github`
- Content type: `application/json`; Secret: the value of `GITHUB_WEBHOOK_SECRET` (a connection saved in the app takes precedence over the `.env` value; if the ping returns 401 bad signature, use the secret shown on the Repository card)
- Events: Pushes, Pull requests, Pull request reviews, Pull request review comments, Issues, Issue comments
- Check Recent Deliveries: the ping should be green. The route needs a connected GitHub source in the workspace.

Without a webhook, Actron still syncs on a schedule and through the merge watch; the webhook only makes it instant.

## 7. Things to take care of (verify each, fix or report)

1. **Exposed keys.** During development real keys were pasted into a chat. Treat these as exposed and replace them before or at deployment: Gemini, Jev (TypeSafe), DeepSeek, GitHub token, Linear key, and all Slack secrets (signing secret, client secret, bot token, app-level token). The new values go only on the server. Record in the report that the human confirmed this, or that it is still open.
2. **Dev login is off in production.** Sign-in with Slack must work before anything else is useful (step 6). Also confirm `/api/auth/dev-login` returns 404 on the server.
3. **FalkorDB persistence.** FalkorDB v4.22.1 can crash replaying its append-only file after a graph with unique constraints is dropped (`docs/falkordb.md`, limitation 12). In production: never run `GRAPH.DELETE` on a constrained graph, do not restart the FalkorDB container during the demo window, and take a backup of the volume (`falkor-data-v2` locally; check the production volume name) before any restart. Check the data directory is on a volume that survives `docker compose down`.
4. **Nothing internal is exposed.** Only Caddy publishes 80 and 443. Postgres, Redis, FalkorDB, Temporal and the backend must not be reachable from outside: check with `ss -tlnp` and an external port scan (or `nmap` from another host) after `ufw` is on. The Temporal UI is bound to `127.0.0.1:8233` (reach it over an SSH tunnel only).
5. **Docker socket.** The worker uses the Docker socket to start Pi and test containers, which is root-equivalent on the host. Note it as a known risk; check builds run with the isolation described in `docs/runbook.md` (no credentials other than one model key, no network in the test container). The build network is not filtered to the model provider (known limitation); do not add secrets to the build environment.
6. **Resources.** Check memory after the full stack is up and during one build (`docker stats`, `free -h`). FalkorDB and Temporal are the big ones. If the server swaps, tell the human.
7. **Cost caps.** `ACTRON_DAILY_MODEL_BUDGET_USD=3` is set. Confirm the budget guard works (Settings shows it) and that a build stops when exceeded.
8. **Backups.** The nightly `pg_dump` runs (`infra/postgres/backup.sh`). Run it once by hand and do a trial restore into a scratch database to prove it works. Also back up `ACTRON_SECRET_KEY` and the FalkorDB volume somewhere off the server, and tell the human where.
9. **Logs.** JSON logs rotate (20 MB x 5 in compose). Check no secret shows in `docker compose logs backend worker` (the redactor should hide them).
10. **Cold start.** After a reboot everything must come back (`restart: unless-stopped`). Reboot the server once and check health, the Slack Socket Mode connection and that Temporal workers reconnect.
11. **Certificates.** Caddy renews by itself; its data volume (`caddy-data`) must persist or you hit Let's Encrypt limits after repeated redeploys.
12. **Time and rate limits.** GitHub API without a token is 60 calls an hour; the server needs `GITHUB_TOKEN`. Gemini's free tier is 20 requests a day per model: do not rely on it. DeepSeek bills per token (about $0.15 and $0.60 per million tokens for `deepseek-flash`, $0.66 and $1.98 for `deepseek-v4-pro`, double at peak hours 01:00 to 04:00 and 06:00 to 10:00 UTC on weekdays).
13. **Frontend build on the server.** The note in `BUILD-LOG.md` says Turbopack can fail on a cold Google-fonts download and the lock file must be regenerated with the image's npm. If the image build fails for these reasons, fix it the way the log describes, not with `npm install` on the host.

## 8. The repository (the team does this; you check it)

The team will make the repository public for the submission, with two branches: `dev` for work in progress and `prod` for what is deployed and submitted (`prod` is set as the repository's default branch on GitHub). The server deploys `prod`; updates reach it by merging `dev` into `prod` and running `git pull` then `make deploy` on the server. The older `main` branch only holds an earlier prototype and is not used. Before the team pushes, check and report:

- `.env` and `infra/.env.prod` are git-ignored; no real secret value appears in any file git would include (scan with the real values from `.env`, listing file names only).
- A `LICENSE` file exists (open in `NEEDS-FROM-USER.md`).
- The README has: setup steps, the graph data model, the Cypher queries and algorithms, tracks entered, a live deployment link, and an honest "How this was built" note.
- No generated or large artefacts are included by mistake (`node_modules`, `.next`, `.venv`, `data/`, `.actron/`).
- `.claude/settings.json` allows every tool; tell the team to decide whether it should be public.

## 9. Verification checklist and report

Write `DEPLOY-REPORT.md` with, for each line, PASS, FAIL (with the cause) or NOT DONE (with what the human must do):

- [ ] `dig` returns the server's IP; certificate valid; HTTP redirects to HTTPS
- [ ] `/api/health` healthy over HTTPS; every integration reports live
- [ ] Sign in with Slack works end to end; session cookie flags correct; dev login returns 404
- [ ] Calva ingested; the Graph screen shows real counts; search finds `docFromTextNotation`
- [ ] Slack: `/actron`, a mention, buttons and thread replies work from the server
- [ ] One real request through investigation, questions, ticket, approval
- [ ] Build with Pi produces a PR on the fork (or the exact stop reason)
- [ ] Live updates on the request page (SSE) work through Caddy
- [ ] GitHub webhook ping green; a merge to the working branch triggers a sync
- [ ] Only ports 22, 80, 443 reachable from outside
- [ ] Backup restored in a trial; reboot test passed
- [ ] Lighthouse on `https://actron.anubhavmalik.com` (desktop performance and accessibility)
- [ ] Rollback: how to return to the previous version (`git checkout <sha>` then `make deploy`; database migrations are forward only, so note the backup to restore if a migration is bad)

Also include: the server size and provider as given by the human, the commands to deploy an update (`git pull`, `make deploy`), how to read logs, how to open the Temporal UI over SSH, and every item left for the human.
