'use client'
import { useEffect, type RefObject } from 'react'
import { isTypingTarget } from '../shortcuts'

/** `j` / `k` move focus through `[data-row]` items inside the container; Enter follows the focused link. */
export function useListKeys(container: RefObject<HTMLElement | null>, enabled = true) {
  useEffect(() => {
    if (!enabled) return
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey || isTypingTarget(e.target)) return
      if (document.querySelector('dialog[open]')) return
      if (e.key !== 'j' && e.key !== 'k') return
      const root = container.current
      if (!root) return
      const rows = Array.from(root.querySelectorAll<HTMLElement>('[data-row]'))
      if (rows.length === 0) return
      e.preventDefault()
      const index = rows.findIndex((r) => r === document.activeElement || r.contains(document.activeElement))
      const next = e.key === 'j' ? Math.min(rows.length - 1, index + 1) : Math.max(0, index === -1 ? 0 : index - 1)
      rows[next]?.focus()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [container, enabled])
}
