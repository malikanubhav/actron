'use client'
import { memo, useMemo } from 'react'
import type { EventEnvelope } from '@/lib/api/types'
import { eventGlyph, eventNodeIds, eventSentence } from '@/lib/events'
import { clockTime, exactTime, shortHash, shortSha } from '@/lib/format'
import { isRequestState } from '@/lib/states'
import { Glyph } from '../glyphs/Glyph'
import { StateChip } from '../core/StateChip'
import { ToolCallCard, type ToolCall, type ToolResult } from './ToolCallCard'
import { cx } from '../ui/cx'

type Payload = Record<string, unknown>

export type TimelineRow =
  | { kind: 'event'; key: string; event: EventEnvelope }
  | { kind: 'tool'; key: string; event: EventEnvelope; call: ToolCall; result?: ToolResult; resultEvent?: EventEnvelope }

/** Pairs tool.called with tool.result by callId; results never appear as their own rows. */
export function buildTimelineRows(events: readonly EventEnvelope[]): TimelineRow[] {
  const rows: TimelineRow[] = []
  const toolRows = new Map<string, Extract<TimelineRow, { kind: 'tool' }>>()
  for (const [index, event] of events.entries()) {
    const p = event.payload as Payload
    const key = String(event.seq ?? event.id)
    // A routine memory check reads as one line: "refreshing" is folded into the "refreshed" event that follows.
    if (event.type === 'memory.refreshing' && events.slice(index + 1).some((e) => e.type === 'memory.refreshed')) continue
    if (event.type === 'tool.called') {
      const callId = String(p.callId ?? key)
      const row: Extract<TimelineRow, { kind: 'tool' }> = {
        kind: 'tool',
        key,
        event,
        call: {
          callId,
          tool: String(p.tool ?? 'tool'),
          args: (p.args && typeof p.args === 'object' ? p.args : {}) as Record<string, unknown>,
          by: p.by === 'pi' ? 'pi' : 'investigator',
          at: event.at,
        },
      }
      toolRows.set(callId, row)
      rows.push(row)
    } else if (event.type === 'tool.result') {
      const row = toolRows.get(String(p.callId))
      const result: ToolResult = {
        ok: p.ok !== false,
        summary: String(p.summary ?? ''),
        nodeIds: Array.isArray(p.nodeIds) ? p.nodeIds.filter((x): x is string => typeof x === 'string') : [],
        durationMs: typeof p.durationMs === 'number' ? p.durationMs : 0,
        error: typeof p.error === 'string' ? p.error : undefined,
      }
      if (row) {
        row.result = result
        row.resultEvent = event
      } else {
        rows.push({ kind: 'event', key, event })
      }
    } else {
      rows.push({ kind: 'event', key, event })
    }
  }
  return rows
}

function rowNodeIds(row: TimelineRow): string[] {
  if (row.kind === 'tool') return row.result?.nodeIds ?? []
  return eventNodeIds(row.event)
}

function Detail({ event }: { event: EventEnvelope }) {
  const p = event.payload as Payload
  if (event.type === 'evidence.found' && typeof p.quote === 'string' && p.quote) {
    return <blockquote className="display mt-1 line-clamp-3 border-l border-line-2 pl-3 text-small text-fg-2">{p.quote}</blockquote>
  }
  if (event.type === 'approval.recorded' && typeof p.target === 'string') {
    return (
      <p className="mt-1 font-mono text-eyebrow uppercase text-fg-3">
        {p.kind === 'pr' ? `HEAD ${shortSha(p.target)}` : `SHA-256 ${shortHash(p.target)}`}
      </p>
    )
  }
  if (event.type === 'build.step' && typeof p.file === 'string') {
    return <p className="mt-1 truncate font-mono text-eyebrow text-fg-3">{p.file}</p>
  }
  if (event.type === 'tests.result' && Array.isArray(p.failing) && p.failing.length > 0) {
    return (
      <ul className="mt-1 flex flex-col gap-0.5">
        {p.failing.slice(0, 3).map((f, i) => (
          <li key={i} className="truncate font-mono text-eyebrow text-state-conflict">
            {String((f as Payload).name ?? 'failing test')}
          </li>
        ))}
      </ul>
    )
  }
  return null
}

export interface TimelineItemProps {
  row: TimelineRow
  pinned?: boolean
  onHighlight?: (ids: string[]) => void
  onPin?: (ids: string[]) => void
  latest?: boolean
}

/** Renders every event type (B.C2) with a glyph, a plain sentence and a mono time (C-AC-9). */
export const TimelineItem = memo(function TimelineItem({ row, pinned = false, onHighlight, onPin, latest = false }: TimelineItemProps) {
  const event = row.event
  const ids = rowNodeIds(row)
  const interactive = ids.length > 0
  const time = (
    <time dateTime={event.at} title={exactTime(event.at)} suppressHydrationWarning className="font-mono text-eyebrow text-fg-3 tabular">
      {clockTime(event.at)}
    </time>
  )

  if (event.type === 'request.state_changed') {
    const to = String((event.payload as Payload).to ?? '')
    return (
      <li data-testid="timeline-item" data-type={event.type} className="enter flex items-center gap-3 py-1">
        <span aria-hidden className="h-px flex-1 bg-line-1" />
        {isRequestState(to) ? <StateChip state={to} /> : <span className="eyebrow">{to}</span>}
        {time}
      </li>
    )
  }

  const handlers = interactive
    ? {
        onMouseEnter: () => onHighlight?.(ids),
        onMouseLeave: () => onHighlight?.([]),
        onFocus: () => onHighlight?.(ids),
        onBlur: () => onHighlight?.([]),
        onClick: () => onPin?.(ids),
        onKeyDown: (e: React.KeyboardEvent) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            onPin?.(ids)
          }
        },
        tabIndex: 0,
        role: 'button' as const,
        'aria-pressed': pinned,
      }
    : {}

  if (event.type === 'handoff.created') {
    const count = Number((event.payload as Payload).evidenceCount ?? 0)
    return (
      <li data-testid="timeline-item" data-type={event.type} className="enter -mx-2 my-2">
        <div className="flex items-center gap-3 rounded-md border border-accent/50 bg-accent-wash px-3 py-3">
          <span className="text-accent">
            <Glyph name="Handoff" size={22} animated={latest} />
          </span>
          <div className="flex min-w-0 flex-1 flex-col">
            <span className="eyebrow text-accent">Handoff to the build</span>
            <span className="text-small text-fg-1">{eventSentence(event)}</span>
          </div>
          <span className="font-mono text-title-sm text-accent tabular" aria-hidden>
            {count}
          </span>
          {time}
        </div>
      </li>
    )
  }

  return (
    <li data-testid="timeline-item" data-type={event.type} className="enter">
      <div
        className={cx(
          'group relative flex gap-3 rounded-md px-2 py-2 outline-offset-0',
          interactive && 'cursor-pointer hover:bg-ink-2',
          pinned && 'bg-ink-2 ring-1 ring-accent/50',
        )}
        {...handlers}
      >
        <span className={cx('mt-0.5 shrink-0', latest ? 'text-fg-1' : 'text-fg-3')}>
          <Glyph name={eventGlyph(event)} size={16} animated={latest && row.kind === 'event' && event.type.startsWith('build')} />
        </span>
        <div className="flex min-w-0 flex-1 flex-col gap-0.5">
          {row.kind === 'tool' ? (
            <ToolCallCard call={row.call} result={row.result} compact />
          ) : (
            <>
              <p className="text-small text-fg-1">{eventSentence(event)}</p>
              <Detail event={event} />
            </>
          )}
          {time}
        </div>
        {interactive ? <span className="sr-only">Highlights {ids.length} nodes on the graph.</span> : null}
      </div>
    </li>
  )
})

export interface TimelineProps {
  events: readonly EventEnvelope[]
  pinnedIds?: readonly string[]
  onHighlight?: (ids: string[]) => void
  onPin?: (ids: string[]) => void
  /** Hide the state-change dividers (replay captions show them instead). */
  hideStateChanges?: boolean
  emptyText?: string
}

export function Timeline({ events, pinnedIds = [], onHighlight, onPin, hideStateChanges = false, emptyText }: TimelineProps) {
  const rows = useMemo(() => {
    const all = buildTimelineRows(events)
    return hideStateChanges ? all.filter((r) => r.event.type !== 'request.state_changed') : all
  }, [events, hideStateChanges])
  const pinned = new Set(pinnedIds)
  return (
    <ol aria-live="polite" aria-relevant="additions" aria-label="Request timeline" className="flex flex-col gap-0.5" data-testid="timeline">
      {rows.length === 0 ? (
        <li className="py-6 text-small text-fg-3">{emptyText ?? 'Waiting for the first event.'}</li>
      ) : (
        rows.map((row, i) => {
          const ids = rowNodeIds(row)
          return (
            <TimelineItem
              key={row.key}
              row={row}
              latest={i === rows.length - 1}
              pinned={ids.length > 0 && ids.every((id) => pinned.has(id))}
              onHighlight={onHighlight}
              onPin={onPin}
            />
          )
        })
      )}
    </ol>
  )
}
