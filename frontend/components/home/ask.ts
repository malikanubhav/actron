import type { NotificationItem, RequestSummary, State } from '@/lib/api/types'
import { STOP_REASON_TEXT } from '@/lib/events'
import type { GlyphName } from '../glyphs/names'

export type AskKind = NotificationItem['kind']

/** Group names and lines shared by Home and the Inbox, so the same thing has the same words on both. */
export const GROUP_COPY = {
  waiting: {
    title: 'Waiting for a decision',
    description: 'A question to answer, a ticket to approve or a pull request to review. Nothing moves until someone acts.',
    empty: 'No questions, approvals or reviews are waiting.',
  },
  stopped: {
    title: 'Stopped',
    description: 'The build stopped. Someone needs to fix the cause before Actron can go on.',
    empty: 'Nothing has stopped.',
  },
} as const

/** The notification kind that is the current ask for a request in this state. */
export const ASK_FOR_STATE: Partial<Record<State, AskKind>> = {
  'Needs your input': 'needs_input',
  'Awaiting approval': 'awaiting_approval',
  'Needs attention': 'build_failed',
  'PR ready for review': 'pr_ready',
}

/** What the person does for each kind of ask: the verb on the row and its glyph. */
export const ASK: Record<AskKind, { verb: string; glyph: GlyphName }> = {
  needs_input: { verb: 'Answer', glyph: 'Question' },
  awaiting_approval: { verb: 'Approve ticket', glyph: 'Approval' },
  build_failed: { verb: 'See why', glyph: 'TestFail' },
  pr_ready: { verb: 'Review PR', glyph: 'PullRequest' },
}

/** The useful part of a notification body ("<request title>: <detail>"), or '' when there is none. */
export function notificationDetail(n: Pick<NotificationItem, 'body'>, requestTitle?: string): string {
  const body = n.body.trim()
  if (requestTitle && body.startsWith(requestTitle)) return body.slice(requestTitle.length).replace(/^[:.]\s*/, '').trim()
  const at = body.indexOf(': ')
  return at >= 0 ? body.slice(at + 2).trim() : ''
}

function reasonSentence(detail: string): string {
  if (!detail) return 'The build stopped.'
  const known = STOP_REASON_TEXT[detail]
  if (known) return known
  if (/^[a-z][a-z0-9_]*$/.test(detail)) {
    const words = detail.replace(/_/g, ' ')
    return `Stopped: ${words}.`
  }
  return detail
}

/** One plain sentence for what the notification asks of the person. */
export function askText(n: Pick<NotificationItem, 'kind' | 'title' | 'body'>, requestTitle?: string): string {
  const detail = notificationDetail(n, requestTitle)
  switch (n.kind) {
    case 'needs_input':
      return detail || 'Actron has a question for you.'
    case 'awaiting_approval': {
      const ticket = /ticket v\d+/i.exec(`${n.title} ${detail}`)?.[0]
      return ticket ? `${ticket.charAt(0).toUpperCase()}${ticket.slice(1)} waits for your approval.` : 'The ticket waits for your approval.'
    }
    case 'build_failed':
      return reasonSentence(detail)
    case 'pr_ready': {
      const pr = /PR #\d+/i.exec(`${n.title} ${detail}`)?.[0]
      return pr ? `${pr.toUpperCase()} is ready for your review.` : 'The pull request is ready for your review.'
    }
  }
}

/**
 * A past notice as history: past tense, and marked resolved when the request has moved past the step it was
 * about. Without the request (it no longer needs anyone), only the notice itself is stated.
 */
export function historyText(
  n: Pick<NotificationItem, 'kind' | 'title' | 'body'>,
  requestTitle?: string,
  request?: { state: State; pipelineStep: number } | null,
): string {
  const detail = notificationDetail(n, requestTitle)
  const step = request?.pipelineStep ?? 0
  const moved = (past: number, word: string) => (request && step > past ? ` · ${word}` : '')
  switch (n.kind) {
    case 'needs_input':
      return `${detail ? `Asked: ${detail}` : 'Actron asked a question'}${request && request.state !== 'Needs your input' ? ' · answered' : ''}`
    case 'awaiting_approval': {
      const ticket = /ticket v\d+/i.exec(`${n.title} ${detail}`)?.[0]
      const name = ticket ? `${ticket.charAt(0).toUpperCase()}${ticket.slice(1)}` : 'The ticket'
      return `${name} was sent for approval${moved(4, 'approved')}`
    }
    case 'build_failed':
      return `The build stopped: ${reasonSentence(detail).replace(/\.$/, '')}${request && request.state !== 'Needs attention' ? ' · resolved' : ''}`
    case 'pr_ready': {
      const pr = /PR #\d+/i.exec(`${n.title} ${detail}`)?.[0]
      return `${pr ? pr.toUpperCase() : 'The pull request'} was opened for review${request?.state === 'Done' ? ' · done' : ''}`
    }
  }
}

const byNewest =(a: NotificationItem, b: NotificationItem) => b.createdAt.localeCompare(a.createdAt)

/** The newest notification whose kind matches the request's current state; older or other kinds are earlier asks. */
export function currentAsk(request: Pick<RequestSummary, 'id' | 'state'>, notifications: readonly NotificationItem[]): NotificationItem | null {
  const kind = ASK_FOR_STATE[request.state]
  if (!kind) return null
  return [...notifications].filter((n) => n.requestId === request.id && n.kind === kind).sort(byNewest)[0] ?? null
}

const STATE_SENTENCE: Record<State, string> = {
  Investigating: 'Checking history and code.',
  'Needs your input': 'Actron has a question.',
  'Ticket ready': 'The ticket is written.',
  'Awaiting approval': 'The ticket waits for approval.',
  Building: 'Building the change.',
  'Needs attention': 'The build stopped.',
  'PR ready for review': 'The pull request is ready for review.',
  'Changes requested': 'Applying the requested changes.',
  Done: 'Finished. Open it for the result.',
  Cancelled: 'Cancelled.',
}

export interface RowFact {
  text: string
  /** Set when the fact is an ask addressed to the person viewing. */
  kind?: AskKind
}

/** The fact a row shows: the open ask when one is addressed to you, else the last event, else a sentence for the state. */
export function rowFact(request: RequestSummary, notifications: readonly NotificationItem[], inboxKnown = false): RowFact {
  const ask = currentAsk(request, notifications)
  if (ask) return { text: askText(ask, request.title), kind: ask.kind }
  // With your inbox loaded, an ask that is not in it waits on someone else.
  if (inboxKnown && ASK_FOR_STATE[request.state]) return { text: `${STATE_SENTENCE[request.state]} It waits on someone else.` }
  const sentence = request.lastEvent?.sentence
  // The backend's state-change sentence ("Now Needs your input.") and a bare "Done." repeat the chip.
  const repeatsChip = !sentence || request.lastEvent?.type === 'request.state_changed' || /^Now /.test(sentence) || sentence.replace(/\.$/, '').toLowerCase() === request.state.toLowerCase()
  if (!repeatsChip) return { text: sentence }
  if (request.state === 'Done' && request.kind === 'question') return { text: 'The answer is ready.' }
  return { text: STATE_SENTENCE[request.state] }
}

export interface RequestBlock {
  requestId: string
  title: string
  state: State | null
  request: RequestSummary | null
  current: NotificationItem | null
  earlier: NotificationItem[]
  latestAt: string
}

export interface InboxSections {
  /** Asks that wait on you now: a question, a ticket, a PR. */
  waiting: RequestBlock[]
  /** Stopped builds that wait on you now. */
  stopped: RequestBlock[]
  /** Requests that no longer wait on you; their notifications are history. */
  earlier: RequestBlock[]
}

/**
 * One block per request. With the list of requests that need someone, the current ask is the notification that
 * matches the request's state; without it (still loading or failed), the newest notification stands in.
 */
export function inboxSections(notifications: readonly NotificationItem[], requests: readonly RequestSummary[] | null): InboxSections {
  const byRequest = new Map<string, NotificationItem[]>()
  for (const n of [...notifications].sort(byNewest)) byRequest.set(n.requestId, [...(byRequest.get(n.requestId) ?? []), n])
  const known = new Map((requests ?? []).map((r) => [r.id, r]))
  const out: InboxSections = { waiting: [], stopped: [], earlier: [] }
  for (const [requestId, items] of byRequest) {
    const request = known.get(requestId)
    const current = request ? currentAsk(request, items) : requests ? null : (items[0] ?? null)
    const title = request?.title ?? titleFromBody(items[0]?.body ?? '')
    const block: RequestBlock = {
      requestId,
      title,
      state: request?.state ?? null,
      request: request ?? null,
      current,
      earlier: items.filter((n) => n !== current),
      latestAt: items[0]?.createdAt ?? '',
    }
    if (!current) out.earlier.push(block)
    else if (current.kind === 'build_failed') out.stopped.push(block)
    else out.waiting.push(block)
  }
  return out
}

function titleFromBody(body: string): string {
  const at = body.indexOf(': ')
  return at >= 0 ? body.slice(0, at) : body
}

/** How many requests wait on you: the same number on Home and in the Inbox. */
export function waitingOnYouCount(notifications: readonly NotificationItem[], requests: readonly RequestSummary[]): number {
  return requests.filter((r) => currentAsk(r, notifications)).length
}
