'use client'
import Link from 'next/link'
import { useRef } from 'react'
import type { NotificationItem } from '@/lib/api/types'
import { useNotifications, useRequests } from '@/lib/hooks/queries'
import { useMarkRead } from '@/lib/hooks/mutations'
import { useListKeys } from '@/lib/hooks/useListKeys'
import { reasonText } from '@/lib/api'
import { shortRequestId } from '@/lib/format'
import type { Tone } from '@/lib/states'
import { ScreenHeader } from '../core/ScreenHeader'
import { RelativeTime } from '../core/Formatting'
import { StateChip } from '../core/StateChip'
import { EmptyState, ErrorState } from '../states/States'
import { SkeletonRows } from '../states/Skeleton'
import { PageFrame } from '../shell/PageFrame'
import { Glyph } from '../glyphs/Glyph'
import { Button } from '../ui/Button'
import { buttonClass } from '../ui/button-class'
import { cx } from '../ui/cx'
import { StateGroup } from '../home/StateGroup'
import { ASK, askText, GROUP_COPY, historyText, inboxSections, type InboxSections, type RequestBlock } from '../home/ask'

/** Same group names and colours as Home; the lines describe notices, since this screen is the notice feed. */
export const INBOX_GROUPS: { id: keyof InboxSections; title: string; tone: Tone; description: string; empty: string }[] = [
  {
    id: 'waiting',
    tone: 'needs_you',
    title: GROUP_COPY.waiting.title,
    description: 'Notices whose ask is still open: answer the question, approve the ticket or review the pull request.',
    empty: 'No open questions, approvals or reviews.',
  },
  {
    id: 'stopped',
    tone: 'conflict',
    title: GROUP_COPY.stopped.title,
    description: 'Notices about builds that stopped and still wait on a fix.',
    empty: 'No stopped builds.',
  },
  {
    id: 'earlier',
    title: 'No longer waiting',
    tone: 'idle',
    description: 'Notices for requests that have moved on.',
    empty: 'Every notice is still current.',
  },
]

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`

/** The feed in numbers: "7 notices on 3 requests. 3 are new." */
export function inboxHeadline(notices: number, requests: number, unread: number): string {
  if (notices === 0) return 'No notices yet.'
  const head = `${plural(notices, 'notice', 'notices')} on ${plural(requests, 'request', 'requests')}.`
  if (unread === 0) return `${head} None are new.`
  if (unread === notices) return `${head} ${notices === 1 ? 'It is new.' : 'All are new.'}`
  return `${head} ${unread === 1 ? '1 is new.' : `${unread} are new.`}`
}

function Kbd({ children }: { children: string }) {
  return <kbd className="inline-flex h-5 min-w-5 items-center justify-center rounded-sm border border-line-2 px-1 font-ui text-caption text-fg-2">{children}</kbd>
}

function MarkRead({ items, onRead }: { items: NotificationItem[]; onRead: (id: string) => void }) {
  if (items.length === 0) return null
  return (
    <button
      type="button"
      onClick={() => items.forEach((n) => onRead(n.id))}
      className="shrink-0 rounded-sm px-1 text-caption text-fg-3 underline decoration-line-2 underline-offset-4 hover:text-fg-1 hover:decoration-fg-2"
    >
      Mark read
    </button>
  )
}

/** The ask that is open now: the fact first, then what to do; Mark read sits on the same line. */
function CurrentItem({ n, title, onRead, unreadInBlock }: { n: NotificationItem; title: string; onRead: (id: string) => void; unreadInBlock: NotificationItem[] }) {
  const unread = !n.readAt
  const ask = ASK[n.kind]
  const text = askText(n, title)
  return (
    <li data-testid="inbox-item" data-unread={unread ? 'true' : 'false'} data-current="true" className="flex items-center gap-3">
      <Link
        href={`/app/requests/${n.requestId}?tab=${n.tab}`}
        data-row
        onClick={() => unread && onRead(n.id)}
        className="group flex min-w-0 flex-1 items-center gap-2 rounded-md px-1 py-2 hover:bg-ink-1 focus-visible:bg-ink-1"
      >
        <span className={cx('shrink-0', n.kind === 'build_failed' ? 'text-state-conflict' : 'text-accent')}>
          <Glyph name={ask.glyph} size={18} />
        </span>
        <span className="line-clamp-2 min-w-0 flex-1 text-body text-fg-1" title={text}>
          {text}
        </span>
        <span className="shrink-0 text-caption text-fg-3">
          {unread ? <span className="font-medium text-fg-1">New · </span> : null}
          notice <RelativeTime value={n.createdAt} focusable={false} />
        </span>
        <span className={buttonClass('secondary', 'sm', 'pointer-events-none ml-2 shrink-0')}>{ask.verb}</span>
      </Link>
      <MarkRead items={unreadInBlock} onRead={onRead} />
    </li>
  )
}

/** A past notice: past tense, quiet, no action. */
function HistoryItem({ n, block, onRead }: { n: NotificationItem; block: RequestBlock; onRead: (id: string) => void }) {
  const unread = !n.readAt
  const text = historyText(n, block.title, block.request)
  return (
    <li data-testid="inbox-item" data-unread={unread ? 'true' : 'false'} data-current="false">
      <Link
        href={`/app/requests/${n.requestId}?tab=${n.tab}`}
        onClick={() => unread && onRead(n.id)}
        className="flex min-w-0 items-start gap-2 rounded-md px-1 py-1.5 text-small text-fg-3 hover:bg-ink-1 hover:text-fg-2"
      >
        <span className="mt-0.5 shrink-0">
          <Glyph name={ASK[n.kind].glyph} size={14} />
        </span>
        <span className="min-w-0 flex-1 truncate" title={text}>
          {text}
        </span>
        <span className="shrink-0 text-caption">
          notice <RelativeTime value={n.createdAt} focusable={false} />
        </span>
      </Link>
    </li>
  )
}

function Block({ b, onRead }: { b: RequestBlock; onRead: (id: string) => void }) {
  const all = [b.current, ...b.earlier].filter((n): n is NotificationItem => Boolean(n))
  const unread = all.filter((n) => !n.readAt)
  const history = (
    <ul className="flex flex-col">
      {b.earlier.map((n) => (
        <HistoryItem key={n.id} n={n} block={b} onRead={onRead} />
      ))}
    </ul>
  )
  return (
    <li className="flex flex-col gap-1 border-b border-line-1 py-3 last:border-b-0" data-testid="inbox-request" data-request={b.requestId}>
      <div className="flex min-w-0 items-center gap-2 px-1 text-caption text-fg-3">
        <span className="data-label text-fg-2">{shortRequestId(b.requestId)}</span>
        {b.request ? (
          <>
            <span aria-hidden>·</span>
            <span>{b.request.requester.name}</span>
            <span aria-hidden>·</span>
            <span className="whitespace-nowrap">
              started <RelativeTime value={b.request.createdAt} focusable={false} />
            </span>
          </>
        ) : null}
        <span aria-hidden>·</span>
        <span className="min-w-0 truncate" title={b.title}>
          {b.title}
        </span>
        <span className="ml-auto flex shrink-0 items-center gap-3">
          {b.current ? null : <MarkRead items={unread} onRead={onRead} />}
          {b.state ? <StateChip state={b.state} /> : null}
        </span>
      </div>
      {b.current ? (
        <>
          <ul className="flex flex-col">
            <CurrentItem n={b.current} title={b.title} onRead={onRead} unreadInBlock={unread} />
          </ul>
          {b.earlier.length ? (
            <details className="px-1">
              <summary className="ml-6 w-fit cursor-pointer rounded-sm px-1 text-caption text-fg-3 hover:text-fg-1">History ({b.earlier.length})</summary>
              {history}
            </details>
          ) : null}
        </>
      ) : (
        history
      )}
    </li>
  )
}

/** Inbox (PROMPT 8.8 F): the notice feed, one block per request, the open ask first and older notices as history. */
export function InboxScreen() {
  const ref = useRef<HTMLDivElement>(null)
  useListKeys(ref)
  const q = useNotifications()
  const needs = useRequests('needs_you')
  const read = useMarkRead()
  const items = q.data?.notifications ?? []
  const unread = items.filter((n) => !n.readAt).length
  const sections = inboxSections(items, needs.isSuccess ? needs.data.requests : null)
  const requestCount = new Set(items.map((n) => n.requestId)).size
  const onRead = (id: string) => void read.run({ id }).catch(() => undefined)
  return (
    <PageFrame>
      <ScreenHeader
        eyebrow="Inbox"
        headline={q.isPending ? 'Loading your inbox…' : q.isError ? 'The inbox could not be loaded.' : inboxHeadline(items.length, requestCount, unread)}
        purpose="Every notice Actron sent you, grouped by request: the open ask first, older notices as history."
        notice={
          <p className="flex items-center gap-1.5 text-caption text-fg-3">
            <Kbd>J</Kbd>
            <Kbd>K</Kbd>
            <span>to move,</span>
            <Kbd>Enter</Kbd>
            <span>to open</span>
          </p>
        }
      />
      {q.isPending ? (
        <SkeletonRows rows={4} />
      ) : q.isError ? (
        <ErrorState title="The inbox could not be loaded." body={reasonText(q.error)} action={<Button onClick={() => void q.refetch()}>Retry</Button>} />
      ) : items.length === 0 ? (
        <EmptyState size="page" glyph="Inbox" title="No notices yet." body="Actron interrupts only for four things: a question, a ticket to approve, a stopped build and a pull request to review." />
      ) : (
        <div ref={ref} className="flex flex-col gap-8">
          {INBOX_GROUPS.map((g) => {
            const blocks = sections[g.id]
            if (g.id === 'earlier' && blocks.length === 0) return null
            return (
              <StateGroup key={g.id} testId={`inbox-group-${g.id}`} tone={g.tone} title={g.title} count={blocks.length} description={g.description} empty={g.empty}>
                <ul className="flex flex-col">
                  {blocks.map((b) => (
                    <Block key={b.requestId} b={b} onRead={onRead} />
                  ))}
                </ul>
              </StateGroup>
            )
          })}
        </div>
      )}
    </PageFrame>
  )
}
