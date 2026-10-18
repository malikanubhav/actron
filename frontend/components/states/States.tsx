import type { ReactNode } from 'react'
import { WifiSlash, ArrowClockwise } from '@phosphor-icons/react/dist/ssr'
import { Glyph } from '../glyphs/Glyph'
import type { GlyphName } from '../glyphs/names'
import { cx } from '../ui/cx'

interface StateProps {
  title: string
  body?: ReactNode
  action?: ReactNode
  glyph?: GlyphName
  className?: string
  /** Inline states sit inside a panel; page states get more room. */
  size?: 'inline' | 'page'
}

/** Empty states teach the next step (PRD 13.4). */
export function EmptyState({ title, body, action, glyph = 'Graph', className, size = 'inline' }: StateProps) {
  return (
    <div
      data-testid="empty-state"
      className={cx('flex flex-col items-start gap-3', size === 'page' ? 'max-w-prose py-16' : 'py-8', className)}
    >
      <span className="text-fg-3">
        <Glyph name={glyph} size={size === 'page' ? 28 : 20} />
      </span>
      <h3 className={cx('display text-fg-1', size === 'page' ? 'text-title' : 'text-title-sm')}>{title}</h3>
      {body ? <div className="max-w-prose text-small text-fg-2">{body}</div> : null}
      {action ? <div className="pt-1">{action}</div> : null}
    </div>
  )
}

/** Errors say what happened and what to do. */
export function ErrorState({ title, body, action, className, size = 'inline' }: Omit<StateProps, 'glyph'>) {
  return (
    <div role="alert" data-testid="error-state" className={cx('flex flex-col items-start gap-3', size === 'page' ? 'py-16' : 'py-6', className)}>
      <span className="text-state-conflict">
        <Glyph name="TestFail" size={size === 'page' ? 28 : 20} />
      </span>
      <h3 className={cx('display text-fg-1', size === 'page' ? 'text-title' : 'text-title-sm')}>{title}</h3>
      {body ? <div className="max-w-prose text-small text-fg-2">{body}</div> : null}
      {action ? <div className="pt-1">{action}</div> : null}
    </div>
  )
}

/** Something worked and something did not; the reason is always visible. */
export function PartialState({ title, body, action, className }: Omit<StateProps, 'glyph' | 'size'>) {
  return (
    <div
      role="status"
      data-testid="partial-state"
      className={cx('flex items-start gap-3 rounded-md border border-state-possible/30 px-4 py-3', className)}
    >
      <span className="mt-0.5 text-state-possible">
        <Glyph name="PossibleConflict" size={18} />
      </span>
      <div className="flex min-w-0 flex-col gap-1">
        <p className="text-small font-medium text-fg-1">{title}</p>
        {body ? <div className="text-small text-fg-2">{body}</div> : null}
        {action ? <div className="pt-1">{action}</div> : null}
      </div>
    </div>
  )
}

function Banner({ tone, icon, children, action, testId }: { tone: 'possible' | 'idle'; icon: ReactNode; children: ReactNode; action?: ReactNode; testId: string }) {
  return (
    <div
      role="status"
      data-testid={testId}
      className={cx(
        'flex items-center gap-3 border-b px-page py-2 text-small',
        tone === 'possible' ? 'border-state-possible/30 text-state-possible' : 'border-line-1 text-fg-2',
      )}
    >
      {icon}
      <span className="min-w-0 flex-1 text-fg-1">{children}</span>
      {action}
    </div>
  )
}

export function ReconnectingBanner({ action }: { action?: ReactNode }) {
  return (
    <Banner testId="reconnecting-banner" tone="possible" icon={<ArrowClockwise size={16} aria-hidden className="motion-safe:animate-spin" />} action={action}>
      Reconnecting to live updates. Nothing is lost; missed events arrive when the stream resumes.
    </Banner>
  )
}

export function OfflineBanner({ action }: { action?: ReactNode }) {
  return (
    <Banner testId="offline-banner" tone="idle" icon={<WifiSlash size={16} aria-hidden />} action={action}>
      Live updates are offline. Actron keeps trying; this page shows the last state it received.
    </Banner>
  )
}
