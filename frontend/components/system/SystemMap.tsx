'use client'
import { useEffect, useMemo, useRef, useState } from 'react'
import type { EventEnvelope } from '@/lib/api/types'
import { ACTOR_LABEL, systemStep, type ActorId, type SystemContext, type SystemStep } from '@/lib/events'
import { DUR, easeEmphasized } from '@/lib/motion'
import { BrandMark, type BrandName } from '../brand/BrandMark'
import { Glyph } from '../glyphs/Glyph'
import { cx } from '../ui/cx'

type Point = { x: number; y: number }

const W = 1000

const LAYOUT: Record<'compact' | 'full', { h: number; pos: Record<ActorId, Point> }> = {
  // The strip on the Request page: one row of actors, work drawn as arcs beneath them.
  compact: {
    h: 72,
    pos: {
      slack: { x: 55, y: 20 },
      ui: { x: 166, y: 20 },
      actron: { x: 277, y: 20 },
      falkordb: { x: 388, y: 20 },
      jev: { x: 499, y: 20 },
      llm: { x: 610, y: 20 },
      pi: { x: 721, y: 20 },
      github: { x: 832, y: 20 },
      linear: { x: 943, y: 20 },
    },
  },
  full: {
    h: 520,
    pos: {
      slack: { x: 80, y: 170 },
      ui: { x: 80, y: 350 },
      actron: { x: 300, y: 260 },
      jev: { x: 530, y: 90 },
      falkordb: { x: 530, y: 260 },
      llm: { x: 530, y: 430 },
      pi: { x: 740, y: 260 },
      github: { x: 925, y: 170 },
      linear: { x: 925, y: 350 },
    },
  },
}

/**
 * One drawn link per actor pair. Sources reach the graph through Actron (it runs every sync), so a sync lights
 * source–Actron and Actron–FalkorDB rather than a second line that would run alongside them.
 */
export const EDGES: [ActorId, ActorId][] = [
  ['slack', 'actron'],
  ['ui', 'actron'],
  ['actron', 'falkordb'],
  ['actron', 'jev'],
  ['actron', 'llm'],
  ['actron', 'pi'],
  ['pi', 'falkordb'],
  ['actron', 'github'],
  ['actron', 'linear'],
]

export const edgeId = (a: ActorId, b: ActorId) => [a, b].sort().join('-')

const DRAWN = new Set(EDGES.map(([a, b]) => edgeId(a, b)))

/** The drawn links a step travels: its own pair, or through Actron when that pair is not drawn. */
export function routeEdges(from: ActorId, to: ActorId): [ActorId, ActorId][] {
  if (from === to) return []
  if (DRAWN.has(edgeId(from, to)) || from === 'actron' || to === 'actron') return [[from, to]]
  return [
    [from, 'actron'],
    ['actron', to],
  ]
}

/** Extra bow for long links that would otherwise run through another actor's chip (positive bends right of a→b). */
const BOW: Record<string, number> = {
  'actron-pi': 130,
  'actron-github': -40,
  'actron-linear': 60,
}

/** The state a link shows when no live event drove it, from slower sources such as ingestion runs. */
export type EdgeState = 'used' | 'active'

const BRAND: Record<ActorId, BrandName> = {
  slack: 'slack',
  ui: 'actron',
  actron: 'actron',
  falkordb: 'falkordb',
  jev: 'typesafe',
  llm: 'llm',
  pi: 'pi',
  github: 'github',
  linear: 'linear',
}

/** What each actor does, one line under its name on the full map. */
export const ACTOR_ROLE: Record<ActorId, string> = {
  slack: 'where people ask',
  ui: 'this app',
  actron: 'orchestrator',
  falkordb: 'the graph',
  jev: 'yes/no judgments',
  llm: 'writing',
  pi: 'coding agent',
  github: 'code (git) and pull requests',
  linear: 'tickets',
}

/** Compact strip: arcs leave the chip's lower edge and bow down by distance. */
function arc(a: Point, b: Point): { a: Point; c: Point; b: Point } {
  const y = a.y + 14
  const depth = Math.min(34, 10 + Math.abs(b.x - a.x) * 0.045)
  return { a: { x: a.x, y }, c: { x: (a.x + b.x) / 2, y: y + depth }, b: { x: b.x, y } }
}

function control(a: Point, b: Point, override?: number): Point {
  // A gentle bow so parallel edges stay readable.
  const mx = (a.x + b.x) / 2
  const my = (a.y + b.y) / 2
  const dx = b.x - a.x
  const dy = b.y - a.y
  const len = Math.hypot(dx, dy) || 1
  const bow = override ?? Math.min(24, len * 0.08)
  return { x: mx - (dy / len) * bow, y: my + (dx / len) * bow }
}

/** The full map's curve for a link, the same shape whichever way a pulse travels it. */
function curve(pos: Record<ActorId, Point>, from: ActorId, to: ActorId): { a: Point; c: Point; b: Point } {
  const canonical = EDGES.find(([x, y]) => (x === from && y === to) || (x === to && y === from)) ?? [from, to]
  const [x, y] = canonical
  const c = control(pos[x], pos[y], BOW[edgeId(x, y)])
  // A quadratic curve is the same shape in both directions once its control point is fixed by the canonical pair.
  return { a: pos[from], c, b: pos[to] }
}

function pointAt(a: Point, c: Point, b: Point, t: number): Point {
  const u = 1 - t
  return { x: u * u * a.x + 2 * u * t * c.x + t * t * b.x, y: u * u * a.y + 2 * u * t * c.y + t * t * b.y }
}

interface Pulse {
  key: string
  from: ActorId
  to: ActorId
  start: number
}

export interface SystemMapState {
  captions: Partial<Record<ActorId, string>>
  active: { actor: ActorId; at: number } | null
  edges: Record<string, number>
  steps: { step: SystemStep; event: EventEnvelope }[]
}

/** Pure: what the map shows after a list of events (used by the component and by tests, C-AC-14). */
export function reduceSystemMap(events: readonly EventEnvelope[]): SystemMapState {
  const ctx: SystemContext = { callers: new Map() }
  const state: SystemMapState = { captions: {}, active: null, edges: {}, steps: [] }
  for (const event of events) {
    if (event.type === 'tool.called') {
      const p = event.payload as Record<string, unknown>
      ctx.callers?.set(String(p.callId), { by: p.by === 'pi' ? 'pi' : 'investigator', tool: String(p.tool ?? ''), args: p.args })
    }
    const step = systemStep(event, ctx)
    if (!step) continue
    state.captions[step.active] = step.caption
    state.active = { actor: step.active, at: Date.parse(event.at) || 0 }
    for (const [a, b] of routeEdges(step.from, step.to)) state.edges[edgeId(a, b)] = Date.parse(event.at) || 0
    state.steps.push({ step, event })
  }
  return state
}

function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true
}

export interface SystemMapProps {
  events: readonly EventEnvelope[]
  compact?: boolean
  className?: string
  /** Animate pulses for events that arrive after mount (live and replay). */
  animate?: boolean
  title?: string
  /** Nothing is running now: the last step is history, so no actor or link is drawn as active. */
  idle?: boolean
  /** Actors that cannot work now, with the plain reason ("not connected", "no key"). */
  unavailable?: Partial<Record<ActorId, string>>
  /** Link states from slower sources than events, such as a sync that finished minutes ago. */
  edgeStates?: Record<string, EdgeState>
}

/**
 * The live system map (PROMPT 8.8a item 1): actors with their real logos, edges between them, a pulse along the
 * edge for each event and a caption per actor. It reflects real events only: with no events it is at rest.
 */
export function SystemMap({ events, compact = false, className, animate = true, idle = false, unavailable = {}, edgeStates = {} }: SystemMapProps) {
  const layout = LAYOUT[compact ? 'compact' : 'full']
  const state = useMemo(() => reduceSystemMap(events), [events])
  const [pulses, setPulses] = useState<Pulse[]>([])
  const [frameTime, setFrameTime] = useState(0)
  const seen = useRef<Set<string>>(new Set())
  const mounted = useRef(false)
  const lastStep = state.steps[state.steps.length - 1]

  // New steps after mount become pulses; history on first render does not replay.
  useEffect(() => {
    const keys = state.steps.map((s) => `${s.event.requestId ?? 'ws'}:${s.event.seq ?? s.event.id}`)
    if (!mounted.current) {
      keys.forEach((k) => seen.current.add(k))
      mounted.current = true
      return
    }
    const fresh: Pulse[] = []
    state.steps.forEach((s, i) => {
      const key = keys[i] as string
      if (seen.current.has(key)) return
      seen.current.add(key)
      if (!animate) return
      // A routed step pulses along each drawn link in turn.
      routeEdges(s.step.from, s.step.to).forEach(([from, to], leg) => {
        fresh.push({ key: `${key}:${leg}`, from, to, start: performance.now() + fresh.length * 120 + leg * DUR[4] })
      })
    })
    if (fresh.length) setPulses((p) => [...p.slice(-12), ...fresh])
  }, [state.steps, animate])

  // Drive pulses with rAF; stop when none remain.
  useEffect(() => {
    if (pulses.length === 0) return
    if (prefersReducedMotion()) {
      const t = setTimeout(() => setPulses([]), DUR[3])
      return () => clearTimeout(t)
    }
    let raf = 0
    const loop = () => {
      const now = performance.now()
      const alive = pulses.filter((p) => now - p.start < DUR[4] * 1.4)
      if (alive.length !== pulses.length) setPulses(alive)
      else setFrameTime(now)
      if (alive.length) raf = requestAnimationFrame(loop)
    }
    raf = requestAnimationFrame(loop)
    return () => cancelAnimationFrame(raf)
  }, [pulses])

  const now = frameTime
  const reduced = prefersReducedMotion()
  const current = idle ? undefined : lastStep
  const activeActor = current?.step.active ?? null
  const activeEdges = new Set(current ? routeEdges(current.step.from, current.step.to).map(([a, b]) => edgeId(a, b)) : [])

  return (
    <div
      data-testid="system-map"
      data-compact={compact ? 'true' : 'false'}
      className={cx('relative w-full', className)}
      style={{ aspectRatio: `${W} / ${layout.h}` }}
    >
      <svg viewBox={`0 0 ${W} ${layout.h}`} className="absolute inset-0 size-full" aria-hidden>
        {EDGES.map(([a, b]) => {
          const id = edgeId(a, b)
          // When two sources describe one link, the strongest state wins: active, then used, then at rest.
          const isActive = activeEdges.has(id) || edgeStates[id] === 'active'
          const used = id in state.edges || edgeStates[id] === 'used'
          const off = !used && !isActive && Boolean(unavailable[a] || unavailable[b])
          const geo = compact ? arc(layout.pos[a], layout.pos[b]) : curve(layout.pos, a, b)
          const pa = geo.a
          const pb = geo.b
          const c = geo.c
          // The strip draws only links that real events used; the full map also shows the possible ones.
          if (compact && !used && !isActive) return null
          return (
            <path
              key={id}
              data-edge={id}
              data-active={isActive ? 'true' : 'false'}
              data-off={off ? 'true' : undefined}
              d={`M${pa.x} ${pa.y} Q${c.x} ${c.y} ${pb.x} ${pb.y}`}
              fill="none"
              // Possible links dashed, links real events used solid and brighter, links to an actor that cannot
              // work now faint and dotted.
              stroke={isActive ? 'var(--state-running)' : used ? 'var(--graph-link-focus)' : 'var(--graph-link)'}
              strokeWidth={isActive ? 2 : used ? 1.25 : 1}
              strokeDasharray={used || isActive ? undefined : off ? '1 6' : '6 4'}
              strokeLinecap={off ? 'round' : undefined}
              opacity={isActive ? 1 : used ? 0.85 : off ? 0.3 : 1}
              style={{ transition: `stroke var(--dur-2) var(--ease-standard), opacity var(--dur-2) var(--ease-standard)` }}
              vectorEffect="non-scaling-stroke"
            />
          )
        })}
        {!reduced
          ? pulses.map((p) => {
              const geo = compact ? arc(layout.pos[p.from], layout.pos[p.to]) : curve(layout.pos, p.from, p.to)
              const t = Math.max(0, Math.min(1, (now - p.start) / DUR[4]))
              if (now < p.start) return null
              const pt = pointAt(geo.a, geo.c, geo.b, easeEmphasized(t))
              return <circle key={p.key} data-pulse={edgeId(p.from, p.to)} cx={pt.x} cy={pt.y} r={compact ? 4 : 5} fill="var(--state-running)" opacity={1 - Math.max(0, t - 0.85) * 6} />
            })
          : null}
      </svg>
      {(Object.keys(layout.pos) as ActorId[]).map((actor) => {
        const p = layout.pos[actor]
        const caption = state.captions[actor]
        const isActive = actor === activeActor
        const offReason = unavailable[actor]
        return (
          <div
            key={actor}
            data-actor={actor}
            data-active={isActive ? 'true' : 'false'}
            data-off={offReason ? 'true' : undefined}
            // Only the chip sits on the actor's point, so links meet its centre; role and caption hang below it.
            className="absolute flex -translate-x-1/2 -translate-y-1/2 justify-center"
            style={{ left: `${(p.x / W) * 100}%`, top: `${(p.y / layout.h) * 100}%`, width: compact ? '11%' : undefined }}
          >
            <span
              className={cx(
                'flex items-center gap-2 rounded-md border bg-ink-0 transition-[border-color,color] duration-2',
                compact ? 'h-7 px-2' : 'h-10 px-3',
                isActive
                  ? 'border-state-running text-fg-1'
                  : offReason
                    ? 'border-dashed border-line-2 text-fg-3'
                    : caption
                      ? 'border-line-2 text-fg-1'
                      : 'border-line-2 text-fg-2',
              )}
            >
              {actor === 'ui' ? (
                <Glyph name="Home" size={compact ? 14 : 18} />
              ) : actor === 'llm' ? (
                // No vendor mark for "the writing model": a neutral glyph rather than a boxed placeholder.
                <Glyph name="Ticket" size={compact ? 14 : 18} />
              ) : (
                <BrandMark name={BRAND[actor]} size={compact ? 14 : 18} decorative />
              )}
              <span className={cx('whitespace-nowrap font-medium', compact ? 'text-caption' : 'text-small')}>{ACTOR_LABEL[actor]}</span>
            </span>
            {!compact ? (
              // Edge actors align their text toward the map's centre so it never crosses the card border.
              <div
                className={cx(
                  'absolute top-full mt-1 flex w-max max-w-56 flex-col',
                  p.x < W * 0.2 ? 'left-0 items-start text-left' : p.x > W * 0.8 ? 'right-0 items-end text-right' : 'left-1/2 -translate-x-1/2 items-center text-center',
                )}
              >
                {/* The page colour behind the text keeps links that cross it from striking it through. */}
                <span className="whitespace-nowrap rounded-sm bg-ink-0 px-1 text-caption text-fg-3">
                  {ACTOR_ROLE[actor]}
                  {offReason ? ` · ${offReason}` : ''}
                </span>
                {caption ? (
                  <span
                    data-testid={`caption-${actor}`}
                    className={cx('mt-0.5 line-clamp-2 max-w-full break-words rounded-sm bg-ink-0 px-1 text-caption', isActive ? 'text-fg-1' : 'text-fg-2')}
                    title={caption}
                  >
                    {caption}
                  </span>
                ) : null}
              </div>
            ) : null}
          </div>
        )
      })}
      {compact ? (
        <p
          className="absolute bottom-0 left-0 right-0 truncate text-caption text-fg-3"
          data-testid={lastStep ? `caption-${lastStep.step.active}` : undefined}
          title={lastStep ? `${ACTOR_LABEL[lastStep.step.active]} · ${lastStep.step.caption}` : undefined}
        >
          {lastStep ? (
            <>
              <span className="font-medium text-fg-2">{ACTOR_LABEL[lastStep.step.active]}</span>
              <span aria-hidden> · </span>
              <span className="text-fg-1">{lastStep.step.caption}</span>
            </>
          ) : (
            'Waiting for activity.'
          )}
        </p>
      ) : null}
      <p className="sr-only" aria-live="polite">
        {lastStep ? `${ACTOR_LABEL[lastStep.step.active]}: ${lastStep.step.caption}` : 'No activity yet.'}
      </p>
    </div>
  )
}
