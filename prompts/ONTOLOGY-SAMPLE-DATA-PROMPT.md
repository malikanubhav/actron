# PROMPT: prepare a real-world sample dataset to harden the Actron ontology

You are a data engineer. Build a realistic, internally consistent dataset that Actron's ontology will be tested against. It combines **real public data** (the Calva code repository, its GitHub history, and the real public archive of its Slack channel) with a **small synthetic Linear workspace** grounded in that real data, plus ground-truth labels.

Work without asking questions. If something is unclear, choose the option that keeps the data most real and most respectful of the people in it, write the choice into `README.md` under "Decisions", and continue. Do not stop until every deliverable in section 10 exists and passes the checks in section 9.

**Where to write:** only inside `/home/vikram/Desktop/actron/data/sample-calva/` (create it). Temporary files go in your scratchpad. Do not modify any other file in the repository. Do not commit or push. This folder is git-ignored and **temporary**: after the ontology checks it will be deleted so that no other agent ever uses it.

---

## 1. Why this dataset exists

Actron builds one graph from four sources: code (a git clone), GitHub (PRs, reviews, issues, checks), Slack (messages, threads) and Linear (issues, comments). Its ontology is in `/home/vikram/Desktop/actron/ontology/` (`code.json`, `github.json`, `slack.json`, `linear.json`, `core.json`). Read all five files first. The dataset must exercise every node type and relationship that ingestion and linking are expected to fill, especially the cross-source links in `core.json` (`MENTIONS`, `CONTAINS_REFERENCE`, `RESOLVES_TO`, `IMPLEMENTED_BY`, `PR_TOUCHED`, `COMMENT_ON_FUNCTION`, `EXTRACTED_FROM`, `CONSTRAINS`, `APPROVED_IN`, `SUPERSEDES`, `THREAD_OF`, `POSTED_BY`, `PREVIOUS_VERSION`, `KNOWS_ABOUT`, ...).

The dataset will be mapped onto the ontology and checked with competency questions (section 7). Anything the data needs that the ontology cannot represent is a gap to fix before the build.

---

## 2. Sources and rules

### 2.1 Code: real
- Repository: **`BetterThanTomorrow/calva`** (MIT licence; a VS Code extension for Clojure; about 2.3 MB of TypeScript and 1 MB of Clojure; about 1,300 PRs).
- Clone `https://github.com/BetterThanTomorrow/calva` into the scratchpad. Record the current default-branch HEAD SHA as `pinnedSha` in `manifest.json`. All code references in labels are resolved at `pinnedSha`.

### 2.2 GitHub: real
- Use the public GitHub REST API. Use `GITHUB_TOKEN` from the environment if set; otherwise stay under 60 requests per hour by limiting volume and caching every response to disk before parsing.
- Keep raw API responses exactly as returned (field names and nesting). Strip nothing except HTTP headers.

### 2.3 Slack: real, from the public Clojurians archive
- The Clojure community's Slack is published on the public web at **`https://clojurians-log.clojureverse.org/`**, readable without login. The channel is **`#calva`**: `https://clojurians-log.clojureverse.org/calva`, with one page per day at `https://clojurians-log.clojureverse.org/calva/YYYY-MM-DD`.
- Verified structure of a day page (17 Oct 2026): each message is an element with class `clojurians-log_components_common__message_row`, containing `..._username_span` (author display name), `..._timestamp_span` (ISO 8601 UTC timestamp, for example `2026-10-16T14:44:54.031319Z`), `..._message_content`/`..._message_body` (text and links), `..._reply_thread` (thread replies) and `..._reactions_row` (reactions). Inspect two or three pages yourself before writing the parser and adjust to what you see.
- **Look for an official export first.** Check the archive's site and its open-source project (search GitHub for `clojurians-log`) for a documented data export or API. If one exists and is public, prefer it to page parsing and record it in the README.
- **Polite collection (mandatory):** fetch `robots.txt` first and obey it (at the time of writing it returned an HTML page, which means no rules; re-check). Use a descriptive User-Agent (`actron-research/0.1 (hackathon dataset; contact: none)`), at most one request every 2 seconds, sequential only, cache every page to disk and never refetch a cached page, stop on any 429 or 5xx and wait at least 60 seconds before continuing, and never attempt to bypass any challenge or block. If the site starts blocking, stop collection, keep what you have, and record it in the README.
- **Scope:** the last 9 months of `#calva` day pages (only days that exist in the channel's index). If that yields fewer than 400 messages, extend back up to 18 months.
- **Pseudonymise people (mandatory).** The archive shows real display names. In everything you write to `data/sample-calva/`, replace every author name and every `@name` mention in message text with a stable pseudonym in the form `adjective-noun-NNNNN` (for example `quiet-river-40213`), derived from an HMAC-SHA256 of the original name with a random key that you generate at the start, keep only in memory, and never write to disk. The same person always gets the same pseudonym within the dataset. Do not store original names anywhere, including caches you leave in `data/sample-calva/` (cache raw pages only in the scratchpad, and delete the scratchpad cache at the end).
- **Convert to Slack's official export format** (section 4.2), so Actron's Slack import path can ingest it exactly like a real workspace export.

### 2.4 Linear: synthetic, grounded in the real data
- Calva does not use Linear. Create a small synthetic Linear workspace for a fictional team, **"Northwind Labs"**, that builds an internal Clojure tooling product on a fork of Calva. Team key `CAL`.
- Personas: invent 8 to 10 Northwind engineers (names, display names, emails on `@example.com`). They are not the people in the Slack archive and never claim to be.
- Their Linear issues and comments reference **real** Calva PRs, issues, files, functions and real `#calva` Slack threads (by permalink-style key), so explicit references and pending references can be tested across tools.
- Also create 6 to 10 **synthetic Northwind PRs** on the fictional fork `northwind-labs/calva`, in GitHub REST shape, with **real patches against `pinnedSha`** (valid unified diffs on real files and lines), reviews and review comments by `nw-<name>` logins mapped to the personas, and Linear keys in titles, bodies or branch names (`CAL-12`, `fix/CAL-31-...`). These test `IMPLEMENTED_BY`, `PR_TOUCHED` and identity matching across Linear and GitHub (by `@example.com` email).

### 2.5 General
- Mark every synthetic file with `"synthetic": true` at the top level or in a sidecar `_meta.json`; list synthetic and real files separately in the README and `manifest.json`.
- Never attribute anything to a real person that they did not write. Never put a real person's name or email in synthetic files.

---

## 3. Pin the code and build a code index

1. At `pinnedSha`, build an index for yourself: TypeScript and Clojure files, classes, functions and methods with qualified names and line ranges (a quick tree-sitter pass with `tree-sitter-language-pack` or careful grep), and callers by simple search.
2. Pick a **shared helper**: a real TypeScript function in Calva called from several distinct features (for example something used by both the REPL connection code and the formatter or the evaluation code). Record it and its callers in `manifest.json`. It anchors the main conflict scenario.
3. Use this index so every code reference you write in labels or synthetic data is real: real paths, real qualified names, real line ranges at `pinnedSha`.

---

## 4. Deliverables per source

### 4.1 Real GitHub data (`github/real/`)
- `repo.json`, `labels.json`, `milestones.json`, `releases.json` (latest 15), `contributors.json`.
- `pulls.json`: 60 to 80 PRs, mixed states (open, closed, merged), spread over the last two years, preferring PRs with review discussion and PRs that touched the files around the shared helper. For each: `pulls/<n>/files.json`, `pulls/<n>/reviews.json`, `pulls/<n>/comments.json` (review comments), `pulls/<n>/commits.json`.
- `issues.json`: 40 to 60 issues (not PRs) with `issues/<n>/comments.json`; prefer issues that are also discussed in `#calva` (search Slack text for issue numbers and links).
- `checks/<sha>.json`: check runs for at least 10 PR heads.
- Note in the README which PRs and issues are referenced from the Slack data (these are the most valuable).

### 4.2 Real Slack data, pseudonymised (`slack/`), in Slack's official export format
- `users.json`: one entry per pseudonymised author: `id` (`U` + 10 uppercase alphanumerics derived from the pseudonym), `name` (the pseudonym), `real_name` (the pseudonym), `profile.display_name`, `is_bot` (true for obvious bots such as GitHub or release bots), no email.
- `channels.json`: one channel `calva` with a stable `id` (`C` + 10 characters), `name`, `created` (earliest message), `members` (all user ids), `topic`, `purpose` (from the archive if shown, else empty).
- `calva/YYYY-MM-DD.json`: an array of messages per day: `type: "message"`, `user`, `text` (Slack mrkdwn: convert links to `<url|label>` or `<url>`, mentions to `<@Uxxxx>` using the pseudonym ids, keep code blocks), `ts` (from the ISO timestamp as `seconds.microseconds`), `thread_ts` for replies (the parent's `ts`), `reply_count`, `reply_users`, `replies` on parents, `reactions` (name, count; `users` empty when unknown), `subtype` where the archive shows one (for example deleted messages).
- `events.jsonl`: Slack doesn't give us edit history from the archive, so **synthesise** a small, clearly marked set of incremental events on real messages, in Events API shape, to test versioning and tombstones: at least 10 `message_changed` events (small realistic edits: typo fixes, an added link, one edit that changes the wording of a decision) and at least 4 `message_deleted` events, plus at least 10 new messages from synthetic Northwind personas (as Slack users `nw-...`) that reference `CAL-n` keys appearing only later in `linear/updates.jsonl`. Mark the file `"synthetic": true` and list each event's base message.

### 4.3 Synthetic Northwind PRs (`github/synthetic/`)
As in 2.4: GitHub REST shape, real patches against `pinnedSha`, reviews and review comments, synthetic commit SHAs (40 hex characters, unique), commits by persona emails. At least one PR changes the shared helper and has a review comment on the exact lines warning about another feature that depends on it.

### 4.4 Synthetic Linear workspace (`linear/`), GraphQL response shape
- `viewer.json`, `teams.json` (team `CAL`), `users.json` (personas), `workflowStates.json`, `labels.json`, `projects.json` (2 to 3), `cycles.json`.
- `issues.json`: 40 to 60 issues with `id` (UUID), `identifier` (`CAL-n`), `number`, `title`, `description` (markdown), `priority`, `estimate`, `url`, `branchName`, `state` (`id`, `name`, `type`), `assignee`, `creator`, `team`, `project`, `labels`, `parent` (some sub-issues), `createdAt`, `updatedAt`, `completedAt`, `canceledAt`, `comments.nodes` (`id`, `body`, `url`, `user`, `createdAt`, `updatedAt`, `editedAt`, `parent`).
- Descriptions and comments reference real Calva files, functions, PRs and issues and real `#calva` threads.
- `updates.jsonl`: at least 15 incremental updates (state changes, edited descriptions, new comments, new issues), same shape, later `updatedAt`.

---

## 5. Scenarios the data must contain (ground truth in section 6)

Find as many as possible in the **real** Slack and GitHub data first; fill the rest with clearly marked synthetic additions (events, Northwind messages, Linear).
1. **Approved decision constraining code** (prefer a real `#calva` thread where maintainers settle how a feature should behave; if none fits cleanly, a synthetic Northwind thread about the shared helper).
2. **Proposal never approved.**
3. **Decision superseded** later for a narrower scope.
4. **Decision edited** (via `events.jsonl`): the wording changes; ground truth gives both versions.
5. **Deleted message** that mentioned a PR (archive deletions if present, else via `events.jsonl`).
6. **Conflicting request**: a Northwind message (synthetic) asking for a change that contradicts scenario 1.
7. **Possible conflict** request.
8. **Nothing-found** request about code with no discussion history.
9. **Explicit references of every kind** found in real or synthetic text: `CAL-n`, `#123`, `BetterThanTomorrow/calva#123`, full PR and issue URLs, a commit SHA, a file path, a qualified function name, a Slack thread key.
10. **Meaning-only mentions**: real messages that clearly discuss a feature or function without naming it.
11. **Pending reference**: a Slack message (synthetic Northwind) referencing `CAL-n` that appears only in `linear/updates.jsonl`.
12. **Identity**: personas appear in Linear and synthetic GitHub with the same `@example.com` email; one persona uses different display names in each; two personas share a first name (must not be merged on name alone). Real Slack pseudonyms have no email and must stay unresolved.
13. **Ticket → PR → code chain**: a Linear issue implemented by a synthetic PR touching specific real functions.
14. **Review-comment reasoning**: real Calva PRs with review comments on specific lines (map several to the function they sit in at the PR's base).
15. **Expertise signals**: a real pseudonymised Slack author who clearly knows an area (many answers about it), and a real GitHub contributor with many commits and reviews there.
16. **Procedure signals**: real PRs and messages that state how changes are validated (test commands, files that change together).
17. **Questions for Q&A mode**: at least 10 real questions from `#calva` whose answers exist in the dataset (in replies, PRs or docs).
18. **Noise**: real chatter, thanks, off-topic links, bot posts.

---

## 6. Ground truth (`labels/`)

Reference records by **source-native keys**, not by Actron ids: Slack `<channel id>:<ts>`, Linear `CAL-n` or comment id, GitHub `owner/name#number`, review comment `review_comment:<id>`, code `path::QualifiedName` at `pinnedSha`, commit SHA.
- `decisions.yaml`: `source`, exact `quote` (must be an exact substring of the source text, after pseudonymisation), `status` (`approved`, `proposed`, `superseded`), `approvedIn`, `decidedBy` (pseudonym or persona), `constrains` (code or feature keys), `supersedes`, and `quoteBefore`/`quoteAfter` for edited ones.
- `links.yaml`: expected links with `from`, `type` (relationship names from the ontology files), `to`, `method` (`explicit` or `inferred`), and a one-line `why`. At least 150 links, at least 40 `inferred`.
- `non_links.yaml`: at least 40 tempting pairs that must not be linked.
- `identities.yaml`, `conflicts.yaml`, `pending_references.yaml`, `tombstones.yaml`, `features.yaml`, `expertise.yaml`, `procedures.yaml`, `qa.yaml`.
- `competency.yaml`: at least 30 plain-English competency questions with expected answers as sets of source keys or values, covering Track 01 (multi-hop request → ticket → PR → function; callers of the shared helper; tests covering it; decisions constraining it), Track 02 and Track 03.
- For every label, a field `origin: real|synthetic` so the checks can report quality on real data separately.

---

## 7. Competency question examples (write at least 30)
- Starting from the conflicting request, which approved decisions constrain the code it would change, and where was each approved?
- Which functions call the shared helper (up to three hops), and which tests cover them at `pinnedSha`?
- Which Linear issue was implemented by the synthetic PR that changed the shared helper, and which Slack thread discussed it?
- Which review comments sit inside a chosen real function across Calva PRs?
- Who (pseudonym or GitHub login) knows the REPL connection area best, and what evidence supports it?
- Which references were pending after the Slack import and resolved after the Linear updates?
- After `events.jsonl`, what is the current wording of decision X, and what was it before?
- Which `#calva` threads mention a PR that was later merged, and which functions did that PR touch?

---

## 8. Things to avoid
- No real names or emails anywhere in `data/sample-calva/`.
- No bypassing of any block, challenge or rate limit; no parallel fetching of the archive.
- No invented Slack history presented as real: every synthetic Slack item is in `events.jsonl` or carries `"synthetic": true`.

---

## 9. Checks you must run before finishing (write `checks/validate.py`, run it, save output)
1. Every JSON and YAML file parses.
2. Every quote in `decisions.yaml` is an exact substring of its source text (after applying edits for `quoteAfter`).
3. Every code key exists at `pinnedSha` (path exists; qualified name found; line ranges correct).
4. Every synthetic patch applies cleanly to `pinnedSha` (`git apply --check`).
5. Every Slack `thread_ts` points at an existing parent in the same channel; every `<@U…>` mention is a real user id in `users.json`; timestamps increase within a thread.
6. Every Linear key referenced exists in `issues.json` or `updates.jsonl` (pending ones only in the latter).
7. Every link and label references an existing record.
8. **Privacy check:** none of the original display names collected during this run appear in any file under `data/sample-calva/` (compare against the in-memory set before discarding it); all synthetic emails end in `@example.com`.
9. Counts meet section 4 (or the README explains a shortfall, for example a smaller archive); print a summary table with real and synthetic counts separately.
Write the output into `VALIDATION.md`.

---

## 10. Final layout
```
/home/vikram/Desktop/actron/data/sample-calva/
  README.md            sources, licences (Calva MIT; Clojurians archive public), collection method and politeness rules followed,
                       pseudonymisation, personas, scenario index (scenario → files and keys, real or synthetic), decisions you made
  manifest.json        pinnedSha, shared helper, fetch dates, counts per file, real vs synthetic file lists
  github/real/...      raw public API responses for BetterThanTomorrow/calva
  github/synthetic/... Northwind PRs on the fictional fork
  slack/...            Slack export format (real #calva, pseudonymised) + events.jsonl (synthetic)
  linear/...           synthetic GraphQL-shaped files + updates.jsonl
  labels/...           ground truth (section 6)
  checks/validate.py   validation script
  VALIDATION.md        validation output
```
Delete your scratchpad caches (including raw archive pages) at the end.

When everything passes, finish with a short summary: counts (real and synthetic), scenarios covered and which were real, anything you could not cover and why.
