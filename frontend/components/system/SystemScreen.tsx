'use client'
import Link from 'next/link'
import dynamic from 'next/dynamic'
import { useQuery } from '@tanstack/react-query'
import type { EventEnvelope, RequestSummary, Run, Settings } from '@/lib/api/types'
import { useIngestion, useRequests, useSettings, useWorkspaceEvents } from '@/lib/hooks/queries'
import { useNow } from '@/lib/hooks/useNow'
import { endpoints } from '@/lib/api/endpoints'
import { qk } from '@/lib/query-keys'
import { ACTOR_LABEL, eventSentence, noStop, sourceName, systemStep, type ActorId } from '@/lib/events'
import { exactTime, relativeTime, shortRequestId } from '@/lib/format'
import { ScreenHeader } from '../core/ScreenHeader'
import { PanelLabelTitle } from '../core/PanelLabelTitle'
import { PageFrame } from '../shell/PageFrame'
import { SkeletonCanvas } from '../states/Skeleton'

const SystemMap = dynamic(() => import('./SystemMap').then((m) => m.SystemMap), { ssr: false, loading: () => <SkeletonCanvas /> })

/** An event this recent still counts as "now". */
export const ACTIVE_WINDOW_MS = 2 * 60_000

const RUN_STATUS: Record<Run['status'], string> = {
  running: 'running',
  done: 'finished',
  partial: 'finished partly',
  failed: 'failed',
}

export function runText(run: Run): string {
  const name = run.source === 'code' ? 'Code' : sourceName(run.source)
  return `${name} ${run.mode === 'incremental' ? 'sync' : 'backfill'} ${RUN_STATUS[run.status]}`
}

export interface Activity {
  key: string
  text: string
  at: string
  requestId?: string | null
  /** Shorter text for the log row, where the request id is shown as a link. */
  logText?: string
}

/** Recent things that happened, newest first, from live events, ingestion runs and request summaries. */
export function recentActivity(events: readonly EventEnvelope[], runs: readonly Run[], requests: readonly RequestSummary[], limit = 10): Activity[] {
  const items: Activity[] = []
  for (const e of events) items.push({ key: `e${e.id}`, text: noStop(eventSentence(e)), at: e.at, requestId: e.requestId })
  for (const run of runs) items.push({ key: `r${run.id}`, text: runText(run), at: run.finishedAt ?? run.startedAt })
  for (const r of requests) {
    if (r.lastEvent) {
      // The server writes "Now Needs attention."; state names read in lower case mid-sentence.
      const sentence = noStop(r.lastEvent.sentence).replace(/^Now (.+)$/, (_m, state: string) => `Now ${state.toLowerCase()}`)
      items.push({ key: `q${r.id}`, text: `Request ${shortRequestId(r.id)}: ${sentence.toLowerCase()}`, logText: sentence, at: r.lastEvent.at, requestId: r.id })
    }
  }
  return items
    .filter((c) => !Number.isNaN(Date.parse(c.at)))
    .sort((a, b) => Date.parse(b.at) - Date.parse(a.at))
    .slice(0, limit)
}

export interface ActivityRow extends Activity {
  /** How many identical entries in a row this row stands for; `at` is the newest, `firstAt` the oldest. */
  count: number
  firstAt: string
}

/** Folds identical consecutive entries (a routine sync every 15 minutes) into one row with a count. */
export function collapseActivity(items: readonly Activity[]): ActivityRow[] {
  const rows: ActivityRow[] = []
  for (const a of items) {
    const prev = rows[rows.length - 1]
    if (prev && (prev.logText ?? prev.text) === (a.logText ?? a.text) && prev.requestId === a.requestId) {
      prev.count += 1
      prev.firstAt = a.at
    } else {
      rows.push({ ...a, count: 1, firstAt: a.at })
    }
  }
  return rows
}

/** The newest thing that happened. */
export function lastActivity(events: readonly EventEnvelope[], runs: readonly Run[], requests: readonly RequestSummary[]): Activity | null {
  return recentActivity(events, runs, requests, 1)[0] ?? null
}

/** One plain sentence: what runs now, or that nothing does and what happened last. */
export function nowLine({
  events,
  runs,
  requests,
  runningRequests,
  now,
}: {
  events: readonly EventEnvelope[]
  runs: readonly Run[]
  requests: readonly RequestSummary[]
  runningRequests: number
  now: number
}): { idle: boolean; text: string } {
  const lastEvent = events[events.length - 1]
  const step = lastEvent ? systemStep(lastEvent) : null
  if (lastEvent && step && now - Date.parse(lastEvent.at) < ACTIVE_WINDOW_MS) {
    return { idle: false, text: `Running now: ${ACTOR_LABEL[step.active]} · ${noStop(step.caption)}.` }
  }
  const running = runs.find((r) => r.status === 'running')
  if (running) return { idle: false, text: `Running now: ${runText(running).replace(/ running$/, '')}, started ${relativeTime(Math.min(Date.parse(running.startedAt), now), now)}.` }
  if (runningRequests > 0) {
    return { idle: false, text: `${runningRequests} ${runningRequests === 1 ? 'request is' : 'requests are'} being worked on. Steps appear here as they happen.` }
  }
  const last = lastActivity(events, runs, requests)
  const capital = (s: string) => s.charAt(0).toUpperCase() + s.slice(1)
  return {
    idle: true,
    text: last ? `Nothing is running right now. Last activity ${relativeTime(Math.min(Date.parse(last.at), now), now)}: ${capital(last.text)}.` : 'Nothing is running right now, and nothing has run yet.',
  }
}

/**
 * Actors that cannot work now and why, from the connected sources and the model settings. `null` inputs (still
 * loading) mark nothing, so the map never flashes everything as off.
 */
/** A sync this recent still marks its links as used. */
export const RECENT_RUN_MS = 15 * 60_000

/** Same id as SystemMap's edgeId; kept local so this screen does not pull the map into its first chunk. */
const edgeId = (a: ActorId, b: ActorId) => [a, b].sort().join('-')

const RUN_ACTOR: Record<string, ActorId> = { code: 'github', github: 'github', slack: 'slack', slack_export: 'slack', linear: 'linear' }

/**
 * Link states from ingestion runs, which the live stream does not replay: a running sync makes its source–Actron
 * and Actron–FalkorDB links active; one that finished in the last 15 minutes makes them used.
 */
export function runEdgeStates(runs: readonly Run[], now: number): Record<string, 'used' | 'active'> {
  const states: Record<string, 'used' | 'active'> = {}
  const mark = (id: string, s: 'used' | 'active') => {
    if (states[id] !== 'active') states[id] = s
  }
  for (const run of runs) {
    const source = RUN_ACTOR[run.source]
    if (!source) continue
    const state = run.status === 'running' ? 'active' : run.finishedAt && now - Date.parse(run.finishedAt) < RECENT_RUN_MS ? 'used' : null
    if (!state) continue
    mark(edgeId(source, 'actron'), state)
    mark(edgeId('actron', 'falkordb'), state)
  }
  return states
}

export function unavailableActors(connected: readonly string[] | null, settings: Pick<Settings, 'jobs' | 'models'> | null): Partial<Record<ActorId, string>> {
  const off: Partial<Record<ActorId, string>> = {}
  if (connected) {
    if (!connected.some((p) => p === 'slack' || p === 'slack_export')) off.slack = 'not connected'
    if (!connected.includes('linear')) off.linear = 'not connected'
    if (!connected.some((p) => p === 'github' || p === 'code')) off.github = 'not connected'
  }
  if (settings) {
    if (!settings.jobs.some((j) => j.provider === 'jev' && j.status === 'live')) off.jev = 'no key'
    if (!settings.models.writing && !settings.models.agent) off.llm = 'no key'
    if (!settings.models.coding) off.pi = 'no key'
  }
  return off
}

function LegendLine({ stroke, dash, faint = false, label }: { stroke: string; dash?: string; faint?: boolean; label: string }) {
  return (
    <li className="inline-flex items-center gap-2">
      <svg aria-hidden viewBox="0 0 24 4" className="h-1 w-6">
        <line x1="0" y1="2" x2="24" y2="2" stroke={stroke} strokeWidth="2" strokeDasharray={dash} strokeLinecap={faint ? 'round' : undefined} opacity={faint ? 0.4 : 1} />
      </svg>
      {label}
    </li>
  )
}

/** Full-screen system map with the live workspace stream and the last 20 events (spec C, C5.2). */
export function SystemScreen() {
  const events = useWorkspaceEvents().data ?? []
  const runs = useQuery({ queryKey: qk.ingestionRuns(), queryFn: () => endpoints.ingestionRuns(undefined, 20), refetchInterval: 60_000 })
  const requests = useRequests(undefined, 20)
  const ingestion = useIngestion()
  const settings = useSettings()
  const now = useNow(30_000)
  const runList = runs.data?.runs ?? []
  const requestList = requests.data?.requests ?? []
  const recent = collapseActivity(recentActivity(events, runList, requestList, 60)).slice(0, 10)
  const line = nowLine({ events, runs: runList, requests: requestList, runningRequests: requests.data?.counts.running ?? 0, now })
  const unavailable = unavailableActors(
    ingestion.data?.sources.filter((s) => s.state !== 'NOT CONNECTED').map((s) => s.provider) ?? null,
    settings.data?.settings ?? null,
  )
  return (
    <PageFrame>
      {/* The stream state lives in the footer; the header does not repeat it. */}
      <ScreenHeader
        eyebrow="System"
        headline="What Actron is doing right now."
        purpose="Which part of Actron is working, on what, and what happened recently."
      />
      <div className="grid grid-cols-1 gap-gutter lg:grid-cols-12">
        <section aria-label="System map" className="flex flex-col gap-4 rounded-lg border border-line-1 p-6 lg:col-span-8">
          <p className="text-small text-fg-1" aria-live="polite" data-testid="system-now" data-idle={line.idle ? 'true' : 'false'} suppressHydrationWarning>
            {line.text}
          </p>
          {/* Room below the map for the role and caption under the bottom actor. */}
          <SystemMap events={events} idle={line.idle} unavailable={unavailable} edgeStates={runEdgeStates(runList, now)} className="mb-10" />
          <ul aria-label="Map legend" className="flex flex-wrap items-center gap-x-5 gap-y-1 text-caption text-fg-3">
            <LegendLine stroke="var(--graph-link)" dash="6 4" label="Available link" />
            <LegendLine stroke="var(--graph-link-focus)" label="Used recently" />
            <LegendLine stroke="var(--state-running)" label="Active now" />
            <LegendLine stroke="var(--graph-link)" dash="1 6" faint label="Not connected or no key" />
          </ul>
        </section>
        <section aria-label="Recent activity" className="flex min-w-0 flex-col gap-3 lg:col-span-4">
          <PanelLabelTitle label="Log" title="Recent activity" />
          <ol className="flex flex-col border-t border-line-1" aria-live="polite" data-testid="system-log">
            {recent.length === 0 ? <li className="py-4 text-small text-fg-3">Nothing has happened yet.</li> : null}
            {recent.map((a) => (
              <li key={a.key} className="flex items-baseline gap-3 border-b border-line-1 py-2">
                {/* Entries span hours or days, so the time is relative; the exact time is on hover. */}
                <time dateTime={a.at} title={exactTime(a.at)} className="w-20 shrink-0 whitespace-nowrap text-caption text-fg-3 tabular" suppressHydrationWarning>
                  {relativeTime(Math.min(Date.parse(a.at), now), now)}
                </time>
                <span className="min-w-0 flex-1 text-small text-fg-1">
                  {a.requestId ? (
                    <>
                      <Link href={`/app/requests/${a.requestId}`} className="font-mono text-caption text-fg-2 underline decoration-line-2 hover:text-fg-1">
                        {shortRequestId(a.requestId)}
                      </Link>
                      <span aria-hidden className="text-fg-3"> · </span>
                    </>
                  ) : null}
                  {a.logText ?? a.text}
                  {a.count > 1 ? (
                    <span className="text-fg-3" title={`From ${exactTime(a.firstAt)} to ${exactTime(a.at)}`}>
                      {' '}
                      · {a.count} times
                    </span>
                  ) : null}
                </span>
              </li>
            ))}
          </ol>
        </section>
      </div>
    </PageFrame>
  )
}
