'use client'
import { useEffect, useId, useRef, type ReactNode } from 'react'
import { X } from '@phosphor-icons/react/dist/ssr'
import { cx } from './cx'

export interface DialogProps {
  open: boolean
  onClose: () => void
  title: ReactNode
  label?: ReactNode
  children: ReactNode
  footer?: ReactNode
  className?: string
  /** Side panel (setup guides) instead of a centred modal. */
  variant?: 'modal' | 'panel'
  initialFocus?: React.RefObject<HTMLElement | null>
}

/**
 * Native <dialog> with showModal(): focus is trapped and Esc closes. Focus returns to the opener on close.
 */
export function Dialog({ open, onClose, title, label, children, footer, className, variant = 'modal', initialFocus }: DialogProps) {
  const ref = useRef<HTMLDialogElement>(null)
  const opener = useRef<Element | null>(null)
  const titleId = useId()

  useEffect(() => {
    const dialog = ref.current
    if (!dialog) return
    if (open && !dialog.open) {
      opener.current = document.activeElement
      dialog.showModal()
      requestAnimationFrame(() => initialFocus?.current?.focus())
    } else if (!open && dialog.open) {
      dialog.close()
      if (opener.current instanceof HTMLElement) opener.current.focus()
    }
  }, [open, initialFocus])

  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      onCancel={(e) => {
        e.preventDefault()
        onClose()
      }}
      onClick={(e) => {
        if (e.target === ref.current) onClose()
      }}
      className={cx(
        'overscroll-contain bg-ink-2 text-fg-1 shadow-overlay backdrop:bg-ink-0/70',
        variant === 'modal'
          ? 'm-auto w-full max-w-lg rounded-lg border border-line-2 p-0'
          : 'ml-auto mr-0 h-dvh max-h-dvh w-guide max-w-full rounded-none border-l border-line-2 p-0',
        className,
      )}
    >
      {open ? (
        <div className={cx('flex flex-col', variant === 'panel' && 'h-full')}>
          <div className="flex items-start justify-between gap-4 border-b border-line-1 px-6 py-4">
            <div className="flex flex-col gap-1">
              {label ? <span className="eyebrow">{label}</span> : null}
              <h2 id={titleId} className="display text-title-sm text-fg-1">
                {title}
              </h2>
            </div>
            <button
              type="button"
              onClick={onClose}
              aria-label="Close"
              className="press -mr-2 inline-flex size-8 items-center justify-center rounded-md text-fg-2 hover:bg-ink-3 hover:text-fg-1"
            >
              <X size={16} aria-hidden />
            </button>
          </div>
          <div className={cx('relative px-6 py-5', variant === 'panel' && 'min-h-0 flex-1 overflow-y-auto overscroll-contain')}>{children}</div>
          {footer ? <div className="flex items-center justify-end gap-2 border-t border-line-1 px-6 py-4">{footer}</div> : null}
        </div>
      ) : null}
    </dialog>
  )
}
