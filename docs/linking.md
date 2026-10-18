# Linking

After every source run, linking connects the new and changed records to people, to each other, to code and to decisions. It runs on the changed ids only, and the result does not depend on the order in which sources arrive: a reference to something not yet ingested is stored as pending and resolved later.

Code: `backend/actron/linking/`, workflow `backend/actron/workflows/linking.py`, activities `backend/actron/activities/link.py`. Spec: A12 in `specs/A-graph-and-ingestion.md`, PRD 8.5.

**Status on 18 Oct 2026:** identity, explicit references and pending resolution work without any model and are tested against FalkorDB. Meaning links, decisions, approvals, supersession and link checks are tested with fake Jev and fake LLM answers. With no keys (the current state) the model steps run as stubs: they create no inferred links and no decisions.

## Order

`LinkingWorkflow(ws, changed_ids, options)` on task queue `link`. Each step is an activity; text steps run in batches (default 100) with a per-run cap (default 2,000 texts; the rest waits for the next run).

1. **Identity** (when an account changed): `link_identity`.
2. **References** per batch, then **pending resolution** for the sources in this run: `link_references`, `link_resolve_pending`.
3. **Classify** (J1) per batch: `link_classify`. Results pass to the next steps; they are not stored on nodes.
4. **Meaning links** per batch: `link_meaning`.
5. **Decisions** per batch: `link_decisions`.
6. **Link checks** on every model-made link of this run: `link_checks`.
7. **Knowledge and ownership**, then **procedures**: `link_knowledge`, `link_procedures`.

Events (A.C6, through `actron.flow.events.publish_workspace_event`): `linking.progress {runId, step, done, total}` after each batch, `linking.finished {runId, counts: {references_resolved, pending, decisions, identities, links_kept, links_dropped}}` at the end. `actron.linking.runner.run_linking` runs the same steps in-process for tests and the CLI.

## 1. Identity (A12.1)

Inputs: `SlackUser` (not bots), `GithubUser`, `LinearUser`, `GitAuthor`.

- Same lowercased email across sources → one `Person`.
- GitHub noreply emails (`<id>+<login>@users.noreply.github.com` or `<login>@users.noreply.github.com`) join the git author to that GitHub user.
- `config/identity_map.yaml` joins accounts whose emails differ. Entries: `- person: <name>`, `accounts: [slack:<id>, github:<login or id>, linear:<uuid>, git:<email>]`. Entries that match no account are reported, not guessed.
- Display names never join accounts.
- Each account gets an `Identity` (`matchMethod` `email`, `mapping_file` or `unresolved`; confidence 1.0, or 0.0 when unresolved) with `HAS_IDENTITY` and `IS_SLACK_USER` / `IS_GITHUB_USER` / `IS_LINEAR_USER` / `IS_GIT_AUTHOR`.
- An account with no match gets its own `Person` and is listed as unresolved in the step result.
- The `Person` id comes from the smallest account key in the group, so it is stable. When a later email or mapping entry joins two people, every link of the extra `Person` (for example `DECIDED_BY`, `KNOWS_ABOUT`, `OWNS`) moves to the kept one, and the extra node is deleted.
- Display name: the mapping file name, else Linear, Slack, GitHub, git.

## 2. Explicit references (A12.2)

Patterns run on the text (Slack text, Linear title and description plus attachment URLs, PR title and body, comments, review bodies, commit messages, doc sections). Each match becomes a `Reference` (`actron:ref:<kind>:<key>`, shared by every text that mentions it), linked from the text with `CONTAINS_REFERENCE` (method `explicit`, quote = the match with up to 60 characters on each side).

| Pattern | Stored kind | Key | Notes |
|---|---|---|---|
| `ABC-12` | `linear_issue` | `ABC-12` | prefix must be a known Linear team key; before any team is known, any prefix except standards (`HTTP`, `UTF`, `ISO`, `SHA`, `RFC`, `CVE`, ...) |
| `https://linear.app/<org>/issue/ABC-12` | `linear_issue` | `ABC-12` | |
| `#123`, `owner/name#123` | `github_pr` (or `github_issue` once resolved) | `owner/name#123` | bare `#123` uses the text's repository (from the PR or issue, else `GITHUB_REPOSITORY`, else the only `CodeRepository`); ignored in code blocks, inline code, HTML entities and hex colours |
| `https://github.com/o/n/pull/1`, `/issues/1` | `github_pr`, `github_issue` | `o/n#1` | |
| `commit <sha>`, `` `<sha>` ``, `/commit/<sha>` | `commit` | sha prefix (7-40 hex) | only in these code-like places; version strings never match |
| tokens with `/` and an extension | `file` | path | created only when they match a `CodeFile` path suffix; never pending |
| `` `name` ``, `` `A.b` ``, `name()` | `symbol` | name | created only when they match a `CodeFunction`/`CodeClass` (qualified name first, then name) |
| `https://<ws>.slack.com/archives/C…/p<16 digits>` | `slack_message` | `C…:<ts>` | resolved through `SlackChannel.id` or `SlackChannel.aliases` |
| PR `headRef` containing a team key, or equal to `LinearIssue.branchName` | `linear_issue` | `ABC-12` | |

Resolution:

- One target: `status = resolved`, `RESOLVES_TO`, and `MENTIONS` from the text (method `explicit`, confidence 1.0).
- Several targets: `status = ambiguous`, `RESOLVES_TO` each, no `MENTIONS`.
- No target: `status = pending`.
- A PR that mentions a Linear issue (title, body or branch), or whose `headRef` equals an issue's `branchName`, gets `IMPLEMENTED_BY` (issue → PR). A Linear attachment URL that is a PR also gives `IMPLEMENTED_BY`.
- **Pending resolution** `resolve_pending(store, source)` runs after each source's run for the kinds that source can satisfy (`linear` → `linear_issue`; `github` → PRs, issues, commits; `code`/`git` → commits; `slack` → messages). Resolved references get `RESOLVES_TO` and the `MENTIONS` from every text that contains them. It also links PRs to Linear issues by branch once Linear arrives.

Edits and deletions (A12.4a): on re-linking an edited text, explicit links whose reference is gone get `deleted = true` and `deletedAt`. A deleted text has all its outgoing `MENTIONS` and `CONTAINS_REFERENCE` tombstoned. Nothing is removed.

## 3. Meaning links (A12.3)

For texts that J1 classifies as `decision`, `proposal`, `request`, `bug_report` or `question`:

- Candidates: the top 10 full-text matches over `CodeFunction`, `CodeClass`, `CodeFile` and `Feature` (search terms: words of 3+ letters, identifiers split, stop words removed, joined with OR), plus code one hop from anything the text explicitly mentions. Targets already linked are dropped.
- All candidates of one text are judged in one Jev request (J3 batched).
- Probability ≥ `LINK_KEEP_THRESHOLD` (0.6): `MENTIONS` with method `inferred`, `confidence` = probability, `model`, `quote` = the sentence that shares the most words with the candidate. Features also get `DISCUSSED_IN`.
- Not built: proposing new `Feature` nodes from clusters of texts (the spec marks it optional).

## 4. Decisions (A12.4)

For texts classified `decision` or `proposal` with probability ≥ 0.5. Slack bot messages (`botId`, subtype `bot_message`, or a bot user) are skipped.

- `extract_decision` returns a statement, an exact quote with its span, a scope and a status hint, or nothing.
- One `Decision` per source text (`actron:decision:<uuid5 of the text id>`), so re-running on an edit updates it. A changed statement is appended to `statementHistory`.
- **Approved** only when the text itself settles it (J1 `decision` ≥ 0.7 and the extraction says "decided"; `DECIDED_BY` → author), or a reply by someone else approves it (J2 ≥ 0.85; `APPROVED_IN` → reply, `DECIDED_BY` → replier). Replies are Slack thread replies, review-comment replies, Linear comments on an issue, and PR or issue conversation comments. Otherwise **proposed**. Authority is never inferred from titles.
- `EXTRACTED_FROM` (method `extracted`, quote, `quoteSpan`, model).
- `CONSTRAINS` → every code or feature node the text mentions explicitly (method `extracted`) or through an inferred link at or above the threshold (method `inferred`), with `active = true`.
- `DECISION_IMPLEMENTED_BY` → the source itself when it is a commit or merged PR, and any commit or PR the text names.
- **Supersession**: a newly approved decision is compared (J6b) with earlier approved decisions that constrain a shared target or have the same scope. `replaces` ≥ 0.7 gives `SUPERSEDES {scope}`. If the new decision covers every target of the old one, the old one becomes `superseded` and all its `CONSTRAINS` links get `active = false`. Otherwise only the shared targets' links get `active = false` and `supersededBy`; the old decision stays approved for the rest (A12.4a).
- A deleted source tombstones its `EXTRACTED_FROM`, `APPROVED_IN`, `DISCUSSED_IN` and outgoing links; the decision keeps its status and shows as "source deleted". An edited source that no longer states the decision tombstones `EXTRACTED_FROM`.

## 5. Link checks (A12.5)

Every `inferred` or `extracted` link made in this run (`MENTIONS`, `DISCUSSED_IN`, `CONSTRAINS`, `EXTRACTED_FROM`) is re-judged with J4 (quote, plain claim such as "This message is about the function formatPaste in src/paste.ts").

- < 0.5: delete the link. A failed `EXTRACTED_FROM` also deletes its decision.
- 0.5 to < 0.7: keep, `flag = "possible"`.
- ≥ 0.7: keep.
- The stub answers 0.5, so without keys links are flagged, never deleted.

## 6. Knowledge, ownership and procedures (A12.6, bonus)

- `KNOWS_ABOUT` (Person → function or file): `score = 1 - exp(-(0.4·commits + 0.3·blameShare·10 + 0.2·reviews + 0.1·messages)/5)`, with commits, reviews and messages from the last 365 days. Top 10 people per node with score ≥ 0.2; `signals` holds the counts as JSON. People who drop out of the top 10 lose the link.
- `OWNS`: CODEOWNERS rules (`@login` or email resolved to a `Person`; `@org/team` skipped; basis `codeowners`; also `CODEOWNER_IS`) and blame share ≥ 0.5 (basis `blame`).
- `Procedure` per top-level directory of merged PRs: `testCommand` = most common test command in those PRs' descriptions (else in `.github/workflows/*`), `coChangedPaths` = path pairs changed together in ≥ 30% of the area's merged PRs (at least twice), template `steps`, `LEARNED_FROM_PR` to the 20 most recent PRs, `APPLIES_TO` the matching `CodeComponent`.
- `LEARNED_FROM_TEXT`: Slack messages, PR descriptions, Linear texts and PR templates that state steps. With a model, `extract_procedure`; without one, a heuristic needs at least two numbered or bulleted steps and a test command.

## Quality (A-AC-77)

`tests/eval/test_link_quality.py` on `tests/fixtures/link_labels.yaml` (44 cases: 20 explicit, 24 inferred) and `tests/fixtures/conflict_labels.yaml` (32 cases). Both fixture files are synthetic and were written for this suite.

| Measure | Mode | Precision | Recall |
|---|---|---|---|
| Explicit references (pattern code) | real code, no model | 1.00 (12 of 12) | 1.00 (12 of 12) |
| Inferred links, J3 at 0.6 | stub | none predicted | 0.00 (0 of 14) |
| Conflicts, J6 `restricts` ≥ 0.8 | stub | none predicted | 0.00 (0 of 13) |
| Any conflict, J6 ≥ 0.5 | stub | none predicted | 0.00 (0 of 21) |

The explicit numbers come from fixtures written by the same author as the patterns, so they are optimistic. The stub rows measure the stub, not Jev; they will be re-run when a key exists. Results are written to `.actron/eval/link_quality.json`.

## Tests

| Area | Tests |
|---|---|
| Identity, A-AC-70 | `tests/unit/linking/test_identity.py` |
| Patterns (67 table cases), A-AC-71 | `tests/unit/linking/test_reference_patterns.py` |
| Resolution, pending, `IMPLEMENTED_BY`, tombstones, A-AC-71/72/73/103/104/106 | `tests/unit/linking/test_references_graph.py` |
| Pending against real FalkorDB, A-AC-72 | `tests/integration/test_pending_references.py` |
| Meaning, A-AC-74 | `tests/unit/linking/test_meaning.py` |
| Decisions, supersession, tombstones, A-AC-75/103/106 | `tests/unit/linking/test_decisions.py` |
| Link checks, A-AC-76 | `tests/unit/linking/test_link_checks.py` |
| Knowledge and procedures, A-AC-78/106 | `tests/unit/linking/test_knowledge.py`, `test_procedures.py` |
| Workflow (time-skipping) and runner | `tests/unit/linking/test_linking_workflow.py`, `test_runner.py` |
| Quality, A-AC-77 | `tests/eval/test_link_quality.py` |

Run: `cd backend && ACTRON_TEST_REDIS_DB=4 uv run pytest tests/unit/linking tests/integration/test_pending_references.py tests/eval/test_link_quality.py -q`.
