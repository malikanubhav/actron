'use client'
import { useEffect, useState } from 'react'
import type { IngestionStatus, Me, Settings } from '@/lib/api/types'
import { useIngestion, useMe, useSettings } from '@/lib/hooks/queries'
import { useUi } from '@/lib/store'
import { exactTime, relativeTimeShort, formatUsd } from '@/lib/format'
import { stateStyle, type Tone } from '@/lib/states'
import { sourceName } from '@/lib/events'
import type { StreamStatus } from '@/lib/stream/connection'
import { DevFixturesBadge } from './DevFixturesBadge'
import { cx } from '../ui/cx'

const dot: Record<Tone, string> = {
  running: 'bg-state-running',
  ok: 'bg-state-ok',
  conflict: 'bg-state-conflict',
  possible: 'bg-state-possible',
  idle: 'bg-state-idle',
  needs_you: 'bg-accent',
}

/** "14M AGO" can read as 14 million: spell minutes as MIN. */
function ago(value: string, now: number): string {
  return relativeTimeShort(value, now).replace(/^(\d+)M AGO$/, '$1 MIN AGO')
}

export function sourceLabel(source: IngestionStatus['sources'][number], now: number): string {
  const name = source.provider === 'slack_export' ? 'SLACK EXPORT' : source.provider === 'code' ? 'CODE' : sourceName(source.provider).toUpperCase()
  switch (source.state) {
    case 'UP TO DATE':
      return `${name} · SYNCED ${source.lastSyncedAt ? ago(source.lastSyncedAt, now) : 'NOW'}`
    case 'NOT CONNECTED':
      return `${name} · NOT CONNECTED`
    default:
      return `${name} · ${source.state}`
  }
}

export function modelStatus(settings: Settings | undefined): { text: string; tone: Tone } {
  if (!settings) return { text: 'MODELS · UNKNOWN', tone: 'idle' }
  const jev = settings.jobs.filter((j) => j.provider === 'jev')
  if (jev.some((j) => j.status === 'live')) return { text: 'JEV · LIVE', tone: 'ok' }
  // No Jev key: judgments fall back to fixed rules. Say that plainly rather than an internal word.
  return { text: 'JEV · NO KEY', tone: 'possible' }
}

export function streamText(status: StreamStatus): { text: string; tone: Tone } {
  switch (status) {
    case 'live':
      return { text: 'LIVE', tone: 'ok' }
    case 'reconnecting':
    case 'connecting':
      return { text: 'RECONNECTING', tone: 'possible' }
    case 'offline':
      return { text: 'OFFLINE', tone: 'conflict' }
    default:
      return { text: 'CLOSED', tone: 'idle' }
  }
}

function Item({ tone, children, title }: { tone?: Tone; children: React.ReactNode; title?: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap" title={title}>
      {tone ? <span aria-hidden className={cx('size-1.5 rounded-full', dot[tone])} /> : null}
      {children}
    </span>
  )
}

/** 32-px mono status bar (PROMPT 8.7). */
export function FooterStatusBar() {
  const me = useMe()
  const ingestion = useIngestion()
  const settings = useSettings()
  const stream = useUi((s) => s.workspaceStream)
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 30_000)
    return () => clearInterval(t)
  }, [])
  const sources = ingestion.data?.sources ?? []
  const connected = sources.filter((s) => s.state !== 'NOT CONNECTED').length
  const model = modelStatus(settings.data?.settings)
  const live = streamText(stream)
  const budget = settings.data?.settings.budget
  const budgetReached = budget ? budget.spentTodayUsd >= budget.capUsd : false
  const env = (me.data as Me | undefined)?.env ?? 'dev'

  return (
    <footer
      aria-label="Status"
      className="sticky bottom-0 z-30 flex h-status shrink-0 items-center gap-5 overflow-hidden border-t border-line-1 bg-ink-0 px-4 font-mono text-eyebrow uppercase text-fg-3"
      data-testid="footer-status"
    >
      {/* Low-priority items on the left clip first; the stream, environment and badge on the right never do. */}
      <div className="flex min-w-0 flex-1 items-center gap-5 overflow-hidden">
      {sources.length === 0 && ingestion.isError ? <Item tone="conflict">INGESTION · UNAVAILABLE</Item> : null}
      {sources.map((s) => (
        <Item
          key={s.provider}
          tone={stateStyle(s.state).tone}
          title={[s.reason, s.lastSyncedAt ? `Last synced ${exactTime(s.lastSyncedAt)}` : null].filter(Boolean).join('. ') || undefined}
        >
          <span suppressHydrationWarning>{sourceLabel(s, now)}</span>
        </Item>
      ))}
      {/* The status lists connected sources only, so the footer counts those and does not imply setup is complete. */}
      <Item>{ingestion.isError && sources.length === 0 ? 'SOURCES · UNKNOWN' : `${connected} ${connected === 1 ? 'SOURCE' : 'SOURCES'} CONNECTED`}</Item>
      <Item tone={model.tone} title={model.tone === 'possible' ? 'No Jev key is set. Judgments use fixed rules until one is added in Settings.' : undefined}>
        {model.text}
      </Item>
      {budgetReached && budget ? (
        <Item tone="possible">
          DAILY BUDGET REACHED · {formatUsd(budget.spentTodayUsd)} OF {formatUsd(budget.capUsd)}
        </Item>
      ) : null}
      </div>
      <div className="flex shrink-0 items-center gap-5">
      <Item tone={live.tone}>
        <span data-testid="stream-status">STREAM · {live.text}</span>
      </Item>
      <Item>{env.toUpperCase()}</Item>
      <DevFixturesBadge inline />
      </div>
    </footer>
  )
}
