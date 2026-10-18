# UI review and fix pass: Actron frontend

You are a fresh agent. The whole Actron product is already built and green. Your job is one thing: review the frontend the way a real user sees it, then fix what makes it hard to read or understand. You change the frontend (and the shared state map if needed). You do not add features.

What Actron is, so you can judge screens as its user: an engineering team asks for a change in Slack or in the app. Actron investigates a FalkorDB graph that links the team's code, GitHub, Slack and Linear. Then it asks clarifying questions, writes a versioned ticket for approval, has the Pi coding agent build the change, and opens a PR. The user is an engineer or lead who opens the app to see what needs them, why Actron reached a conclusion (the evidence path in the graph), and what is running. It is a hackathon entry (FalkorDB Graph Hacks, deadline 18 Oct 2026, 11:59 PM IST), so judges will also look at it: it must read as a real, production-grade SaaS product and must not look AI-generated.

Work unattended. Do not stop to ask questions; make a reasonable choice, write it in the decisions section of your report, and keep going. Use subagents for independent work (see section 6).

## 1. Read first (in this order)

1. `BUILD-REPORT.md`: what exists and how to run it.
2. `BUILD-LOG.md`, the W7 entries and "real-data UI pass": every design review round so far, and the 17 deferred minor items from audit round 7.
3. `specs/C-experience.md`, sections C1 (tokens, type scale), C2 (components: GraphCanvas, StateChip, Pipeline), C11 (AI-look audit tells).
4. `DESIGN.md`: the design system as built, and the reasons for each change from the spec.
5. `frontend/AGENTS.md`: this Next.js version has breaking changes; read the docs it points to before you change routing, fonts or config.
6. The real-data screenshots in `frontend/tests/screenshots/real/` (Calva data, no fixtures). Look at every one at 1440 before you change anything.

## 2. Rules

- No git commits, pushes or remote changes. The user commits.
- Dark only. Page base stays `#0A0A0A` (`--ink-0`). No light theme.
- `frontend/styles/tokens.css` is the only place colours, type and spacing are defined. Components use tokens, never raw values.
- `frontend/lib/states.json` is shared with the Slack bot (`backend/actron/integrations/slack_blocks.py`). If you change a state colour or name there, keep the hex equal to `tokens.css`, and run the backend Slack tests.
- One yellow (`--accent`) action per screen, and the accent stays reserved for "the evidence path, the primary action, needs you". Do not spread it.
- Keep text plain and short. No marketing copy, no emoji, no code comments that explain the obvious.
- Every fix keeps all existing tests green. Update unit tests and Playwright snapshots only when the change is intended, and say which ones in the report.
- Keep accessibility at least where it is: AA contrast for all text (check with the existing contrast test), visible focus, reduced motion respected, Lighthouse accessibility 98+.

## 3. What the user reported (fix these first)

The user's words, cleaned up: "The UI is good. The font in places can be better, not the headings. The graph only shows nodes and links in white. On Home, progress, running and the other states should be highlighted, because I can't tell what each one means."

What I verified in the code and screenshots, so you start from the cause:

### 3.1 Graph is all white (highest priority)
- Node colours come from `--node-*` tokens through `GROUP_TOKEN` in `components/graph/GraphCanvas.tsx`. The values are near-white greys: code `#C9CDD3`, github `#9BA6B4`, slack `#B7A6D9`, linear `#8FB3E8`, and core was changed from the accent to `#EDEDED` in review round 1. On a black canvas they all read as white.
- Links are drawn in `--text-2`/`--text-3` grey; only the traced path uses the accent.
- On the request canvas (`request-1-evidence-1440.png`) the legend says CORE and CODE, both white dots. Clusters ("194 tests", "21 functions") are white discs with dark text. Nothing tells the user which node is the request, a seed function, a test cluster, a decision or a person.
- Connect's memory graph (`connect-1440.png`) is a grey hairball with overlapping labels.

What to do:
- Give each source a clearly different, muted hue that still sits well on `#0A0A0A` (for example a cool blue-grey for code, a violet for Slack, a blue for Linear, a neutral-warm for GitHub, and a distinct colour for core types such as Request, Investigation, Decision, Person). They must be told apart at a glance and pass 3:1 against the canvas. They must not equal the accent or any state colour, so the evidence path and states still stand out.
- Use shape per type as spec C2 says (check `shapeFor` covers the types that actually appear in real data: request, function, test cluster, file, commit, PR, decision, person).
- Links: solid for explicit, dashed for inferred (already in code; make the difference visible at normal zoom), opacity by confidence, and a slightly brighter tone for links touching the focused node. Keep the evidence path in the accent, drawn on top.
- The request node should be the visual anchor (larger, labelled, distinct). Cluster discs should carry their source colour, not white.
- Legend: list every group and shape actually on screen, with the same colours, plus explicit vs inferred and "evidence path".
- Apply the same palette to the graph explorer, Connect memory graph, the 3D hero and the landing ontology section so the colours mean the same thing everywhere.
- Fix label overlap on the request canvas and Connect memory graph (deferred minor in audit round 7). Fewer labels at low zoom is fine; overlapping text is not.
- Graph explorer empty state (`graph-1440.png`): the canvas is a large empty box. Show something useful before a search, for example the most-connected functions or the type-level graph, so the screen does not look broken.

### 3.2 Body font (not the headings)
- Fonts: Newsreader (headings), IBM Plex Sans (UI), JetBrains Mono (data). Headings are fine; leave Newsreader.
- In the real screenshots body text at 13 to 16 px looks uneven and thin, for example "Make docFromTextNotation in the test utilities…" and "Pick a result to see it with its neighbours". Grey-on-black small text at weight 400 makes it worse.
- Mono uppercase with wide tracking is used almost everywhere: eyebrows, tabs, chips, pipeline, buttons such as "MARK READ" and "OPENS TICKET", the footer, Settings provider column. 46 component files use `font-mono` and 59 places use `uppercase`. This is the main reason the text feels heavy and machine-like.

What to do:
- Compare IBM Plex Sans with two or three other free UI faces suited to a dense dark product UI (not Inter, not the defaults every AI-made site uses). Render Home, Inbox and the Request screen with each, look at the screenshots side by side, and pick one. If Plex stays, fix how it is used instead (weight, size, colour, line height). Record the comparison and the choice in the report.
- Raise readability of small text: body copy at 14 px or more where people read sentences, secondary text no dimmer than needed for hierarchy, check weights 400/500 on dark.
- Cut mono caps back to real data and true labels: ids, hashes, counts, code, timestamps, the footer status. Actions ("Mark read", "Open ticket"), tab names, and descriptive labels go to the UI font in sentence case. The audit rounds kept mono caps as "the brief's live grammar"; the user has now overruled that for anything that is not data.
- Check that the font loads without layout shift (the existing C-AC-3 test) and that the first-load JavaScript budget still passes.

### 3.3 Home: states are hard to tell apart
- Home (`home-1440.png`, `home-1920.png`) shows sections "Waiting on you", "In progress" and below them finished work. Section labels are small grey mono eyebrows; the groups look the same.
- Each row has a state chip, a sentence "Now Needs your input." (repeats the chip, odd capitalisation), and a mini pipeline of six grey dashes with no visible label. The user cannot tell what the dashes mean.
- "Needs your input" and "Awaiting approval" and "PR ready" all use the same accent outline, so different asks look the same.

What to do:
- Make each group visually distinct and self-explaining: a section header with the group's state colour (needs you: accent; running: blue; stopped/needs attention: red; done: green; cancelled: grey), a count, and a one-line plain description of what the group means.
- Rows: keep one state chip, and replace the repeated "Now Needs your input." with the useful fact (the question asked, "Ticket v1 waits for approval", the failure reason, the PR number). Give the mini pipeline a visible current-step label (for example "Step 2 of 6 · Clarify") and a tooltip, or replace it with that label.
- Distinguish the kinds of "needs you" inside the accent family by text and icon (answer, approve ticket, review PR), not by more colours.
- Empty groups: one quiet line, not a full section header with "Nothing is running." taking a band of space.
- Same treatment for the Inbox groups and the request header chip, so a state looks the same on every screen and in Slack.

## 4. Other problems found in the real screenshots (fix after section 3)

1. Getting started checklist: "Next: connect slack." (lowercase brand name); finished steps are struck through, which reads as cancelled. Use a done tick and normal text.
2. Connect: headline "Your memory is 50% built." then a large empty gap before the purpose line; "Still filling: Repository, Repository." repeats a name; the GitHub card shows two connection rows as one with "Setup 1 of 4 steps" next to "PARTIAL".
3. Settings: two rows both labelled "GitHub" (one is the code source, one is GitHub), with different schedules and the same working branch field. Name them so a user knows which is which ("Code (git)", "GitHub API"). The models table shows "STUB" twice per row (provider and status).
4. Request screen: the build tab title repeats the page headline in large red serif; the timeline text "The stub judged 20 candidates." exposes an internal word; "SYSTEM ACTRON UI · Notified the person who must act" strip is hard to parse.
5. Inbox: "J / K TO MOVE · ENTER TO OPEN" key hints in mono caps under the purpose line; "OPENS QUESTIONS" and "MARK READ" look like labels, not actions; three rows read the same for the same request ("Actron needs your input") with the question cut off. Group per request or lead with the question.
6. System view: the lines between actors are so faint they are nearly invisible; the map does not show what is happening "right now" when idle. Make idle state explicit and links visible.
7. Footer status bar: "CODE · SYNCING" stays on while nothing is syncing in the screenshots; confirm it reflects real state.
8. Request titles on Home are identical for three requests; show the short id more clearly or the differing state fact so rows can be told apart.
9. The 17 deferred minor items at the end of audit round 7 in `BUILD-LOG.md`: fix the ones that still show in the real screenshots.

## 5. How to review (use the installed skills)

Project skills are in `.claude/skills/`, user skills in `~/.claude/skills/`. Load each with the Skill tool before you use it.

1. Before changing anything, run a user-perspective review of every real screenshot and the live app at http://localhost:3000 (Dev login):
   - `impeccable`: run its critique and audit for each main screen (Home, Request, Graph, Connect, Inbox, Settings, System, landing).
   - `interface-design`: its audit for consistency of spacing, type and colour.
   - `web-design-guidelines`: check the frontend code against its rules.
   - `better-ui` and `frontend-design` for the visual fixes; `interaction-design` and `12-principles-of-animation` only where a fix changes motion.
   For each screen, write down as a first-time user: what am I looking at, what does each colour mean, what should I do next, what confused me. Merge the findings with sections 3 and 4 into one prioritised list in `UI-REVIEW.md` (project root) before fixing.
2. Fix in priority order: section 3.1, 3.3, 3.2, then section 4, then new findings.
3. After the fixes, run an independent review: a fresh subagent that sees only the new screenshots (not the code, not your list) and reports anything that looks confusing, unreadable or AI-generated, using spec C11's list of tells. Fix material findings and repeat until a round finds none.

## 6. Roles and subagents

Use subagents in parallel where files do not overlap. Opus for design judgment and frontend changes; Sonnet for routine test updates.

- Principal product designer (independent reviewer): the user-perspective review and the final screenshot-only audits. Never edits code.
- Visual designer: palette for nodes and states, type choice, hierarchy. Writes the token changes and the reasons in `DESIGN.md`.
- Design engineer, graph: `components/graph/*`, `components/connect/MemoryPanel.tsx`, `components/connect/memory-graph.ts`, `components/hero/*`.
- Design engineer, screens: Home, Inbox, Request, Settings, Connect, System, shell and footer.
- QA: keeps unit, e2e and contrast tests green, updates snapshots that change on purpose, re-captures screenshots.

## 7. How to run and check

```bash
make up                                    # whole stack; frontend on http://localhost:3000, Dev login
cd frontend
npm run typecheck && npm run lint && npm test
npm run capture                            # fixture screenshots into tests/screenshots/
npx tsx scripts/capture-real.ts            # real-data screenshots into tests/screenshots/real/
cd .. && ./scripts/test_all.sh             # every level; must pass before you finish
```

The frontend in compose is a production build: rebuild the frontend container (or run `next dev` against the compose backend on another port) so screenshots show your changes. Real data is the `dev` workspace (Calva); do not reset it.

## 8. Done means

- Every item in section 3 is fixed and visible in new real-data screenshots at 1440 and 1920.
- Section 4 items fixed, or listed in the report with a reason.
- A screenshot-only review round finds no material issues.
- `./scripts/test_all.sh` passes once at the end (spec coverage, Lighthouse desktop 98+ accessibility, performance budget, contrast tests included).
- `UI-REVIEW.md` at the project root contains: the findings list with status, before and after screenshot paths per screen, the font comparison and choice, the new palette with contrast ratios, every token or `states.json` change, decisions made without asking, and anything left undone.
- One entry appended to `BUILD-LOG.md` summarising the pass. `DESIGN.md` updated to match the new tokens and rules.
- Nothing committed.
