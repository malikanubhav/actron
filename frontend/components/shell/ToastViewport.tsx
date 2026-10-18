'use client'
import Link from 'next/link'
import { useEffect } from 'react'
import { X } from '@phosphor-icons/react/dist/ssr'
import { AUTO_DISMISS_MS, persists, useToasts, visibleToasts, type Toast } from '@/lib/toasts'
import { Glyph } from '../glyphs/Glyph'
import type { GlyphName } from '../glyphs/names'
import { cx } from '../ui/cx'

const GLYPH: Record<Toast['kind'], GlyphName> = {
  info: 'Request',
  success: 'TestPass',
  error: 'TestFail',
  needs_you: 'Question',
}

function ToastItem({ toast }: { toast: Toast }) {
  const dismiss = useToasts((s) => s.dismiss)
  useEffect(() => {
    if (persists(toast.kind)) return
    const t = setTimeout(() => dismiss(toast.id), AUTO_DISMISS_MS)
    return () => clearTimeout(t)
  }, [toast.id, toast.kind, dismiss])
  return (
    <li
      role={toast.kind === 'error' ? 'alert' : 'status'}
      data-testid="toast"
      data-kind={toast.kind}
      className={cx(
        'enter pointer-events-auto flex w-96 items-start gap-3 rounded-lg border bg-ink-2 px-4 py-3 shadow-overlay',
        toast.kind === 'error' ? 'border-state-conflict/50' : toast.kind === 'needs_you' ? 'border-accent/60' : 'border-line-2',
      )}
    >
      <span
        className={cx(
          'mt-0.5',
          toast.kind === 'error' ? 'text-state-conflict' : toast.kind === 'needs_you' ? 'text-accent' : toast.kind === 'success' ? 'text-state-ok' : 'text-fg-2',
        )}
      >
        <Glyph name={GLYPH[toast.kind]} size={16} />
      </span>
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <p className="text-small font-medium text-fg-1">{toast.title}</p>
        {toast.body ? <p className="text-caption text-fg-2">{toast.body}</p> : null}
        {toast.delivery ? <p className="text-caption text-fg-3">{toast.delivery}</p> : null}
        {toast.action ? (
          <div className="pt-1">
            {toast.action.href ? (
              <Link href={toast.action.href} onClick={() => dismiss(toast.id)} className="text-caption font-medium text-fg-1 underline">
                {toast.action.label}
              </Link>
            ) : (
              <button
                type="button"
                onClick={() => {
                  toast.action?.onClick?.()
                  dismiss(toast.id)
                }}
                className="text-caption font-medium text-fg-1 underline"
              >
                {toast.action.label}
              </button>
            )}
          </div>
        ) : null}
      </div>
      <button
        type="button"
        onClick={() => dismiss(toast.id)}
        aria-label="Dismiss"
        className="press -mr-1 inline-flex size-6 items-center justify-center rounded-sm text-fg-3 hover:bg-ink-3 hover:text-fg-1"
      >
        <X size={12} aria-hidden />
      </button>
    </li>
  )
}

/** Bottom-right, stacked, at most three (PROMPT 8.7). */
export function ToastViewport() {
  const toasts = useToasts((s) => s.toasts)
  const shown = visibleToasts(toasts)
  return (
    <ol aria-label="Notifications" className="pointer-events-none fixed bottom-12 right-6 z-50 flex flex-col items-end gap-2">
      {shown.map((t) => (
        <ToastItem key={t.id} toast={t} />
      ))}
    </ol>
  )
}
