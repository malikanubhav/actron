'use client'
import { cloneElement, isValidElement, useId, useState, type ReactElement, type ReactNode } from 'react'
import { cx } from './cx'

export interface TooltipProps {
  content: ReactNode
  children: ReactElement<Record<string, unknown>>
  side?: 'top' | 'bottom' | 'right' | 'left'
  className?: string
}

/** Hover and focus tooltip, linked with aria-describedby. No entrance animation (high-frequency). */
export function Tooltip({ content, children, side = 'top', className }: TooltipProps) {
  const id = useId()
  const [open, setOpen] = useState(false)
  if (!isValidElement(children)) return children
  const trigger = cloneElement(children, {
    'aria-describedby': open ? id : undefined,
    onMouseEnter: () => setOpen(true),
    onMouseLeave: () => setOpen(false),
    onFocus: () => setOpen(true),
    onBlur: () => setOpen(false),
    onKeyDown: (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    },
  })
  return (
    <span className="relative inline-flex">
      {trigger}
      {open ? (
        <span
          role="tooltip"
          id={id}
          className={cx(
            'pointer-events-none absolute z-50 w-max max-w-xs rounded-sm border border-line-2 bg-ink-2 px-2 py-1 text-caption text-fg-1 shadow-overlay',
            side === 'top' && 'bottom-full left-1/2 mb-2 -translate-x-1/2',
            side === 'bottom' && 'top-full left-1/2 mt-2 -translate-x-1/2',
            side === 'right' && 'left-full top-1/2 ml-2 -translate-y-1/2',
            side === 'left' && 'right-full top-1/2 mr-2 -translate-y-1/2',
            className,
          )}
        >
          {content}
        </span>
      ) : null}
    </span>
  )
}
