'use client'
import Link from 'next/link'
import { useLocalFlag } from '@/lib/hooks/useLocalFlag'
import type { ConnectionView } from '@/lib/api/types'
import { Glyph } from '../glyphs/Glyph'
import { Button } from '../ui/Button'
import { cx } from '../ui/cx'

export interface OnboardingStep {
  id: string
  title: string
  href: string
  done: boolean
}

export function onboardingSteps(connections: readonly ConnectionView[], hasRequests: boolean): OnboardingStep[] {
  const connected = (p: ConnectionView['provider'][]) => connections.find((c) => p.includes(c.provider) && c.status === 'connected')
  const repo = connected(['github', 'code'])
  const branch = typeof repo?.config.workingBranch === 'string' && repo.config.workingBranch !== ''
  return [
    { id: 'repo', title: 'Connect your repository', href: '/app/connect', done: Boolean(repo) },
    { id: 'branch', title: 'Choose the working branch', href: '/app/connect', done: branch },
    { id: 'slack', title: 'Connect Slack', href: '/app/connect', done: Boolean(connected(['slack', 'slack_export'])) },
    { id: 'linear', title: 'Connect Linear', href: '/app/connect', done: Boolean(connected(['linear'])) },
    { id: 'request', title: 'Ask your first request', href: '/app', done: hasRequests },
  ]
}

const KEY = 'actron.onboarding.dismissed'

/** First-run checklist on Home and Connect (PRD 13.9b; C-AC-39): ticks itself, dismissible once complete. */
export function OnboardingChecklist({
  steps,
  className,
  action,
  body,
  compact = false,
}: {
  steps: OnboardingStep[]
  className?: string
  /** The one main action on a first-run screen. */
  action?: React.ReactNode
  body?: React.ReactNode
  /** One line instead of the card strip, for Home once requests exist. */
  compact?: boolean
}) {
  const [dismissed, setDismissed] = useLocalFlag(KEY)
  const done = steps.filter((s) => s.done).length
  const complete = done === steps.length
  if (dismissed) return null
  const next = steps.find((s) => !s.done)
  const nextText = next ? `Next: ${next.title.charAt(0).toLowerCase()}${next.title.slice(1)}` : null
  // Done steps first, then the next one, so a finished later step never sits after "Next".
  const ordered = [...steps.filter((s) => s.done), ...steps.filter((s) => !s.done)]
  if (compact && next) {
    return (
      <section aria-labelledby="onboarding-title" data-testid="onboarding" data-compact="true" className={cx('flex items-center gap-2 text-small', className)}>
        <h2 id="onboarding-title" className="text-fg-2">
          Getting started: {done} of {steps.length} done
        </h2>
        <span aria-hidden className="text-fg-3">·</span>
        <Link href={next.href} className="font-medium text-fg-1 underline decoration-line-2 underline-offset-4 hover:decoration-fg-2">
          {nextText}
        </Link>
      </section>
    )
  }
  return (
    <section aria-labelledby="onboarding-title" data-testid="onboarding" className={cx('flex flex-col gap-4 rounded-lg border border-line-1 p-5', className)}>
      <div className="flex items-end justify-between gap-4">
        <div className="flex flex-col gap-1">
          <span className="eyebrow">
            Getting started · {done} of {steps.length} done
          </span>
          <h2 id="onboarding-title" className="display text-title-sm text-fg-1">
            {complete ? 'Actron is set up.' : nextText ? `${nextText}.` : 'Set up Actron.'}
          </h2>
          {body ? <p className="max-w-prose text-small text-fg-2">{body}</p> : null}
        </div>
        {action && !complete ? action : null}
        {complete ? (
          <Button
            size="sm"
            variant="ghost"
            onClick={() => setDismissed(true)}
          >
            Dismiss
          </Button>
        ) : null}
      </div>
      <ol className="grid grid-cols-5 gap-2">
        {ordered.map((s) => (
          <li key={s.id} data-done={s.done ? 'true' : 'false'}>
            <Link
              href={s.href}
              className={cx(
                'flex h-full flex-col gap-2 rounded-md border px-3 py-3 transition-colors duration-1',
                s.done ? 'border-line-1 text-fg-2 hover:bg-ink-1' : s === next ? 'border-accent/60 text-fg-1 hover:bg-ink-1' : 'border-line-1 text-fg-2 hover:bg-ink-1',
              )}
            >
              <span className={cx('flex items-center gap-1.5 text-caption font-medium', s.done ? 'text-state-ok' : s === next ? 'text-fg-1' : 'text-fg-3')}>
                {s.done ? <Glyph name="TestPass" size={14} /> : <span aria-hidden className={cx('size-1.5 rounded-full', s === next ? 'bg-accent' : 'bg-line-2')} />}
                {s.done ? 'Done' : s === next ? 'Next' : 'To do'}
              </span>
              <span className="text-small">{s.title}</span>
            </Link>
          </li>
        ))}
      </ol>
    </section>
  )
}
