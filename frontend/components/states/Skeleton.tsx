import { cx } from '../ui/cx'

/** Static blocks that match the real layout's dimensions (no shimmer). */
export function SkeletonBlock({ className }: { className?: string }) {
  return <span aria-hidden className={cx('skeleton block', className)} />
}

export function SkeletonText({ lines = 3, className }: { lines?: number; className?: string }) {
  return (
    <span aria-hidden className={cx('flex flex-col gap-2', className)}>
      {Array.from({ length: lines }, (_, i) => (
        <span key={i} className={cx('skeleton block h-3', i === lines - 1 ? 'w-2/3' : 'w-full')} />
      ))}
    </span>
  )
}

export function SkeletonHeader() {
  return (
    <div aria-busy="true" aria-label="Loading" className="flex flex-col gap-3" data-testid="skeleton-header">
      <SkeletonBlock className="h-3 w-40" />
      <SkeletonBlock className="h-12 w-2/3" />
      <SkeletonBlock className="h-5 w-1/2" />
    </div>
  )
}

/** Matches a request row on Home and Inbox (64 px tall). */
export function SkeletonRows({ rows = 3 }: { rows?: number }) {
  return (
    <ul aria-busy="true" aria-label="Loading requests" className="flex flex-col" data-testid="skeleton-rows">
      {Array.from({ length: rows }, (_, i) => (
        <li key={i} className="flex h-16 items-center gap-4 border-b border-line-1">
          <SkeletonBlock className="h-4 w-1/3" />
          <SkeletonBlock className="h-5 w-28" />
          <span className="flex-1" />
          <SkeletonBlock className="h-1 w-28" />
        </li>
      ))}
    </ul>
  )
}

export function SkeletonColumn({ items = 5 }: { items?: number }) {
  return (
    <div aria-busy="true" aria-label="Loading" className="flex flex-col gap-4" data-testid="skeleton-column">
      {Array.from({ length: items }, (_, i) => (
        <div key={i} className="flex gap-3">
          <SkeletonBlock className="size-5 shrink-0" />
          <SkeletonText lines={2} className="flex-1" />
        </div>
      ))}
    </div>
  )
}

export function SkeletonCanvas() {
  return (
    <div aria-busy="true" aria-label="Loading the graph" data-testid="skeleton-canvas" className="h-full min-h-96 w-full rounded-lg border border-line-1" />
  )
}
