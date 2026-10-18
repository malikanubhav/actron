/**
 * Pure logic for the connector forms (spec C, C12): which fields show, client-side checks, payloads, and the
 * Connect screen headline. The form renders only what GET /api/connectors defines; nothing here names a field.
 */
import type { ConnectionView, ConnectorCheck, ConnectorDefinition, FormField, IngestionStatus, SyncState } from '@/lib/api/types'
import { formatNumber, relativeTime } from '@/lib/format'

export type FieldValue = string | string[] | number | File | null
export type Values = Record<string, FieldValue>
export type SlackPath = 'oauth' | 'token'

export interface FormState {
  /** The last "Check connection" succeeded for the current values. */
  validated: boolean
  /** An OAuth round trip finished (Slack "Add to Slack"). */
  oauthOk: boolean
  /** Which path the user chose when OAuth is offered. */
  path: SlackPath
}

export function initialValues(def: ConnectorDefinition): Values {
  const values: Values = {}
  for (const f of def.fields) {
    if (f.ui_component === 'multiselect') values[f.field_id] = []
    else if (f.default !== undefined && f.default !== null) values[f.field_id] = f.default
    else if (f.type === 'file') values[f.field_id] = null
    else values[f.field_id] = ''
  }
  return values
}

export function hasValue(value: FieldValue | undefined): boolean {
  if (value === null || value === undefined) return false
  if (Array.isArray(value)) return value.length > 0
  if (typeof value === 'number') return Number.isFinite(value)
  if (typeof value === 'string') return value.trim().length > 0
  return true
}

export const isInputField = (f: FormField) =>
  !['info', 'webhookPanel', 'manifestPanel', 'oauthButton'].includes(f.ui_component) && f.type !== 'info' && f.type !== 'oauth'

export function oauthEnabled(def: ConnectorDefinition): boolean {
  return Boolean(def.oauth?.enabled) && def.fields.some((f) => f.ui_component === 'oauthButton')
}

/** Whether a field belongs to the path the user is on. */
function onPath(field: FormField, def: ConnectorDefinition, state: FormState): boolean {
  if (!oauthEnabled(def)) return field.path !== 'oauth'
  if (field.path === 'oauth') return false // the button renders in the path chooser
  if (field.path === 'token') return state.path === 'token'
  return true
}

/**
 * Visible fields: a field with `dependsOn` shows only after the form validated (or OAuth finished) and, when its
 * parent is itself dependent, after the parent has a value.
 */
export function visibleFields(def: ConnectorDefinition, values: Values, state: FormState): FormField[] {
  const byId = new Map(def.fields.map((f) => [f.field_id, f]))
  const unlocked = state.validated || state.oauthOk
  const visible = (field: FormField, depth = 0): boolean => {
    if (depth > 8) return false
    if (!onPath(field, def, state)) return false
    if (!field.dependsOn) return true
    if (!unlocked) return false
    const parent = byId.get(field.dependsOn)
    if (!parent) return true
    if (parent.path === 'token' && state.oauthOk && state.path === 'oauth') return true
    if (!parent.dependsOn) return true
    return visible(parent, depth + 1) && hasValue(values[parent.field_id])
  }
  return def.fields.filter((f) => visible(f))
}

/** Fields "Check connection" sends: root inputs on the current path (the ones that unlock the rest). */
export function rootFields(def: ConnectorDefinition, state: FormState): FormField[] {
  return def.fields.filter((f) => isInputField(f) && !f.dependsOn && onPath(f, def, state) && f.type !== 'file')
}

/** Prefix a secret must start with, read from its placeholder ("xoxb-…" → "xoxb-"). */
export function placeholderPrefix(field: FormField): string | null {
  const p = field.placeholder ?? ''
  if (!p.endsWith('…')) return null
  const prefix = p.slice(0, -1)
  return /[-_]$/.test(prefix) ? prefix : null
}

/** Inline client-side checks, phrased plainly. Returns null when the value is fine. */
export function fieldError(field: FormField, value: FieldValue | undefined): string | null {
  if (!isInputField(field)) return null
  if (!hasValue(value)) return field.required ? `Enter the ${field.label.toLowerCase()}.` : null
  if (typeof value === 'string') {
    const v = value.trim()
    const prefix = placeholderPrefix(field)
    if (prefix && !v.startsWith(prefix)) return `This should start with ${prefix}`
    if (field.placeholder === 'owner/name' && !/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(v)) return 'Use the form owner/name.'
  }
  if (typeof value === 'number' && field.ui_component === 'stepper') {
    const min = field.min ?? 1
    const max = field.max ?? 3650
    if (value < min || value > max) return `Choose between ${min} and ${max} days.`
  }
  if (value instanceof File) {
    const accept = field.accept?.split(',').map((a) => a.trim().toLowerCase()) ?? []
    if (accept.length && !accept.some((ext) => value.name.toLowerCase().endsWith(ext))) return `Choose a ${accept.join(' or ')} file.`
    if (field.maxSizeMb && value.size > field.maxSizeMb * 1024 * 1024) return `The file is larger than ${field.maxSizeMb} MB.`
  }
  return null
}

export function needsValidation(def: ConnectorDefinition, state: FormState): boolean {
  if (state.oauthOk && state.path === 'oauth') return false
  return rootFields(def, state).some((f) => f.required) && def.fields.some((f) => f.dependsOn)
}

export function canCheck(def: ConnectorDefinition, values: Values, state: FormState): boolean {
  const roots = rootFields(def, state)
  return roots.length > 0 && roots.every((f) => fieldError(f, values[f.field_id]) === null)
}

export function canSubmit(def: ConnectorDefinition, values: Values, state: FormState): boolean {
  if (needsValidation(def, state) && !state.validated) return false
  if (oauthEnabled(def) && state.path === 'oauth' && !state.oauthOk) return false
  return visibleFields(def, values, state).every((f) => fieldError(f, values[f.field_id]) === null)
}

/** Non-secret values become config; secrets go separately and are never shown again. */
export function buildPayload(def: ConnectorDefinition, values: Values, state: FormState) {
  const config: Record<string, unknown> = {}
  const secret: Record<string, string> = {}
  for (const f of visibleFields(def, values, state)) {
    if (!isInputField(f) || f.type === 'file') continue
    const v = values[f.field_id]
    if (!hasValue(v)) continue
    if (f.is_secret) secret[f.field_id] = String(v).trim()
    else config[f.field_id] = typeof v === 'string' ? v.trim() : v
  }
  if (oauthEnabled(def)) config.via = state.path
  return { config, secret }
}

/** Values the options endpoint receives: non-secret strings only (secrets never go in a URL). */
export function optionQuery(def: ConnectorDefinition, values: Values): Record<string, string> {
  const out: Record<string, string> = {}
  for (const f of def.fields) {
    if (f.is_secret || !isInputField(f)) continue
    const v = values[f.field_id]
    if (typeof v === 'string' && v.trim()) out[f.field_id] = v.trim()
    else if (Array.isArray(v) && v.length) out[f.field_id] = v.join(',')
  }
  return out
}

/* ------------------------------------------------------------------ connections and headline */

export const SOURCE_ORDER = ['github', 'slack', 'linear', 'slack_export'] as const

/** Worst first: the card shows the state that needs attention. */
const STATE_RANK: Record<SyncState, number> = {
  FAILED: 0,
  PARTIAL: 1,
  BACKFILLING: 2,
  SYNCING: 3,
  'UP TO DATE': 4,
  'NOT CONNECTED': 5,
}

/**
 * The connection a source card shows. The repository form creates two rows (`code` and `github`, spec A, A11);
 * the GitHub card shows them as one: the worse state with its reason, both sets of counts, and the github row's id
 * (Sync now and Disconnect act on both server side).
 */
export function connectionFor(provider: string, connections: readonly ConnectionView[]): ConnectionView | undefined {
  if (provider !== 'github') return connections.find((c) => c.provider === provider && c.status !== 'disconnected')
  const rows = connections.filter((c) => (c.provider === 'github' || c.provider === 'code') && c.status !== 'disconnected')
  if (rows.length < 2) return rows[0]
  const github = rows.find((c) => c.provider === 'github') ?? rows[0]!
  const worst = [...rows].sort((a, b) => STATE_RANK[a.sync.state] - STATE_RANK[b.sync.state])[0]!
  const synced = rows.map((c) => c.sync.lastSyncedAt)
  return {
    ...github,
    status: rows.some((c) => c.status === 'error') ? 'error' : github.status,
    sync: {
      state: worst.sync.state,
      reason: worst.sync.reason ?? rows.find((c) => c.sync.reason)?.sync.reason ?? null,
      lastSyncedAt: synced.every(Boolean) ? [...(synced as string[])].sort()[0]! : null,
      perMinute: rows.reduce((n, c) => n + (c.sync.perMinute ?? 0), 0),
      counts: Object.assign({}, ...rows.map((c) => c.sync.counts)) as Record<string, number>,
    },
  }
}

export function syncState(connection: ConnectionView | undefined): SyncState {
  return connection ? connection.sync.state : 'NOT CONNECTED'
}

/**
 * One name per connection row. The repository form creates two rows that read the same repository in different
 * ways, so each gets its own name and a one-line description.
 */
const CONNECTION_NAMES: Record<string, string> = {
  code: 'Code (git)',
  github: 'GitHub API',
  slack: 'Slack',
  linear: 'Linear',
  slack_export: 'Slack export',
}

const CONNECTION_ABOUT: Record<string, string> = {
  code: 'Files, functions and commits from the working branch, read with git.',
  github: 'Pull requests, reviews, branches, labels and people, read through the GitHub API.',
  slack: 'Messages in the chosen channels; Actron also posts questions and updates there.',
  linear: 'Issues and comments from the chosen team; approved tickets are created there.',
  slack_export: 'A one-time import of an exported Slack workspace.',
}

export function connectionName(provider: string): string {
  return CONNECTION_NAMES[provider] ?? provider
}

export function connectionAbout(provider: string): string | null {
  return CONNECTION_ABOUT[provider] ?? null
}

/** The rows behind one source card: the repository card has the `code` row first, then `github`. */
export function connectionRows(provider: string, connections: readonly ConnectionView[]): ConnectionView[] {
  const live = connections.filter((c) => c.status !== 'disconnected')
  if (provider !== 'github') return live.filter((c) => c.provider === provider)
  return [...live.filter((c) => c.provider === 'code'), ...live.filter((c) => c.provider === 'github')]
}

export interface ReasonText {
  /** One or two sentences: what happened and what to do next. */
  text: string
  /** A next step the card can offer as a button. */
  action?: 'add-token'
}

/**
 * A partial or failed sync reason as plain sentences with a next step. Known reasons get their own wording; any
 * other reason keeps the provider's words (they name the item that failed) and adds "Sync again later."
 */
export function reasonSentence(provider: string, reason: string | null | undefined, counts: Record<string, number> = {}): ReasonText {
  const raw = (reason ?? '').trim()
  if (!raw) return { text: 'The provider did not say why. Sync again later.' }
  if (/rate limit/i.test(raw) && (provider === 'github' || provider === 'code')) {
    const prs = counts.GithubPullRequest ?? 0
    const after = prs > 0 ? ` after ${formatNumber(prs)} pull request${prs === 1 ? '' : 's'}` : ''
    return {
      text: `GitHub's public rate limit stopped the read${after}. Add a GitHub access token to read the full history.`,
      action: 'add-token',
    }
  }
  // Already a sentence written for people (fixtures and newer connectors): keep it.
  if (/^[A-Z]/.test(raw) && /[.?]$/.test(raw)) return { text: raw }
  return { text: `The provider reported: ${raw.replace(/[.\s]+$/, '')}. Sync again later.` }
}

const NAMES: Record<string, string> = { ...CONNECTION_NAMES, slack_export: 'The Slack export' }

export function workingBranch(connection: ConnectionView | undefined): string | null {
  if (!connection) return null
  const c = connection.config
  const v = c.workingBranch ?? c.working_branch
  return typeof v === 'string' && v ? v : null
}

export function connectHeadline(
  connections: readonly ConnectionView[],
  ingestion: Pick<IngestionStatus, 'memoryPercent'> | null | undefined,
  now: number = Date.now(),
): string {
  const active = connections.filter((c) => c.status !== 'disconnected' && c.sync.state !== 'NOT CONNECTED')
  const repo = connectionFor('github', active)
  if (active.length === 0 || !repo) return 'Connect a repository to start.'
  const percent = Math.round(ingestion?.memoryPercent ?? 0)
  const failed = active.find((c) => c.sync.state === 'FAILED')
  if (failed) return `${NAMES[failed.provider] ?? 'A source'} stopped syncing. Your memory is ${percent}% built.`
  if (active.some((c) => c.sync.state === 'BACKFILLING' || c.sync.state === 'SYNCING')) return `Your memory is ${percent}% built.`
  const partial = active.find((c) => c.sync.state === 'PARTIAL')
  // The percentage measures the history window read; a partial source skipped items inside it, so "100% built"
  // next to "partly read" would contradict itself.
  if (partial) {
    const name = NAMES[partial.provider] ?? 'One source'
    return percent >= 100 ? `Memory is built, but ${partial.provider === 'github' || partial.provider === 'slack_export' ? `the ${connectionName(partial.provider)}` : name} skipped some items.` : `Your memory is ${percent}% built. ${name} is partly read.`
  }
  const last = active
    .map((c) => (c.sync.lastSyncedAt ? Date.parse(c.sync.lastSyncedAt) : 0))
    .reduce((a, b) => Math.max(a, b), 0)
  return last ? `Memory is up to date. Last sync ${relativeTime(last, now)}.` : 'Memory is up to date.'
}

/**
 * One short sentence for the Connect purpose line, only while the headline shows a percentage: what it measures.
 * Which source is reading or skipped items is on its card, so it is not repeated here.
 */
export function memoryExplainer(ingestion: Pick<IngestionStatus, 'memoryPercent'> | null | undefined): string | null {
  const percent = ingestion?.memoryPercent ?? 0
  return percent > 0 && percent < 100 ? 'The percentage is the share of each source’s history read so far.' : null
}

/* ------------------------------------------------------------------ guide progress */

export function visibleGuideSteps(def: ConnectorDefinition, isHttps: boolean) {
  // Socket Mode is only needed without a public HTTPS address (C13, Slack step 3).
  return def.guide.filter((s) => !(isHttps && s.checkId === 'socket_mode'))
}

/** Guide steps a source works without (instant updates fall back to polling). */
export const OPTIONAL_GUIDE_STEPS: ReadonlySet<string> = new Set(['webhook_ping'])

export function guideProgress(def: ConnectorDefinition, checks: readonly ConnectorCheck[] | undefined, isHttps: boolean) {
  const steps = visibleGuideSteps(def, isHttps)
  const isDone = (s: (typeof steps)[number]) => Boolean(s.checkId && checks?.find((c) => c.id === s.checkId)?.ok === true)
  const done = steps.filter(isDone).length
  /** Steps still open that the source needs; 0 means only optional steps are left. */
  const requiredLeft = steps.filter((s) => !isDone(s) && !(s.checkId && OPTIONAL_GUIDE_STEPS.has(s.checkId))).length
  return { done, total: steps.length, requiredLeft }
}
