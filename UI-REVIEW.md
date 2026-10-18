# UI review and fix pass

A review of the Actron frontend as a first-time user sees it, on real Calva data, and the fixes that followed. Brief: `prompts/UI-REVIEW-AND-FIX-PROMPT.md`. Date: 18 Oct 2026. Nothing is committed.

## Summary

- The three things the user reported are fixed: the graph uses a colour per source and a shape per type with a real legend; Home and Inbox show each state as its own coloured group with a count and a plain sentence; body text uses Public Sans and mono capitals are kept for data only.
- Section 4 items are fixed except where the cause is backend content (listed under "Left undone").
- Twelve independent screenshot-only audits on real data found 18, 9, 4, 3, 1, 1, 1, 1, 1, 2, 4 and then 0 material issues. Round 12 (the last) found none and 13 minor ones. Each round used a fresh reviewer, so the count is not strictly falling: a new reviewer notices different details.
- Late change on the user's request: the Connect memory graph went back to the mesh layout (all type nodes in one force graph, a short line from each node down to its name). A fixed column layout was tried for a few rounds to stop label mix-ups, and dropped.
- Tests: see "Checks" at the end.

## How the review was done

- Read BUILD-REPORT, the W7 and real-data entries in BUILD-LOG (including the 17 deferred minors of audit round 7), spec C1, C2 and C11, DESIGN.md and frontend/AGENTS.md.
- Looked at all 18 real-data screenshots before changing anything (kept unchanged in `frontend/tests/screenshots/real-before/`).
- Impeccable: context loaded with its launcher; its detector over `frontend/components` and `frontend/app` returned no findings. Its critique ran as an independent reviewer agent that saw the screenshots and the live app but not the code. Full report: `docs/ui-review/round0-user-review.md`.
- web-design-guidelines: rules fetched and checked by search over the components. Findings: native `<select>` had no explicit dark background (fixed in `globals.css`); loading headlines ended in "." instead of "…" (fixed); `outline-none` appears only on inputs whose wrapper shows focus with `focus-within` (kept). Its "Title Case for buttons" rule conflicts with the product's sentence-case voice (spec C1.6) and was not applied.
- interface-design, better-ui and frontend-design were the checklist for spacing, type and colour in the fixes.
- Work was split by file ownership across four implementation agents (graph; Home, Inbox and core; Request, System and shell; Settings, Connect and landing). The lead owned tokens, global CSS, fonts, tests shared across areas, scripts and the documents.
- After the fixes, a fresh reviewer that saw only the new screenshots audited every screen against spec C11's list of tells, once per round, until a round found no material issues.

## What a first-time user saw (before)

| Screen | What am I looking at | What do colours mean | What next | What confused me |
|---|---|---|---|---|
| Home | a queue of requests under a poster headline | yellow pill = needs input, red = needs attention; six grey dashes unexplained | not obvious; every row has a quiet "Open" | three rows with the same title; "Now Needs your input." repeats the chip; dashes have no label |
| Request | timeline, graph, tabs | red = failed step; yellow = primary action and path; the graph is all white | "Edit ticket" is primary, but the cause is a missing bot identity | "stub", "fixed pipeline", "(ExternalError).."; build title repeats the headline in red; system strip is cryptic |
| Graph | a search box and an empty canvas | nothing is coloured | type a search | the empty box looks broken; results are raw code chunks; node panel shows hashes and `deleted false` |
| Connect | memory percentage, sources, memory graph | grey hairball | unclear | big gap under the headline; "Repository, Repository"; "Setup 1 of 4" next to PARTIAL |
| Inbox | five rows that all say "Actron needs your input" | same yellow icon for different asks | rows look like labels, not actions | question cut off; stale approval listed |
| Settings | two rows called GitHub, a table of STUB pills | 16 orange pills | unclear which GitHub is which | STUB twice per row; "Reset cursor" |
| System | service chips with near-invisible dotted lines | none | none | idle state is not stated |
| Landing | strongest screen | node colours are near-greys there too | — | blank space until sections scroll in |

## Findings and status

Severity: material = a user or judge misreads the product or is blocked; minor = visible polish. Source: U = user report (prompt section 3), P = prompt section 4, R = reviewer (round 0 or an audit round), W = web guidelines.

| # | Screen | Finding | Sev | Src | Status |
|---|---|---|---|---|---|
| 1 | Graph (all) | Nodes and links all read as white; sources cannot be told apart | material | U, R | fixed: new palette, link tones |
| 2 | Graph (all) | No visible shape per type; request not the anchor; white cluster discs with unexplained counts | material | U, R | fixed: shapes per type, request anchor, clusters in source colour, counts explained |
| 3 | Graph | Overlapping labels on the request canvas and Connect memory graph | material | U, R | fixed: collision-aware placement, path and quote cards as obstacles |
| 4 | Graph explorer | Empty canvas before a search | material | U, R | fixed: the 24 most connected files, clickable |
| 5 | Graph explorer | Raw properties in the node panel; code chunks and duplicate names in results | material | R | fixed: plain fields first, raw fold, grouped results with paths |
| 6 | Graph (all) | Legend listed groups only, CORE and CODE both white | material | U, R | fixed: Source, Links and Type rows; "Core (Actron's records)" |
| 7 | Graph (all) | Evidence path only visible after "Show path" | material | R1 | fixed: the first evidence path is drawn by default |
| 8 | Home | Groups looked the same | material | U | fixed: state-coloured header, count, one-line meaning |
| 9 | Home | "Now Needs your input." repeated the chip; mini pipeline unlabelled | material | U, R | fixed: the ask itself (question, failure reason, "Ticket v1 waits for approval"); "Step 2 of 6 · Clarify" |
| 10 | Home, Inbox | Identical titles cannot be told apart | material | P, R | fixed: id, requester and age on each row; the differing fact |
| 11 | Home, Inbox | Different asks look the same | material | U | fixed: glyph and action word per ask (Answer, Approve ticket, See why, Review PR) |
| 12 | Home, Inbox, rail | Counts disagreed (3 vs 5 vs 7) | material | R | fixed: Home and rail count requests that wait on you; Inbox counts notices on requests |
| 13 | All | Mono uppercase on labels, tabs, chips, actions | material | U, R | fixed: UI font, sentence case; mono for data only |
| 14 | All | Small body text thin and uneven | material | U, R | fixed: Public Sans, `--text-2` raised, sentences ≥ 14 px |
| 15 | All | Internal words: "stub", "fixed pipeline", "(ExternalError)", `missing_identity`, "Reset cursor", "Actron UI" | material | P, R | fixed: plain words throughout |
| 16 | Request | Failed build's primary action did not fix the cause | material | R | fixed: "How to set the bot identity" → Settings section; Retry secondary |
| 17 | Request | Build tab repeated the headline in red serif; empty stats for a build that never started; emoji | material | P, R | fixed: compact status, error line, next step; emoji removed |
| 18 | Request | System strip hard to parse | minor | P | fixed: "Last step: Actron · Sent an inbox notice: …" |
| 19 | Request | The request itself was a small grey quote under the error headline | material | R2 | fixed: request title in lead size with id, requester and age |
| 20 | Request | Template ticket text shown as a real ticket | material | R2 | partly: notice "Written from a template…", duplicates merged; the text itself is backend |
| 21 | Inbox | Key hints in mono caps; actions looked like labels; generic row titles; stale items looked live | material | P, R | fixed: per-request blocks, ask first, history folded in past tense, one quiet Mark read |
| 22 | Inbox, Home | Same headline and groups on both screens | material | R2 | fixed: Inbox is the notice feed ("7 notices on 3 requests.") |
| 23 | Settings | Two rows both "GitHub"; STUB twice per row; stub headline | material | P, R | fixed: "Code (git)" and "GitHub API"; one summary line; plain headline |
| 24 | Connect | Gap under headline; "Repository, Repository"; setup count next to PARTIAL; 50% vs 100% | material | P, R | fixed |
| 25 | Connect | Raw "public rate limit" reason with no next step | material | R2 | fixed: sentence plus "Add a GitHub token" |
| 26 | Connect | Memory graph without a key; unlabelled node; counts clipped by shapes; labels paired with the wrong node | material | R1–R7 | fixed: shape families key, every node labelled, counts after labels, a short line from each node to its name (mesh kept at the user's request) |
| 27 | Home, Connect | Checklist: "connect slack." lower case; strikethrough; out-of-order steps; on two screens | minor | P, R | fixed: ticks, done first, compact line once a repository is connected |
| 28 | System | Links nearly invisible; idle state not explicit; actors unexplained; not-connected parts looked wired | material | P, R | fixed: visible link styles with legend, idle line, roles, dimmed not-connected actors, recent activity log |
| 29 | System | Caption crossed the card border at 1440 | material | R3 | fixed |
| 30 | Footer | "CODE · SYNCING" while idle; "JEV STUB"; "2 OF 2 SOURCES"; "14M AGO" | minor | P, R | verified real state (re-syncs every 15 min); "JEV · NO KEY", "2 SOURCES CONNECTED", "14 MIN AGO" |
| 31 | Request | Branch name wrapped mid-token | material | R3 | fixed: own line, middle truncation, copy |
| 32 | Landing | Product shots used the old design; cut panels; quote cards over labels | material | R1–R3 | fixed: re-captured from a fresh fixture build, whole panels, card placement |
| 33 | App screens | 64-px headline pushed the work below the fold | minor | R | fixed: 48 px on app screens |
| 34 | Rail | Icon-only navigation | minor | R | fixed: visible labels |
| 35 | Home | Kind chips ambiguous; disabled "Ask Actron" nearly invisible | minor | R | fixed: Auto toggle; legible disabled primary |
| 36 | All | Native selects without a dark background; loading text without "…" | minor | W | fixed |
| 37 | Round-7 deferred minors | label placement, quote card over path end, Connect density, chip vs setup count, PR header wrap, caption truncation, journey fixtures, diff clipping, inbox Read style, pipeline meter label, accent outline chips, repeated statements, sparse explorer, tab set change, Settings "stubs", local webhook URL, glyph grid | minor | P | fixed except: PR-ready header wrap (no live PR-ready request to check), landing journey still uses fixture data (labelled once), empty cells on the dev glyph grid (dev page) |

## Before and after screenshots

Before (unchanged copies of the original real-data captures): `frontend/tests/screenshots/real-before/`. After: `frontend/tests/screenshots/real/` (same names, plus `landing-*`, `landing-full-*` and `notfound-*`, captured by `scripts/capture-real.ts`).

| Screen | Before | After |
|---|---|---|
| Home | `real-before/home-1440.png`, `-1920` | `real/home-1440.png`, `-1920` |
| Inbox | `real-before/inbox-1440.png`, `-1920` | `real/inbox-1440.png`, `-1920` |
| Request, evidence | `real-before/request-1-evidence-1440.png`, `-1920` | `real/request-1-evidence-1440.png`, `-1920` |
| Request, ticket | `real-before/request-1-ticket-1440.png`, `-1920` | `real/request-1-ticket-1440.png`, `-1920` |
| Request, build | `real-before/request-1-build-1440.png`, `-1920` | `real/request-1-build-1440.png`, `-1920` |
| Graph | `real-before/graph-1440.png`, `-1920` | `real/graph-1440.png`, `-1920` |
| Connect | `real-before/connect-1440.png`, `-1920` | `real/connect-1440.png`, `-1920` |
| Settings | `real-before/settings-1440.png`, `-1920` | `real/settings-1440.png`, `-1920` |
| System | `real-before/system-1440.png`, `-1920` | `real/system-1440.png`, `-1920` |
| Landing, 404 | not captured before | `real/landing-*.png`, `real/notfound-*.png` |

The fixture screenshots in `frontend/tests/screenshots/` and the landing journey images in `frontend/public/landing/` were re-captured from a fresh fixture build.

## Font comparison and choice

Home, Inbox and the Request ticket tab were rendered in the live app with each candidate injected over `--font-ui` (side-by-side sheets: `docs/ui-review/sheet-home.png`, `sheet-inbox.png`, `sheet-request.png`).

| Face | At 13–16 px on #0A0A0A |
|---|---|
| IBM Plex Sans (before) | thin at 400, uneven letter widths; words run together ("Notationin the") |
| IBM Plex Sans, tuned smoothing | no visible difference |
| Source Sans 3 | even but small and narrow; secondary lines shrink |
| Hanken Grotesk | even, airy; slightly wide for dense rows |
| Mona Sans | crisp, but word spacing as tight as Plex |
| **Public Sans (chosen)** | even letter and word spacing, steady weight at 400/500, reads well grey on black; not a default "AI site" face |

Headings stay Newsreader; data stays JetBrains Mono. The fonts load through `next/font` with `display: swap` and size-adjusted fallbacks (C-AC-3 tests pass). One known quirk: in "docFromTextNotation" the "m" and "T" sit very close at 1x in Public Sans; at 3x they do not touch, so kerning was left on.

## Palette and contrast

Node colours (one muted hue per source; colour = source, shape = type). Contrast against the canvas `#0A0A0A` and against `--ink-3` `#1A1A1A`; every pair of node colours differs by at least 0.11 in OKLab, and none equals the accent or a state colour.

| Token | Value | On ink-0 | On ink-3 | Meaning |
|---|---|---|---|---|
| `--node-code` | `#97A8C0` steel blue-grey | 8.2:1 | 7.2:1 | code and git |
| `--node-github` | `#C8B08E` warm sand | 9.5:1 | 8.3:1 | GitHub API |
| `--node-slack` | `#C77DDB` orchid | 7.0:1 | 6.1:1 | Slack |
| `--node-linear` | `#6F8DF5` cornflower blue | 6.4:1 | 5.6:1 | Linear |
| `--node-core` | `#E58FA8` rose | 8.3:1 | 7.3:1 | Actron's records: request, investigation, decision, person |
| `--graph-link` | `#6E6E6E` | 3.9:1 | 3.4:1 | links at rest |
| `--graph-link-focus` | `#C4C4C4` | 11.4:1 | 10.0:1 | links touching the focused or selected node |
| `--text-2` | `#B4B4B4` | 9.5:1 | 8.4:1 | secondary text |

The evidence path stays `--accent` `#E4F24C`, drawn last and thickest. Slack and Linear were first `#C690DE` and `#8C95F2`; audit round 1 could not tell them apart (OKLab distance 0.089), so they moved to the values above (0.134).

State colours are unchanged. States now look the same on every screen: the chip (UI font, sentence case) and the group header use the same tone map from `lib/states.json`.

## Token and states.json changes

`frontend/styles/tokens.css`:
- `--node-code` `#C9CDD3` → `#97A8C0`; `--node-github` `#9BA6B4` → `#C8B08E`; `--node-slack` `#B7A6D9` → `#C77DDB`; `--node-linear` `#8FB3E8` → `#6F8DF5`; `--node-core` `#EDEDED` → `#E58FA8`.
- New `--graph-link` `#6E6E6E` and `--graph-link-focus` `#C4C4C4` (Tailwind `graph.link`, `graph.link-focus`).
- `--text-2` `#A8A8A8` → `#B4B4B4`.
- `--font-ui` → Public Sans (`--font-public-sans` from `next/font`).
- `--tracking-eyebrow` 0.08em → 0.04em (mono data labels only).

`frontend/app/globals.css`: `.eyebrow` is now the UI face, 13/18, weight 500, sentence case; new `.data-label` for mono uppercase data; explicit dark background for native `select`.

`frontend/lib/states.json`: not changed. The UI shows the same state names in sentence case through `sentenceCase()` in `lib/states.ts`. The Slack bot reads `backend/actron/flow/states.json` first, so names and colours stay equal to Slack; the backend Slack tests did not need to run because neither file changed.

Other shared changes: disabled primary buttons keep a faint accent border and readable text (`components/ui/button-class.ts`); `scripts/make-brand-assets.ts` reads node, link, accent and ink colours from tokens.css (new `--hero-only` flag) and `public/landing/hero-fallback.png` was re-rendered; `scripts/capture-screens.ts` crops whole panels; `scripts/capture-real.ts` also captures the landing page and a logged-in 404.

## Decisions made without asking

- UI face: Public Sans replaces IBM Plex Sans (comparison above).
- Mono capitals only for data (ids, hashes, counts, code, timestamps, durations, cost, the footer status). This overrules the audit rounds' "live grammar" decision, as the user asked.
- `lib/states.json` unchanged; sentence case is derived in the UI (see above).
- Core types get their own colour (rose) rather than a colour per core type; types are told apart by shape.
- Home splits "needs you" into "Waiting for a decision" (accent: answer, approve, review) and "Stopped" (red: needs attention); Inbox uses the same group names and colours but is the notice feed.
- Home counts requests that wait on the signed-in user; the rail badge counts the same thing; Inbox counts notices.
- The request canvas draws the first evidence path by default; "Show path" on another item replaces it.
- The request page keeps the situation headline (spec voice) and shows the request title right under it.
- App screen headlines are 48 px; 64 px only when a screen asks for it.
- The rail shows a visible label under each icon; the visible label is the accessible name (axe `label-content-name-mismatch`).
- For setup stops (`missing_identity`, `missing_fork`, `missing_branch`) the yellow action leads to the fix and Retry is secondary. The button says "How to set the bot identity", not "Set", because builds read the identity from `.env` (see Left undone).
- Inbox history items are folded and written in past tense; "approved"/"answered" are inferred from the request's current state.
- The ticket shows "Written from a template because no writing model is set. Edit it before you approve." when it was written without a model.
- The Settings models table drops its "Runs on" column while every job uses the same fallback; the line above the table says so.
- The landing hero gets a colour key; the journey section says once that the shots come from the development fixtures.
- Landing hero (user request after the review): the headline is one scale step smaller on wide screens (64 px, was 80), the text and graph columns split the width evenly and the graph is larger (camera closer, bigger box). The 3D graph now breathes, orbits about two and a half times faster and plays a 10-second loop (query rings, the evidence path drawing itself, a pulse at its end) with a caption chip carrying the FalkorDB mark and naming each stage. Reduced motion, software WebGL and phones still get the static image, with the same chip fixed on "Evidence path found". Labels "Request" and "Function" are sprites, not drei `Html` (the first `Html` label never rendered).
- The landing hero always shows the ontology concept graph (all five sources, coloured), not a sample of the signed-in workspace. A real sample is almost all code (1,007 of 1,008 nodes in this workspace) under a key that lists five sources. This replaces spec C6's "sample from `/api/graph/sample`"; the hero no longer calls the API, so signed-out visitors no longer get a 401 in the console. The headline became "Your AI doesn’t know what your team already decided. Actron does." and the hero fits the first screen (graph sized from the window height, text centred against it).
- One shared dev server at a time was used by all agents (two `next dev` processes cannot share the build directory).

## Left undone (with reasons)

- **Ticket and question text without a model** (circular acceptance criterion, "Existing tests", "0 earlier decisions relate to it" next to a possible conflict, counts in question text that differ from the Evidence tab because they come from separate investigations at different times): written by backend templates (`backend/`), outside a frontend pass. The UI now says the ticket came from a template and merges duplicates.
- **Bot identity from Settings**: builds read only `ACTRON_BOT_NAME` and `ACTRON_BOT_EMAIL` from the environment (`backend/actron/flow/build.py`), so saving the Settings fields does not unblock a build. The UI says so and points to `.env`. A backend change is needed for the Settings fields to take effect.
- **Sync counts during a run**: the backend returns empty counts for a running sync; the Connect card keeps the last finished counts on the client. Returning the last finished run's counts from the API would fix it at the source.
- **PR-ready header wrap** (round-7 minor): no real request is in the PR-ready state, so it could not be checked on real data.
- **Landing journey shots** still show fixture data (a live workspace with Slack, Linear and a model key is needed); the page says so once.
- **"m"/"T" closeness** in "docFromTextNotation" at 1x in Public Sans (font metrics; kerning left on).
- **Minor items from the last rounds, not changed** (none material; all are polish):
  - Request evidence graph: some labels are cut to a few words and about four small test nodes have no label at 1440. Names show on hover and in the list view (the legend says "Hover for names"). More room needs a taller panel.
  - Request timeline: code in tool calls can break inside a long identifier at 1440 (`docFromTextNota/tion`); clock times have no date next to "9 h ago".
  - Request page: the step bar and the right-hand tabs both name stages; "Show path" in the landing step 02 shot is yellow because the fixture is captured with a trace running.
  - Home and Inbox: the state pill repeats the section heading in other words ("Needs your input" under "Waiting for a decision"); the Inbox badge counts requests while the headline counts notices (both say so in their tooltips); row actions sit far right at 1920.
  - System: "Available" (dashed) and "Not connected" (dotted) links are close in contrast on purpose, so working parts stand out; Actron–GitHub can run behind the FalkorDB box.
  - Settings: the Model jobs table has two columns while every job uses the fallback (it gains a model column when a key is set).
  - Landing: Slack/Core and Code/Linear hues are close at hero dot size (shapes tell them apart in the app); "96 node types" (ontology) next to the app's "23" (types present in this workspace); the "How it works" shots repeat one layout.
  - Footer: "JEV · NO KEY" is not explained in the app (hover text only).
  - Ticket and question text from templates (backend, see above).

## Checks

`./scripts/test_all.sh` passed once on the final code (18 Oct 2026, 10:28–10:39 UTC, 11 min 17 s; log `.actron/test-all/20261018T102814Z/`):

| Stage | Result |
|---|---|
| Backend ruff, mypy --strict | pass |
| Backend unit / property | 750 / 23 passed |
| Backend integration / contract | 397 / 83 passed |
| Backend workflows / API / eval | 65 / 82 / 19 passed |
| Backend line coverage | 88% |
| Frontend typecheck, lint | clean |
| Frontend unit | 888 passed, 80.2% line coverage |
| Frontend e2e on the fixture build | 128 passed |
| Frontend e2e on the full stack (fakes) | 40 passed |
| Lighthouse desktop | performance 99–100, accessibility 100 on `/`, `/app`, `/app/connect` and a real request |
| Lighthouse mobile `/` | performance 98 (target 85), accessibility 100 |
| Spec coverage | A 106/106, B 91/91, C 57/57 |

Tests and scripts changed on purpose in this pass:
- Frontend unit: tokens (new palette, `--text-2`), contrast (link tones), fonts, copy, screen and graph tests; new `hero-timeline.test.ts`, `og.test.ts`, `home-ask.test.ts`.
- Frontend e2e: screen eyebrows and state names in sentence case, the five-second check, system-map toggle text, the setup-guide check, the full-stack explorer search (results are now grouped by type); glyph snapshots refreshed (`--update-snapshots`).
- Backend tests: `backend/tests/conftest.py` now makes the suite independent of the developer's local `.env`. It loads settings from a copy of `.env` without credentials, bot identity and `ACTRON_PUBLIC_URL`, pins `ACTRON_DAILY_MODEL_BUDGET_USD` at 20 and sets `LITELLM_MODE=PRODUCTION` (LiteLLM otherwise loads the real `.env` into the process). Reason: real keys, a $3 daily budget and a dev-tunnel URL added to `.env` during the pass broke 20 backend tests that assume a key-free setup. No product code changed. Live checks against real providers stay in `scripts/live_smoke.sh`.
- Scripts: `capture-real.ts` (landing page, logged-in 404), `capture-screens.ts` (whole-panel crops), `make-brand-assets.ts` (reads tokens, `--hero-only`).

Request page layout (found by the user after the pass, fixed):
- The three columns had a fixed height guessed from the header. Header lines added in this pass (request title, who started it, costs) made the page run 30 to 350 px past the screen, and a first attempt at a fixed frame height let tall headers spill past it, leaving the sticky status bar in the middle of the page.
- Now the frame is at least the visible height and the columns take what the header leaves (minimum 400 px); if the header plus that does not fit, the page scrolls and the status bar stays at the bottom. Long answers under the headline are cut to five lines with "Show full answer"; the meta and cost lines share a row.
- `tests/e2e/request-fit.spec.ts` (14 cases): at 1440×900 the page does not scroll and the columns end above the status bar; at 1440×600 the status bar stays at the bottom, below the columns.
