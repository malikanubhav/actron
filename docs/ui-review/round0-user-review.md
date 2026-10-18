# Actron: first-time-user design review (Reviewer A)

Date: 2026-10-18. Viewport: 1440x900 (1920 checked briefly). Dark only.
Sources: the 18 real-data screenshots in `frontend/tests/screenshots/real/`, plus extra live screenshots in
`/tmp/claude-1000/-home-vikram/d5621bc0-3199-4725-b16c-36a21999016d/scratchpad/review/` (landing page by scroll position, sign-in, Home full page and hover, Inbox as "Dev user", graph explorer with a search and a selected node, request page expanded graph, Show path, List view, Show map, System lower half, Connect and Settings full page, nav tooltip). No data was changed.

Severity: **material** = a judge or first-time user will misread the product, lose trust, or be blocked. **minor** = polish, still visible.

---

## 0. Cross-screen findings (read first)

These show up on every screen and are the main reasons the app can read as "a prototype" instead of a product.

1. **Internal words are on screen everywhere** (material). The footer on every page says `CODE · SYNCING · GITHUB · PARTIAL · 2 OF 2 SOURCES · JEV STUB · STREAM · LIVE · DEV`. The Settings hero is "16 of 16 model jobs run as stubs." The request timeline says "The stub judged 20 candidates" and "Investigation started with the fixed pipeline". Evidence says `INVESTIGATION · PIPELINE · STUB 0 TOKENS · $0.00`. Inbox shows `missing_identity`. Timeline shows `(ExternalError)..`. Settings has "Reset cursor", job names like `classify_message`, kind "json", "Slack user ids". A judge reads "stub" as "this is fake". A user does not know what Jev, Pi, stub, pipeline, cursor or stream mean.
2. **Monospace uppercase is used for almost every label** (material for readability). Eyebrows, tabs, status pills, stepper, buttons ("MARK READ", "OPENS QUESTIONS", "SHOW MAP", "RAW LOG"), table headers, metadata lines, the footer. At 11–12px with wide tracking and low-contrast grey this is slow to read, and because everything uses it nothing stands out. Tabs (EVIDENCE/QUESTIONS/TICKET) look the same as labels (TIMELINE, GRAPH) and as pills. It is the single strongest "AI-generated dev-tool" tell in the app.
3. **Body sans has tight tracking at small sizes** (minor-to-material). Small grey sans text looks cramped and letters collide: "Make docFromTextNotation in the test utilities" in Inbox rows, "Narrow judgments with probabilities:is this..." on the landing page, "Pick a result to see it withits neighbours" on Graph. Grey-on-near-black at 13px plus negative tracking makes secondary text hard to read.
4. **Three type families per screen, many sizes**. Serif display (very large), serif section titles, sans body, mono labels, mono code. Hero headlines are 64–80px on every app page, including Settings and System, which pushes the working content below the fold. A tool page does not need a poster headline.
5. **Hero headlines are sentences built from data, and some are wrong or contradictory**:
   - Home "3 requests need you." vs Inbox "Nothing needs you." for the same user (Dev user). The real-data Inbox says "5 things need you" while Home says 3.
   - Connect: "Your memory is 50% built." (real screenshot) and "Your memory is 100% built. GitHub is partly read." (live) in the same session; both next to a "PARTIAL" pill.
   - Graph: "23 node types" in the app vs "96 node types" on the landing hero.
   - Ticket: "0 earlier decisions relate to it" while the Evidence tab shows "Possible conflict: An earlier decision may conflict with this request."
   - Evidence "Tests covering 200" vs graph bubble "194 tests".
6. **Graph colour system has no usable contrast**. The source palette is five near-greys: code `#C9CDD3`, github `#9BA6B4`, slack `#B7A6D9`, linear `#8FB3E8`, core `#A8A8A8` (`components/landing/og.tsx`). On screen, CORE and CODE dots in the legend are both white; GitHub is a slightly darker grey. The only real colour on the canvas is the yellow evidence path. A first-time user cannot tell sources apart.
7. **Emoji**: the Build tab header has a whale emoji (`PI · IN DOCKER 🐳`), also on the landing page Build step. Reads as AI-generated.
8. **Unlabelled icon nav**. Six icons, no labels; a tooltip ("Graph G G") appears only on hover. The Connect icon (a chain link) and System icon (a diamond of dots) do not suggest their pages.

---

## 1. Home (`/app`)

**What am I looking at?** A big "3 requests need you." headline, a request composer, a five-step getting-started strip, then "Waiting on you", "In progress" and "Finished recently" lists. It is clear this is the main queue.

**What do the colours mean?** Yellow pill = needs your input. Red pill = needs attention (something failed). Green pill = done. The six dashes at the right of a row look like a progress bar: one yellow dash at position 2 for "needs input", a red dash at position 5 for "needs attention". This is not labelled; I had to guess they are the six pipeline stages. In the getting-started strip yellow border = next step, strikethrough = done.

**What should I do next?** Not obvious. The yellow "next step" card says "Connect Slack", the composer invites me to type, and the queue has three rows each with a quiet "Open" text link. There is no primary action for the queue.

**What confused me.**
- All three rows have the same title ("Make docFromTextNotation in the test utilities accept Windows line e…"). The only difference is a cryptic ID (91BWP7, AW4YHM, 6SBK2H) that is the tail of a ULID. I cannot tell them apart.
- "Now Needs your input." repeats the pill, with odd capitalisation. The column adds nothing.
- The real-data screenshot shows "Next: connect slack." (lower-case brand). Live build shows "Connect Slack." — fixed, but check the Connect page too.
- Getting-started step 05 "Ask your first request" is done while 03 and 04 are not; numbered steps done out of order look broken. Done steps are struck through and very low contrast.
- Feature / Bug / Question chips look like buttons but the helper text says "Actron suggests the kind". Are they selectable or not?
- "Ask Actron" is disabled at very low contrast; it looks like a dead button rather than "type first".
- "Finished recently" has a lone right-aligned "Inbox" link with no context.
- In-progress empty state "Nothing is running." is fine.

**Heuristics (0 = no problem, 4 = severe).**
| Heuristic | Score | Note |
|---|---|---|
| Visibility of system status | 2 | Pills good; stage dashes unlabelled; count disagrees with Inbox |
| Match with real world | 2 | IDs, "Now Needs your input." |
| User control | 1 | Fine |
| Consistency | 2 | Mono caps everywhere; pills vs chips vs buttons look alike |
| Error prevention | 1 | |
| Recognition over recall | 3 | Identical titles, must remember IDs |
| Flexibility | 1 | Keyboard shortcut on composer |
| Aesthetic / minimalist | 2 | Poster headline + onboarding pushes queue below fold at 1440 |
| Error recovery | 1 | |
| Help | 2 | No legend for dashes |

**Cognitive load:** medium. Three sections compete above the fold; at 1440 only 2.5 queue rows are visible.

**Top issues.**
1. Requests with the same title are indistinguishable; the ID is not a human handle — material. Show the failure reason or current question as the row's second line (e.g. "Stopped: bot identity for commits is not set").
2. "3 requests need you" contradicts Inbox ("Nothing needs you" / "5 things") — material.
3. Stage dashes have no labels or tooltip — minor.
4. Queue sits below a poster headline, composer and onboarding; the thing that "needs you" is not visible on first load — material.
5. Status column text ("Now Needs attention.") duplicates the pill — minor.

---

## 2. Request page (`/app/requests/:id`) — Evidence, Ticket, Build tabs

**What am I looking at?** A three-column workspace: Timeline (left), "Graph · the agent's path" (centre), tabbed panel Evidence / Questions / Ticket / Build / PR (right). Above it a six-step stepper (Investigate → Review) and a "System" bar.

For the failed request the page title is the failure reason, "The bot identity for commits is not set.", and the actual request is a small grey quote under it. For the needs-input request the title is "One question before the ticket." This "title = next action" is a good idea; the cost is that the request's own name is demoted to 13px grey.

**What do the colours mean?** Red = the failed stage (stepper "05 BUILD", pill, Build headline in red serif). Yellow = primary action (Edit ticket, Send answer), the current stage when it needs input, the selected answer, the evidence path. Amber/orange border = possible conflict. Green check = completed stage. The graph is all grey/white.

**What should I do next?** Clear on the needs-input request: the Questions tab is open, the answer is preselected, "Send answer" is yellow. On the failed request it is less clear: "Read the reason, then edit the ticket or retry." But the reason (bot identity not set) is a settings problem, not a ticket problem. "Edit ticket" is the yellow primary action, yet editing the ticket will not fix a missing bot email. There is no link to Settings > Bot name/email for commits, which is empty.

**Evidence tab.** "EVIDENCE 232" is a big number with no meaning to me. Possible-conflict card does not name the decision or link to it. "Callers 23 / Tests covering 200" is clear. "top 1% most depended-on" is clear and useful. `INVESTIGATION · PIPELINE · STUB 0 TOKENS · $0.00` is internal. Impact cards repeat "HIGH CONFIDENCE" on each item, so the badge carries no information. "Show path" works and turns into a yellow "Tracing path" state — good.

**Ticket tab.** Header "REVISION V1 · SHA-256 4DAC…4D96" — the hash is shown twice and is noise for most users. "LINEAR NOT CONNECTED" in the metadata line reads like an error. The acceptance criterion is a tautology ("Given the current code, when the change is made, then make docFromTextNotation … accept Windows line endings") which makes the ticket writer look weak. "0 earlier decisions relate to it" contradicts the Evidence conflict.

**Build tab.** `PI · IN DOCKER 🐳` emoji; the branch name `actron/req_01M55NKKDWY7STS9PKW96SBK2H-r1 · from…` is truncated; the red serif headline repeats the page title; "TOOK 543 MS"; Tests passed "—", failed "—", Repair attempts "0" give a full stats grid for a build that never started. "No steps reported yet." and "No test results yet." read as "still loading", but the build is finished/failed. RAW LOG is collapsed; the actual error text is not on screen.

**Timeline.** Readable sentences ("Vikram started this request in Actron.") mixed with tool cards in mono (`search(limit 20, "Make doc…`) and internal lines ("The stub judged 20 candidates", "Memory could not be checked: Could not reach the repository (ExternalError).."). Double period. The diamond icon next to tool cards is unexplained.

**System bar.** `SYSTEM ACTRON UI · Notified the person who must act` in mono bold. Takes a full row on every request; "Show map" reveals a strip of service chips (SLACK, ACTRON UI, ACTRON, FALKORDB, JEV, LLM, PI…) that means nothing to an engineer reviewing a request.

**Graph (centre).** See section 3 for detail. On the request page: the request is a tiny white square on the left; nodes are uniform grey dots; dashed and solid lines are thin and low contrast; labels truncate ("Make docFromTextNotation in…", "formatter trimming > format…") and overlap ("21 CodeFunction" sits on a line). Grey count bubbles ("194", "21") are unexplained until you read "194 tests". The legend shows CORE and CODE with identical white dots. Expanded mode is a hairball: ~200 nodes fanned into a dense block in the top-left, edges overlap into a solid mass. "List view" is clearer than the canvas (grouped "CODEFUNCTION · 228" list), which says the canvas is not doing its job.

**Heuristics.**
| Heuristic | Score | Note |
|---|---|---|
| Visibility of system status | 1 | Stepper and pill are clear |
| Match with real world | 3 | Stub, pipeline, Pi, Docker emoji, SHA, ExternalError |
| User control | 2 | Cancel is a plain text link next to destructive context, OK; Retry next to Edit ticket without saying what Retry does |
| Consistency | 2 | Tabs, labels and pills share one style |
| Error prevention | 3 | Primary action on failure points to the wrong fix |
| Recognition over recall | 2 | Original request demoted |
| Flexibility | 1 | Aggregated/Expanded, list view, zoom |
| Aesthetic / minimalist | 3 | Three dense columns + system bar + stepper + hero |
| Error recovery | 3 | Error reason shown, fix not linked, raw log hidden |
| Help | 2 | No legend for count bubbles or diamond icons |

**Cognitive load:** high. Three equal-weight panels, each with its own header pattern; the eye has no first place to land below the title.

**Top issues.**
1. Failure recovery points to the wrong fix: "Edit ticket" is primary, but the cause is an empty bot email in Settings; no link — material.
2. Graph canvas is not readable: uniform grey nodes, identical legend colours, truncated/overlapping labels, expanded hairball — material.
3. Internal words in timeline, evidence meta, build header, ticket meta — material.
4. Evidence and Ticket contradict each other on earlier decisions; 200 vs 194 tests — material (trust).
5. Build tab shows an empty stats grid and "No steps reported yet" for a failed build, plus emoji — minor.

---

## 3. Graph explorer (`/app/graph`)

**What am I looking at?** Hero "23 node types, 19,954 nodes, 76,757 links." Then a search box with Source filter chips (CODE, GITHUB, SLACK, LINEAR, CORE), a large empty canvas ("Search to start."), and a right column "Select a node to see its properties, sources and links."

**What do the colours mean?** Nothing is coloured. After search, results show a label and a type in camel case (`CodeChunk`, `CodeFunction`, `GitCommit`). After selection the canvas shows one white ring node with grey neighbours, solid and dashed lines (explicit vs inferred, from the legend). Source cannot be read from colour.

**What should I do next?** Type. That is clear. After that it is weaker: results are dominated by raw code chunks ("/** Cursor positions indicated in textAndSele…", "}); describe('textAndSelections - multiple cur…") which look like garbage to a newcomer. The same function name appears twice with no way to tell the two apart.

**What confused me.**
- The empty canvas takes 60% of the page with only a tiny icon and two lines. An example query or a default view (e.g. the latest request's path) would show the product immediately.
- Clicking a result in my first run scrolled the page so the canvas went above the viewport and the right column showed the bottom of a property dump.
- The detail panel is a raw property table: `ingestedAt 2026-10-17T19:10:30.089Z`, `contentHash c526bfe6…`, `deleted false`, `isTest false`, `decorators []`, and the whole function body wrapped in a narrow column. The node title breaks mid-word ("textNotationFromDocAndSelecti / ons"). "WHERE IT CAME FROM: Derived inside Actron; no external source." for a code function is surprising.
- Outgoing links show `STRUCTURAL 1.00` per row: the score is meaningless when every structural link is 1.00. Group label `FUNCTION_DEFINED_IN` is a raw relation name.
- "Ask the graph" buttons (Callers, Who knows this, Decisions on this, Shortest path to here) are the best idea on the page and are placed below the title in a small row; "Shortest path to here" is disabled with no reason.
- Canvas labels are dim grey and small, some overlap a node ("src/extension-test/e2e/suit…" crosses a square node).

**Heuristics.**
| Heuristic | Score | Note |
|---|---|---|
| Visibility of system status | 1 | |
| Match with real world | 3 | Raw types, raw relation names, raw property keys |
| User control | 1 | |
| Consistency | 2 | |
| Error prevention | 1 | |
| Recognition over recall | 2 | Duplicate results, no preview |
| Flexibility | 2 | Filters exist; no saved views |
| Aesthetic / minimalist | 3 | Hero + empty canvas; property dump |
| Error recovery | 1 | |
| Help | 2 | One line of help |

**Cognitive load:** low before search, high after selection.

**Top issues.**
1. No visible colour coding by source; legend dots identical; the "every link shows where it came from" promise is not visible on the canvas — material.
2. Empty first state wastes the page; no example or default subgraph — material for a demo.
3. Node detail is a raw database dump (hashes, booleans, ISO timestamps, wrapped code) — material.
4. Search results dominated by code chunks and duplicate names without disambiguation (file path) — minor.
5. Hero stats headline is vanity text and pushes the tool down — minor.

---

## 4. Connect (`/app/connect`, "Memory")

**What am I looking at?** Hero "Your memory is 50% built." (or "100% built. GitHub is partly read."). Getting-started strip (same as Home). Left: one card per source (GitHub, Slack, Linear, Slack export) with stats and setup forms. Right: "Memory graph — What Actron has read so far" (node-type bubbles) with per-source counts and a "Linking — How sources join up" grid.

**What do the colours mean?** Orange "PARTIAL" pill + amber callout "GitHub is partly read. public rate limit". Grey "NOT CONNECTED" pills. Red "Disconnect" text. The bubble graph is grey/white; triangles and rings are different node shapes but there is no shape legend.

**What should I do next?** The strip says connect Slack. The Slack card below is a long form (manifest, bot token, app token, history days, check connection). OK once found, but at 1440 it is below the fold.

**What confused me.**
- "Memory" in the eyebrow, "Connect" in the nav; two names for one page.
- 50% / 100% built changes, and "100% built" sits next to "PARTIAL" and "public rate limit". What is the percentage of?
- Subtitle (real data): "Still filling: Repository, Repository." — same word twice, two repos with the same label.
- "public rate limit" is a cause without an action. What do I do? Add a token? Where?
- "35,917 ITEMS / MIN" is a throughput number with no reason to care.
- Bubble chart: "Repository" appears twice; labels overlap bubbles ("Pull requests" on top of "7"); numbers like "5.5k" inside bubbles are clear but the size encoding is not explained.
- Linking grid "Waiting for a source 156", "Links kept 0", "Links dropped 0" — I do not know what is good or bad.
- The Slack manifest block is an empty dark bar (no preview), next to "COPY MANIFEST".
- Sticky footer overlaps content in the full-page view (expected, but the footer is a solid bar over the GitHub card actions at 1440).

**Heuristics.**
| Heuristic | Score | Note |
|---|---|---|
| Visibility of system status | 2 | Partial shown; % meaning unclear |
| Match with real world | 2 | "Memory", "cursor", "items/min" |
| User control | 1 | Disconnect is red text, OK |
| Consistency | 2 | Page name mismatch |
| Error prevention | 1 | "Check connection" before saving — good |
| Recognition over recall | 1 | "Where do I find this?" links — good |
| Flexibility | 1 | Step-by-step guide option |
| Aesthetic / minimalist | 2 | Two dense columns |
| Error recovery | 3 | Rate-limit problem without a fix |
| Help | 1 | Guides present |

**Cognitive load:** medium-high.

**Top issues.**
1. Percentage headline contradicts the PARTIAL state and changes meaning between loads — material.
2. "GitHub is partly read. public rate limit" gives no next action — material.
3. Duplicate "Repository" labels for two repos (here, Settings, bubble chart) — minor/material: user cannot tell which repo is which.
4. Bubble graph has no shape/size legend and overlapping labels — minor.
5. Page named "Memory" vs nav "Connect" — minor.

---

## 5. Inbox (`/app/inbox`)

**What am I looking at?** Hero "5 things need you." Grouped list: "Needs your input · 4 — Answer or approve", "Build failed or blocked · 1 — Stopped and waiting", "PR ready · 0 — Ready for review". Each row: icon, title, a long grey line, time, "OPENS TICKET/QUESTIONS/BUILD", "MARK READ".

**What do the colours mean?** Green checkbox icon = approval. Yellow question icon = question. Red X icon = failed. Small coloured icons are the only distinction; the titles are generic.

**What should I do next?** Click a row. The keyboard hint "J / K TO MOVE · ENTER TO OPEN" is useful.

**What confused me.**
- Three rows have the same title "Actron needs your input"; the real content (the question) is at the end of a long grey second line after the repeated request title, then truncated: "…: docFromTextNotation is called from 5 functions and 964 tests. Should its current b…". The question should be the title.
- "This request needs your attention … missing_identity" exposes an internal code.
- "OPENS QUESTIONS" and "MARK READ" in mono caps look like labels, not actions. MARK READ has no visible button affordance.
- The "Ticket v1 is ready for your approval" row is for a request that Home shows as failed at build (approved by Vikram 6h ago per the Ticket tab). Stale items stay in the inbox.
- As Dev user: "Nothing needs you." appears twice (hero and empty state), and the J/K hint shows with nothing to move. Meanwhile Home says 3 requests need you.
- Empty "PR ready · 0" section is shown with a heading but an empty body.

**Heuristics.**
| Heuristic | Score | Note |
|---|---|---|
| Visibility of system status | 2 | Stale approval item |
| Match with real world | 2 | `missing_identity` |
| User control | 1 | Mark read |
| Consistency | 3 | Count differs from Home; actions styled as labels |
| Error prevention | 1 | |
| Recognition over recall | 3 | Generic titles, buried question |
| Flexibility | 0 | Keyboard nav |
| Aesthetic / minimalist | 2 | Repeated request title on every row |
| Error recovery | 1 | |
| Help | 1 | |

**Cognitive load:** medium; scanning is hard because the distinguishing text is at the end of truncated lines.

**Top issues.**
1. Row titles are generic; the actual question or reason is buried and truncated — material.
2. Inbox and Home disagree on what needs me (per-user vs workspace, never explained) — material.
3. Actions ("OPENS …", "MARK READ") look like metadata, not buttons — minor.
4. Internal code `missing_identity` — minor.
5. Empty state duplicates the hero text and shows a keyboard hint with nothing to navigate — minor.

---

## 6. Settings (`/app/settings`)

**What am I looking at?** Hero "16 of 16 model jobs run as stubs." Sections: Connections (two rows both labelled "GitHub", schedules, working branch), Models (16-row table: job, kind, provider, status — all STUB), Thresholds (three decimals), People (approvers, bot name, bot email), public replays checkbox, Budget, Danger zone (Reset cursor / Disconnect ×2).

**What do the colours mean?** Orange STUB pill on all 16 rows; orange PARTIAL; green UP TO DATE / blue SYNCING; red danger box.

**What should I do next?** Unclear. The hero frames the page around a developer configuration fact. The real blocker for the failed builds — the empty "Bot name for commits" and "Bot email for commits" fields — is two-thirds down, with no highlight.

**What confused me.**
- Two connections both named "GitHub" with no repo name. Danger zone has two "GitHub" rows; I cannot tell which I would disconnect.
- 16 identical orange STUB pills: badges without meaning. "Provider" column also says STUB.
- Job names in snake_case (`is_approval`, `judge_link`); kinds mix sentence case ("Yes or no, as a probability") and lower-case "json", "tools".
- Footnote: "Judgments use Jev; text uses the LLM (not set); the investigator uses the pipeline; Pi codes with no model. Model names come from the server environment." — dense, all internal.
- Thresholds are bare decimals (0.8, 0.5, 0.6) with no scale or preview.
- "Approvers: Slack user ids" — users must look up IDs.
- "Save changes" is greyed in the top-right and far from the fields.
- "Reset cursor" — internal term.

**Heuristics.**
| Heuristic | Score | Note |
|---|---|---|
| Visibility of system status | 2 | |
| Match with real world | 4 | stubs, cursor, snake_case jobs, user ids |
| User control | 1 | |
| Consistency | 2 | Casing mixed |
| Error prevention | 3 | Empty bot identity breaks builds, not flagged |
| Recognition over recall | 3 | Two "GitHub" rows |
| Flexibility | 1 | |
| Aesthetic / minimalist | 2 | 16-row table of identical pills |
| Error recovery | 2 | |
| Help | 2 | |

**Cognitive load:** medium-high.

**Top issues.**
1. Hero and model table say "stubs" 17 times — judges read the product as fake — material.
2. Empty bot identity (the cause of the failed builds) is not flagged or linked from the failure — material.
3. Two indistinguishable "GitHub" connections, including in Danger zone — material.
4. Internal vocabulary: snake_case jobs, "json", "Reset cursor", "Slack user ids" — minor.
5. Save button far from fields; thresholds without scale — minor.

---

## 7. System (`/app/system`)

**What am I looking at?** Hero "What Actron is doing right now." A large canvas with nine service chips (SLACK, ACTRON UI, ACTRON, FALKORDB, JEV, PI, GITHUB, LINEAR, LLM) joined by faint dotted lines. Below: "Waiting for activity. The map moves only when something really happens." and "Log · last 20 — Recent events: No events yet."

**What do the colours mean?** Only the vendor logos are coloured. Lines are nearly invisible dotted grey. Green "STREAM · LIVE" pill.

**What should I do next?** Nothing; it is a monitor. With no activity it is a large empty diagram.

**What confused me.**
- This is an architecture diagram, not an operations view. An engineer wants: what is running, queued, failed; sync status per source; errors. None of that is here, although the footer shows "CODE · SYNCED 3M AGO", which is activity the log does not list.
- JEV, PI, LLM, ACTRON vs ACTRON UI are internal component names.
- Dotted lines at ~10% contrast; I cannot see which connects to which.
- The canvas occupies the full first screen; the log is below the fold.
- "something really happens" — informal filler.

**Heuristics.**
| Heuristic | Score | Note |
|---|---|---|
| Visibility of system status | 3 | The status page shows less status than the footer |
| Match with real world | 3 | Component names |
| Consistency | 1 | |
| Aesthetic / minimalist | 2 | Big empty diagram |
| Help | 2 | |
| Others | 1 | |

**Cognitive load:** low, but low value.

**Top issues.**
1. Page shows architecture, not what is running/failed; log is empty while syncs happen — material.
2. Connection lines are too faint to read — minor.
3. Internal component names as the main content — minor.
4. Log below the fold — minor.

---

## 8. Landing page (`/`)

**What am I looking at?** Nav (How it works, The graph, Built with, Sign in). Hero "Before an AI changes your code, it should know what your team decided." with a dot-cloud graph and a yellow highlighted path. Sections: The problem (a clear four-node diagram), How it works (five steps, each with a real UI capture), The graph (ontology by source with Cypher examples), Built with (vendor list), final CTA.

**What do the colours mean?** Yellow = evidence path and CTA. Red = "breaks". Grey nodes. The legend under the hero ("MEMORY GRAPH · 96 NODE TYPES · EVIDENCE PATH: REQUEST TO FUNCTION") explains the yellow line — good.

**What should I do next?** "Open the app" — clear. This is the strongest screen. The problem diagram (Format on save / Paste and indent BREAKS / Keep comments when formatting — DECIDED IN SLACK · NOT IN CONTEXT) explains the product in five seconds.

**What confused me.**
- Each UI capture is captioned "CAPTURED FROM THE DEVELOPMENT FIXTURES, NOT A LIVE WORKSPACE" in mono caps. Honest, but "development fixtures" is internal and repeated five times; "Example workspace" would do.
- "96 node types" vs "23 node types" in the app.
- Sections are revealed on scroll: a full-page capture shows a ~3,000px blank area in "How it works". Anyone who jumps, prints or screenshots sees an empty page; reduced-motion users may too (unverified).
- Captures are miniatures of the dense request page, small text unreadable at landing scale.
- Built-with list includes Pi with the 🐳 in the Build capture.
- The "Each part does one job." vendor table reads like a hackathon sponsor list; fine for judges, but it is the most template-like section.

**Heuristics.** Mostly 0–1. Match with real world 2 (fixtures wording, Cypher). Aesthetic 1.

**Cognitive load:** low-medium. Good.

**Top issues.**
1. Scroll-reveal leaves large blank areas when not scrolled frame by frame — material for a judge who skims or screenshots (verify with reduced motion).
2. "Development fixtures" caption repeated on every capture — minor.
3. Node-type count inconsistent with the app — minor.
4. UI captures too small to read — minor.

---

## 9. Sign-in (seen briefly)

Dev login button with a DEV badge. Fine for a demo; the DEV marker also persists in the app footer ("DEV") which judges will see on every page — minor.

---

## Prioritised list (most severe first)

1. **All app screens — internal vocabulary on screen** ("stub" 17× on Settings incl. hero, "JEV STUB" footer on every page, "The stub judged…", "fixed pipeline", "ExternalError", "missing_identity", "Reset cursor", Pi/Jev/LLM). Material: judges read "stub" as "not real"; users cannot decode it.
2. **Request page + Graph explorer — graph is not readable.** Five near-grey source colours (CORE and CODE both white in the legend), thin low-contrast links, truncated and overlapping labels, unexplained count bubbles, expanded mode is a hairball. Material: the evidence path is the product's core claim and it is not legible; List view is clearer than the canvas.
3. **Home vs Inbox vs Connect — numbers and states contradict.** "3 requests need you" vs "Nothing needs you"/"5 things"; memory 50% vs 100% next to PARTIAL; 23 vs 96 node types; Ticket "0 earlier decisions" vs Evidence "possible conflict"; 200 vs 194 tests. Material: trust.
4. **Request page (failed build) — recovery points to the wrong fix.** Primary "Edit ticket" for a missing bot email; Settings bot fields are empty and not linked or flagged; raw log hidden. Material.
5. **Home + Inbox — requests are not distinguishable.** Same title on three rows, cryptic ULID tails, generic "Actron needs your input" titles with the real question truncated at the end of the line; stale approval item stays. Material.
6. **Everywhere — monospace uppercase for labels, tabs, pills and actions, plus tight-tracked low-contrast small sans.** Material for readability; nothing has hierarchy; "MARK READ"/"OPENS QUESTIONS" do not look clickable.
7. **Graph explorer — empty first state and raw node dump.** Large blank canvas; detail panel shows contentHash, booleans, ISO timestamps, wrapped code, title broken mid-word. Material for a demo.
8. **Settings — two identical "GitHub" connections** (also in Danger zone and "Repository, Repository" on Connect). Material: user cannot tell which repo they disconnect.
9. **System — architecture diagram instead of status;** empty log while syncs happen; links nearly invisible. Material for the "what is running" job.
10. **Poster-size hero on every app page** pushes the working content below the fold at 1440 (Home queue, Settings, System, Graph). Minor-to-material.
11. **Emoji and badge noise:** 🐳 on Build tab, 16 identical STUB pills, "HIGH CONFIDENCE" on every impact card, "EVIDENCE 232". Minor (AI-look tell).
12. **Landing — scroll-reveal blank areas and "development fixtures" captions.** Minor-to-material for judges who skim.
13. **Unlabelled icon sidebar** (Connect = chain link, System = dots). Minor.
