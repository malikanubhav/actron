/**
 * Command palette logic (PROMPT 8.7): fuzzy matching, recent items first, commands for screens, requests,
 * graph nodes and actions.
 */
import type { RequestSummary, SearchResult } from './api/types'

export type CommandKind = 'screen' | 'request' | 'node' | 'action'

export interface Command {
  id: string
  kind: CommandKind
  title: string
  subtitle?: string
  href?: string
  /** Action commands run this instead of navigating. */
  action?: 'new-request' | 'sync-now' | 'approve-current' | 'shortcuts' | 'sign-out'
  keywords?: string[]
  shortcut?: string
}

export const SCREEN_COMMANDS: Command[] = [
  { id: 'screen:home', kind: 'screen', title: 'Home', subtitle: 'Requests that need you, running and done', href: '/app', shortcut: 'G H' },
  { id: 'screen:inbox', kind: 'screen', title: 'Inbox', subtitle: 'Everything that needs you', href: '/app/inbox', shortcut: 'G I' },
  { id: 'screen:graph', kind: 'screen', title: 'Graph', subtitle: 'Explore the memory', href: '/app/graph', shortcut: 'G G' },
  { id: 'screen:system', kind: 'screen', title: 'System', subtitle: 'What Actron is doing right now', href: '/app/system' },
  { id: 'screen:connect', kind: 'screen', title: 'Connect', subtitle: 'Sources and memory', href: '/app/connect' },
  { id: 'screen:settings', kind: 'screen', title: 'Settings', subtitle: 'Models, thresholds, approvers', href: '/app/settings' },
]

export const ACTION_COMMANDS: Command[] = [
  { id: 'action:new', kind: 'action', title: 'New request', subtitle: 'Ask Actron for a change or a question', action: 'new-request', shortcut: 'N', keywords: ['ask', 'create'] },
  { id: 'action:sync', kind: 'action', title: 'Sync now', subtitle: 'Read new data from every connected source', action: 'sync-now', keywords: ['refresh', 'ingest'] },
  { id: 'action:shortcuts', kind: 'action', title: 'Keyboard shortcuts', subtitle: 'Show every shortcut', action: 'shortcuts', shortcut: '?' },
]

export const APPROVE_COMMAND: Command = {
  id: 'action:approve',
  kind: 'action',
  title: 'Approve current',
  subtitle: 'Approve the ticket or pull request on this page',
  action: 'approve-current',
  shortcut: 'A',
}

export function requestCommand(r: RequestSummary): Command {
  return {
    id: `request:${r.id}`,
    kind: 'request',
    title: r.title,
    subtitle: `${r.state} · ${r.requester.name}`,
    href: `/app/requests/${r.id}`,
    keywords: [r.id, r.kind, r.state],
  }
}

export function nodeCommand(n: SearchResult): Command {
  return {
    id: `node:${n.id}`,
    kind: 'node',
    title: n.label,
    subtitle: `${n.type}${n.snippet ? ` · ${n.snippet}` : ''}`,
    href: `/app/graph?node=${encodeURIComponent(n.id)}`,
    keywords: [n.type, n.id],
  }
}

/**
 * Subsequence fuzzy score: higher is better, null when not all query characters appear in order.
 * Bonuses for word starts, consecutive runs and prefix matches.
 */
export function fuzzyScore(query: string, text: string): number | null {
  const q = query.trim().toLowerCase()
  if (!q) return 0
  const t = text.toLowerCase()
  if (t === q) return 1000
  if (t.startsWith(q)) return 800 - t.length
  const contiguous = t.indexOf(q)
  if (contiguous >= 0) return 600 - contiguous - t.length / 10
  let score = 0
  let ti = 0
  let run = 0
  for (const ch of q) {
    if (ch === ' ') continue
    const found = t.indexOf(ch, ti)
    if (found === -1) return null
    const wordStart = found === 0 || /[\s/._:-]/.test(t[found - 1] ?? '')
    run = found === ti ? run + 1 : 0
    score += 10 + (wordStart ? 15 : 0) + run * 5 - Math.min(10, found - ti)
    ti = found + 1
  }
  return score
}

export function commandScore(query: string, command: Command): number | null {
  const fields = [command.title, command.subtitle ?? '', ...(command.keywords ?? [])]
  let best: number | null = null
  fields.forEach((f, i) => {
    const s = fuzzyScore(query, f)
    if (s === null) return
    const weighted = i === 0 ? s : s * 0.6
    if (best === null || weighted > best) best = weighted
  })
  return best
}

/** Filter and rank. With no query, recent items come first, then the rest in their given order. */
export function rankCommands(query: string, commands: readonly Command[], recent: readonly string[] = []): Command[] {
  const q = query.trim()
  if (!q) {
    const recentSet = new Map(recent.map((id, i) => [id, i]))
    const withRecent = commands.filter((c) => recentSet.has(c.id)).sort((a, b) => (recentSet.get(a.id) ?? 0) - (recentSet.get(b.id) ?? 0))
    return [...withRecent, ...commands.filter((c) => !recentSet.has(c.id))]
  }
  const recentBoost = new Map(recent.map((id, i) => [id, 50 - i * 5]))
  return commands
    .map((c) => ({ c, s: commandScore(q, c) }))
    .filter((x): x is { c: Command; s: number } => x.s !== null)
    .map((x) => ({ ...x, s: x.s + (recentBoost.get(x.c.id) ?? 0) }))
    .sort((a, b) => b.s - a.s)
    .map((x) => x.c)
}

const RECENT_KEY = 'actron.palette.recent'

export function readRecent(): string[] {
  try {
    const raw = window.localStorage.getItem(RECENT_KEY)
    const parsed: unknown = raw ? JSON.parse(raw) : []
    return Array.isArray(parsed) ? parsed.filter((x): x is string => typeof x === 'string') : []
  } catch {
    return []
  }
}

export function pushRecent(id: string, limit = 8): string[] {
  const next = [id, ...readRecent().filter((x) => x !== id)].slice(0, limit)
  try {
    window.localStorage.setItem(RECENT_KEY, JSON.stringify(next))
  } catch {
    // Storage unavailable; recents last for this session only.
  }
  return next
}
