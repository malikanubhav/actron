import { DEV_FIXTURES } from '@/lib/env'
import { cx } from '../ui/cx'

/** Visible on every screen when the UI runs on development fixtures (spec C, C-AC-20). */
export function DevFixturesBadge({ className, inline = false }: { className?: string; inline?: boolean }) {
  if (!DEV_FIXTURES) return null
  return (
    <span
      data-testid="dev-fixtures-badge"
      role="status"
      aria-label="This screen shows development fixtures, not real data"
      title="Development fixtures: recorded test data, not your workspace."
      className={cx(
        'inline-flex h-5 shrink-0 items-center whitespace-nowrap rounded-sm border border-accent px-1.5 font-mono text-eyebrow uppercase text-accent',
        !inline && 'dev-badge-fixed fixed bottom-3 right-3 z-[60] bg-ink-0',
        className,
      )}
    >
      DEV FIXTURES
    </span>
  )
}
