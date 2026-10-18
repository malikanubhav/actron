/**
 * Derived request view: applies live events to the cached RequestDetail (spec C, C4) and writes the situation
 * headline and purpose line for the current state (PROMPT 8.8 D). The server's own headline stays the default;
 * live counts (graph queries, tests) are filled in from the event stream between refetches.
 */
import type {
  Approval,
  Build,
  EventEnvelope,
  Evidence,
  EvidenceRole,
  Label,
  Question,
  QuestionOption,
  RequestDetail,
  State,
  Surface,
} from './api/types'
import { eventSentence, stopReasonText } from './events'
import { countWord, plural } from './format'
import { needsYou, stepForState, tierFor } from './states'

type Payload = Record<string, unknown>
const str = (v: unknown, d = ''): string => (typeof v === 'string' ? v : d)
const num = (v: unknown, d = 0): number => (typeof v === 'number' && Number.isFinite(v) ? v : d)
const obj = (v: unknown): Payload => (v && typeof v === 'object' ? (v as Payload) : {})

function person(value: unknown) {
  const p = obj(value)
  return {
    personId: typeof p.personId === 'string' ? p.personId : null,
    userId: typeof p.userId === 'string' ? p.userId : null,
    name: typeof p.name === 'string' ? p.name : typeof value === 'string' ? value : 'Someone',
    avatarUrl: typeof p.avatarUrl === 'string' ? p.avatarUrl : null,
  }
}

function normaliseOptions(raw: unknown): QuestionOption[] {
  if (!Array.isArray(raw)) return []
  return raw.map((o) =>
    typeof o === 'string'
      ? { value: o, label: o }
      : {
          value: str(obj(o).value),
          label: str(obj(o).label, str(obj(o).value)),
          note: typeof obj(o).note === 'string' ? (obj(o).note as string) : undefined,
          preselected: obj(o).preselected === true,
        },
  )
}

function upsertBuild(builds: Build[], id: string, patch: Partial<Build>, at: string): Build[] {
  const index = builds.findIndex((b) => b.id === id)
  if (index === -1) {
    const created: Build = {
      id,
      status: 'queued',
      queuePosition: null,
      branch: '',
      baseSha: '',
      headSha: null,
      testsPassed: 0,
      testsFailed: 0,
      attempts: 0,
      startedAt: at,
      finishedAt: null,
      stopReason: null,
      tokens: { input: 0, output: 0 },
      costUsd: 0,
      report: null,
      ...patch,
    }
    return [...builds, created]
  }
  const next = builds.slice()
  next[index] = { ...(builds[index] as Build), ...patch }
  return next
}

/** Applies one event to a request. Pure; returns the same object when nothing changes. */
export function applyEvent(detail: RequestDetail, event: EventEnvelope): RequestDetail {
  const p = event.payload as Payload
  let next: RequestDetail = {
    ...detail,
    updatedAt: event.at > detail.updatedAt ? event.at : detail.updatedAt,
    lastEvent: event.type === 'request.state_changed' ? detail.lastEvent : { type: event.type, sentence: eventSentence(event), at: event.at },
  }
  switch (event.type) {
    case 'request.state_changed': {
      const to = str(p.to) as State
      if (!to) break
      next = {
        ...next,
        state: to,
        needsYou: needsYou(to),
        pipelineStep: to === 'Needs attention' || to === 'Cancelled' ? detail.pipelineStep : stepForState(to),
      }
      break
    }
    case 'tool.called': {
      if (p.by === 'pi') break
      const inv = next.investigation ?? { mode: 'agent' as const, toolCalls: 0, tokens: { input: 0, output: 0 }, costUsd: 0, stub: false }
      next = { ...next, investigation: { ...inv, toolCalls: inv.toolCalls + 1 } }
      break
    }
    case 'evidence.found': {
      const evidenceId = str(p.evidenceId)
      if (!evidenceId || next.evidence.some((e) => e.evidenceId === evidenceId)) break
      const source = obj(p.source)
      const confidence = num(p.confidence)
      const item: Evidence = {
        evidenceId,
        role: str(p.role, 'impact') as EvidenceRole,
        nodeId: str(p.nodeId),
        nodeType: str(p.nodeType),
        title: str(p.title, str(p.nodeType)),
        quote: typeof p.quote === 'string' ? p.quote : null,
        source: {
          type: str(source.type),
          id: str(source.id, str(p.nodeId)),
          url: typeof source.url === 'string' ? source.url : null,
          author: typeof source.author === 'string' ? source.author : null,
          at: typeof source.at === 'string' ? source.at : null,
        },
        confidence,
        tier: tierFor(confidence, p.flag === true),
        path: Array.isArray(p.path) ? p.path.filter((x): x is string => typeof x === 'string') : [],
      }
      next = { ...next, evidence: [...next.evidence, item] }
      break
    }
    case 'investigation.completed': {
      const label = str(p.label) as Label
      if (label) next = { ...next, label }
      break
    }
    case 'question.asked': {
      next = { ...next, pipelineStep: Math.max(next.pipelineStep, 2) as RequestDetail['pipelineStep'] }
      const questionId = str(p.questionId)
      if (!questionId || next.questions.some((q) => q.questionId === questionId)) break
      const options = normaliseOptions(p.options)
      const question: Question = {
        questionId,
        text: str(p.text),
        kind: options.length ? 'choice' : 'text',
        options,
        evidenceIds: Array.isArray(p.evidenceIds) ? p.evidenceIds.filter((x): x is string => typeof x === 'string') : [],
        required: p.required !== false,
        answer: null,
      }
      next = { ...next, questions: [...next.questions, question] }
      break
    }
    case 'answer.received': {
      const questionId = str(p.questionId)
      next = {
        ...next,
        questions: next.questions.map((q) =>
          q.questionId === questionId
            ? { ...q, answer: { value: str(p.value), by: person(p.by), surface: (str(p.surface, event.surface) as Surface) ?? 'ui', at: event.at } }
            : q,
        ),
      }
      break
    }
    case 'ticket.revised': {
      next = { ...next, pipelineStep: Math.max(next.pipelineStep, 3) as RequestDetail['pipelineStep'] }
      const n = num(p.n)
      const hash = str(p.hash)
      if (n && hash) next = { ...next, currentRevision: { n, hash } }
      break
    }
    case 'approval.recorded':
    case 'approval.refused': {
      const approval: Approval = {
        id: `evt-${event.seq ?? event.id}`,
        kind: p.kind === 'pr' ? 'pr' : 'ticket',
        target: str(p.target),
        status: event.type === 'approval.recorded' ? 'accepted' : 'refused',
        reason: typeof p.reason === 'string' ? p.reason : null,
        by: person(p.by),
        surface: p.surface === 'slack' ? 'slack' : 'ui',
        at: event.at,
      }
      const duplicate = next.approvals.some(
        (a) => a.id === approval.id || (a.kind === approval.kind && a.target === approval.target && a.status === approval.status && a.at === approval.at),
      )
      if (!duplicate) next = { ...next, approvals: [...next.approvals, approval] }
      break
    }
    case 'build.queued':
      next = { ...next, builds: upsertBuild(next.builds, str(p.buildId), { status: 'queued', queuePosition: num(p.position, 1) }, event.at) }
      break
    case 'build.started':
      next = {
        ...next,
        builds: upsertBuild(
          next.builds,
          str(p.buildId),
          { status: 'running', queuePosition: null, branch: str(p.branch), baseSha: str(p.baseSha), startedAt: event.at },
          event.at,
        ),
      }
      break
    case 'tests.result':
      next = {
        ...next,
        builds: upsertBuild(next.builds, str(p.buildId), { testsPassed: num(p.passed), testsFailed: num(p.failed) }, event.at),
      }
      break
    case 'build.repair': {
      next = { ...next, builds: upsertBuild(next.builds, str(p.buildId), { attempts: num(p.attempt) }, event.at) }
      break
    }
    case 'build.failed':
      next = {
        ...next,
        builds: upsertBuild(next.builds, str(p.buildId), { status: 'failed', stopReason: str(p.reason) || null, finishedAt: event.at }, event.at),
      }
      break
    case 'build.passed':
      next = {
        ...next,
        builds: upsertBuild(next.builds, str(p.buildId), { status: 'passed', headSha: str(p.headSha) || null, finishedAt: event.at }, event.at),
      }
      break
    case 'pr.opened':
      next = {
        ...next,
        pipelineStep: 6,
        pr: {
          number: num(p.number),
          url: str(p.url),
          headSha: str(p.headSha),
          state: 'open',
          targetBranch: next.pr?.targetBranch ?? next.revisions[next.revisions.length - 1]?.content.targetBranch ?? '',
        },
      }
      break
    case 'pr.updated':
      if (next.pr) next = { ...next, pr: { ...next.pr, headSha: str(p.headSha, next.pr.headSha) } }
      break
    case 'request.done': {
      const outcome = str(p.outcome)
      if (outcome === 'approved' || outcome === 'answered' || outcome === 'cancelled' || outcome === 'closed') {
        next = { ...next, outcome, pr: next.pr && outcome === 'approved' ? { ...next.pr, state: 'merged' } : next.pr }
      }
      break
    }
    case 'request.cancelled':
      next = { ...next, outcome: 'cancelled' }
      break
    default:
      break
  }
  return next
}

export function applyEvents(detail: RequestDetail, events: readonly EventEnvelope[]): RequestDetail {
  return events.reduce(applyEvent, detail)
}

/** Events that change data only the server can compute fully; the stream hook refetches after them. */
export const REFETCH_AFTER = new Set([
  'request.state_changed',
  'ticket.revised',
  'ticket.synced',
  'investigation.completed',
  'pr.opened',
  'pr.updated',
  'build.passed',
  'build.failed',
  'writeback.done',
  'request.done',
])

/** Events after which the request's subgraph changes. */
export const SUBGRAPH_AFTER = new Set(['evidence.found', 'investigation.completed', 'writeback.done'])

/* ------------------------------------------------------------------ headline and purpose */

export function latestBuild(detail: Pick<RequestDetail, 'builds'>): Build | null {
  return detail.builds.length ? (detail.builds[detail.builds.length - 1] as Build) : null
}

export function currentRevision(detail: RequestDetail) {
  if (!detail.currentRevision) return null
  return detail.revisions.find((r) => r.n === detail.currentRevision?.n) ?? null
}

/** The last accepted ticket approval and whether it is for an earlier revision (stale). */
export function ticketApprovalState(detail: RequestDetail): { approvedN: number | null; stale: boolean } {
  const accepted = detail.approvals.filter((a) => a.kind === 'ticket' && a.status === 'accepted')
  const last = accepted[accepted.length - 1]
  if (!last || !detail.currentRevision) return { approvedN: null, stale: false }
  const rev = detail.revisions.find((r) => r.hash === last.target)
  const approvedN = rev?.n ?? null
  return { approvedN, stale: last.target !== detail.currentRevision.hash }
}

function conflictCount(detail: RequestDetail): number {
  return detail.evidence.filter((e) => e.role === 'conflict' || e.role === 'constraint').length
}

export function deriveHeadline(detail: RequestDetail): string {
  const build = latestBuild(detail)
  switch (detail.state) {
    case 'Investigating': {
      const n = detail.investigation?.toolCalls ?? 0
      return n === 0 ? 'Investigating. Reading your memory.' : `Investigating. ${plural(n, 'graph query', 'graph queries')} so far.`
    }
    case 'Needs your input': {
      const decisions = conflictCount(detail)
      if (detail.label === 'conflict' || detail.label === 'possible_conflict') {
        return decisions === 1
          ? 'One earlier decision affects this request.'
          : `${countWord(decisions)} earlier decisions affect this request.`
      }
      const open = detail.questions.filter((q) => !q.answer).length
      return open <= 1 ? 'One question before the ticket.' : `${countWord(open)} questions before the ticket.`
    }
    case 'Ticket ready':
      if (detail.label === 'nothing_found' || detail.label === 'clear') return 'Nothing in your history touches this. Safe to continue.'
      return 'The ticket is written. Saving it now.'
    case 'Awaiting approval': {
      const n = detail.currentRevision?.n ?? 1
      return `Ticket v${n} is ready for your approval.`
    }
    case 'Building': {
      if (!build) return 'Building. Preparing the container.'
      if (build.status === 'waiting_budget') return 'The build is waiting. The daily model budget is spent.'
      if (build.status === 'queued') return `Queued for a build. Position ${build.queuePosition ?? 1}.`
      const total = build.testsPassed + build.testsFailed
      if (total === 0) return 'Building. Pi is making the change.'
      return `Building. ${build.testsPassed} of ${total} tests passed.`
    }
    case 'Changes requested':
      return 'Rebuilding with the review feedback.'
    case 'PR ready for review':
      return detail.pr ? `PR #${detail.pr.number} is ready for review.` : 'The pull request is ready for review.'
    case 'Needs attention': {
      if (build && build.status === 'failed' && build.attempts >= 2)
        return `The build failed after ${countWord(build.attempts).toLowerCase()} repairs. Here is why.`
      if (build && (build.status === 'failed' || build.status === 'stopped')) return stopReasonText(build.stopReason)
      return detail.headline || 'Actron stopped and needs you.'
    }
    case 'Done':
      if (detail.outcome === 'answered') return 'Answered. The sources are below.'
      return 'Done. Merged scope recorded in memory.'
    case 'Cancelled':
      return detail.outcome === 'closed' ? 'The pull request was closed. Nothing else will run.' : 'Cancelled. Nothing else will run.'
  }
}

export function derivePurpose(detail: RequestDetail): string {
  switch (detail.state) {
    case 'Investigating':
      return 'Actron is reading the graph. You can leave; it asks when it needs you.'
    case 'Needs your input':
      return 'Answer the questions on the right so Actron can write the ticket.'
    case 'Ticket ready':
      return 'The ticket is being saved to Linear. Approval opens next.'
    case 'Awaiting approval':
      return 'Read the ticket, then approve it to start the build.'
    case 'Building':
    case 'Changes requested':
      return 'Pi is making the change in a container. Follow it in the Build tab.'
    case 'PR ready for review':
      return 'Check the diff, tests and constraints, then approve or request changes.'
    case 'Needs attention':
      return 'Read the reason, then edit the ticket or retry.'
    case 'Done':
      return detail.outcome === 'answered' ? 'Read the answer and open its sources.' : 'Open the pull request or replay how it was handled.'
    case 'Cancelled':
      return 'Start a new request from Home if you still need this change.'
  }
}

/** Tab the main action lives in, for deep links and the inbox. */
export function primaryTab(detail: Pick<RequestDetail, 'state' | 'questions'> & { kind?: RequestDetail['kind'] }): 'evidence' | 'questions' | 'ticket' | 'build' | 'pr' {
  if ((detail as { kind?: string }).kind === 'question') return 'evidence'
  switch (detail.state) {
    case 'Needs your input':
      return detail.questions.length ? 'questions' : 'evidence'
    case 'Ticket ready':
    case 'Awaiting approval':
      return 'ticket'
    case 'Building':
    case 'Changes requested':
    case 'Needs attention':
      return 'build'
    case 'PR ready for review':
    case 'Done':
      return 'pr'
    default:
      return 'evidence'
  }
}
