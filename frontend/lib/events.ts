/**
 * Event vocabulary (PROMPT appendix E; spec B, B.C2 and B.C2a; spec A, A.C6).
 * One place turns an event into: a plain timeline sentence, a glyph, and a system-map step.
 */
import type { EventEnvelope, Surface } from './api/types'
import { formatDuration, formatNumber, plural, shortSha } from './format'
import type { GlyphName } from '@/components/glyphs/names'

export const REQUEST_EVENT_TYPES = [
  'request.created',
  'investigation.started',
  'tool.called',
  'tool.result',
  'evidence.found',
  'investigation.completed',
  'question.asked',
  'answer.received',
  'ticket.revised',
  'ticket.synced',
  'approval.recorded',
  'approval.refused',
  'handoff.created',
  'build.queued',
  'build.started',
  'build.step',
  'tests.result',
  'build.repair',
  'build.failed',
  'build.passed',
  'pr.opened',
  'pr.updated',
  'review.feedback',
  'pr.approved',
  'writeback.done',
  'notification.sent',
  'request.cancelled',
  'request.done',
  'answer.ready',
  'memory.refreshing',
  'memory.refreshed',
  'memory.unverified',
  'request.state_changed',
  'judgment.made',
  'budget.reached',
] as const

export const WORKSPACE_EVENT_TYPES = [
  'ingestion.started',
  'ingestion.progress',
  'ingestion.partial',
  'ingestion.finished',
  'linking.progress',
  'linking.finished',
] as const

export const ALL_EVENT_TYPES = [...REQUEST_EVENT_TYPES, ...WORKSPACE_EVENT_TYPES] as const
export type EventType = (typeof ALL_EVENT_TYPES)[number]

export function isKnownEventType(type: string): type is EventType {
  return (ALL_EVENT_TYPES as readonly string[]).includes(type)
}

type Payload = Record<string, unknown>

const str = (value: unknown, fallback = ''): string =>
  typeof value === 'string' ? value : typeof value === 'number' ? String(value) : fallback
const num = (value: unknown, fallback = 0): number => (typeof value === 'number' && Number.isFinite(value) ? value : fallback)
const obj = (value: unknown): Payload => (value && typeof value === 'object' ? (value as Payload) : {})
const personName = (value: unknown, fallback = 'Someone'): string => {
  if (typeof value === 'string') return value
  const name = obj(value).name
  return typeof name === 'string' && name ? name : fallback
}

export function surfaceName(surface: unknown): string {
  if (surface === 'slack') return 'Slack'
  if (surface === 'ui') return 'Actron'
  return 'the system'
}

export function sourceName(source: string): string {
  switch (source) {
    case 'github':
    case 'code':
      return 'GitHub'
    case 'slack':
    case 'slack_export':
      return 'Slack'
    case 'linear':
      return 'Linear'
    default:
      return source.charAt(0).toUpperCase() + source.slice(1)
  }
}

/** Last readable segment of a graph id: "code:fn:src/evaluate.ts#evaluateCode" → "evaluateCode". */
export function idTail(id: string): string {
  const afterHash = id.includes('#') ? id.slice(id.lastIndexOf('#') + 1) : id
  const parts = afterHash.split(/[/:]/).filter(Boolean)
  return parts[parts.length - 1] ?? id
}

/** Arguments in mono, short: "evaluateCode, depth 3". */
export function shortArgs(args: unknown): string {
  const a = obj(args)
  const out: string[] = []
  for (const [key, value] of Object.entries(a)) {
    if (value === undefined || value === null) continue
    if (Array.isArray(value)) {
      const items = value.map((v) => (typeof v === 'string' ? idTail(v) : String(v)))
      out.push(items.length > 2 ? `${items.slice(0, 2).join(', ')} +${items.length - 2}` : items.join(', '))
    } else if (typeof value === 'string') {
      out.push(key === 'query' ? `"${value}"` : idTail(value))
    } else if (typeof value === 'number' || typeof value === 'boolean') {
      out.push(`${key.replace(/([A-Z])/g, ' $1').toLowerCase()} ${value}`)
    }
  }
  return out.join(', ')
}

export function toolCallLabel(tool: string, args: unknown): string {
  return `${tool}(${shortArgs(args)})`
}

const ROLE_PHRASE: Record<string, string> = {
  conflict: 'a decision that conflicts with this request',
  constraint: 'a constraint to preserve',
  impact: 'code this change reaches',
  similar_work: 'similar earlier work',
  owner: 'the people who know this code',
  test: 'a test that covers this code',
}

const OUTCOME_TEXT: Record<string, string> = {
  approved: 'PR approved and recorded in memory',
  answered: 'Question answered',
  cancelled: 'Cancelled',
  closed: 'PR closed',
}

export const STOP_REASON_TEXT: Record<string, string> = {
  scope_change: 'The change grew beyond the approved ticket.',
  tests_weakened: 'The change weakened existing tests.',
  timeout: 'The build ran past its time limit.',
  missing_fork: 'There is no push target. Add a fork in Connect.',
  missing_branch: 'The target branch no longer exists.',
  missing_identity: 'The bot identity for commits is not set.',
  memory_stale: 'Memory could not be refreshed with the latest merged code.',
  failed_after_repairs: 'Tests still failed after two repair attempts.',
}

/**
 * A backend reason in plain words: drops exception class names ("AuthError: …", "… (ExternalError).") and the
 * trailing full stop, so callers can end the sentence once.
 */
export function plainReason(text: string): string {
  return text
    .replace(/^\s*[A-Z][A-Za-z]*(Error|Exception):\s*/, '')
    .replace(/\s*\([A-Z][A-Za-z]*(Error|Exception)\)/g, '')
    .replace(/[.\s]+$/, '')
    .trim()
}

const NOTICE_TEXT: Record<string, string> = {
  needs_input: 'a question needs an answer',
  awaiting_approval: 'the ticket is ready for approval',
  build_failed: 'the build needs attention',
  pr_ready: 'the pull request is ready for review',
}

function noticeText(p: Payload): string {
  return NOTICE_TEXT[str(p.kind)] ?? (str(p.title).replace(/[.\s]+$/, '').toLowerCase() || 'something needs attention')
}

/** The event names no person, so the notice says where it went and what it said. */
function noticeWhere(p: Payload): string {
  return p.channel === 'slack_dm' ? 'Sent a Slack message' : p.channel === 'slack_thread' ? 'Posted in the Slack thread' : 'Sent an inbox notice'
}

/** Backend tool summaries say "1 results"; fix the count's grammar. */
export function plainSummary(text: string): string {
  return text.replace(/(^|[^\d.])1 (result|function|test|caller|node|item|match)(e?s)\b/g, (_m, before: string, noun: string) => `${before}1 ${noun}`)
}

/** Drops a trailing full stop so a caller can end the sentence once. */
export function noStop(text: string): string {
  return text.replace(/[.\s]+$/, '')
}

const JUDGMENT_VERB: Record<string, string> = {
  rank_candidates: 'ranked',
  needs_question: 'checked whether to ask about',
  judge_conflict: 'checked for conflicts in',
  judge_link: 'checked',
  check_link: 'checked',
}

export function stopReasonText(reason: string | null | undefined): string {
  if (!reason) return 'The build stopped.'
  return STOP_REASON_TEXT[reason] ?? reason
}

function refusalText(reason: string): string {
  switch (reason) {
    case 'stale_revision':
      return 'the ticket changed after this approval was started'
    case 'stale_head':
      return 'the pull request has newer commits'
    case 'external_edit':
      return 'the ticket was edited in Linear'
    case 'not_an_approver':
      return 'this person is not an approver'
    default:
      return reason.replace(/_/g, ' ')
  }
}

function countsText(counts: Payload): string {
  const parts: string[] = []
  const prs = num(counts.prs)
  const commits = num(counts.commits)
  const functions = num(counts.functions)
  const procedures = num(counts.procedures)
  if (prs) parts.push(plural(prs, 'PR'))
  if (commits) parts.push(plural(commits, 'commit'))
  if (functions) parts.push(plural(functions, 'function'))
  if (procedures) parts.push(plural(procedures, 'procedure'))
  return parts.length ? parts.join(', ') : 'no changes'
}

function sumCounts(counts: unknown): number {
  return Object.values(obj(counts)).reduce<number>((total, value) => total + num(value), 0)
}

/** The plain-language sentence for a timeline item. Never empty (C-AC-9). */
export function eventSentence(event: EventEnvelope): string {
  const p = event.payload as Payload
  switch (event.type) {
    case 'request.created': {
      const who = personName(p.requester, 'Someone')
      return p.source === 'slack' ? `${who} asked in Slack.` : `${who} started this request in Actron.`
    }
    case 'investigation.started':
      return p.mode === 'pipeline'
        ? 'Investigation started. No agent model is set, so Actron ran its standard graph checks.'
        : 'Investigation started. Actron is choosing graph tools.'
    case 'tool.called':
      return `Called ${toolCallLabel(str(p.tool, 'tool'), p.args)}.`
    case 'tool.result':
      return p.ok === false ? `The tool call failed: ${plainReason(str(p.error, 'no reason given'))}.` : `${noStop(plainSummary(str(p.summary, 'Tool finished')))}.`
    case 'evidence.found':
      return `Found ${ROLE_PHRASE[str(p.role)] ?? 'evidence'}.`
    case 'investigation.completed':
      return str(p.summary) || 'Investigation finished.'
    case 'question.asked':
      return `Asked: ${str(p.text, 'a question')}`
    case 'answer.received':
      return `${personName(p.by)} answered in ${surfaceName(p.surface)}: ${str(p.value)}.`
    case 'ticket.revised':
      return `Ticket v${num(p.n, 1)} written${p.by ? ` by ${personName(p.by)}` : ''}.`
    case 'ticket.synced':
      // B-AC-35: with Linear unreachable or not connected, the ticket stays in Actron and the reason is shown.
      if (p.skipped) return `Ticket v${num(p.n, 1)} kept in Actron. Not in Linear: ${str(p.reason, 'Linear did not answer')}.`
      return `Ticket synced to Linear as ${str(p.identifier, 'an issue')}.`
    case 'approval.recorded':
      return p.kind === 'pr'
        ? `${personName(p.by)} approved the pull request in ${surfaceName(p.surface)}.`
        : `${personName(p.by)} approved the ticket in ${surfaceName(p.surface)}.`
    case 'approval.refused':
      return `Approval refused: ${refusalText(str(p.reason, 'unknown'))}.`
    case 'handoff.created':
      return `Handed ${plural(num(p.evidenceCount), 'piece', 'pieces')} of evidence to the build.`
    case 'build.queued':
      return `Build queued at position ${num(p.position, 1)}.`
    case 'build.started':
      return `Build started on ${str(p.branch, 'a new branch')} from ${shortSha(str(p.baseSha, 'unknown'))}.`
    case 'build.step':
      return str(p.text) || 'Build step.'
    case 'tests.result': {
      const passed = num(p.passed)
      const failed = num(p.failed)
      const total = passed + failed
      return failed ? `${passed} of ${total} tests passed. ${failed} failed.` : `${passed} of ${total} tests passed.`
    }
    case 'build.repair':
      return `Repair attempt ${num(p.attempt, 1)}: ${str(p.reason, 'fixing failing tests')}.`
    case 'build.failed':
      return `The build failed. ${stopReasonText(str(p.reason))}`
    case 'build.passed':
      return `The build passed at ${shortSha(str(p.headSha, 'unknown'))}.`
    case 'pr.opened':
      return `Opened PR #${num(p.number)}.`
    case 'pr.updated':
      return `PR #${num(p.number)} updated to ${shortSha(str(p.headSha, 'unknown'))}.`
    case 'review.feedback':
      return p.kind === 'question'
        ? `${personName(p.by)} asked about the PR: ${str(p.text)}`
        : `${personName(p.by)} requested changes: ${str(p.text)}`
    case 'pr.approved':
      return `${personName(p.by)} approved the PR at ${shortSha(str(p.headSha, 'unknown'))} in ${surfaceName(p.surface)}.`
    case 'writeback.done':
      return `Memory updated: ${countsText(obj(p.counts))}.`
    case 'notification.sent': {
      return `${noticeWhere(p)}: ${noticeText(p)}.`
    }
    case 'request.cancelled':
      return `Cancelled by ${personName(p.by)}${p.reason ? `: ${str(p.reason)}` : ''}.`
    case 'request.done':
      return `Done. ${OUTCOME_TEXT[str(p.outcome)] ?? 'Finished'}.`
    case 'answer.ready':
      return 'The answer is ready, with its sources.'
    case 'memory.refreshing':
      return 'Updating memory with the latest merged code.'
    case 'memory.refreshed':
      return num(p.functionsChanged) === 0
        ? `Memory is current at ${shortSha(str(p.sha, 'unknown'))}; no functions changed.`
        : `Memory is current at ${shortSha(str(p.sha, 'unknown'))}; ${plural(num(p.functionsChanged), 'function')} changed.`
    case 'memory.unverified':
      return `Memory could not be checked: ${plainReason(str(p.reason, 'no reason given'))}.`
    case 'request.state_changed':
      return `Now ${str(p.to, 'in a new state').toLowerCase()}.`
    case 'judgment.made': {
      const verb = JUDGMENT_VERB[str(p.job)] ?? 'judged'
      const count = num(p.count)
      const noun = str(p.what, 'items')
      const what = `${verb} ${count} ${count === 1 ? noun.replace(/s$/, '') : noun}`
      if (p.provider === 'jev') return `Jev ${what}.`
      if (p.provider === 'llm') return `The model ${what}.`
      // No model key is set: a fixed rule made the call. Say so plainly.
      return `${what.charAt(0).toUpperCase()}${what.slice(1)} without a model (no key set).`
    }
    case 'budget.reached':
      return `The daily model budget is spent ($${num(p.spentUsd).toFixed(2)} of $${num(p.capUsd).toFixed(2)}). The build waits.`
    case 'ingestion.started':
      return `${sourceName(str(p.source))} ${p.mode === 'incremental' ? 'sync' : 'backfill'} started.`
    case 'ingestion.progress':
      return `${sourceName(str(p.source))}: ${formatNumber(sumCounts(p.counts))} items read.`
    case 'ingestion.partial':
      return `${sourceName(str(p.source))} finished partly: ${plainReason(str(p.reason, 'some items failed'))}.`
    case 'ingestion.finished':
      if (p.status === 'failed') return `${sourceName(str(p.source))} sync failed: ${plainReason(str(p.reason, 'no reason given'))}.`
      return `${sourceName(str(p.source))} finished in ${formatDuration(num(p.durationMs))}.`
    case 'linking.progress':
      return `Linking ${str(p.step, 'references')}: ${formatNumber(num(p.done))} of ${formatNumber(num(p.total))}.`
    case 'linking.finished':
      return `Linking finished. ${formatNumber(num(obj(p.counts).references_resolved))} references resolved.`
    default:
      return `${event.type.replace(/[._]/g, ' ')}.`
  }
}

const TOOL_GLYPHS: Record<string, GlyphName> = {
  search: 'Search',
  search_code: 'Search',
  find_symbol: 'Search',
  callers: 'Callers',
  references: 'Callers',
  callees: 'Callees',
  impact: 'Impact',
  criticality: 'Criticality',
  shortest_path: 'ShortestPath',
  decisions_for: 'Decisions',
  tests_for: 'Tests',
  owners: 'Owners',
  procedures_for: 'Procedures',
  related_work: 'PullRequest',
  history: 'PullRequest',
}

export function toolGlyph(tool: string): GlyphName {
  return TOOL_GLYPHS[tool] ?? 'ToolCall'
}

export function eventGlyph(event: EventEnvelope): GlyphName {
  const p = event.payload as Payload
  switch (event.type) {
    case 'request.created':
      return 'Request'
    case 'investigation.started':
    case 'investigation.completed':
      return 'Investigate'
    case 'tool.called':
    case 'tool.result':
      return toolGlyph(str(p.tool))
    case 'evidence.found':
      return p.role === 'conflict' ? 'Conflict' : p.role === 'constraint' ? 'Decision' : 'Evidence'
    case 'question.asked':
    case 'answer.received':
      return 'Question'
    case 'ticket.revised':
    case 'ticket.synced':
      return 'Ticket'
    case 'approval.recorded':
    case 'pr.approved':
      return 'Approval'
    case 'approval.refused':
      return 'PossibleConflict'
    case 'handoff.created':
      return 'Handoff'
    case 'build.queued':
    case 'build.started':
    case 'build.step':
      return 'Build'
    case 'tests.result':
      return num(p.failed) > 0 ? 'TestFail' : 'TestPass'
    case 'build.repair':
      return 'Repair'
    case 'build.failed':
      return 'TestFail'
    case 'build.passed':
      return 'TestPass'
    case 'pr.opened':
    case 'pr.updated':
    case 'review.feedback':
      return 'PullRequest'
    case 'writeback.done':
    case 'memory.refreshing':
    case 'memory.refreshed':
    case 'memory.unverified':
      return 'MemoryUpdated'
    case 'notification.sent':
      return 'Inbox'
    case 'request.cancelled':
      return 'TestFail'
    case 'request.done':
      return 'Approval'
    case 'answer.ready':
      return 'Evidence'
    case 'request.state_changed':
      return 'Request'
    case 'judgment.made':
      return 'Decision'
    case 'budget.reached':
      return 'PossibleConflict'
    case 'ingestion.started':
    case 'ingestion.progress':
    case 'ingestion.finished':
      return 'Connect'
    case 'ingestion.partial':
      return 'PossibleConflict'
    case 'linking.progress':
    case 'linking.finished':
      return 'Graph'
    default:
      return 'Request'
  }
}

/* ---------------------------------------------------------------- system map (B.C2a) */

export const ACTORS = ['slack', 'ui', 'actron', 'falkordb', 'jev', 'llm', 'pi', 'github', 'linear'] as const
export type ActorId = (typeof ACTORS)[number]

export const ACTOR_LABEL: Record<ActorId, string> = {
  slack: 'Slack',
  ui: 'Actron UI',
  actron: 'Actron',
  falkordb: 'FalkorDB',
  jev: 'Jev',
  llm: 'LLM',
  pi: 'Pi',
  github: 'GitHub',
  linear: 'Linear',
}

export interface SystemStep {
  from: ActorId
  to: ActorId
  /** The actor whose caption updates. */
  active: ActorId
  caption: string
}

export interface SystemContext {
  /** tool.called events seen so far, by callId, so a result knows who called. */
  callers?: Map<string, { by: 'investigator' | 'pi'; tool: string; args: unknown }>
}

const surfaceActor = (surface: Surface | unknown): ActorId => (surface === 'slack' ? 'slack' : 'ui')

const short = (text: string, max = 48): string => (text.length > max ? `${text.slice(0, max - 1)}…` : text)

/** The edge and caption an event drives on the system map. `null` for events with no actor pair. */
export function systemStep(event: EventEnvelope, ctx: SystemContext = {}): SystemStep | null {
  const p = event.payload as Payload
  switch (event.type) {
    case 'request.created': {
      const from: ActorId = p.source === 'slack' ? 'slack' : 'ui'
      return { from, to: 'actron', active: 'actron', caption: `New request from ${personName(p.requester)}` }
    }
    case 'investigation.started':
      return { from: 'actron', to: 'actron', active: 'actron', caption: 'Investigating' }
    case 'tool.called': {
      const from: ActorId = p.by === 'pi' ? 'pi' : 'actron'
      return { from, to: 'falkordb', active: 'falkordb', caption: toolCallLabel(str(p.tool, 'tool'), p.args) }
    }
    case 'tool.result': {
      const call = ctx.callers?.get(str(p.callId))
      const to: ActorId = call?.by === 'pi' ? 'pi' : 'actron'
      const label = call ? `${call.tool}(${shortArgs(call.args)})` : 'result'
      return {
        from: 'falkordb',
        to,
        active: 'falkordb',
        caption: p.ok === false ? `${label} · failed` : `${label} · ${plainSummary(str(p.summary, 'done'))}`,
      }
    }
    case 'evidence.found':
      return { from: 'falkordb', to: 'actron', active: 'actron', caption: `Evidence: ${str(p.role, 'found').replace('_', ' ')}` }
    case 'judgment.made': {
      const to: ActorId = p.provider === 'llm' ? 'llm' : 'jev'
      return { from: 'actron', to, active: to, caption: `Judging ${num(p.count)} ${str(p.what, 'items')}` }
    }
    case 'investigation.completed':
      return { from: 'actron', to: 'actron', active: 'actron', caption: short(str(p.summary, 'Investigation finished')) }
    case 'question.asked':
      return { from: 'actron', to: 'slack', active: 'slack', caption: `Asked: ${short(str(p.text, 'a question'), 40)}` }
    case 'answer.received': {
      const from = surfaceActor(p.surface)
      return { from, to: 'actron', active: 'actron', caption: `Answered by ${personName(p.by)}` }
    }
    case 'ticket.revised':
      return { from: 'llm', to: 'actron', active: 'actron', caption: `Ticket v${num(p.n, 1)} written` }
    case 'ticket.synced':
      return {
        from: 'actron',
        to: 'linear',
        active: 'linear',
        caption: `Ticket ${str(p.identifier, '')} v${num(p.n, 1)}`.replace('  ', ' '),
      }
    case 'approval.recorded': {
      const from = surfaceActor(p.surface)
      return { from, to: 'actron', active: 'actron', caption: `Approved by ${personName(p.by)}` }
    }
    case 'approval.refused': {
      const from = surfaceActor(p.surface)
      return { from, to: 'actron', active: 'actron', caption: 'Approval refused' }
    }
    case 'handoff.created':
      return { from: 'actron', to: 'pi', active: 'pi', caption: 'Evidence handed to the build' }
    case 'build.queued':
      return { from: 'actron', to: 'pi', active: 'pi', caption: `Queued, position ${num(p.position, 1)}` }
    case 'build.started':
      return { from: 'actron', to: 'pi', active: 'pi', caption: `Building on ${str(p.branch, 'a branch')}` }
    case 'build.step':
      return { from: 'pi', to: 'pi', active: 'pi', caption: short(str(p.text, 'Working')) }
    case 'tests.result': {
      const passed = num(p.passed)
      const total = passed + num(p.failed)
      return { from: 'pi', to: 'actron', active: 'pi', caption: `${passed}/${total} tests passed` }
    }
    case 'build.repair':
      return { from: 'pi', to: 'pi', active: 'pi', caption: `Repair attempt ${num(p.attempt, 1)}` }
    case 'build.failed':
      return { from: 'pi', to: 'actron', active: 'pi', caption: 'Build failed' }
    case 'build.passed':
      return { from: 'pi', to: 'actron', active: 'pi', caption: 'Build passed' }
    case 'pr.opened':
      return { from: 'actron', to: 'github', active: 'github', caption: `PR #${num(p.number)} opened` }
    case 'pr.updated':
      return { from: 'actron', to: 'github', active: 'github', caption: `PR #${num(p.number)} updated` }
    case 'review.feedback': {
      const from = surfaceActor(p.surface)
      return { from, to: 'actron', active: 'actron', caption: 'Review feedback' }
    }
    case 'pr.approved': {
      const from = surfaceActor(p.surface)
      return { from, to: 'actron', active: 'actron', caption: `PR approved by ${personName(p.by)}` }
    }
    case 'writeback.done':
      return { from: 'actron', to: 'falkordb', active: 'falkordb', caption: 'Memory updated' }
    case 'notification.sent':
      return {
        from: 'actron',
        to: p.channel === 'ui' ? 'ui' : 'slack',
        active: p.channel === 'ui' ? 'ui' : 'slack',
        caption: `${noticeWhere(p)}: ${noticeText(p)}`,
      }
    case 'request.cancelled':
      return { from: surfaceActor(event.surface), to: 'actron', active: 'actron', caption: 'Cancelled' }
    case 'request.done':
      return { from: 'actron', to: 'actron', active: 'actron', caption: 'Done' }
    case 'answer.ready':
      return { from: 'llm', to: 'actron', active: 'actron', caption: 'Answer ready' }
    case 'memory.refreshing':
      return { from: 'github', to: 'falkordb', active: 'falkordb', caption: 'Syncing merged code' }
    case 'memory.refreshed':
      return { from: 'github', to: 'falkordb', active: 'falkordb', caption: 'Memory is current' }
    case 'memory.unverified':
      return { from: 'github', to: 'falkordb', active: 'falkordb', caption: 'Memory not verified' }
    case 'budget.reached':
      return { from: 'actron', to: 'llm', active: 'actron', caption: 'Daily budget reached' }
    case 'ingestion.started':
    case 'ingestion.progress':
    case 'ingestion.partial':
    case 'ingestion.finished': {
      const source = str(p.source)
      const from: ActorId = source === 'slack' || source === 'slack_export' ? 'slack' : source === 'linear' ? 'linear' : 'github'
      return { from, to: 'falkordb', active: 'falkordb', caption: short(eventSentence(event)) }
    }
    case 'linking.progress':
    case 'linking.finished':
      return { from: 'actron', to: 'falkordb', active: 'falkordb', caption: short(eventSentence(event)) }
    case 'request.state_changed':
      return null
    default:
      return null
  }
}

/** Node ids an event touches, for canvas highlights on hover. */
export function eventNodeIds(event: EventEnvelope): string[] {
  const p = event.payload as Payload
  const ids: string[] = []
  if (Array.isArray(p.nodeIds)) ids.push(...p.nodeIds.filter((v): v is string => typeof v === 'string'))
  if (typeof p.nodeId === 'string') ids.push(p.nodeId)
  if (Array.isArray(p.path)) ids.push(...p.path.filter((v): v is string => typeof v === 'string'))
  return Array.from(new Set(ids))
}
