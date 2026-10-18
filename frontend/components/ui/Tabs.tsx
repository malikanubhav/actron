'use client'
import { useId, useRef, type ReactNode } from 'react'
import { cx } from './cx'

export interface TabItem<T extends string> {
  id: T
  label: string
  badge?: ReactNode
  /** Says what the badge counts; shown on hover. */
  hint?: string
}

/** ARIA tabs with arrow-key navigation; switching is instant (high-frequency, no animation). */
export function Tabs<T extends string>({
  items,
  value,
  onChange,
  label,
  children,
  className,
}: {
  items: TabItem<T>[]
  value: T
  onChange: (id: T) => void
  label: string
  children: ReactNode
  className?: string
}) {
  const base = useId()
  const refs = useRef<(HTMLButtonElement | null)[]>([])
  const index = Math.max(0, items.findIndex((i) => i.id === value))
  const move = (to: number) => {
    const n = (to + items.length) % items.length
    const item = items[n]
    if (!item) return
    onChange(item.id)
    refs.current[n]?.focus()
  }
  return (
    <div className={cx('flex min-h-0 flex-col', className)}>
      <div role="tablist" aria-label={label} className="flex shrink-0 items-stretch gap-4 border-b border-line-1 px-4">
        {items.map((item, i) => (
          <button
            key={item.id}
            ref={(el) => {
              refs.current[i] = el
            }}
            id={`${base}-tab-${item.id}`}
            role="tab"
            type="button"
            aria-selected={item.id === value}
            aria-controls={`${base}-panel`}
            tabIndex={item.id === value ? 0 : -1}
            onClick={() => onChange(item.id)}
            title={item.hint}
            onKeyDown={(e) => {
              if (e.key === 'ArrowRight') move(i + 1)
              else if (e.key === 'ArrowLeft') move(i - 1)
              else if (e.key === 'Home') move(0)
              else if (e.key === 'End') move(items.length - 1)
            }}
            className={cx(
              'relative -mb-px flex h-10 items-center gap-1.5 border-b text-small font-medium transition-colors duration-1',
              item.id === value ? 'border-accent text-fg-1' : 'border-transparent text-fg-3 hover:text-fg-1',
            )}
          >
            {item.label}
            {item.badge}
          </button>
        ))}
      </div>
      <div id={`${base}-panel`} role="tabpanel" aria-labelledby={`${base}-tab-${items[index]?.id ?? ''}`} tabIndex={0} className="min-h-0 flex-1 outline-none">
        {children}
      </div>
    </div>
  )
}
