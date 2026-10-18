# Ingestion

This file describes how data gets into the graph. The code and git sections are written by W2 and live under their own headings. The GitHub, Slack, Slack export, Linear and sync sections below are written by W3.

## Code ingestion (W2)

Entry point: `actron.connectors.code.pipeline.ingest_code(ws, repo, *, url, branch, clone_dir, depth, token, emit, since_sha, store=None, repo_dir=None)`. With no `since_sha` it is a full backfill; with the stored cursor (`sync_cursors.cursor.last_sha`) it is an incremental run. It returns a `CodeIngestReport` (graph counts per node type and relationship, nodes written, unresolved calls, files changed and deleted, commits read, renames, PageRank method, partial reason, timings). Progress goes to the optional `emit` as `ingestion.progress {source: "code", runId, phase, counts}` after each phase. The steps are also methods on `CodeIngestion` (`walk_and_parse`, `resolve`, `link_tests`, `git_log`, `hunks`, `write_snapshot`, `documents`, `manifests`, `codeowners`, `write_history`, `blame`, `metrics`) but they share in-memory state, so a workflow should run `ingest_code` as one heartbeating activity.

**Clone.** `ACTRON_CLONE_DIR/<ws>/<owner>__<name>`, working branch only: `git clone --no-tags --single-branch --depth <ACTRON_GIT_HISTORY_DEPTH> [--branch <b>]`, later `git fetch --depth <d> origin +refs/heads/<b>:refs/remotes/origin/<b>` and a hard reset. No `--filter=blob:none`: with a partial clone, history reads fetched blobs one commit at a time (2 minutes per 200 commits on Calva). Private repos use a `GIT_ASKPASS` script that reads the token from the subprocess environment; the token is never in argv or the remote URL, and credentials in a given URL are stripped.

**Walk and skip.** Every tracked file (`git ls-files`, submodules excluded) becomes a `CodeFile` with `contentHash` (sha256), `size`, `language`, `loc` and `text`. Skipped files keep the node without text: `binary` (extension list or NUL in the first 8 KB), `lockfile`, `minified`, `generated` (`dist`, `build`, `node_modules`, `vendor`, `__generated__` directories, or `@generated` / `DO NOT EDIT` on the first line), `too_large` (over 1 MB).

**Parsing (tree-sitter-language-pack 1.22.1, tree-sitter 0.26.0).** Tier 1: Python, TypeScript, TSX, JavaScript, Go, Java, Rust. Tier 2: Kotlin, Ruby, PHP, C, C++, Scala, Swift, Clojure. Each function and class becomes `CodeFunction` / `CodeClass` with exact line ranges and the whole body. Qualified names: Python and TS `Class.method`, `outer.inner`; Go `Recv.Method`; Java dotted inside the file (`Outer.Inner.method`, overloads `~2`); Rust `Type::method` and `module::fn` for inline modules; TS/JS test callbacks are named by their strings, `describe > it`. Repeated names in one file get `~n` in source order. Lambdas and anonymous callbacks are not functions; their calls belong to the enclosing function. Caveat found here: in tree-sitter 0.26.0 `Point.row` / `Point.column` return a borrowed reference and corrupt the heap for values above 256; the code uses `node.start_point[0]`.

**Verified tier-2 node-type map** (parsed a sample file per language on 17–18 Oct 2026; `lang_maps.py`):

| Language | Classes | Functions | Calls | Name |
|---|---|---|---|---|
| Kotlin | `class_declaration` (also interfaces), `object_declaration` | `function_declaration` | `call_expression` (callee is the first child) | first `type_identifier` / `simple_identifier` child |
| Ruby | `class`, `module` | `method`, `singleton_method` | `call` (`receiver`, `method`) | `name` field |
| PHP | `class_declaration`, `interface_declaration`, `trait_declaration`, `enum_declaration` | `function_definition`, `method_declaration` | `function_call_expression`, `member_call_expression`, `scoped_call_expression`; `object_creation_expression` = new | `name` field; namespaces `namespace_definition` |
| C | `struct_specifier`, `union_specifier` (with a body) | `function_definition` | `call_expression` | `declarator` chain to `identifier` |
| C++ | adds `class_specifier` | `function_definition` (methods use `field_identifier`, out-of-class use `qualified_identifier`) | `call_expression`, `new_expression` | qualified names from `namespace_definition` |
| Scala | `class_definition`, `object_definition`, `trait_definition`, `enum_definition` | `function_definition` (`function_declaration` = abstract, skipped) | `call_expression`, `instance_expression` | `name` field |
| Swift | `class_declaration` (also struct and enum), `protocol_declaration` | `function_declaration`, `init_declaration` | `call_expression` | `name` field |
| Clojure | lists headed `defprotocol`, `defrecord`, `deftype` | lists headed `defn`, `defn-`, `defmacro`, `defmulti`, `defmethod`, `deftest` | list forms with a symbol head | `sym_lit` `name` / `namespace` fields; `ns` form gives the namespace and `:require` aliases; `(comment ...)` forms are skipped |

**Chunks and documents.** Lines outside every function and class are grouped into runs and split into `CodeChunk`s of at most 80 lines with 10 lines of overlap (`kind` `module_level`, `config`, `data`, `other`). Markdown (ATX and Setext, fenced code ignored, front matter kept in the preamble) and rst (underline and overline styles) become `CodeDocument` sections with `SECTION_OF`, `SUBSECTION_OF` and slugs with `~n`; lines before the first heading form a preamble section titled with the file name. Together, functions, classes, chunks and sections cover every line of every stored file (A-AC-28, verified on all 876 stored Calva files). Backticked paths and names that resolve to exactly one file, function or class give `DOC_MENTIONS_*` (method `explicit`, confidence 1.0).

**Resolution.** Tiers: `local` 1.0, self/cls/this/super 0.95 (stored as `resolution: local`), `import` 0.95 (dynamic `import()` / `require()` 0.6), `project` 0.7 (unique qualified name), `name_only` 0.4 (unique name). Tier 2 is capped at 0.6; Clojure `ns :require` aliases resolve as `import`. Calls through external packages make no edge; the file gets `IMPORTS_PACKAGE` when the package is declared in a manifest. TS imports resolve relative paths with `.ts/.tsx/.js/index.*` and `tsconfig.json` `baseUrl`/`paths`; Python handles relative and package imports; Go uses `go.mod`; Java resolves by package path; Rust follows `crate::`, `super::`, `self::` and `mod` files. Repeated calls between the same pair aggregate into one `CALLS` edge with `count` and `callSiteLines`; calls to classes become `INSTANTIATES`. `CALLS.method` is `structural` for local/import and `inferred` for project/name_only. Unresolved = ambiguous name-only matches plus tier-1 bare-name calls that match nothing and are not builtins; in Clojure an ambiguous bare name is treated as a core name (Calva ships two copies of `clojure_core.clj` under `test-data/`).

**Tests.** Test files and functions per spec A6.7 (Python `test_*`, TS/JS `*.test.*`, `*.spec.*`, `*-test.ts`, `src/extension-test/**`, Mocha `suite`/`test` and BDD `describe`/`it`, Clojure `deftest`, Go `Test*`, Java `@Test`, Rust `#[test]` and `#[cfg(test)]`). `TESTS` / `TESTS_CLASS` from calls (confidence of the call) or naming (0.6); `TEST_FILE_FOR` by file name (0.8) or by where more than half the test targets live.

**Manifests and owners.** `pyproject.toml`, `setup.cfg`, `requirements*.txt`, `package.json`, `pnpm-workspace.yaml` → `CodeComponent` per manifest directory (nearest wins), `CodeDependency` + `USES_PACKAGE`, workspace packages → `COMPONENT_DEPENDS_ON`. A repo without manifests gets one root component. CODEOWNERS (`.github/`, root, `docs/`) with gitignore patterns; the last matching rule wins → `MATCHES_OWNER_RULE`.

**Metrics** (`actron/graph/algos.py`, `connectors/code/metrics.py`): `callerCount`, `transitiveCallerCount` (backwards `[:CALLS*1..3]`), `pageRank` via `CALL algo.pageRank('CodeFunction', 'CALLS')` (Python power iteration fallback), `criticalityPercentile` from `0.6·pageRank_norm + 0.4·log1p(transitive)_norm` over non-test functions. Only functions whose values changed are rewritten. `algos.shortest_path` (`algo.SPpaths`, both directions) and `algos.bfs_callees` (`algo.BFS`) have Python fallbacks. All query timeouts stay at or below the server's `TIMEOUT_MAX` (60 s).

**Incremental runs (A6.10).** The whole snapshot is walked and parsed (resolution needs it), but only files whose `contentHash` changed are written. In those files, a function or class node is rewritten only when its body hash or line range changed; ids never depend on line numbers, so inserting lines above a function keeps its id and every link to it. Symbols that disappear are tombstoned (`deleted`, `deletedAt`) with their links kept; deleted files tombstone their symbols, chunks and sections; outgoing `CALLS`, `INSTANTIATES`, `TESTS`, `IMPORTS`, `INHERITS_FROM` links of changed files are replaced. Renames and moves: for each commit, deleted symbols are compared with added ones (body with the symbol's own name masked and indentation removed: equal → 1.0, else token Jaccard ≥ 0.8, same kind); symbols kept in a git-renamed file are moves with similarity 1.0. Chains across several commits are composed. `RENAMED_TO` / `CLASS_RENAMED_TO` / `FILE_RENAMED_TO` carry `commitSha` and `similarity`; `CALLS` and `TESTS` from unchanged callers are re-pointed to the new node. When the cursor is not an ancestor of the new head (force push), the last `depth` commits are re-read and the report carries `partial_reason: "history rewritten"`. Earlier code is read on demand by `history_tools.get_code_at(store_or_repo_dir, fn_id, sha)` and commits by `history_tools.history(store, fn_id, limit)`, both following `RENAMED_TO` back up to 5 hops.

## Git history (W2)

`git log --raw --numstat -M -z` (cursor range `since..HEAD`, else `--max-count=<depth>`) → `GitCommit` (sha, subject, message, author, dates in UTC, parents, merge flag, additions, deletions, `inClone = true`), `GitAuthor` (lowercased email; `commitCount`, first and last commit recomputed from the graph), `GitFileChange` (status added/modified/deleted/renamed, `oldPath`, line counts, binary flag, `hunks` as `"start-end"` strings because the loader allows only scalar arrays), with `COMMIT_IN_REPO`, `AUTHORED_BY`, `HAS_PARENT`, `HAS_FILE_CHANGE`, `CHANGE_OF_FILE`. Merge commits keep their parents but no file changes (their changes arrive through the merged commits); commits at the shallow-clone boundary are recorded without file changes. Hunks come from one `git log -p --unified=0` stream; the file at each commit and its parent is read through one `git cat-file --batch` process and parsed (cached by blob id). Each changed line maps to the innermost function, or to the class outside its methods: `TOUCHED` / `TOUCHED_CLASS` with `changeType` (added if the symbol was not in the parent version, deleted if it is gone, else modified) and `linesChanged`. Links are made only to nodes that exist in the graph (current or tombstoned). `lastCommitSha` / `lastChangedAt` come from the newest touching commit. A commit first created from the GitHub API with `inClone = false` is completed with file changes and `inClone = true` when it arrives (A-AC-101). Branches and tags from `git for-each-ref` (`GitBranch`, `GitTag`, `BRANCH_HEAD`, `TAGS_COMMIT`), `HEAD_COMMIT` from the repository. `git blame --line-porcelain` on changed stored files (8 in parallel) → `BLAME_OWNS_FILE` and `BLAME_OWNS` with `lines` and `lineShare`.

**Real numbers: BetterThanTomorrow/calva at `b2476a7fa428`** (branch `published`, depth 2000, 18 Oct 2026, local FalkorDB v4.22.1): full ingestion 36 s (hunk mapping 23 s, blame 4 s, snapshot writes 3 s). Nodes: 1,108 `CodeFile` (876 with text), 5,533 `CodeFunction`, 157 `CodeClass`, 5,194 `CodeChunk`, 1,509 `CodeDocument`, 7 `CodeComponent`, 73 `CodeDependency`, 2,000 `GitCommit`, 137 `GitAuthor`, 3,699 `GitFileChange`, 1 `GitBranch`. Links include 11,754 `CALLS`, 152 `INSTANTIATES`, 4,150 `TESTS`, 98 `TEST_FILE_FOR`, 976 `IMPORTS`, 5,436 `TOUCHED`, 7,277 `BLAME_OWNS`. Resolution tiers: 7,300 local, 7,458 import, 238 self, 1 project, 1,312 name-only, 1,575 unresolved (all TypeScript: mostly method calls on receivers whose names exist in several classes, and calls to Promise `resolve`/`reject` parameters). A second full run creates no nodes or links. The five most recent commits touching `activate` in `src/extension.ts` match `git log -L 86,675`. Tests: `tests/integration/test_ingest_calva.py` (marked `slow`).

## GitHub connector (W3)

**Where:** `backend/actron/integrations/github_client.py`, `backend/actron/connectors/github.py`, `backend/actron/connectors/github_links.py`.

**What it does.** Reads one repository (and an optional upstream) through the REST API and writes `GithubRepository`, users, pull requests with files, commits, reviews and review comments, issues and comments, labels, milestones, releases, branches, check runs and workflow runs, with the links in the ontology.

**Steps, in order** (`STEPS` in `connectors/steps.py`, one activity per HTTP page): `repo, org, contributors, pulls, pr_files, pr_commits, reviews, review_comments, issues, issue_comments, labels, milestones, releases, branches, check_runs, workflow_runs`. The steps that read history (`repo`, `pulls`, `pr_files`, `pr_commits`, `reviews`, `review_comments`, `issues`, `issue_comments`, `check_runs`) also run for the upstream repository.

**Cursor.** Keyed by repository (lowercase `owner/name`): `pulls_updated`, `issues_since`, `review_comments_since`, `issue_comments_since`, `runs_created`, `etags`, plus facts the later steps need (`repo_id`, `default_branch`, `owner_type`). Keys that start with `_` are scratch values for one run (`_prs` lists the PRs changed in this run for the file, commit, review and check steps; `_suites`; `_rate_stop`). Pull request and comment cursors only move forward. A listing's ETag is stored only after the whole listing finished, so a failed run never hides pages. A PR whose `updated_at` equals the stored cursor is not fetched again.

**Limits.** With a token: 100 items per page, no page cap inside the history window. Without a token: 30 per page, two pages per listing, five PRs for the per-PR steps, and a rate-limit answer ends the run `partial` with the reason "public rate limit". A 404 on one PR records a partial reason and the run continues. 403 or 429 with an exhausted limit or `Retry-After` raises `RetryableProviderError(retry_after)`.

**Commits not in the clone.** Commits that come from the API (PR commits, merge commits) are written with `inClone=false` only when the graph does not hold them yet, so a commit already ingested from the clone is never overwritten.

**Links to the code snapshot** (`github_links.py`):
- `PR_FILE_IS`: PR file to `CodeFile` by path (confidence 1.0, or 0.7 when a rename was followed).
- `PR_TOUCHED`: PR to the functions whose line range overlaps the file's hunks (0.9, with `linesChanged`).
- `COMMENT_ON_CODE_FILE` and `COMMENT_ON_FUNCTION`: the file is read at the comment's commit (`git show <sha>:<path>` in the clone; the commit is fetched when missing), the innermost function at the comment's line is found with tree-sitter (Python, TypeScript, JavaScript, Go, Java, Rust; a form scanner for Clojure), then renames are followed through `FILE_RENAMED_TO`, `RENAMED_TO` and git's rename history. Confidence 0.8, or 0.7 when a rename was followed. If the function no longer exists the link goes to its tombstone and the run records it. When there is no clone or the commit cannot be fetched, the line is mapped on the current snapshot with confidence 0.5 and method `inferred`, and the run records it.
- `MERGED_AS`: PR to its merge commit (created from the API when it is not in the clone).
- Explicit references (`ENG-12`, `#123`, URLs) are not resolved here; the raw text stays in the node for the linking step.

**Webhooks** (`handle_webhook` in `github.py`, pure functions): verify `X-Hub-Signature-256` (HMAC-SHA256 over the raw body, constant-time compare, no secret means nothing verifies), drop a repeated `X-GitHub-Delivery` (Redis `SET NX EX`), then route:

| Event | Result |
|---|---|
| `ping` | 200 |
| `push` to the working branch | trigger `code` and `github` now |
| `push` to another branch | 204, nothing |
| `pull_request` closed and merged into the working branch | trigger `code` and `github`, re-ingest the PR |
| `pull_request` merged into another branch | trigger `github`, re-ingest the PR |
| other `pull_request` actions, reviews, review comments, issues, issue comments | `github` trigger after a 30 s debounce |

`activities.ingest.apply_webhook_decision` carries the decision out. `trigger_sync` uses the schedule's trigger; when a run is going it sets a follow-up flag and the workflow starts one more run when it ends, so a merge during a sync is never missed. `check_pr_merged(repo, number, token)` is the single poll used by the merge watch.

**Verified.** Contract tests against `tests/fakes/github.py` (`A-AC-44` to `A-AC-48`), incremental and webhook tests, and a live test (`A-AC-49`, `pytest -m live tests/live/test_github_live.py`) that pulls five recent BetterThanTomorrow/calva PRs and recent review comments from the public API without a token and checks a `GithubReviewComment` is stored.

## Slack connector (W3)

**Where:** `backend/actron/integrations/slack_client.py`, `backend/actron/connectors/slack.py`.

The client is a small httpx wrapper over the Web API (not `slack_sdk`), so tests can use an in-process fake and read `x-oauth-scopes`. `ratelimited` and HTTP 429 raise `RetryableProviderError(retry_after)`; `invalid_auth`, `missing_scope` and similar raise `AuthError`.

**Steps:** `workspace, users, channels, members, history, replies`. Only channels in the connection's list (or, with no list, channels the bot is in) are read. A listed channel the bot is not in is skipped and written to the run's `errors`. History is read newest first per channel; the per-channel `oldest` moves only after the channel's last page. Catch-up re-reads the 24 hours before `oldest` so edits are seen, and unchanged messages are skipped by comparing with the graph, so only new or changed messages are written and counted. Threads are read for parents with new replies.

**Messages.** `SlackMessage` ids are `slack:msg:<channel>:<ts>`; `permalink` is built from the workspace domain; reactions and files come from the message. Bot messages carry `botId` and `subtype=bot_message`; Actron's own messages (same user as the bot) get the same tag. Edits keep the old text as `@v<n>` through `actron.graph.versions`; a retried write never adds a version twice.

**Live events.** `await handle_message_event(ws, event, *, workspace=None, enqueue=None)` handles `message`, `message_changed`, `message_deleted`, `channel_rename` and `member_joined_channel`. A delete tombstones the message and sets `deleted` on its outgoing `MENTIONS` and `CONTAINS_REFERENCE` links (A12.4a); the removed links are listed in a `slack.message_deleted` workspace event.

**Text for display and linking:** `normalize_slack_text(text, users, channels)` turns `<@U1>` into `@name`, `<#C1|x>` into `#x`, `<url|label>` into `label (url)`, and unescapes entities. Raw mrkdwn stays in `text`.

**Limits.** The ontology has no `mimetype` or reaction count property, so files keep id and name and reactions keep their name only.

## Slack export import (W3)

**Where:** `backend/actron/connectors/slack_export.py`.

Reads Slack's export format from a folder or a `.zip`: `users.json`, `channels.json` (and `groups.json`), one folder per channel with `YYYY-MM-DD.json` day files, and an optional `events.jsonl` applied afterwards in order. Mapping, ids, versions and tombstones are the same code as live Slack. A channel's original id (`original_id`, `previous_id` or `aliases` in `channels.json`) goes to `SlackChannel.aliases`. The workspace id is the export's team id, or `export-<hash of path>`.

**Re-import.** A day file whose SHA-256 is unchanged is skipped; inside a changed file only new or edited messages are written; `events_offset` records how many event lines were applied.

**Zip validation** (`validate_export`, run before anything is extracted): at most 200 MB compressed, 2 GB expanded, 256 MB per file, 100,000 files, expansion ratio under 200; no absolute paths, `..`, backslashes, drive letters or symbolic links; at least one channel day file. Extraction writes only inside the target folder, under `ACTRON_CLONE_DIR/<ws>/slack_export/`. `run_import(ws, config)` runs all steps without Temporal for the CLI.

## Linear connector (W3)

**Where:** `backend/actron/integrations/linear_client.py`, `backend/actron/connectors/linear.py`.

**Steps:** `teams, users, states, labels, projects, issues`. With a team in the connection only that team's issues, states and labels are read. Issues are filtered by `updatedAt > cursor` and read newest first; the cursor moves after the last team's last page. Comments beyond the first 50 are read separately. Attachment URLs go to `attachmentUrls`; `branchName` is stored for linking.

**Edits.** A changed title or description (and a changed comment body) copies the old node to `<id>@v<n>` with `ISSUE_PREVIOUS_VERSION` or `COMMENT_PREVIOUS_VERSION` and bumps `version`. The ids of edited nodes are in the run's changed ids, so linking re-runs on them.

**Writes.** `issue_create` uses an id derived from `sha256(ws + request_id)` (UUID v4 format). If the call fails and the issue already exists, the existing issue is returned, so a retry after a lost answer never duplicates. `issue_update` and `comment_create` are plain mutations. `detect_external_edit(description, expected_hash)` checks the marker `<!-- actron:ticket sha256=<hash> rev=<n> -->`, the hash of the fenced canonical JSON block, and the approved hash; any mismatch is an external edit.

**Not verified live.** Field names follow the spec's queries and the fake server. No Linear key was available, so they were not checked against Linear's schema (see NEEDS-FROM-USER.md).

## Source sync workflow, activities and schedules (W3)

**Where:** `backend/actron/workflows/source_sync.py`, `backend/actron/activities/ingest.py`, `backend/actron/connectors/steps.py`.

`SourceSyncWorkflow(ws, source, mode, resume=None)` reads the cursor, starts a run record, and for each step loops: `fetch_page`, `write_batch`, merge and `save_cursor`, `publish_progress`. After 200 pages it continues as new with `resume` (run id, cursor, totals, step index, page token). Retry policy: first retry after 2 s, doubling, at most 5 minutes apart, 8 attempts; `AuthError`, `ValidationError` and `OntologyViolation` are not retried. A rate limit raises `ApplicationError(next_retry_delay=Retry-After)`; temporalio 1.34 supports this and the time-skipping test shows the retries wait for it. An authorisation failure ends the run `failed` with the reason, marks the connection `error` and pauses the schedule.

Large batches (over 1 MB) are parked in Redis and travel as a key. Changed ids are kept in Redis per run; `start_linking` starts `LinkingWorkflow` on the `link` queue with them (5,000 per workflow). Progress is stored as `ingestion.started`, `ingestion.progress`, `ingestion.partial` and `ingestion.finished` events (`request_id` null) and published on `ws:<ws>:ingestion`.

**Schedules:** `ensure_sync_schedule(ws, source)` creates `sync-<ws>-<source>` (code 15 min, GitHub 5, Linear 5, Slack 10; Slack export has none), overlap SKIP. `connect_source` starts the backfill and creates the schedule. `trigger_sync` is "Sync now".

## Connector forms and setup checks (W3)

`backend/actron/connectors/forms.json` holds the form for each provider (fields as in spec C12). `forms.py` serves it with `load_forms()` and provides `validate(provider, values)` (a live call, plain-language result), `options(provider, field, values)` (branches with the default first, channels the bot is in, Linear teams and labels) and `checks(provider, ws)` (Slack scopes from `x-oauth-scopes`, Socket Mode, GitHub push access, Linear viewer and team) with the troubleshooting text from C13. Secrets are never part of a result.
