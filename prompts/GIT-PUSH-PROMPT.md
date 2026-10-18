# Publish Actron to GitHub: commits, `dev` and `prod` branches

You are an agent preparing the Actron repository for publication. The team has authorised you to make commits and push to the repository named below, and only that. Read this whole file first. Work unattended; when a step needs a human, write it to `NEEDS-FROM-USER.md` under "Publishing", skip to the next independent step, and keep going.

## 1. Facts

- Local repo: `/home/vikram/Desktop/actron`. It is initialised on an unborn branch (`main`) with **no commits** yet and no remote. Everything is untracked.
- Target: `https://github.com/malikanubhav/actron` (public). It was created on 17 October 2026 and has one branch, `main`, with two commits by Anubhav from that day (specification docs, then a first implementation). The user has write access.
- The hackathon (FalkorDB Graph Hacks) requires the main work to start after 15 October 2026 12:01 AM IST. That repo's creation date and these commit dates are inside the window; they are the team's proof. **Never rewrite, rebase, squash or force-push history. Never backdate: do not set or change `GIT_AUTHOR_DATE` or `GIT_COMMITTER_DATE`.**
- None of the code in Anubhav's `main` is used. The new commits contain only our own files; the old files simply stop being present on top of the existing history.
- Branches wanted: `dev` (work in progress) and `prod` (what is deployed and submitted; set as the default branch on GitHub). Leave `main` untouched.

## 2. Rules

- **Identity:** use the author name and email the user has exported in their shell as `GIT_AUTHOR_NAME`, `GIT_AUTHOR_EMAIL`, `GIT_COMMITTER_NAME`, `GIT_COMMITTER_EMAIL`. Do not write them into any file, do not run `git config --global`, and do not run `git config` to store them. If they are not set, stop and tell the user to export them, then wait.
- **Credentials:** use whatever Git authentication the user already has on this machine (SSH key or the credential helper). Never ask for, print or store a token or password. Do not use `gh`.
- No secrets in any commit. No `.env`, no `infra/.env.prod`, no session-state files, no keys in prompts or docs.
- Do not push anything except `dev` and `prod`. No tags, no deleting branches, no force flags of any kind.
- Do not change product code. The only edits you may make are listed in section 4 step 4.

## 3. Prerequisite for the human (check, do not work around)

The project's `.claude/settings.json` denies `git commit`, `git push`, `git remote`, `git config` and `gh`. That was deliberate so that no earlier agent could publish. For this task the user must either remove the `git commit`, `git push` and `git remote` deny lines (keeping `gh`, `sudo` and the other denies), or run this agent from a session that does not load that file. If a git command is blocked by the permission check, **do not look for a way around it**: stop and report which command was blocked.

## 4. Steps

1. **Look.** `git status --short | head`, `git log` (should say no commits), the size of the tree, and the list of top-level entries. Confirm `.env` is ignored (`git check-ignore -v .env`).
2. **Pre-push checks. Stop and report if any fails:**
   - **Secrets.** Read every secret-looking value from `.env` (names containing KEY, TOKEN, SECRET, PASSWORD, value 16 characters or longer) and search every file git would include (`git ls-files -o -c --exclude-standard`, skipping `node_modules` and `.venv`) for those exact values. Also search for token shapes (`xox[bpa]-`, `xapp-1-`, `github_pat_`, `lin_api_`, `sk-` followed by 24 or more hex characters, `apikey_`, `AIza`). Fake tokens in test fixtures are fine, but every match must be looked at and judged, not skipped. Print file names and the kind of match, never the value.
   - **Licence.** A `LICENSE` file must exist at the repository root. If it does not, stop before any commit and tell the user to choose one (for example MIT or Apache-2.0); do not choose for them.
   - **Size.** No tracked file over 5 MB; no `node_modules`, `.venv`, `.next`, `data/`, `.actron/`, `*.rdb`, `*.aof`, `video/captures` raw clips, or browser session-state files.
   - **Keep out of the public repo by default** (add each to `.gitignore`, unless the user has said otherwise in `NEEDS-FROM-USER.md`; say in the report that you did this and how to reverse it): `.claude/` (third-party skills and a permissive settings file), `skills-lock.json`, `prompts/` (working prompts for deployment, video, live setup, UI review and publishing: they name servers, domains, Slack and Linear details and say which keys were exposed during development), `docs/blog-research.md` (internal notes) and everything under `video/` (raw captures, audio, session state, narration drafts). **Once a file is pushed it stays in the public history forever, because history is never rewritten here, so these are excluded now rather than removed later.** The root `PROMPT.md`, `PRD.md`, `PLAN.md` and `specs/` do go in: they are the spec-driven build record the README describes.
3. **Connect to the existing history without touching it.**
   - `git remote add origin https://github.com/malikanubhav/actron.git` then `git fetch origin`.
   - Read what is on `origin/main` (`git ls-tree -r --name-only origin/main`). Report anything in it that is not in our tree and may be worth keeping. In particular, if `docs/implementation-review.md` exists, keep it: copy it from `origin/main` into `docs/implementation-review.md` unchanged (`git show origin/main:docs/implementation-review.md`) so Anubhav's finding about FalkorDB persistence stays in the repo. Do not copy code.
   - Put our work on top of `origin/main`: `git update-ref refs/heads/dev origin/main`, `git symbolic-ref HEAD refs/heads/dev`, then `git reset` (mixed, no `--hard`) so the working tree is untouched and the index equals `origin/main`. `git status` will then show our files as new and the old prototype files as deleted. Show the list of deleted paths in the report.
4. **README note.** Before committing, add a short factual section to `README.md` (above "AI use disclosure"), titled "Timeline": the repository was created on 17 October 2026; the product requirements, ontology and specs were written on 17 October; the build ran 17 to 18 October (take the first and last timestamps from `BUILD-LOG.md`); the first two commits in the history are an earlier prototype that this project builds on and does not reuse. Keep it to four or five lines. This is the only edit to existing files besides `.gitignore` and the copied `implementation-review.md`.
5. **Commits.** Split the work into these commits, in this order, staging by path (`git add <paths>`), checking `git diff --cached --stat` before each. Messages are in imperative mood, no full stop, a short body only where it helps. Do not mention a replaced or earlier prototype in any message. Add the trailer `Co-Authored-By: Claude <noreply@anthropic.com>` to the commits that contain generated implementation code (3 to 5 below), as the README discloses AI assistance; leave it off the others.
   1. `docs: add product requirements, graph ontology and build specs` : `PRD.md`, `PLAN.md`, `PROMPT.md`, `ontology/`, `specs/`, `config/`, `DESIGN-DIRECTIONS.md`, and the removal of the old files if they cannot be attached to a later commit.
   2. `feat(graph): add ontology loader, FalkorDB store and source ingestion` : `backend/actron/graph`, `backend/actron/connectors`, `backend/actron/integrations`, `backend/actron/db`, `backend/actron/config.py` and what they import, with their tests.
   3. `feat(flow): add request workflows, MCP graph tools, investigator and Pi build` : `backend/actron/flow`, `workflows`, `activities`, `mcp_graph`, `models`, `linking`, `api`, `worker.py`, `cli.py`, with their tests and fixtures.
   4. `feat(web): add Next.js app, graph canvas and design system` : `frontend/` (without screenshots), `DESIGN.md`, `UI-REVIEW.md`.
   5. `chore(infra): add compose stacks, deploy scripts and Slack manifests` : `infra/`, `scripts/`, `Makefile`, `.env.example`, `.gitignore`.
   6. `docs: add README, architecture, graph model and run reports` : `README.md`, `docs/`, `BUILD-LOG.md`, `BUILD-REPORT.md`, `DEMO.md`, `NEEDS-FROM-USER.md`, `LICENSE`, `frontend/tests/screenshots/` (screenshots). Nothing from `video/` or `prompts/`.
   Everything must end up committed; after the last commit `git status --short` must show nothing (except ignored files). If a path does not fit a commit, put it in the closest one. If a commit would be empty, skip it.
6. **Push.** `git push -u origin dev`. Then `git branch prod dev` and `git push -u origin prod`. Do not push `main`. Do not push with any force option; if a push is rejected, stop and report the exact message.
7. **Verify from outside.** In a fresh temporary directory outside the repo: `git clone --branch prod https://github.com/malikanubhav/actron.git`, then check: `.env` is absent; the secret scan from step 2 on the clone is clean; `README.md`, `LICENSE`, `ontology/`, `backend/`, `frontend/` and `infra/compose.prod.yaml` are present; `git log --oneline` shows Anubhav's two commits at the bottom with their original dates, then ours; the Mermaid blocks in the README start with a valid diagram keyword (`flowchart` or `sequenceDiagram`); `prompts/`, `video/`, `.claude/` and `docs/blog-research.md` are absent. Remove the temporary clone afterwards.
8. **Human steps to report** (do not try to do them): GitHub, repository Settings, Branches, set the default branch to `prod`; optionally protect `prod`; add the repository description and topics; confirm both team members are on the hackathon submission.

## 5. Report

Write `PUBLISH-REPORT.md` in the repository root (and commit it on `dev` only if the user asks later): the commit list with short hashes and messages, the branches pushed, what was excluded from the public repo and why, the files from the old prototype that were removed or kept, the results of each pre-push check, and anything left for the human. No secrets, no email addresses.
