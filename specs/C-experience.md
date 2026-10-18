# Spec C: Experience (frontend, Slack presentation, story)

**Scope:** PRD section 13 (all), 11.4, 14 (consumer side), 19; PROMPT section 8 (intent, process, shell, screen blueprints, story requirements, Slack blueprints). This spec turns them into exact tokens, components, screens, data flow, tests and acceptance criteria. Where PROMPT section 8.8 gives a screen blueprint, it is part of this spec.

**Intent in one line:** make it undeniable that Actron's decisions come from the graph, and show every step as it happens, so a judge understands the product in two minutes and remembers it.

**Rule for choices:** this spec gives defaults for every design decision. The build may change a default only when the Impeccable critique or audit flags it, and must record the old value, the new value and the reason in `DESIGN.md`.

---

## C1. Design system (tokens in `frontend/styles/tokens.css`, mirrored in `tailwind.config.ts`)

### C1.1 Colour (dark theme: the default and the only required theme)
The app is dark only, regardless of the operating system's preference. There is no light theme.
| Token | Default | Use |
|---|---|---|
| `--ink-0` | `#0A0A0A` | page background **and** all chrome (rail, footer status bar, headers, panels by default). Matches the user's VS Code setup (Dracula with every background overridden to `#0A0A0A`): one flat, neutral black |
| `--ink-1` | `#0F0F0F` | panels when they need a fill (rare; prefer hairlines on `--ink-0`) |
| `--ink-2` | `#141414` | raised cards, menus, palette, modals, toasts |
| `--ink-3` | `#1A1A1A` | hover, inputs |
| `--line-1` | `#1F1F1F` | hairlines that separate panels and regions |
| `--line-2` | `#2A2A2A` | stronger borders, focus base |
| `--text-1` | `#EDEDED` | primary text (about 17:1 on `#0A0A0A`) |
| `--text-2` | `#A8A8A8` | secondary text (about 8.5:1) |
| `--text-3` | `#808080` | labels, eyebrows (about 5:1, passes AA for small text); disabled controls may use `#5C5C5C` with a text label |
| `--accent` | `#E4F24C` | the evidence path, the primary action, "needs you" emphasis. Name: "highlighter" (evidence is highlighted like on paper) |
| `--accent-ink` | `#0A0A0A` | text on accent |
| `--state-ok` | `#4CC38A` | done, passed, up to date |
| `--state-conflict` | `#F2555A` | conflict, failed |
| `--state-possible` | `#F0A44B` | possible conflict, partial |
| `--state-running` | `#5BC0EB` | running, investigating, building |
| `--state-idle` | `#8C8C8C` | idle, not connected, cancelled |
| `--node-code`, `--node-github`, `--node-slack`, `--node-linear`, `--node-core` | `#C9CDD3`, `#9BA6B4`, `#B7A6D9`, `#8FB3E8`, `#E4F24C` (muted; graph only) | node colours by source on the canvas |
- Colour carries meaning only. No gradients on surfaces, no glass blur. Tests check WCAG AA contrast (4.5:1 for text, 3:1 for large text and UI components) for every text/background pair used.

### C1.2 Typography
- **Display** (headlines, evidence quotes, panel titles): default **Newsreader** (variable, optical sizes) via `next/font/google`. Alternatives if Impeccable flags it: Source Serif 4, Fraunces.
- **UI** (body, controls): default **IBM Plex Sans** via `next/font/google`. Alternatives: Manrope, Geist.
- **Mono** (data, labels, eyebrows, ids, code, timestamps, metrics): **JetBrains Mono** via `next/font/google`.
- Banned as primary faces: Inter, Roboto, Arial, Helvetica, system UI stacks, Space Grotesk.
- Scale (px / line-height): `12/16` mono-xs (eyebrows, labels, uppercase, letter-spacing 0.08em), `13/18`, `14/20` body-sm, `16/24` body, `18/26`, `22/28` title-sm (display), `28/34` title, `36/42`, `48/52` headline-sm, `64/68` headline (screen headlines at ≥ 1280 px), `80/84` hero (landing). Numbers use tabular figures (`font-variant-numeric: tabular-nums`).
- Headline rules: display face, weight 400–500, one sentence, max 2 lines at 1440, `text-wrap: balance`.
- Quote rules: display face italic off, 18–22 px, hanging opening quotation mark, source line in mono-xs below.

### C1.3 Space, layout, shape
- Spacing scale (px): 2, 4, 8, 12, 16, 20, 24, 32, 40, 48, 64, 80, 96.
- Grid: 12 columns, 24 px gutters, content max width 1600, page padding 32 at 1440 and 48 at 1920.
- Radius: 4 (chips, inputs), 6 (buttons, cards), 10 (panels, modals). No pill-shaped cards.
- Borders: 1 px `--line-1`; focus ring 2 px `--accent` with 2 px offset.
- Elevation: none by default; overlays (menus, palette, modals, toasts) use `0 8px 24px rgba(0,0,0,0.45)` and `--ink-2`.

### C1.4 Motion
- Durations: `--dur-1` 120 ms (hover, press), `--dur-2` 200 ms (chips, tabs), `--dur-3` 320 ms (panels, toasts), `--dur-4` 520 ms (path tracing per hop), `--dur-5` 900 ms (landing reveals).
- Easings: `--ease-standard` `cubic-bezier(0.2, 0, 0, 1)`, `--ease-emphasized` `cubic-bezier(0.3, 0, 0, 1)`, `--ease-exit` `cubic-bezier(0.4, 0, 1, 1)`.
- Allowed motions (only these): evidence-path tracing, node entrance, pulse along system-map edges, chip state change, timeline item entrance, number tickers, toast enter and exit, tab and panel transitions, skeleton-to-content cross-fade, glyph animated states, landing scroll reveals, hero orbit.
- `prefers-reduced-motion: reduce` → no travelling or orbiting motion; changes become instant or 120 ms fades.

### C1.5 Iconography
- **Brand marks** in `frontend/public/brands/` (SVG): slack, github, linear, falkordb, typesafe (Jev), pi, python, typescript, docker, temporal, mcp (if an official mark exists; else wordmark). Source: official press kits or `simple-icons`. `LICENSES.md` lists source URL, owner, usage note. Rendered by `<BrandMark name size tone="color"|"mono">`.
- **Actron glyphs** (`frontend/components/glyphs/`), 24-px grid, 1.5 px stroke, round caps, each a React component with `animated?: boolean`: `Request`, `Investigate`, `ToolCall`, `Search`, `Callers`, `Callees`, `Impact` (ripple), `Criticality` (rising bars), `ShortestPath` (route trace), `Decisions`, `Tests`, `Owners`, `Procedures`, `Evidence`, `Decision`, `Conflict`, `PossibleConflict`, `Question`, `Ticket`, `Approval`, `Handoff` (slide), `Build`, `TestPass` (tick draw), `TestFail`, `Repair`, `PullRequest`, `MemoryUpdated`, `Graph`, `Inbox`, `Connect`, `Settings`. Generic controls (close, chevron, search field icon, external link, copy) use Phosphor regular.
- Banned: sparkles, robots, magic wands, brains, generic "AI" icons, emoji as icons.

### C1.6 Voice (applies to UI, Slack and docs)
Calm, precise, evidence-first; short sentences; plain verbs; no hype words, no exclamation marks, no emoji. Headlines state the situation. Errors say what happened and what to do. Empty states teach the next step. Use the same state names as Slack.

**Acceptance criteria**
- C-AC-1: Tokens exist as CSS variables and Tailwind theme values; no hard-coded colours, sizes or durations in components (lint rule or test scanning for hex codes and px values outside tokens).
- C-AC-2: Every text/background pair used meets WCAG AA (automated contrast test over the token pairs list).
- C-AC-3: Fonts load through `next/font` with `display: swap` and subsetting; no layout shift from font loading (CLS check).
- C-AC-4: All glyphs render on `/app/dev/glyphs` in static and animated states; visual snapshot tests at 1x and 2x.
- C-AC-5: Brand marks exist for each listed brand (or a wordmark with a `NEEDS-FROM-USER.md` entry) with `LICENSES.md`.
- C-AC-6: A static check finds no banned icon names, no emoji in UI strings, and no banned words in UI copy (`supercharge`, `unleash`, `seamless`, `AI-powered`, `revolutionary`, `magic`).
- C-AC-7: With reduced motion, no element animates position or rotation (Playwright with `reducedMotion: 'reduce'` and a check of computed animations).

Tests: `frontend/tests/unit/tokens.test.ts`, `contrast.test.ts`, `copy-lint.test.ts`; `frontend/tests/e2e/glyphs.spec.ts`; `frontend/tests/e2e/reduced-motion.spec.ts`.

---

## C2. Components (in `frontend/components/`, each with a Vitest test and, for visual ones, a Playwright snapshot)

| Component | Props (essential) | States and behaviour |
|---|---|---|
| `Eyebrow` | `children` | mono-xs uppercase, `--text-3` |
| `ScreenHeader` | `eyebrow`, `headline`, `purpose`, `actions?`, `pipeline?` | headline crossfades on change; `aria-live="polite"` on the headline region |
| `PanelLabelTitle` | `label`, `title` | mono label + display title |
| `StateChip` | `state` (one of B.C1 states or ingestion states) | colour and text from one map shared with Slack (`lib/states.ts`); transition 200 ms |
| `Pipeline` | `steps`, `current`, `status` | numbered 01–06; current step highlighted with accent underline; failed step in conflict colour |
| `TimelineItem` | `event` | renders every event type (B.C2) with glyph, plain sentence, mono time; hover emits highlight ids; click pins |
| `ToolCallCard` | `call`, `result?` | tool glyph, name, args in mono (truncated with tooltip), result summary, duration, running state with subtle progress |
| `EvidenceCard` | `evidence` | role label, quote (display face), source chip with `BrandMark`, author, date, confidence tier, actions "Show path", "Open source" |
| `ConfidenceTier` | `value`, `flag?` | HIGH (≥ 0.8), MEDIUM (0.6–0.8), POSSIBLE (flagged or < 0.6) with a short tooltip explaining the number |
| `LabelBanner` | `label`, `sentence` | conflict, possible conflict, nothing found, clear |
| `QuestionCard` | `question`, `onAnswer` | choice buttons or text input; answered state with who and where |
| `TicketView` | `revision`, `revisions`, `onEdit` | sections of B.C5; affected functions as node links; revision selector; diff view between revisions |
| `ApprovalCard` | `kind`, `target`, `current`, `approval?`, `onApprove` | shows revision and short hash or PR and short SHA; stale state text; confirm dialog naming the target; 409 reason inline |
| `BuildTheatre` | `build`, `steps`, `tests` | current step sentence, file with language icon, live diff preview (last change), pass/fail tickers, failing tests with folded output, repair attempts, MCP calls by Pi, raw log fold |
| `DiffViewer` | `files` | file list, unified diff with syntax colours (Shiki, lazy), line numbers |
| `TestList` | `results` | grouped pass/fail/skip, failing first, output folded |
| `ConstraintsChecklist` | `constraints` | each constraint with proof (test name or evidence link), status |
| `GraphCanvas` | `graph`, `mode`, `highlight`, `pathToTrace?` | d3-force layout in a web worker, Canvas 2D renderer, node shapes per type, colours per source, link style per method (solid explicit, dashed inferred) and opacity per confidence, zoom/pan/fit, hover card, keyboard focus traversal, list-view alternative, aggregated and expanded modes, path tracing (520 ms per hop with quote cards) |
| `SystemMap` | `events`, `compact?` | actors with `BrandMark`s, edges, pulses per event (B.C2a), captions per actor, compact strip and full-screen variants |
| `SourceCard` | `source`, `connection`, `run` | Connect screen card per PROMPT 8.8 B |
| `CountTicker` | `value` | tabular mono digits, rolls on change |
| `Skeleton*` | per layout | matches real layout dimensions |
| `Toast` system | `kind`, `title`, `body`, `action?`, `delivery?` | stack of three, persistence rules from PROMPT 8.7 |
| `CommandPalette` | — | Cmd/Ctrl+K, fuzzy search over requests, nodes, screens, actions |
| `EmptyState`, `ErrorState`, `PartialState`, `OfflineBanner`, `ReconnectingBanner` | `title`, `body`, `action?` | copy per voice rules |
| `BrandMark` | `name`, `size`, `tone` | real logos |
| `FooterStatusBar` | — | per PROMPT 8.7 |
| `ReplayControls` | `playing`, `speed`, `position` | play, pause, step, speed 0.5×–4×, scrubber |

**Acceptance criteria**
- C-AC-8: Every component above has unit tests for each listed state (rendering, accessible name and role, keyboard interaction where interactive).
- C-AC-9: `TimelineItem` renders every event type in B.C2 with a non-empty sentence and a glyph (table-driven test over all types).
- C-AC-10: `StateChip` and Slack blocks use the same state names and colours from one shared map (test compares `lib/states.ts` with the backend's exported map via generated types or a shared JSON).
- C-AC-11: `ApprovalCard` shows the stale state when `target` differs from `current`, and surfaces a 409 reason from a mocked mutation.
- C-AC-12: `GraphCanvas` holds 60 fps (frame time ≤ 16.7 ms p95) with 300 nodes and 600 links during pan and zoom on the Playwright laptop profile; layout runs off the main thread.
- C-AC-13: `GraphCanvas` path tracing highlights exactly the nodes and links of the given path, shows a quote card per hop that has a quote, and completes within `hops × 520 ms + 300 ms` (reduced motion: immediate).
- C-AC-14: `SystemMap` animates the right edge and caption for each event type in B.C2a (table-driven test with mocked events) and shows only real events.

Tests: `frontend/tests/unit/components/*.test.tsx`, `frontend/tests/e2e/canvas-performance.spec.ts`, `frontend/tests/e2e/system-map.spec.ts`.

---

## C3. App structure and routes (Next.js App Router)

```
frontend/app/                                   (Next.js App Router root)
  (public)/page.tsx                    /                     landing
  (public)/opengraph-image.tsx         Open Graph image for the landing page
  (public)/replay/[id]/page.tsx        /replay/[id]          public replay (only when the workspace allows public replays)
  (public)/replay/[id]/opengraph-image.tsx
  app/signin/page.tsx                  /app/signin
  app/layout.tsx                       shell for /app/*: rail, footer, palette, toasts, SSE workspace stream
  app/page.tsx                         /app                  Home
  app/connect/page.tsx                 /app/connect
  app/requests/[id]/page.tsx           /app/requests/[id]
  app/requests/[id]/replay/page.tsx    /app/requests/[id]/replay
  app/graph/page.tsx                   /app/graph
  app/system/page.tsx                  /app/system           full-screen system map (live)
  app/inbox/page.tsx                   /app/inbox
  app/settings/page.tsx                /app/settings
  app/dev/glyphs/page.tsx              /app/dev/glyphs       (dev and test builds only)
  not-found.tsx, error.tsx, global-error.tsx
```
Paths are relative to `frontend/app/` (so `/app/signin` is the file `frontend/app/app/signin/page.tsx`).
```
- Server components for page shells and initial data where it helps first paint; client components for live and interactive parts. Initial data for Home and Request is fetched on the server with the session cookie and hydrated into TanStack Query (`HydrationBoundary`).
- Middleware redirects unauthenticated `/app/*` to `/app/signin` (except `/app/signin`).
- Heavy modules (`GraphCanvas`, `DiffViewer`, Shiki, the 3D hero, `SystemMap` full-screen) load with `next/dynamic` and Suspense fallbacks that match their layout.

**Acceptance criteria**
- C-AC-15: All routes exist and render their header (eyebrow, headline, purpose) in every state; unauthenticated access to `/app/*` redirects to sign-in.
- C-AC-16: The landing page and `/app` first-load JavaScript is under 250 KB gzipped (build report check); graph, diff and 3D code are in separate chunks.

Tests: `frontend/tests/e2e/routes.spec.ts`, `frontend/tests/unit/bundle-budget.test.ts` (reads the Next.js build manifest).

---

## C4. Data flow

- **How the browser reaches the backend (same origin, no CORS):** Next.js `rewrites` proxy `/api/*`, `/slack/*` and `/webhooks/*` to `API_INTERNAL_URL` (default `http://backend:8080` in compose, `http://127.0.0.1:8080` when running the frontend outside Docker). The browser always calls same-origin `/api/...`, so session and CSRF cookies are first-party and `SameSite=Lax` works. Server components call `API_INTERNAL_URL` directly and forward the incoming request's cookies. `NEXT_PUBLIC_API_URL` is not used for browser calls; it may be removed or kept only for the OpenAPI type generation script. The backend sends no CORS headers.
- **API client:** `lib/api.ts` generated types (openapi-typescript) plus a small fetch wrapper adding the CSRF header, JSON errors to typed `ApiError {code, message, status}`, and the `Idempotency-Key` header (UUID per user action, reused on retry).
- **Query keys:** `['requests', filters]`, `['request', id]`, `['events', id]` (array of envelopes), `['subgraph', id, mode]`, `['ingestion']`, `['connections']`, `['notifications']`, `['settings']`, `['graph-search', q]`, `['node', id]`.
- **Live updates:** `useRequestStream(id)` opens one `EventSource` (`/api/requests/{id}/events`), appends envelopes to `['events', id]` (dedupe by `seq`), applies derived updates to `['request', id]` (state, revision, build, PR), invalidates `['subgraph', id, *]` on `evidence.found`, `investigation.completed`, `writeback.done`; reconnects with exponential backoff and `Last-Event-ID`; exposes `status: live|reconnecting|offline`. `useWorkspaceStream()` (shell) updates `['requests']`, `['ingestion']`, `['notifications']` and the footer.
- **Mutations:** answers, ticket edits, approvals, feedback, cancel, connections, sync-now, settings. Optimistic update where the outcome is predictable (answer recorded, approval pending), rollback on error, toast with the server's reason on 409.
- **UI state (Zustand):** selected node, pinned highlights, canvas mode, open panels, palette open, replay position. Nothing from the server.
- **Development fixtures:** MSW handlers in `frontend/tests/fixtures/msw/` serve recorded API responses and scripted SSE streams when `NEXT_PUBLIC_ACTRON_DEV_FIXTURES=1`; a visible `DEV FIXTURES` badge is rendered by the shell.

**Acceptance criteria**
- C-AC-17: The stream hook dedupes, orders by `seq`, resumes after a dropped connection without losing events (test with a mock EventSource that drops mid-stream), and reports `reconnecting` then `live`.
- C-AC-18: Optimistic mutations roll back on 409 and show the reason; a successful server response replaces the optimistic state.
- C-AC-19: The same user action retried after a network error reuses its idempotency key.
- C-AC-20: The dev fixtures badge renders only with the flag on.

Tests: `frontend/tests/unit/stream.test.ts`, `mutations.test.ts`, `api.test.ts`, `frontend/tests/e2e/dev-fixtures.spec.ts`.

---

## C5. Screens

Each screen implements its blueprint in PROMPT 8.8 (A to G) plus the items below. Headline copy for every state is defined in the blueprint; keep its voice.

### C5.1 Landing (`/`)
Sections in order, each full-width with generous space:
1. **Hero:** eyebrow `ACTRON`; hero headline "Before an AI changes your code, it should know what your team decided."; one-line purpose "Actron reads your code, pull requests, tickets and Slack into one FalkorDB graph, checks every request against it, and builds the change with the evidence attached."; buttons "Watch a replay" (primary, accent) and "Open the app"; the 3D memory graph visual (C6) at the right or behind, with the evidence path glowing.
2. **The problem:** one sentence and a small illustration: a shared function with two callers and a forgotten decision.
3. **How it works:** the five-step journey (Ask in Slack → Evidence from the graph → You decide → Pi builds → Review the PR), each with a real screenshot captured by Playwright from the running app and a one-sentence caption; steps reveal on scroll.
4. **The graph:** a rendered view of the ontology (node types grouped by source with counts from the real workspace) and three example Cypher queries with plain-language explanations.
5. **Built with:** real logos (FalkorDB, Jev/TypeSafe, Pi, MCP, Temporal, Slack, GitHub, Linear) with one line each on what it does in Actron.
6. **Close:** "Open the app" and "Watch a replay".
Footer: tracks entered, repository link, AI-use note.

### C5.2 System view (`/app/system`)
Full-screen `SystemMap` with the live workspace stream: actors laid out left to right (Slack and the UI → Actron → FalkorDB, Jev, LLM → Pi → GitHub, Linear), captions, a running log of the last 20 events below in mono. Headline: "What Actron is doing right now." Purpose: "Every graph query, judgment and build step, as it happens."

### C5.3 Replay (`/app/requests/[id]/replay` and public `/replay/[id]`)
Plays back recorded events (B.C2) of a finished request through the same components as the Request page (timeline, canvas, system map strip, tabs), driven by `ReplayControls` instead of SSE. A caption bar above the canvas shows one plain sentence per step (from the event's timeline sentence). Headline: "Replay: <request title>." Purpose: "Watch how Actron handled this request, step by step." Public replay requires the workspace setting "allow public replays" and shows no secrets or private message text beyond what the request displayed.

### C5.4 Request page additions
- The `SystemMap` compact strip sits between the header and the three columns (collapsible, remembered per user).
- The handoff (`handoff.created`) is rendered as a distinct, wider timeline item with the `Handoff` glyph and the number of evidence items handed over.
- When the investigator is choosing tools, the header headline reads "Investigating. <n> graph queries so far." and the timeline shows each `ToolCallCard` as it starts.

**Acceptance criteria**
- C-AC-21: The landing page renders all six sections with real screenshots (files exist and were produced by the capture script), real logos and real ontology counts (from the API, with a static fallback snapshot taken at build time).
- C-AC-22: Every screen passes the five-second test checklist: eyebrow, situation headline, purpose line, one obvious main action, visible state (Playwright assertions per screen and state).
- C-AC-23: The Request page shows tool calls live as the scripted investigation runs (e2e with backend fakes): cards appear in order, the system map pulses, nodes highlight.
- C-AC-24: Replay plays all events in order, respects speed and pause, and ends in the same final view as the live page (snapshot comparison).
- C-AC-25: Public replay is unavailable when the workspace setting is off (404) and redacts as specified when on.
- C-AC-26: The System view reflects workspace events within one second of their publication.

Tests: `frontend/tests/e2e/landing.spec.ts`, `screens-five-second.spec.ts`, `request-live.spec.ts`, `replay.spec.ts`, `system-view.spec.ts`; capture script `frontend/scripts/capture-screens.ts`.

---

## C6. 3D hero and shaders

- React Three Fiber + drei; a sample of up to 3,000 nodes and 6,000 links from `GET /api/graph/sample?limit=3000` (or a build-time snapshot JSON when the API is unavailable), laid out once with a 3D force layout in a worker and cached; instanced meshes for nodes; line segments for links; one evidence path rendered with a custom shader (additive glow, animated dash offset); slow orbit (0.02 rad/s); pauses when off-screen (IntersectionObserver) or the tab is hidden; `prefers-reduced-motion`, `navigator.hardwareConcurrency <= 4`, `saveData`, or no WebGL → a static pre-rendered PNG/WebP of the same scene.
- Loaded after first paint (`next/dynamic` with `ssr: false`, triggered on idle); never blocks LCP (the LCP element is the hero headline).

**Acceptance criteria**
- C-AC-27: The hero loads after the headline paints; Lighthouse Performance on `/` stays ≥ 90 with the hero enabled.
- C-AC-28: Fallback image is used under reduced motion and when WebGL is unavailable (Playwright with WebGL disabled).
- C-AC-29: The scene pauses rendering when scrolled out of view (frame counter test).

Tests: `frontend/tests/e2e/hero.spec.ts`, Lighthouse CI (C8).

---

## C7. Accessibility

- Semantic landmarks per page; headings in order; every interactive element reachable by keyboard with a visible focus ring; no keyboard traps; skip link to main content.
- The canvas exposes a list alternative (button "List view") with the same nodes and selection, and keyboard navigation between nodes (arrow keys move focus along links; Enter opens the inspector).
- Live regions: timeline (`aria-live="polite"`), toasts (`role="status"`, errors `role="alert"`).
- Forms: labels, descriptions, error messages linked with `aria-describedby`.
- Colour is never the only signal: state chips include text; links in the canvas differ by dash style as well as opacity.

**Acceptance criteria**
- C-AC-30: axe finds zero serious or critical violations on every route in every primary state (Playwright + `@axe-core/playwright`).
- C-AC-31: A keyboard-only e2e run completes the core journey (sign in → open request → answer → approve → open PR tab) without a mouse.
- C-AC-32: The canvas list view and keyboard navigation work (e2e).

Tests: `frontend/tests/e2e/a11y.spec.ts`, `keyboard-journey.spec.ts`, `canvas-a11y.spec.ts`.

---

## C8. Performance and Lighthouse

- Targets (production build, Lighthouse CI desktop preset and a mobile run for the landing page): Performance ≥ 90, Accessibility ≥ 95, Best Practices ≥ 95, SEO ≥ 90 (landing) on `/`, `/app`, `/app/requests/<fixture id>`, `/app/connect`. Core Web Vitals: LCP < 2.5 s, CLS < 0.05, INP < 200 ms (Playwright trace on the laptop profile).
- Techniques: server-rendered shells, streaming with Suspense, `next/font`, `next/image` for screenshots (AVIF/WebP, sized), route-level code splitting, no blocking third-party scripts, caching headers for static assets, compression via Caddy.
- `scripts/test_all.sh` runs `lhci autorun` with `lighthouserc.json` assertions; scores and vitals are written to `BUILD-REPORT.md`.

**Acceptance criteria**
- C-AC-33: Lighthouse CI assertions pass on all four routes.
- C-AC-34: Measured LCP, CLS and INP meet targets on the Request page during a live scripted investigation.

Tests: `frontend/lighthouserc.json`, `frontend/tests/e2e/web-vitals.spec.ts`.

---

## C9. Slack presentation

Block Kit builders in `backend/actron/integrations/slack_blocks.py` implement PROMPT 8.9 exactly (acknowledgement, status message per state, approval confirmation, needs-you DM, build finished, failure). The state text map is shared with the UI (C-AC-10).

**Acceptance criteria**
- C-AC-35: Snapshot tests of the blocks for every state and message type; every block payload passes Slack's Block Kit size limits (50 blocks, text lengths) checked by a validator.
- C-AC-36: No emoji used as status and no exclamation marks in any Slack text (copy lint).

Tests: `backend/tests/unit/slack/test_blocks.py`, `backend/tests/unit/slack/test_copy_lint.py`.

---

## C10. Design process evidence

- `DESIGN.md` records: chosen direction (PRD 13.2), tokens (final values), type choices and reasons, spacing, motion, voice, and every change from the defaults in this spec with the Impeccable finding that motivated it.
- `DESIGN-DIRECTIONS.md` records two alternative token sets (both dark, for example "Ink dossier" with a warmer near-black and serif-forward headlines, and "Signal console" with higher contrast and a stronger accent) that can be swapped by replacing `tokens.css` values.
- `BUILD-LOG.md` records each review round (screens, screenshots taken, issues found, fixes).

**Acceptance criteria**
- C-AC-37: At least two review rounds are logged for the Request and Connect pages and one for each other screen, each listing concrete issues and fixes.
- C-AC-38: Screenshots of every screen at 1440 and 1920 exist in `frontend/tests/screenshots/` and are referenced in the README.

---

## C11. Production SaaS completeness (PRD 13.9b)

Implement every item in PRD 13.9b. Component and route additions: `OnboardingChecklist`, `NotFound` (`app/not-found.tsx`), `ErrorPage` (`app/error.tsx`, `app/global-error.tsx`), `UnsavedChangesGuard`, `TruncatedText`, `RelativeTime`, `CostBadge`, `SmallScreenNotice`, Actron brand assets in `frontend/public/actron-brand/` (`logo.svg`, `wordmark.svg`, favicons, `apple-touch-icon.png`), Open Graph routes (`app/(public)/opengraph-image.tsx`, `app/(public)/replay/[id]/opengraph-image.tsx`).

**AI-look audit (fresh eyes).** After the review loops in PROMPT 8.2, spawn a separate reviewer subagent that receives only the screenshots (1440 and 1920, every screen and main state) and this brief: "You are a principal product designer at a top SaaS company. Would you ship this? List everything that looks generic, templated or machine-generated, and everything that a careful human designer would have done differently." It also checks this list of tells: uniform card grids; gradient or glow accents; emoji or sparkle icons; vague headings ("Dashboard", "Overview", "Welcome back"); centred everything; inconsistent spacing; too many font sizes; placeholder or filler copy; generic stock illustrations; buttons that all look the same weight; badges without meaning; decorative motion; dense paragraphs; inconsistent casing; missing empty, loading or error states; misaligned icons and text baselines. Fix every finding (or record why not) and run the audit again until it returns no material findings. Record both rounds in `BUILD-LOG.md`.

**Acceptance criteria**
- C-AC-39: The onboarding checklist shows on first run, ticks each step automatically when its condition becomes true, and can be dismissed once complete.
- C-AC-40: Every route has a unique title and meta description; 404, 500 and global error pages render in the product's voice inside the shell (except the global error page).
- C-AC-41: Logo, wordmark, favicon set and Open Graph images exist; the landing page's Open Graph image renders with the real headline (fetch `/opengraph-image` in a test).
- C-AC-42: Formatting helpers (relative time with tooltip, numbers, durations, middle truncation with copy) are used everywhere (a lint test scans components for raw `toLocaleString`/`Date` rendering outside the helpers) and have unit tests.
- C-AC-43: Forms validate inline, disable submit until valid, show a loading state, and the ticket editor and settings warn before leaving with unsaved changes.
- C-AC-44: Deep links to request tabs work; scroll and tab state are restored on back navigation.
- C-AC-45: The landing page and public replay pass a 375 px layout test with no horizontal scroll and Lighthouse mobile Performance ≥ 85; app routes below 1,024 px show the small-screen notice.
- C-AC-46: The Build tab and request summary show tokens and estimated cost from the API.
- C-AC-47: "Watch a replay" appears only when a finished request exists.
- C-AC-48: The AI-look audit has been run at least twice and the final round lists no material findings; both rounds are in `BUILD-LOG.md`.

Tests: `frontend/tests/unit/format.test.ts`, `onboarding.test.tsx`, `forms.test.tsx`; `frontend/tests/e2e/meta-and-errors.spec.ts`, `og-image.spec.ts`, `navigation-state.spec.ts`, `responsive.spec.ts`, `cost.spec.ts`.

## C12. Connector forms (what the user must provide)

The Connect screen renders each source's form from definitions served by the backend (`GET /api/connectors`), so forms and validation live in one place. The field shape follows fabric's connector `ui_form` (`field_id`, `type`, `required`, `label`, `description`, `ui_component`, `info`, `is_secret`) plus Actron's `dependsOn` (field shown and filled only after the named field validates), `optionsFrom` (where a select's options come from), `default` and `placeholder`. Definitions live in `backend/actron/connectors/forms.json`; the frontend never hard-codes fields.

**Flow per source:** fill the first fields → "Check connection" calls `POST /api/connectors/{provider}/validate` (a live test call; shows what it found, for example "Repository found: BetterThanTomorrow/calva, default branch dev, 1,296 PRs") → dependent fields appear with options from `GET /api/connectors/{provider}/options?field=<id>` → "Connect" saves (secrets encrypted, shown again only as the last four characters) and starts the backfill. Every field shows its `description` under the label and its `info` as a "Where do I find this?" disclosure with exact steps.

**GitHub (repository: code and GitHub data)**
| field_id | type, component | required | label | what it is / info shown |
|---|---|---|---|---|
| `access_token` | string, password input, `is_secret` | yes | Access token | A fine-grained personal access token. Info: "GitHub → Settings → Developer settings → Fine-grained tokens. Repository access: the repository below (and the fork). Permissions: Contents read and write, Pull requests read and write, Issues read, Metadata read, Actions read, Checks read." |
| `repository` | string, text input, placeholder `owner/name` | yes | Repository | The repository your team merges into; Actron reads its code and history. Validated live. |
| `working_branch` | select, `dependsOn: repository`, `optionsFrom: branches` (default first, then most recent; protected marked) | yes | Working branch | "Actron reads and keeps this branch in memory. Choose the branch your team builds on." |
| `fork` | string, text input, `default`: same as repository | no | Push to | Where Actron pushes branches and opens pull requests. Validated for write access. |
| `upstream` | string, text input | no | Upstream (history only) | Optional original repository whose PRs and issues are read for history. |
| `history_days` | number, stepper, default 90 | no | History to read | Days of PRs, issues and reviews in the first backfill. |
| `webhook` | info panel, `dependsOn: repository` | no | Instant updates | Shows the payload URL (`<ACTRON_PUBLIC_URL>/webhooks/github`), content type `application/json`, a secret generated by Actron and stored encrypted in the connection (`GITHUB_WEBHOOK_SECRET` is only the development fallback) with a copy button, and the events to tick (push, pull requests, pull request reviews, pull request review comments, issues, issue comments). Explains that without it Actron still polls. |

**Slack**

Primary path, **Add to Slack (OAuth)**: one button, `ui_component: "oauthButton"`, label "Add to Slack", using Slack's official button style and logo. Clicking it opens Slack's consent page; after approval the user returns to Connect with the workspace name shown ("Connected to Northwind Labs as @Actron") and the fields below from `channels` onward appear. Shown only when `SLACK_CLIENT_ID` and `SLACK_CLIENT_SECRET` are configured. Errors from the callback are shown in plain words ("You cancelled the Slack approval. Try again when you're ready." / "Slack says the request expired. Start again.").

Second path, **Connect with tokens** (a form with two tokens; always available, shown side by side with "Add to Slack"; the only path when OAuth is not configured):
| field_id | type, component | required | label | what it is / info shown |
|---|---|---|---|---|
| `manifest` | info panel | — | Create the Slack app | "Create a Slack app from a manifest and paste this" with the manifest from `infra/slack/` and a copy button; links to Slack's app page. |
| `bot_token` | string, password input, `is_secret`, placeholder `xoxb-…` | yes (token path) | Bot token | Lets Actron read the chosen channels and post messages. Info: "Your app → OAuth & Permissions → Install to Workspace → Bot User OAuth Token." Validated with `auth.test` (shows the workspace and bot name). |
| `app_token` | string, password input, `is_secret`, placeholder `xapp-…` | no | App-level token (for live events without a public URL) | Needed when Actron runs without a public HTTPS URL (for example on a laptop): Slack then sends live messages, `/actron` commands and button clicks over Socket Mode. Info: "Your app → Basic Information → App-Level Tokens → Generate, scope `connections:write`; also turn on Socket Mode in the app settings." Validated by opening a Socket Mode connection (`apps.connections.open`). If empty, Actron uses HTTP events at `ACTRON_PUBLIC_URL` and the `.env` value `SLACK_APP_TOKEN` as a fallback. |

The two paths are equal options on the Slack card: "Add to Slack" (button) and "Connect with tokens" (this form, two tokens). The token path is the only one shown when OAuth is not configured.

Fields shown after either path:
| field_id | type, component | required | label | what it is / info shown |
|---|---|---|---|---|
| `channels` | multi-select, `dependsOn: bot_token`, `optionsFrom: channels` (channels the bot is a member of) | yes | Channels to read | "Invite Actron to a channel with `/invite @Actron` to see it here." |
| `requests_channel` | select, `dependsOn: channels` | no | Where people ask Actron | Default: the first selected channel. `/actron` works in any channel the bot is in. |
| `history_days` | number, stepper, default 90 | no | History to read | Days of messages in the first backfill. |

**Linear**
| field_id | type, component | required | label | what it is / info shown |
|---|---|---|---|---|
| `api_key` | string, password input, `is_secret`, placeholder `lin_api_…` | yes | API key | "Linear → Settings → Security & access → Personal API keys." |
| `team` | select, `dependsOn: api_key`, `optionsFrom: teams` | yes | Team | Team whose issues Actron reads and where it creates tickets. |
| `ticket_label` | select, `dependsOn: team`, `optionsFrom: labels`, optional "create 'actron'" | no | Label for Actron's tickets | Added to every ticket Actron creates. |
| `history_days` | number, stepper, default 90 | no | History to read | Days of issues and comments in the first backfill. |

**Slack export (optional, alternative to live Slack history)**
| field_id | type, component | required | label | what it is / info shown |
|---|---|---|---|---|
| `archive` | file upload (`.zip`, up to 200 MB) | yes | Slack export | "Workspace settings → Import/Export data → Export." Validated for structure before import. |
| `events` | file upload (`.jsonl`) | no | Later changes | Optional events applied after the import. |

**Deployment-level settings (not in the UI):** the Slack app's client id and client secret (used for both "Add to Slack" and Sign in with Slack) and signing secret stay in `.env` (the app-level token can be given in the token form or in `.env`), because they belong to the app, not to a workspace, and sign-in happens before a workspace exists. `.env` values for the per-source fields above act only as a development fallback when no connection exists; a saved connection always wins.

**Acceptance criteria**
- C-AC-49: The Connect screen renders every field in this section from `GET /api/connectors` (no hard-coded fields), with labels, descriptions, "Where do I find this?" info, placeholders and defaults.
- C-AC-50: Dependent fields appear only after their parent validates, and their options come from the options endpoint (branches, channels, teams, labels); validation results are shown in plain words.
- C-AC-51: Secret fields are password inputs, never echoed back after saving (only the last four characters), and never logged.
- C-AC-52: The GitHub webhook panel shows the payload URL, a generated secret with copy, and the event list; the Slack manifest panel copies the manifest.
- C-AC-53: With Slack OAuth configured, the Slack card shows both "Add to Slack" and "Connect with tokens" (bot token required, app-level token optional, each validated live); after a (faked) successful OAuth round trip, the card shows the workspace name and the channel picker; a cancelled or expired approval shows the plain-language error; without OAuth configured, only the token path is shown.

Tests: `frontend/tests/unit/connector-form.test.tsx`, `frontend/tests/e2e/connect-forms.spec.ts`; backend `tests/api/test_connectors_forms.py`.

## C13. In-app setup guides (Slack, GitHub, Linear)

Every source card on Connect has a "Set up step by step" button that opens a guide in a side panel (720 px wide, keyboard accessible, closable with Esc, state kept if closed and reopened). The guide is a numbered checklist; each step has a short title, one or two sentences, the exact clicks, copy buttons for every value the user must paste, deep links that open the right external page in a new tab, and a live check that turns the step green when Actron can confirm it. The guide never asks the user to paste a secret anywhere except the form fields. Copy follows the voice rules (C1.6).

**Slack guide**
1. **Create the app from Actron's manifest.** Copy button for the manifest (dev or production variant chosen automatically from whether `ACTRON_PUBLIC_URL` is HTTPS). Deep link "Open Slack app creation" to `https://api.slack.com/apps?new_app=1` (and, if Slack supports it, a prefilled manifest link `https://api.slack.com/apps?new_app=1&manifest_yaml=<url-encoded manifest>` **[VERIFY]**). Clicks: "Create New App → From an app manifest → choose your workspace → paste → Create".
2. **Install the app to your workspace.** Clicks: "Install App → Install to Workspace → Allow". Then either use "Add to Slack" on the card (OAuth) or copy the Bot User OAuth Token (`xoxb-…`) into the form. Check: `auth.test` succeeds; shows workspace and bot name.
3. **(Laptop only) Turn on Socket Mode and create the app-level token.** Clicks: "Socket Mode → Enable"; "Basic Information → App-Level Tokens → Generate token, scope `connections:write`". Paste the `xapp-…` token into the form. Check: a Socket Mode connection opens. Hidden when Actron has a public HTTPS URL.
4. **Check the permissions.** A table of every bot scope with one line on why Actron needs it (the scope list in spec B, B12a, rendered as a table with one line per scope: `app_mentions:read` hear @Actron; `channels:history`, `groups:history` read messages in channels the bot is in; `channels:read`, `groups:read` list channels for the picker; `chat:write` post and edit Actron's messages; `commands` the /actron command; `im:write` direct messages when a person must act; `reactions:read` read reactions; `team:read` workspace name; `users:read`, `users:read.email` names and emails for matching people across tools). Check: the scopes granted to the token (from Slack's `x-oauth-scopes` response header on `auth.test`) include every required scope; missing ones are listed with "Reinstall the app after adding these scopes."
5. **Invite Actron to your channels.** Copy button for `/invite @Actron`. Check: the channel list (bot membership) is not empty; the picker refreshes automatically.
6. **Try it.** Copy button for `/actron hello`. Check: Actron receives the command and replies in the channel (event observed).
- **Troubleshooting** (shown when a check fails, mapped from Slack error codes): `invalid_auth` / `not_authed` ("The token is wrong or was revoked. Copy it again from OAuth & Permissions."), `missing_scope` (lists the missing scopes and says to reinstall), `not_in_channel` ("Invite Actron with /invite @Actron."), `account_inactive`, `token_revoked`, `ratelimited` ("Slack asked us to slow down; we retry automatically."), Socket Mode failures ("Turn on Socket Mode and check the app-level token has connections:write.").

**GitHub guide**
1. **Create a fine-grained access token.** Deep link to `https://github.com/settings/personal-access-tokens/new` (prefilled with name "Actron", description and permissions if GitHub supports template parameters **[VERIFY]**). Clicks and a table of permissions with why: Contents read and write (read code, push Actron's branches to the push target), Pull requests read and write (read reviews, open PRs), Issues read, Metadata read, Actions read and Checks read (test results). Repository access: the repository and the push target.
2. **Paste the token and the repository.** Check: the repository is found; shows default branch, PR count, and whether the token can write to the push target.
3. **Choose the working branch.** Explains what it means (the branch Actron keeps in memory).
4. **(Deployed only) Add the webhook for instant updates.** Copy buttons for the payload URL and secret, the content type and the event list; deep link to the repository's "Settings → Webhooks → Add webhook". Check: GitHub's ping delivery is received and verified.
- **Troubleshooting:** 401 (token wrong or expired), 403 with "Resource not accessible" (missing permission, named), 404 (repository name or access), rate limit (shows reset time), webhook signature failures (secret mismatch).

**Linear guide**
1. **Create a personal API key.** Deep link to Linear's security settings page (`https://linear.app/settings/account/security` **[VERIFY]**). Clicks: "Personal API keys → New key → name it Actron".
2. **Paste the key.** Check: the viewer query succeeds; shows your name and organisation.
3. **Choose the team** and optionally a label for Actron's tickets. Check: the team's issues can be read; a dry-run ticket permission check passes.
- **Troubleshooting:** authentication errors, missing team access, rate limits.

**Shared rules for guides**
- Each step's check runs automatically when the related field changes, and can be re-run with "Check again".
- Progress is shown at the top ("3 of 6 done") and on the source card.
- Copy buttons confirm with a short "Copied" state; deep links show an external-link icon and open in a new tab.
- Guides are written as content files (`frontend/content/guides/slack.mdx`, `github.mdx`, `linear.mdx`) rendered with the design system, so wording can be changed without code changes.
- Step ids and check ids (added 18 Oct 2026, W10): `GET /api/connectors` serves each guide as `GuideStep[]` (`{id, title, checkId}`, from `backend/actron/connectors/forms.json`) and `GET /api/connectors/{provider}/checks` returns a check with each `checkId`. GitHub: `token`, `push_access`, `working_branch`, `webhook_ping` (plus `repository`). Slack: `app_created`, `auth_test`, `socket_mode`, `scopes`, `channels`, `command_received`. Linear: `key_created`, `viewer`, `team` (issues readable and ticket permission). The options endpoint takes no secrets in the URL; it reuses the secrets of the same user's last accepted validate call (Redis, encrypted, 15 minutes).

**Acceptance criteria**
- C-AC-54: Each source card opens its guide; every step listed above is present with its copy buttons, deep links and check.
- C-AC-55: Checks turn green on success and show the mapped troubleshooting text on each listed failure (driven by fake providers in e2e tests).
- C-AC-56: The Slack permissions step detects missing scopes from the token and lists them; the GitHub step detects a token that cannot write to the push target.
- C-AC-57: Guides are keyboard accessible, pass axe, and keep their progress when closed and reopened.

Tests: `frontend/tests/e2e/setup-guides.spec.ts`, `frontend/tests/unit/guides.test.tsx`; backend `tests/api/test_connector_checks.py`.

## Spec C coverage summary
Acceptance criteria C-AC-1 to C-AC-57. Living docs updated by this spec: `docs/frontend.md`, `docs/testing.md`, README screenshots section.
