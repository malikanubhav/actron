'use client'
import Link from 'next/link'
import { forwardRef, type AnchorHTMLAttributes, type ButtonHTMLAttributes, type ReactNode } from 'react'
import { cx } from './cx'


export { buttonClass, type ButtonVariant, type ButtonSize } from './button-class'
import { buttonClass, type ButtonVariant, type ButtonSize } from './button-class'

export function Spinner({ className }: { className?: string }) {
  return <span aria-hidden className={cx('spinner', className)} />
}

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  size?: ButtonSize
  loading?: boolean
  loadingText?: string
  icon?: ReactNode
  shortcut?: string
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = 'secondary', size = 'md', loading = false, loadingText, icon, shortcut, className, children, disabled, type = 'button', ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      aria-keyshortcuts={shortcut}
      className={buttonClass(variant, size, className)}
      {...rest}
    >
      {loading ? <Spinner /> : icon}
      <span>{loading && loadingText ? loadingText : children}</span>
      {shortcut && !loading ? (
        <kbd className="ml-1 rounded-sm border border-current px-1 font-mono text-eyebrow leading-4 opacity-60" aria-hidden>
          {shortcut}
        </kbd>
      ) : null}
    </button>
  )
})

export interface LinkButtonProps extends AnchorHTMLAttributes<HTMLAnchorElement> {
  href: string
  variant?: ButtonVariant
  size?: ButtonSize
  icon?: ReactNode
  external?: boolean
}

export function LinkButton({ href, variant = 'secondary', size = 'md', icon, external, className, children, ...rest }: LinkButtonProps) {
  if (external) {
    return (
      <a href={href} target="_blank" rel="noreferrer noopener" className={buttonClass(variant, size, className)} {...rest}>
        {icon}
        <span>{children}</span>
      </a>
    )
  }
  return (
    <Link href={href} className={buttonClass(variant, size, className)} {...rest}>
      {icon}
      <span>{children}</span>
    </Link>
  )
}
