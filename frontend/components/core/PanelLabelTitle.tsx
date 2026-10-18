import type { ReactNode } from 'react'
import { cx } from '../ui/cx'

/** Every panel: a sentence-case label and a display title (PRD 13.5). */
export function PanelLabelTitle({
  label,
  title,
  aside,
  className,
  as: Heading = 'h2',
  id,
}: {
  label: ReactNode
  title: ReactNode
  aside?: ReactNode
  className?: string
  as?: 'h2' | 'h3'
  id?: string
}) {
  return (
    <div className={cx('flex items-end justify-between gap-4', className)}>
      <div className="flex min-w-0 flex-col gap-1">
        <span className="eyebrow">{label}</span>
        <Heading id={id} className="display text-title-sm text-fg-1">
          {title}
        </Heading>
      </div>
      {aside ? <div className="flex shrink-0 items-center gap-2">{aside}</div> : null}
    </div>
  )
}
