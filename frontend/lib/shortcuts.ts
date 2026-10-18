/**
 * Keyboard shortcuts (PROMPT 8.7): `g h` home, `g i` inbox, `g g` graph, `n` new request, `a` approve (with
 * confirmation), `?` shortcut sheet, Cmd/Ctrl+K palette, `j`/`k` lists.
 */
export type ShortcutAction =
  | 'go-home'
  | 'go-inbox'
  | 'go-graph'
  | 'go-system'
  | 'go-connect'
  | 'go-settings'
  | 'new-request'
  | 'approve'
  | 'shortcuts'
  | 'palette'

export const SHORTCUTS: { keys: string; action: ShortcutAction; label: string }[] = [
  { keys: 'mod+k', action: 'palette', label: 'Open the command palette' },
  { keys: 'g h', action: 'go-home', label: 'Go to Home' },
  { keys: 'g i', action: 'go-inbox', label: 'Go to Inbox' },
  { keys: 'g g', action: 'go-graph', label: 'Go to Graph' },
  { keys: 'g s', action: 'go-system', label: 'Go to System' },
  { keys: 'g c', action: 'go-connect', label: 'Go to Connect' },
  { keys: 'n', action: 'new-request', label: 'New request' },
  { keys: 'a', action: 'approve', label: 'Approve the ticket or PR on this page (asks to confirm)' },
  { keys: '?', action: 'shortcuts', label: 'Show keyboard shortcuts' },
]

export const LIST_SHORTCUTS = [
  { keys: 'j', label: 'Next item' },
  { keys: 'k', label: 'Previous item' },
  { keys: 'enter', label: 'Open the item' },
]

export const SEQUENCE_TIMEOUT_MS = 1200

export interface KeyLike {
  key: string
  metaKey?: boolean
  ctrlKey?: boolean
  altKey?: boolean
  shiftKey?: boolean
  target?: EventTarget | null
}

/** True when the event comes from a field where typing must not trigger shortcuts. */
export function isTypingTarget(target: EventTarget | null | undefined): boolean {
  if (!target || typeof (target as HTMLElement).tagName !== 'string') return false
  const el = target as HTMLElement
  const tag = el.tagName.toLowerCase()
  if (tag === 'input' || tag === 'textarea' || tag === 'select') return true
  return el.isContentEditable === true
}

/**
 * A small state machine for single keys and two-key sequences. Feed key events; it returns the action when a
 * shortcut completes.
 */
export class ShortcutMatcher {
  private pending: string | null = null
  private pendingAt = 0

  constructor(private readonly now: () => number = () => Date.now()) {}

  reset(): void {
    this.pending = null
  }

  feed(e: KeyLike): ShortcutAction | null {
    const key = e.key.length === 1 ? e.key.toLowerCase() : e.key
    if ((e.metaKey || e.ctrlKey) && key === 'k') {
      this.pending = null
      return 'palette'
    }
    if (e.metaKey || e.ctrlKey || e.altKey) return null
    if (isTypingTarget(e.target)) return null
    const t = this.now()
    if (this.pending && t - this.pendingAt <= SEQUENCE_TIMEOUT_MS) {
      const combo = `${this.pending} ${key}`
      this.pending = null
      const hit = SHORTCUTS.find((s) => s.keys === combo)
      if (hit) return hit.action
    }
    this.pending = null
    if (key === 'g') {
      this.pending = 'g'
      this.pendingAt = t
      return null
    }
    if (e.key === '?') return 'shortcuts'
    const single = SHORTCUTS.find((s) => s.keys === key)
    return single ? single.action : null
  }
}

export function hrefFor(action: ShortcutAction): string | null {
  switch (action) {
    case 'go-home':
      return '/app'
    case 'go-inbox':
      return '/app/inbox'
    case 'go-graph':
      return '/app/graph'
    case 'go-system':
      return '/app/system'
    case 'go-connect':
      return '/app/connect'
    case 'go-settings':
      return '/app/settings'
    default:
      return null
  }
}
