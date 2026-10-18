import type { ReactNode } from 'react'
import { toneVar, type Tone } from '@/lib/states'
import { cx } from '../ui/cx'

const dot: Record<Tone, string> = {
  needs_you: 'bg-accent',
  running: 'bg-state-running',
  conflict: 'bg-state-conflict',
  ok: 'bg-state-ok',
  idle: 'bg-state-idle',
  possible: 'bg-state-possible',
}

/**
 * A list group named by state (Home and Inbox use the same one, so a state looks the same on every screen):
 * a rule and dot in the state colour, a title, a count and one line saying what the group means. An empty group
 * collapses to one quiet line.
 */
export function StateGroup({
  tone,
  title,
  count,
  description,
  empty,
  testId,
  children,
}: {
  tone: Tone
  title: string
  count: number
  description: string
  /** Shown instead of the header when the group has nothing in it. */
  empty: string
  testId?: string
  children?: ReactNode
}) {
  if (count === 0) {
    return (
      <section aria-label={title} data-testid={testId} data-tone={tone} data-empty="true" className="flex items-center gap-2 text-small">
        <span aria-hidden className="size-1.5 shrink-0 rounded-full bg-state-idle" />
        <h2 className="font-medium text-fg-2">{title}</h2>
        <span aria-hidden className="text-fg-3">·</span>
        <p className="text-fg-3">{empty}</p>
      </section>
    )
  }
  return (
    <section aria-label={title} data-testid={testId} data-tone={tone} className="flex flex-col gap-3">
      <header
        className="flex flex-col gap-1 border-t-2 pt-3"
        style={{ borderColor: `color-mix(in srgb, ${toneVar(tone)} 70%, transparent)` }}
      >
        <div className="flex items-center gap-3">
          <span aria-hidden className={cx('size-2 shrink-0 rounded-full', dot[tone])} />
          <h2 className="display text-title-sm text-fg-1">{title}</h2>
          <span className="font-mono text-small tabular" style={{ color: toneVar(tone) }}>
            <span className="sr-only">count </span>
            {count}
          </span>
        </div>
        <p className="pl-5 text-small text-fg-2">{description}</p>
      </header>
      {children}
    </section>
  )
}
