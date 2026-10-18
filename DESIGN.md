# Actron design record

The design system for the Actron web UI, as built (spec C, C10). The tokens live in `frontend/styles/tokens.css`; `frontend/tailwind.config.ts` mirrors them as CSS variables, and `frontend/lib/motion.ts` mirrors the motion tokens for JavaScript. Two alternative token sets are in `DESIGN-DIRECTIONS.md`.

## Direction: "Evidence console"

From PRD 13.2. The system and density of a Linear-grade tool (monochrome, hairlines, keyboard first), the live grammar of a mission console (eyebrows, state chips, a streaming timeline, a numbered pipeline, a footer status bar, delivery toasts), and an editorial voice for the two things that carry the story: situation headlines and evidence quotes. Since the UI review pass (18 Oct 2026, `UI-REVIEW.md`) the console grammar no longer means mono capitals everywhere: labels, tabs, chips and actions use the UI face in sentence case, and mono is kept for data.

- **Who:** a developer or lead who asked for a change in Slack and opens Actron to see whether it is safe, what it touches and what they must decide; a reviewer checking the build; a hackathon judge with two minutes.
- **Mode (Impeccable):** Operate for every `/app` screen (precision and restraint), Persuade for the landing page (one committed signature).
- **Signature:** the evidence path. On the canvas the path from the request to the exact function traces hop by hop in the accent colour, and each hop with a quote shows a typeset quote card with its source. The same idea appears as the logo mark, as the highlighter wash behind a traced quote, and as the only yellow on most screens.
- **Feel:** a quiet, flat, near-black workbench; colour only when it means something; loud only when a person must act.

## Product context (Impeccable init, inferred)

Impeccable's init asks a person for product context. The user was not available, so the context comes from the brief only (PRD 1, 11, 13; PROMPT 8; spec C) and is recorded here instead of a separate PRODUCT.md:
- One sentence: Actron checks what your team already decided and built before an AI writes code, then carries the change from a Slack request to a tested pull request, and shows the graph path behind every step.
- Users: developers and technical leads working in Slack, Linear and GitHub.
- Voice: calm, precise, evidence first (PRD 13.4).
- Assumption: no light theme is ever needed (user decision 17 Oct 2026).

## Colour (final values)

| Token | Value | Use |
|---|---|---|
| `--ink-0` | `#0A0A0A` | page and all chrome |
| `--ink-1` | `#0F0F0F` | panels that need a fill, inputs |
| `--ink-2` | `#141414` | cards, menus, palette, modals, toasts |
| `--ink-3` | `#1A1A1A` | hover |
| `--line-1` / `--line-2` | `#1F1F1F` / `#2A2A2A` | hairlines / stronger borders |
| `--text-1` | `#EDEDED` | primary text (17.1:1 on ink-0) |
| `--text-2` | `#B4B4B4` | secondary text, including secondary sentences (9.5:1) — changed, see below |
| `--text-3` | `#858585` | labels, eyebrows (5.4:1 on ink-0, 4.7:1 on ink-3) — changed, see below |
| `--text-disabled` | `#5C5C5C` | disabled controls only, always with a text label |
| `--accent` / `--accent-ink` | `#E4F24C` / `#0A0A0A` | "highlighter": evidence path, primary action, needs-you |
| `--accent-wash` | `rgb(228 242 76 / 0.14)` | highlighter behind a traced quote, the handoff row |
| `--state-ok` `--state-conflict` `--state-possible` `--state-running` `--state-idle` | `#4CC38A` `#F2555A` `#F0A44B` `#5BC0EB` `#8C8C8C` | state chips, shared with Slack through `frontend/lib/states.json` |
| `--node-code` | `#97A8C0` steel blue-grey | graph nodes from code and git (8.2:1 on ink-0) |
| `--node-github` | `#C8B08E` warm sand | graph nodes from the GitHub API (9.5:1) |
| `--node-slack` | `#C77DDB` orchid | graph nodes from Slack (7.0:1) |
| `--node-linear` | `#6F8DF5` cornflower blue | graph nodes from Linear (6.4:1) |
| `--node-core` | `#E58FA8` rose | Actron's own types: request, investigation, decision, person, procedure (8.3:1) |
| `--graph-link` / `--graph-link-focus` | `#6E6E6E` (3.9:1) / `#C4C4C4` (11.4:1) | links at rest / links touching the focused or selected node; the evidence path is `--accent`, drawn on top |

Node colours are muted, distinct hues: every pair differs by at least 0.11 in OKLab, none equals the accent or a state colour, and all pass 3:1 against the canvas (`contrast.test.ts`). Colour encodes source; shape encodes type (request and investigation square, function and class circle, tests pill, file and document page, commit, file change and PR triangle, decision diamond, person ring, Slack message speech bubble, issue hexagon). The same palette is used by the request canvas, the graph explorer, the Connect memory graph, the 3D hero, its static fallback (`scripts/make-brand-assets.ts` reads tokens.css) and the Open Graph image (`og.tsx` mirrors the hex, checked by `og.test.ts`).

No gradients on surfaces, no glass, no blue tint. Every text and background pair used is checked for WCAG AA in `frontend/tests/unit/contrast.test.ts`.

## Type

- **Display: Newsreader** (variable, optical sizes) for headlines, panel titles and evidence quotes. A transitional serif with a real optical-size axis, so 64-px headlines are tight and 18-px quotes stay readable; it gives the "decisions on paper" voice the dossier direction asked for. Kept from the spec default; Impeccable's guidance argued against Fraunces (too decorative for an operate surface) and Source Serif 4 (plainer at headline sizes).
- **UI: Public Sans** (variable) for body, labels, tabs, chips and controls. Chosen in the UI review pass over IBM Plex Sans, Source Sans 3, Hanken Grotesk and Mona Sans after rendering Home, Inbox and Request with each (`docs/ui-review/sheet-*.png`): it kept the most even letter and word spacing and a steady weight at 13–16 px on black, where Plex looked thin and uneven.
- **Data: JetBrains Mono** (400/500/600) for ids, hashes, counts, code, timestamps, durations, cost and the footer status, always with tabular figures (`.data-label` for the uppercase form). Labels, tabs, chips, actions and section eyebrows are not data and use the UI face in sentence case (`.eyebrow` is UI 13/18 medium).
- All three load through `next/font/google` with `display: swap`, Latin subset and size-adjusted fallbacks (no layout shift on load).
- Sentences people read are 14 px or larger in `--text-2` or brighter; `--text-3` is for labels and meta only.
- Scale (px/line-height): 12/16 data label (mono, uppercase, 0.04em), 13/18 caption, 14/20 small, 16/24 body, 18/26 lead, 22/28 title-sm, 28/34 title, 36/42 title-lg, 48/52 headline-sm, 64/68 headline, 80/84 hero. Headlines balance and never exceed two lines at 1440.

## Space, layout, shape

- 4-point scale only: 2, 4, 6, 8, 12, 16, 20, 24, 32, 40, 48, 64, 80, 96 (enforced by `tokens.test.ts`).
- 12-column grid, 24-px gutters, content max 1600, page padding 32 (48 at 1920, 16 on phones).
- App shell: 64-px rail, 32-px footer status bar, no top bar; every screen opens with eyebrow, situation headline and purpose line.
- Request page: timeline 3 / canvas 5 / tabs 4 columns, filling the viewport below a dense header and the system strip.
- Radius: 4 (chips, inputs), 6 (buttons, cards), 10 (panels, modals). Elevation only on overlays (`0 8px 24px rgb(0 0 0 / .45)` on ink-2); everything else is hairlines on ink-0.

## Motion

Durations 120 / 200 / 320 / 520 / 900 ms; easings standard `cubic-bezier(.2,0,0,1)`, emphasized `(.3,0,0,1)`, exit `(.4,0,1,1)`. Only these motions exist: evidence-path tracing (520 ms per hop), node entrance, pulses along system-map edges, chip colour change, timeline item entrance, number tickers, toast entrance, headline cross-fade on a state change (never on first paint), glyph animated states, the landing reveal and the hero. The hero is a 10-second loop (`components/hero/timeline.ts`) that tells what Actron does: a ring leaves the request while it searches the FalkorDB graph, the evidence path draws itself hop by hop, holds, then fades; the whole graph breathes (2% swell over 4.5 s) and orbits once in about two minutes, and a caption chip with the FalkorDB mark names the stage ("Request received", "Searching the FalkorDB graph", "Following links to the code", "Evidence path found"). Rings and labels are not accent-coloured except the path and its end. Under `prefers-reduced-motion` nothing travels or rotates: the path appears at once, pulses are replaced by the caption update, entrances become 120-ms fades (`reduced-motion.spec.ts`).

The shell does not ship the `motion` library: headline swaps and toasts are CSS, which keeps every non-graph route under the 250 KB first-load budget (largest: Request at 230 KB gzipped).

## Iconography

- Actron glyph set: 33 SVG glyphs on a 24-px grid, 1.5 stroke, round caps, `currentColor`, each with an animated state (draw, trace, ripple, rise, slide, pulse). `/app/dev/glyphs` shows them for visual tests.
- Brand marks are real: Slack, FalkorDB, Pi and TypeSafe from the owners' sites; GitHub, Linear, MCP, Temporal, Docker and language marks from Simple Icons (`frontend/public/brands/LICENSES.md`).
- Phosphor (regular) only for generic controls. No sparkles, robots, wands or brains.
- Logo: the evidence-path glyph — a hollow request node traced through two hops to a highlighted end node — with the "Actron" wordmark in Newsreader, outlined to paths.

## Voice

Calm, precise, evidence first. Headlines state the situation ("Ticket v2 is ready for your approval.", "Building. 3 of 14 tests passed."). Errors say what happened and what to do. Empty states teach the next step. Sentence case everywhere; capitals only in mono data labels (ids, hashes, the footer status). No hype words, exclamation marks or emoji (`copy-lint.test.ts`).

## Changes from the spec defaults (with the finding behind each)

| What | Spec default | Now | Why (finding) |
|---|---|---|---|
| `--text-3` | `#808080` | `#858585` | Contrast audit: `#808080` on `--ink-3` is 4.41:1, below AA for the small labels that sit on hovered rows and inputs. `#858585` gives 4.72:1 there and 5.37:1 on ink-0 without changing the hierarchy. |
| `--node-core` | `#E4F24C` | `#EDEDED`, then `#E58FA8` | Critique, round 1 (Connect): the core node colour equalled the accent and competed with the evidence path, so it became white. UI review pass: with every source a near-grey the graph read as all white; core is now rose, distinct from the accent and every state. |
| `--node-*` | near-greys `#C9CDD3` `#9BA6B4` `#B7A6D9` `#8FB3E8` | `#97A8C0` `#C8B08E` `#C77DDB` `#6F8DF5` | User report: "the graph only shows nodes and links in white". Sources now differ at a glance (see Colour). |
| `--text-2` | `#A8A8A8` | `#B4B4B4` | User report: small grey body text read thin; secondary sentences raised one step. |
| UI face | IBM Plex Sans | Public Sans | User report: body font uneven and thin at 13–16 px; comparison in `UI-REVIEW.md`. |
| Mono capitals | eyebrows, tabs, chips, pipeline, buttons, legend | data only | User overruled the "live grammar" decision of audit rounds 1–2: mono caps made actions read as metadata and the UI feel machine-made. |
| Screen headline | headline (64 px) on overview screens | headline-sm (48 px) on every app screen; 64 px only by explicit `size="xl"` | Review: the poster headline pushed the queue below the fold at 1440. |
| Primary button, disabled | ink-3 fill, disabled text | transparent with a faint accent border, `--text-2` text | Review: a disabled "Ask Actron" read as a dead button and Home lost its primary action. |
| Request header headline | headline-sm/headline (48–64 px) | title-lg (36 px) on working screens | Layout critique, round 1: at 1440×900 the three columns started below the fold. Overview screens keep the 64-px headline. |
| System map strip | spec left free | one row of actors with arcs for links that real events used, plus one caption line | Round 1: the two-dimensional map at strip size crossed every edge into one band and took 250 px. The full System view keeps the two-dimensional map. |
| System strip default | spec: collapsible, remembered | collapsed by default to one caption line ("FALKORDB · callers(…) · 12 results"), map on demand | AI-look audit round 1: the strip repeated the stepper and pushed the columns below the fold. |
| Confidence tier text | `HIGH` | `HIGH CONFIDENCE` | Audit round 2: "IMPACT · HIGH" read as high impact. |
| Primary action placement | spec left free | the header holds the one yellow action (Approve, Edit ticket, Request changes is secondary); in-panel buttons are secondary | Audits 3 and 5: two yellow buttons for one action. |
| Hero on phones and software WebGL | spec: fallback for reduced motion, ≤ 4 cores, save-data, no WebGL | also below 768 px and when WebGL runs on the CPU | Lighthouse against the real backend: the orbit cost 4.8 s of main-thread time under software rendering. |
| Graph labels | spec left free | drawn in screen space, only the 12 largest clusters until zoom or focus, with a page-colour halo | Round 1–2: labels scaled with the zoom transform rendered with broken spacing and overlapped in dense graphs. |

## Screen shaping (Impeccable shape, one line each)

| Screen | Purpose | Main action | Headline examples |
|---|---|---|---|
| Sign in | start a session with Slack | Sign in with Slack | "Sign in to see what your team already decided." |
| Connect | connect sources, watch memory fill | Connect / Sync now | "Your memory is 62% built." / "Connect a repository to start." |
| Home | what needs you, running, done | Ask Actron | "4 requests need you. 1 is building." / "No requests yet." |
| Request | decide, approve, follow the build, review | Approve / Answer | the eight state headlines in PROMPT 8.8 D |
| Graph | explore memory with provenance | search, expand | "96 node types, 61,497 nodes, 281,656 links." |
| Inbox | everything waiting for you | open at the right tab | "3 things need you." |
| System | what Actron is doing now | watch | "What Actron is doing right now." |
| Settings | models, thresholds, approvers, budget | Save changes | "1 of 16 model jobs run as stubs." |
| Replay | watch a finished request step by step | Play | "Replay: <title>." |

## Review record

Review rounds and the independent AI-look audit are logged in `BUILD-LOG.md` (W7 entries). Screenshots of every screen at 1440 and 1920 are in `frontend/tests/screenshots/` (`npx tsx scripts/capture-screens.ts`).
