import type { ReactNode } from 'react'
import { cx } from '../ui/cx'

/** The content frame for signed-in screens: max width 1600, page padding 32 (48 at 1920), 12-column grid inside. */
export function PageFrame({
  children,
  className,
  wide = false,
  dense = false,
  fill = false,
}: {
  children: ReactNode
  className?: string
  wide?: boolean
  /** Working screens (Request, Replay) keep the header tight so the columns start above the fold. */
  dense?: boolean
  /** The frame is exactly as tall as the visible area (inside the app shell) and its columns take what the header leaves. */
  fill?: boolean
}) {
  return (
    <div
      className={cx(
        'mx-auto flex w-full flex-col px-4 sm:px-page',
        // Same top padding on every screen, so the eyebrow does not jump when moving from Home to a request.
        // A request fills the screen, so it spends less on padding: the panels get the height.
        fill ? 'gap-3 pb-4 pt-6' : dense ? 'gap-5 pb-8 pt-10' : 'gap-8 pb-16 pt-10',
        wide ? 'max-w-none' : 'max-w-content',
        fill && 'request-frame',
        className,
      )}
    >
      {children}
    </div>
  )
}

/** 12-column grid with 24 px gutters (spec C, C1.3). */
export function Grid12({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cx('grid grid-cols-12 gap-gutter', className)}>{children}</div>
}
