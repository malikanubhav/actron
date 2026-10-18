import Link from 'next/link'
import type { RequestSummary } from '@/lib/api/types'
import { initials, shortRequestId } from '@/lib/format'
import { isFinal, PIPELINE, sentenceCase } from '@/lib/states'
import { KIND_LABEL } from '@/lib/kind'
import { StateChip } from '../core/StateChip'
import { pipelineStepLabel, type PipelineStatus } from '../core/Pipeline'
import { RelativeTime } from '../core/Formatting'
import { BrandMark } from '../brand/BrandMark'
import { Glyph } from '../glyphs/Glyph'
import { buttonClass } from '../ui/button-class'
import { cx } from '../ui/cx'
import { ASK, rowFact, type RowFact } from './ask'

export function pipelineStatus(r: Pick<RequestSummary, 'state'>): PipelineStatus {
  if (r.state === 'Done') return 'done'
  if (r.state === 'Needs attention') return 'failed'
  if (r.state === 'Cancelled') return 'cancelled'
  return 'active'
}

export function Avatar({ name, url, size = 'sm' }: { name: string; url?: string | null; size?: 'sm' | 'md' }) {
  return url ? (
    // Avatars come from Slack; small and remote, so a plain img.
    // eslint-disable-next-line @next/next/no-img-element
    <img src={url} alt="" className={cx('shrink-0 rounded-full', size === 'sm' ? 'size-5' : 'size-7')} />
  ) : (
    <span
      aria-hidden
      className={cx(
        'inline-flex shrink-0 items-center justify-center rounded-full border border-line-2 bg-ink-2 font-mono text-fg-2',
        size === 'sm' ? 'size-5 text-eyebrow' : 'size-7 text-eyebrow',
      )}
    >
      {initials(name)}
    </span>
  )
}

/**
 * One request on Home: short id and title, one state chip, the useful fact (the open question, the ticket to
 * approve, why the build stopped, the PR to review), requester, the current step and what to do (PROMPT 8.8 C).
 */
export function RequestRow({ request, href, fact }: { request: RequestSummary; href?: string; fact?: RowFact }) {
  const link = href ?? `/app/requests/${request.id}`
  const shown = fact ?? rowFact(request, [])
  const status = pipelineStatus(request)
  const step = pipelineStepLabel(request.pipelineStep, status)
  const ask = shown.kind ? ASK[shown.kind] : null
  return (
    <li className="border-b border-line-1 last:border-b-0" data-testid="request-row" data-state={request.state} data-ask={shown.kind}>
      <Link
        href={link}
        data-row
        className="group grid grid-cols-[minmax(0,5fr)_10rem_minmax(0,4fr)_8rem] items-center gap-x-gutter rounded-md px-3 py-3 outline-offset-0 hover:bg-ink-1 focus-visible:bg-ink-1"
      >
        <span className="flex min-w-0 flex-col gap-1">
          <span className="flex min-w-0 items-center gap-2 text-caption text-fg-3">
            {request.source === 'slack' ? <BrandMark name="slack" size={11} decorative /> : null}
            <span className="data-label text-fg-2">{shortRequestId(request.id)}</span>
            <span aria-hidden>·</span>
            <Avatar name={request.requester.name} url={request.requester.avatarUrl} />
            <span className="truncate text-fg-2">{request.requester.name}</span>
            <span aria-hidden>·</span>
            <span className="whitespace-nowrap">
              started <RelativeTime value={request.createdAt} focusable={false} />
            </span>
            <span aria-hidden>·</span>
            <span>{sentenceCase(KIND_LABEL[request.kind])}</span>
          </span>
          <span className="line-clamp-2 text-body text-fg-1" title={request.title}>
            {request.title}
          </span>
        </span>
        <span className="flex min-w-0 flex-col items-start gap-1.5">
          <StateChip state={request.state} live={!isFinal(request.state)} />
          <span className="truncate text-caption text-fg-3" title={PIPELINE.map((s) => `${s.n} ${s.text}`).join(' · ')} data-testid="pipeline-step">
            {step}
          </span>
        </span>
        <span className="flex min-w-0 flex-col gap-1">
          <span className="flex min-w-0 items-start gap-2 text-small text-fg-1" data-testid="row-fact">
            {ask ? (
              <span className={cx('mt-0.5 shrink-0', shown.kind === 'build_failed' ? 'text-state-conflict' : 'text-accent')}>
                <Glyph name={ask.glyph} size={16} />
              </span>
            ) : null}
            <span className="line-clamp-2" title={shown.text}>
              {shown.text}
            </span>
          </span>
          <span className={cx('text-caption text-fg-3', ask && 'pl-6')}>
            Updated <RelativeTime value={request.lastEvent?.at ?? request.updatedAt} focusable={false} />
          </span>
        </span>
        <span className="flex justify-end" aria-hidden>
          <span className={buttonClass(ask ? 'secondary' : 'ghost', 'sm', 'pointer-events-none')}>{ask ? ask.verb : 'Open'}</span>
        </span>
      </Link>
    </li>
  )
}
