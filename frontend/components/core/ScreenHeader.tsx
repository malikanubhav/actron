'use client'
import { useState, type ReactNode } from 'react'
import { Eyebrow } from './Eyebrow'
import { cx } from '../ui/cx'

export interface ScreenHeaderProps {
  eyebrow: ReactNode
  headline: string
  purpose: ReactNode
  actions?: ReactNode
  pipeline?: ReactNode
  /** `lg` (48 px) for app overview screens, `md` for dense working screens (Request), `xl` (64 px at wide screens) only where a screen asks for it. */
  size?: 'xl' | 'lg' | 'md'
  className?: string
  /** Extra line under the purpose (notices such as budget reached). */
  notice?: ReactNode
  /** What counts as a new situation (for example the request state). Text changes within it, such as a growing
   *  count, update in place without the cross-fade. Defaults to the headline itself. */
  headlineKey?: string
  /** Lines of height the headline always takes, for headlines whose length follows live data (Connect), so a
   *  change from one line to two does not shift the page (CLS). */
  headlineLines?: 1 | 2
}

/**
 * Every screen opens with an eyebrow, a situation headline and a one-line purpose (PRD 13.5). The headline
 * cross-fades when the situation changes and is announced politely.
 */
export function ScreenHeader({ eyebrow, headline, purpose, actions, pipeline, size = 'lg', className, notice, headlineKey, headlineLines }: ScreenHeaderProps) {
  // The first headline paints as is; later situation changes cross-fade in (spec C, C2).
  const situation = headlineKey ?? headline
  const [firstSituation] = useState(situation)
  return (
    <header className={cx('flex flex-col', size === 'md' ? 'gap-2' : 'gap-4', className)} data-testid="screen-header">
      <div className="flex flex-wrap items-start justify-between gap-x-8 gap-y-4">
        <div className={cx('flex min-w-0 max-w-5xl flex-col', size === 'lg' ? 'gap-2' : 'gap-3')}>
          <Eyebrow as="div">{eyebrow}</Eyebrow>
          <div aria-live="polite" aria-atomic="true">
            <h1
              key={situation}
              className={cx(
                situation !== firstSituation && 'headline-swap',
                'display text-fg-1',
                size === 'xl' ? 'text-headline-sm xl:text-headline' : size === 'lg' ? 'text-headline-sm' : 'text-title-lg',
                headlineLines === 2 && 'min-h-[2lh]',
              )}
            >
              {headline}
            </h1>
          </div>
          <p className="max-w-measure text-lead text-fg-2">{purpose}</p>
          {notice}
        </div>
        {actions ? <div className={cx('flex shrink-0 items-center gap-2', size === 'lg' ? 'pt-6' : 'pt-8')}>{actions}</div> : null}
      </div>
      {pipeline}
    </header>
  )
}
