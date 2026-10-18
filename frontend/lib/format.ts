/**
 * Formatting rules (PRD 13.9b; spec C, C-AC-42). Every date, number, duration and long id on screen goes
 * through these helpers.
 */

const numberFormat = new Intl.NumberFormat('en-GB')
const compactFormat = new Intl.NumberFormat('en-GB', { notation: 'compact', maximumFractionDigits: 1 })
const usdFormat = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})
const exactFormat = new Intl.DateTimeFormat('en-GB', {
  weekday: 'short',
  day: 'numeric',
  month: 'short',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
})
const clockFormat = new Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
const dayFormat = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })

function toDate(value: string | number | Date): Date {
  return value instanceof Date ? value : new Date(value)
}

/** "just now", "4 min ago", "2 h ago", "3 days ago", then a date. */
export function relativeTime(value: string | number | Date, now: number = Date.now()): string {
  const then = toDate(value).getTime()
  if (Number.isNaN(then)) return 'unknown time'
  const seconds = Math.round((now - then) / 1000)
  if (seconds < 0) {
    const ahead = -seconds
    if (ahead < 60) return 'in a moment'
    if (ahead < 3600) return `in ${Math.round(ahead / 60)} min`
    return `in ${Math.round(ahead / 3600)} h`
  }
  if (seconds < 45) return 'just now'
  if (seconds < 3600) return `${Math.max(1, Math.round(seconds / 60))} min ago`
  if (seconds < 86400) return `${Math.round(seconds / 3600)} h ago`
  const days = Math.round(seconds / 86400)
  if (days === 1) return 'yesterday'
  if (days < 14) return `${days} days ago`
  return dayFormat.format(toDate(value))
}

/** Uppercase compact form for mono status labels: "2M AGO", "JUST NOW". */
export function relativeTimeShort(value: string | number | Date, now: number = Date.now()): string {
  const then = toDate(value).getTime()
  if (Number.isNaN(then)) return '—'
  const seconds = Math.max(0, Math.round((now - then) / 1000))
  if (seconds < 45) return 'JUST NOW'
  if (seconds < 3600) return `${Math.max(1, Math.round(seconds / 60))}M AGO`
  if (seconds < 86400) return `${Math.round(seconds / 3600)}H AGO`
  return `${Math.round(seconds / 86400)}D AGO`
}

/** Exact local time for tooltips. */
export function exactTime(value: string | number | Date): string {
  const date = toDate(value)
  if (Number.isNaN(date.getTime())) return 'Unknown time'
  return exactFormat.format(date)
}

/** Mono timestamp for timelines: "09:12:03". */
export function clockTime(value: string | number | Date): string {
  const date = toDate(value)
  if (Number.isNaN(date.getTime())) return '--:--:--'
  return clockFormat.format(date)
}

export function shortDate(value: string | number | Date): string {
  const date = toDate(value)
  if (Number.isNaN(date.getTime())) return 'Unknown date'
  return dayFormat.format(date)
}

/** Thousands separators: 41,203. */
export function formatNumber(value: number): string {
  if (!Number.isFinite(value)) return '—'
  return numberFormat.format(value)
}

export function formatCompact(value: number): string {
  if (!Number.isFinite(value)) return '—'
  return compactFormat.format(value)
}

/** "2m 14s", "1h 03m", "840 ms". */
export function formatDuration(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return '—'
  if (ms < 1000) return `${Math.round(ms)} ms`
  const totalSeconds = Math.round(ms / 1000)
  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const seconds = totalSeconds % 60
  if (hours > 0) return `${hours}h ${String(minutes).padStart(2, '0')}m`
  if (minutes > 0) return `${minutes}m ${String(seconds).padStart(2, '0')}s`
  return `${seconds}s`
}

export function formatUsd(value: number): string {
  if (!Number.isFinite(value)) return '—'
  if (value > 0 && value < 0.01) return '<$0.01'
  return usdFormat.format(value)
}

export function formatTokens(tokens: { input: number; output: number }): string {
  return `${formatCompact(tokens.input + tokens.output)} tokens`
}

export function formatPercent(value: number, digits = 0): string {
  if (!Number.isFinite(value)) return '—'
  return `${value.toFixed(digits)}%`
}

/** Middle truncation keeps both ends of ids and paths: "src/nrepl/…/evaluate.ts". */
export function truncateMiddle(text: string, max: number): string {
  if (max < 5 || text.length <= max) return text
  const keep = max - 1
  const head = Math.ceil(keep / 2)
  const tail = Math.floor(keep / 2)
  return `${text.slice(0, head)}…${text.slice(text.length - tail)}`
}

/** "3f2a…c91e" for hashes and SHAs. */
export function shortHash(hash: string, size = 4): string {
  if (hash.length <= size * 2 + 1) return hash
  return `${hash.slice(0, size)}…${hash.slice(-size)}`
}

export function shortSha(sha: string): string {
  return sha.slice(0, 7)
}

/** "1 test" / "14 tests". */
export function plural(count: number, one: string, many = `${one}s`): string {
  return `${formatNumber(count)} ${count === 1 ? one : many}`
}

/** Spoken-number words for headlines under ten: "Two earlier decisions…". */
const WORDS = ['No', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine']
export function countWord(count: number): string {
  return count >= 0 && count < WORDS.length ? (WORDS[count] as string) : formatNumber(count)
}

export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  if (parts.length === 0) return '?'
  const first = parts[0]?.[0] ?? ''
  const last = parts.length > 1 ? (parts[parts.length - 1]?.[0] ?? '') : ''
  return (first + last).toUpperCase()
}

/** Request ids are long ULIDs; the eyebrow shows the last six characters. */
export function shortRequestId(id: string): string {
  const core = id.replace(/^req_/, '')
  return core.slice(-6).toUpperCase()
}
