// FIXTURE: recorded-style test data for development and tests only; never used in production builds.
// Derives the API's RequestDetail from a fixture request's events, so GET /api/requests/{id} always matches the
// stream. Uses the UI's own reducer (lib/request-view) and fills what only the server knows.
import type { AllowedAction, EventEnvelope, Evidence, RequestDetail, RequestSummary, Revision, SharedQuery, State, TicketContent } from '@/lib/api/types'
import { applyEvent, deriveHeadline, derivePurpose } from '@/lib/request-view'
import { PEOPLE } from './people'
import { reqNode } from './requests'
import type { RequestSpec } from './spec'

export interface RequestRecord {
  spec: RequestSpec
  events: EventEnvelope[]
  /** Ticket contents by revision number (spec tickets plus edits made through the API). */
  contents: Map<number, { content: TicketContent; by: string }>
}

export const ALLOWED: Record<State, AllowedAction[]> = {
  Investigating: ['cancel'],
  'Needs your input': ['answer', 'cancel'],
  'Ticket ready': ['edit_ticket', 'cancel'],
  'Awaiting approval': ['edit_ticket', 'approve_ticket', 'cancel'],
  Building: ['cancel'],
  'Needs attention': ['edit_ticket', 'retry', 'cancel'],
  'PR ready for review': ['pr_feedback', 'approve_pr', 'close_pr', 'cancel'],
  'Changes requested': ['cancel'],
  Done: [],
  Cancelled: [],
}

export function recordFor(spec: RequestSpec, events: EventEnvelope[]): RequestRecord {
  const contents = new Map<number, { content: TicketContent; by: string }>()
  spec.tickets.forEach((t, i) => contents.set(i + 1, t))
  return { spec, events, contents }
}

function emptyDetail(spec: RequestSpec): RequestDetail {
  return {
    id: spec.id,
    title: spec.title,
    kind: spec.kind,
    state: 'Investigating',
    label: null,
    requester: PEOPLE[spec.requester],
    source: spec.source,
    createdAt: spec.createdAt,
    updatedAt: spec.createdAt,
    lastEvent: null,
    pipelineStep: 1,
    needsYou: false,
    text: spec.text,
    headline: '',
    purpose: '',
    slack: spec.slack,
    findings: null,
    evidence: [],
    questions: [],
    revisions: [],
    currentRevision: null,
    approvals: [],
    builds: [],
    pr: null,
    investigation: null,
    outcome: null,
    answer: null,
    allowedActions: [],
  }
}

export function findingsFor(spec: RequestSpec, evidence: Evidence[]): SharedQuery {
  const decisions = evidence.filter((e) => e.nodeType === 'Decision')
  return {
    requestId: spec.id,
    seeds: spec.tools[0]?.nodeIds.slice(0, 3).map((id, i) => ({ id, type: 'CodeFunction', score: Math.round((0.93 - i * 0.07) * 100) / 100 })) ?? [],
    decisions: decisions.map((e) => ({
      id: e.nodeId,
      statement: e.title,
      status: 'approved',
      quote: e.quote ?? '',
      source: { id: e.source.id, type: e.source.type, url: e.source.url ?? '' },
      conflict: {
        label: e.confidence >= 0.8 ? ('conflict' as const) : e.confidence >= 0.5 ? ('possible_conflict' as const) : ('none' as const),
        probability: e.confidence,
      },
      path: e.path,
    })),
    relatedWork: evidence
      .filter((e) => e.role === 'similar_work')
      .map((e) => ({ id: e.nodeId, type: e.nodeType, title: e.title, state: e.nodeType === 'LinearIssue' ? 'In Progress' : 'closed', url: e.source.url ?? '', path: e.path })),
    impact: {
      callers: spec.tools.find((t) => t.tool === 'callers')?.nodeIds.map((id) => ({ id, depth: 1 })) ?? [],
      tests: evidence.filter((e) => e.role === 'test').map((e) => ({ id: e.nodeId })),
      criticality: evidence.filter((e) => e.role === 'impact').map((e) => ({ id: e.nodeId, percentile: 97.5 })),
    },
    owners: spec.tools
      .filter((t) => t.tool === 'owners')
      .flatMap((t) => t.nodeIds)
      .map((personId, i) => ({ personId, name: Object.values(PEOPLE).find((p) => p.personId === personId)?.name ?? personId, basis: ['blame', 'reviews'], score: 0.72 - i * 0.08 })),
    procedures: spec.build ? [{ id: `actron:procedure:${spec.id}`, testCommand: 'npm run unit-test' }] : [],
    label: spec.label,
    graph: {
      nodes: [{ id: reqNode(spec.id), type: 'Request', label: spec.title }],
      edges: [],
    },
  }
}

export function deriveDetail(record: RequestRecord): RequestDetail {
  const { spec, events } = record
  let detail = events.reduce(applyEvent, emptyDetail(spec))

  const revisions: Revision[] = []
  let synced: Revision['linear'] = null
  for (const e of events) {
    const p = e.payload
    if (e.type === 'ticket.revised') {
      const n = Number(p.n)
      const stored = record.contents.get(n)
      if (!stored) continue
      revisions.push({
        n,
        hash: String(p.hash),
        content: stored.content,
        createdBy: String(p.by ?? stored.by),
        createdAt: e.at,
        linear: synced,
        externalEdit: false,
      })
    }
    if (e.type === 'ticket.synced') {
      synced = { issueId: String(p.linearIssueId), identifier: String(p.identifier), url: String(p.url) }
      const last = revisions[revisions.length - 1]
      if (last) last.linear = synced
    }
  }

  const builds = detail.builds
    .map((b) =>
      spec.build && b.id === spec.build.buildId
        ? { ...b, branch: b.branch || spec.build.branch, tokens: spec.build.tokens, costUsd: spec.build.costUsd, report: b.status === 'running' || b.status === 'queued' ? null : spec.build.report }
        : b,
    )
    // Fixture times are fixed while "Running for" counts from the real clock; a running build started a few
    // minutes ago reads as live instead of hung for a day.
    .map((b) => (b.status === 'running' ? { ...b, startedAt: new Date(Date.now() - 3 * 60_000).toISOString() } : b))
  const completed = events.some((e) => e.type === 'investigation.completed')
  const answered = events.some((e) => e.type === 'answer.ready')
  const last = revisions[revisions.length - 1]
  detail = {
    ...detail,
    revisions,
    builds,
    pr: detail.pr ? { ...detail.pr, targetBranch: last?.content.targetBranch ?? 'dev' } : null,
    investigation: {
      mode: spec.mode,
      toolCalls: detail.investigation?.toolCalls ?? 0,
      tokens: completed ? spec.investigation.tokens : { input: Math.round(spec.investigation.tokens.input / 3), output: 0 },
      costUsd: completed ? spec.investigation.costUsd : Math.round((spec.investigation.costUsd / 3) * 100) / 100,
      stub: false,
    },
    findings: completed ? findingsFor(spec, detail.evidence) : null,
    answer:
      answered && spec.answer
        ? { text: spec.answer.text, citations: detail.evidence.filter((e) => spec.answer?.citationIds.includes(e.evidenceId)) }
        : null,
    allowedActions: ALLOWED[detail.state],
    createdAt: spec.createdAt,
  }
  return { ...detail, headline: deriveHeadline(detail), purpose: derivePurpose(detail) }
}

export function summaryOf(detail: RequestDetail): RequestSummary {
  return {
    id: detail.id,
    title: detail.title,
    kind: detail.kind,
    state: detail.state,
    label: detail.label,
    requester: detail.requester,
    source: detail.source,
    createdAt: detail.createdAt,
    updatedAt: detail.updatedAt,
    lastEvent: detail.lastEvent,
    pipelineStep: detail.pipelineStep,
    needsYou: detail.needsYou,
  }
}
