/**
 * Toast queue (PROMPT 8.7): bottom-right, at most three visible, auto-dismiss after 6 s except errors and
 * "needs you" toasts, which stay until dismissed.
 */
import { create } from 'zustand'

export type ToastKind = 'info' | 'success' | 'error' | 'needs_you'

export interface ToastAction {
  label: string
  href?: string
  onClick?: () => void
}

export interface Toast {
  id: string
  kind: ToastKind
  title: string
  body?: string
  action?: ToastAction
  /** Cross-surface delivery line: "Approved in Slack by Dana. Build started." */
  delivery?: string
  createdAt: number
}

export const MAX_VISIBLE = 3
export const AUTO_DISMISS_MS = 6000

export function persists(kind: ToastKind): boolean {
  return kind === 'error' || kind === 'needs_you'
}

interface ToastState {
  toasts: Toast[]
  push: (toast: Omit<Toast, 'id' | 'createdAt'> & { id?: string }) => string
  dismiss: (id: string) => void
  clear: () => void
}

let counter = 0

export const useToasts = create<ToastState>((set) => ({
  toasts: [],
  push: (toast) => {
    counter += 1
    const id = toast.id ?? `t${Date.now().toString(36)}${counter}`
    set((s) => {
      const without = s.toasts.filter((t) => t.id !== id)
      return { toasts: [...without, { ...toast, id, createdAt: Date.now() }] }
    })
    return id
  },
  dismiss: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
  clear: () => set({ toasts: [] }),
}))

/** The three newest toasts, newest last (it sits at the bottom of the stack). */
export function visibleToasts(toasts: readonly Toast[]): Toast[] {
  return toasts.slice(-MAX_VISIBLE)
}

export const toast = {
  info: (title: string, rest: Partial<Omit<Toast, 'id' | 'kind' | 'title'>> = {}) => useToasts.getState().push({ kind: 'info', title, ...rest }),
  success: (title: string, rest: Partial<Omit<Toast, 'id' | 'kind' | 'title'>> = {}) =>
    useToasts.getState().push({ kind: 'success', title, ...rest }),
  error: (title: string, rest: Partial<Omit<Toast, 'id' | 'kind' | 'title'>> = {}) => useToasts.getState().push({ kind: 'error', title, ...rest }),
  needsYou: (title: string, rest: Partial<Omit<Toast, 'id' | 'kind' | 'title'>> = {}) =>
    useToasts.getState().push({ kind: 'needs_you', title, ...rest }),
}
