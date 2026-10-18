import { cx } from './cx'

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger'
export type ButtonSize = 'sm' | 'md'

/** Button classes, usable from server components (no 'use client'). */
const base =
  'press inline-flex shrink-0 items-center justify-center gap-2 whitespace-nowrap rounded-md border font-ui font-medium select-none disabled:cursor-not-allowed'

const variants: Record<ButtonVariant, string> = {
  primary: 'border-transparent bg-accent text-accent-ink hover:bg-accent/90 disabled:border-accent/40 disabled:bg-transparent disabled:text-fg-2',
  secondary: 'border-line-2 bg-transparent text-fg-1 hover:bg-ink-3 hover:border-fg-3/40 disabled:text-fg-disabled disabled:border-line-1',
  ghost: 'border-transparent bg-transparent text-fg-2 hover:bg-ink-3 hover:text-fg-1 disabled:text-fg-disabled',
  danger: 'border-state-conflict/50 bg-transparent text-state-conflict hover:bg-state-conflict/10 disabled:text-fg-disabled disabled:border-line-1',
}

const sizes: Record<ButtonSize, string> = {
  sm: 'h-7 px-3 text-caption',
  md: 'h-9 px-4 text-small',
}

export function buttonClass(variant: ButtonVariant = 'secondary', size: ButtonSize = 'md', className?: string): string {
  return cx(base, variants[variant], sizes[size], className)
}

