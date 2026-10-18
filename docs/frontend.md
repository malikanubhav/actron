# Frontend

The web UI in `frontend/`: Next.js 16 (App Router), React 19, TypeScript strict, TanStack Query v5, Zustand for UI-only state, Tailwind over CSS-variable tokens. The design record (tokens, type, motion, every change from the spec defaults and why) is `DESIGN.md`; two alternative token sets are in `DESIGN-DIRECTIONS.md`; how to run, build and test is in `frontend/README.md`.

## What each screen is for

| Route | Purpose | Main action | Where |
|---|---|---|---|
| `/` | tell the story in one scroll: problem, product, five-step journey, graph model, stack | Watch a replay / Open the app | `app/(public)/page.tsx`, `components/landing`, `components/hero` |
| `/app/signin` | start a session with Slack identity (dev login in dev) | Sign in with Slack | `app/app/signin` |
| `/app` | what needs you, what is running, what is done | ask Actron | `components/home` |
| `/app/connect` | connect sources and watch memory fill | Connect / Sync now | `components/connect` (forms rendered from `GET /api/connectors`) |
| `/app/requests/[id]` | see what Actron found, decide, approve, follow the build, review the PR | Approve / Answer | `components/request` |
| `/app/requests/[id]/replay`, `/replay/[id]` | play back a finished request's recorded events | Play | `components/replay` |
| `/app/graph` | explore memory with provenance on every link | search, expand | `components/graph` |
| `/app/system` | what Actron is doing right now (live system map) | watch | `components/system` |
| `/app/inbox` | everything waiting for you | open at the right tab | `components/inbox` |
| `/app/settings` | models per job, thresholds, approvers, budget, bot identity, working branch | Save changes | `components/settings` |

Every screen opens with a mono eyebrow, a situation headline in the display face and a one-line purpose.

## How data reaches the screen

- The browser only calls same-origin `/api/...`; `next.config.ts` rewrites `/api`, `/slack` and `/webhooks` to `API_INTERNAL_URL` (compose: `http://backend:8080`). Compression is off in Next so server-sent events are not buffered behind gzip (found when first run against the real backend).
- `lib/api.ts` adds the CSRF header from `/api/me`, one `Idempotency-Key` per user action (reused on retry) and turns error bodies into a typed `ApiError`. Types: `lib/api/types.ts` (the B.C7 contract).
- Query keys (`lib/query-keys.ts`): `requests`, `request`, `events`, `subgraph`, `ingestion`, `connections`, `notifications`, `settings`, `graph-search`, `node`.
- Live updates: `lib/stream/` opens one `EventSource` per open request, dedupes by `seq`, resumes with `Last-Event-ID`, reports `live | reconnecting | offline`, and writes into the query cache; the shell keeps one workspace stream (`/api/stream`) for Home, inbox, ingestion and the footer.
- Mutations are optimistic where the outcome is predictable and roll back with the server's 409 reason in a toast (`stale_revision`, `stale_head`, `not_an_approver`).
- State names and colours come from `lib/states.json`, which a test compares with the backend's `backend/actron/flow/states.json`, so Slack and the UI always agree.

## The graph canvas and the evidence path

`components/graph`: d3-force runs in a web worker; a Canvas 2D renderer draws nodes by type (shape) and source (colour), links by method (solid explicit, dashed inferred) and confidence (opacity). Aggregated mode groups by type when there are more than 300 nodes. "Show path" traces the evidence path hop by hop (520 ms per hop) with a typeset quote card on each hop that has a quote. "List view" shows the same nodes and selection for keyboard and screen-reader users. Canvas p95 frame time is checked in `tests/e2e/canvas-performance.spec.ts`.

## Development fixtures

`NEXT_PUBLIC_ACTRON_DEV_FIXTURES=1` makes MSW answer every API call from `tests/fixtures/` (a full recorded request lifecycle, connections, ingestion, graph) and shows a DEV FIXTURES badge on every screen. Production builds never include fixture data; with no data, screens show designed empty states.

## How the design skills were used

| Stage | Skill | What it changed |
|---|---|---|
| Direction and system | impeccable (init, shape), interface-design | the "Evidence console" direction, tokens, one-line shaping per screen (DESIGN.md) |
| Building | frontend-design, frontend-ui-engineering, vercel-react-best-practices | server shells with hydrated queries, code-split canvas, Shiki and 3D hero, no waterfalls; first-load JS under 250 KB on every non-graph route |
| States and interaction | interaction-design | skeletons matching layout, toasts with delivery status, stale approval card, reconnecting banner |
| Motion | 12-principles-of-animation | only the motions listed in DESIGN.md, token durations, reduced-motion variants |
| Polish and review | better-ui, impeccable critique and audit | the spec changes listed in DESIGN.md (contrast, core node colour, header density, system strip) |
| Fresh eyes | an independent reviewer that saw only screenshots | seven audit rounds until no material findings (BUILD-LOG.md, W7 entries) |

## Quality gates

`npm run typecheck`, `npm run lint` (zero warnings), `npm test` (Vitest, 588 tests), Playwright (fixture build: 114 tests incl. axe on 18 routes and states, keyboard-only journey, reduced motion, 375-px landing), Lighthouse CI (desktop Performance 99–100, Accessibility 100, Best Practices 96–100, SEO 100 on the landing; mobile landing Performance 94; measured against the real backend). Counts are kept current in `docs/testing.md`.
