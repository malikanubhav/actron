import type { ReactNode } from 'react'
import { cx } from '../ui/cx'

/** Sentence-case label above a headline or panel (spec C, C2). */
export function Eyebrow({ children, className, as: Tag = 'p' }: { children: ReactNode; className?: string; as?: 'p' | 'span' | 'div' }) {
  return <Tag className={cx('eyebrow', className)}>{children}</Tag>
}
