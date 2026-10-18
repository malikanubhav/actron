// FIXTURE: recorded-style test data for development and tests only; never used in production builds.
// Turns a RequestSpec into contract events (spec B, B.C2), stage by stage. The engine plays the same stages live.
import type { Actor, EventEnvelope, State, Surface, TicketContent } from '@/lib/api/types'
import { PEOPLE, type PersonKey } from './people'
import type { BuildSpec, RequestSpec } from './spec'
import { canonicalJson, sha256 } from './util'

export interface Step {
  type: string
  payload: Record<string, unknown>
  actor?: Actor
  surface?: Surface
  /** Seconds after the previous step in recorded history; the live engine uses its own gaps. */
  gap?: number
}

const person = (key: PersonKey) => ({ personId: PEOPLE[key].personId, name: PEOPLE[key].name })

export function ticketHash(requestId: string, content: TicketContent): string {
  return sha256(canonicalJson({ ...content, requestId }))
}

export function state(from: State | null, to: State, reason: string): Step {
  return { type: 'request.state_changed', payload: { from, to, reason }, gap: 0 }
}

export function createdSteps(spec: RequestSpec): Step[] {
  return [
    {
      type: 'request.created',
      payload: {
        kind: spec.kind,
        title: spec.title,
        text: spec.text,
        requester: person(spec.requester),
        source: spec.source,
        ...(spec.slack ? { slack: { channel: spec.slack.channel, threadTs: spec.slack.threadTs } } : {}),
      },
      actor: spec.source === 'slack' ? 'slack' : 'person',
      surface: spec.source === 'slack' ? 'slack' : 'ui',
      gap: 0,
    },
    { type: 'investigation.started', payload: { mode: spec.mode }, gap: 2 },
  ]
}

/** Freshness gate, tool calls, judgments, evidence and the completion event. */
export function investigationSteps(spec: RequestSpec): Step[] {
  const steps: Step[] = [
    { type: 'memory.refreshing', payload: { fromSha: 'a41c9e2', toSha: 'a41c9e2' }, gap: 1 },
    { type: 'memory.refreshed', payload: { sha: 'a41c9e27b3d0f5e1c8a24f6b9d0e3c7a15b2f8d4', functionsChanged: 0 }, gap: 1 },
  ]
  spec.tools.forEach((tool, i) => {
    const callId = `call_${spec.id.slice(-6)}_${i + 1}`
    steps.push({ type: 'tool.called', payload: { callId, tool: tool.tool, args: tool.args, by: 'investigator' }, gap: 2 })
    steps.push({
      type: 'tool.result',
      payload: {
        callId,
        tool: tool.tool,
        ok: tool.ok !== false,
        summary: tool.summary,
        nodeIds: tool.nodeIds,
        durationMs: tool.durationMs,
        ...(tool.error ? { error: tool.error } : {}),
      },
      gap: Math.max(1, Math.round(tool.durationMs / 1000)),
    })
    for (const j of spec.judgments.filter((x) => x.afterTool === i)) {
      steps.push({ type: 'judgment.made', payload: { job: j.job, provider: j.provider ?? 'jev', count: j.count, what: j.what }, gap: 1 })
    }
    // Evidence arrives spread over the tool calls, in spec order.
    spec.evidence.forEach((e, index) => {
      if (Math.floor((index * spec.tools.length) / spec.evidence.length) !== i) return
      {
        steps.push({
          type: 'evidence.found',
          payload: {
            evidenceId: e.evidenceId,
            role: e.role,
            nodeId: e.nodeId,
            nodeType: e.nodeType,
            title: e.title,
            quote: e.quote,
            source: { type: e.source.type, url: e.source.url, author: e.source.author, at: e.source.at, id: e.source.id },
            confidence: e.confidence,
            flag: e.flag === true,
            path: e.path,
          },
          gap: 1,
        })
      }
    })
  })
  steps.push({
    type: 'investigation.completed',
    payload: { label: spec.label, summary: spec.summary, counts: spec.counts, findingsRef: `findings_${spec.id}` },
    gap: 2,
  })
  return steps
}

export function questionSteps(spec: RequestSpec): Step[] {
  if (spec.questions.length === 0) return []
  // The notification goes out with the first question, so the last event a list row shows is a question.
  const steps: Step[] = [
    { type: 'notification.sent', payload: { kind: 'needs_input', toPersonId: PEOPLE[spec.requester].personId, channel: spec.source === 'slack' ? 'slack_thread' : 'ui' }, gap: 1 },
    ...spec.questions.map((q) => ({
      type: 'question.asked',
      payload: { questionId: q.questionId, text: q.text, options: q.options, evidenceIds: q.evidenceIds, required: q.required },
      gap: 1,
    })),
  ]
  steps.push(state('Investigating', 'Needs your input', 'questions'))
  return steps
}

export function answerStep(questionId: string, value: string, by: PersonKey, surface: 'slack' | 'ui'): Step {
  return {
    type: 'answer.received',
    payload: { questionId, value, by: person(by), surface },
    actor: surface === 'slack' ? 'slack' : 'person',
    surface,
    gap: 60,
  }
}

/** Ticket revision n, synced to Linear, then awaiting approval. */
export function ticketSteps(spec: RequestSpec, n: number, from: State, by = 'Actron', content?: TicketContent): Step[] {
  const body = content ?? spec.tickets[n - 1]?.content
  if (!body) return []
  const hash = ticketHash(spec.id, body)
  const steps: Step[] = []
  const viaTicketReady = from === 'Investigating' || from === 'Needs your input'
  if (viaTicketReady) steps.push(state(from, 'Ticket ready', n === 1 ? 'questions_answered' : 'ticket_edited'))
  steps.push({ type: 'ticket.revised', payload: { n, hash, contentRef: `ticket_${spec.id}_v${n}`, by }, gap: 4 })
  steps.push({ type: 'notification.sent', payload: { kind: 'awaiting_approval', toPersonId: PEOPLE[spec.requester].personId, channel: 'slack_dm' }, gap: 1 })
  if (spec.linear) steps.push({ type: 'ticket.synced', payload: { linearIssueId: spec.linear.issueId, identifier: spec.linear.identifier, url: spec.linear.url, n }, gap: 2 })
  if (from !== 'Awaiting approval') steps.push(state(viaTicketReady ? 'Ticket ready' : from, 'Awaiting approval', n === 1 ? 'ticket_saved' : 'ticket_edited'))
  return steps
}

export function approvalStep(kind: 'ticket' | 'pr', target: string, by: PersonKey, surface: 'slack' | 'ui'): Step {
  return {
    type: 'approval.recorded',
    payload: { kind, target, by: person(by), surface },
    actor: surface === 'slack' ? 'slack' : 'person',
    surface,
    gap: 90,
  }
}

function buildStep(build: BuildSpec, text: string, file?: string, diff?: string): Step {
  return { type: 'build.step', payload: { buildId: build.buildId, step: text, text, ...(file ? { file } : {}), ...(diff ? { detail: { diff } } : {}) }, gap: 20 }
}

/**
 * The build from handoff onwards. `upTo` stops early: 'steps' stops after the first steps (a running build).
 */
export function buildSteps(spec: RequestSpec, upTo: 'all' | 'steps' = 'all'): Step[] {
  const build = spec.build
  if (!build) return []
  const steps: Step[] = [
    state('Awaiting approval', 'Building', 'ticket_approved'),
    { type: 'handoff.created', payload: { investigationId: `inv_${spec.id}`, buildId: build.buildId, evidenceCount: spec.evidence.length }, gap: 1 },
    { type: 'build.queued', payload: { buildId: build.buildId, position: build.position }, gap: 1 },
    { type: 'build.started', payload: { buildId: build.buildId, branch: build.branch, baseSha: build.baseSha }, gap: 8 },
  ]
  build.steps.forEach((s, i) => {
    steps.push(buildStep(build, s.text, s.file, s.diff))
    build.piTools
      .filter((t) => t.afterStep === i)
      .forEach((t, k) => {
        const callId = `pi_${build.buildId}_${i}_${k}`
        steps.push({ type: 'tool.called', payload: { callId, tool: t.tool, args: t.args, by: 'pi' }, gap: 2 })
        steps.push({ type: 'tool.result', payload: { callId, tool: t.tool, ok: true, summary: t.summary, nodeIds: t.nodeIds, durationMs: t.durationMs }, gap: 1 })
      })
  })
  if (upTo === 'steps') return steps
  build.attempts.forEach((attempt, i) => {
    steps.push({
      type: 'tests.result',
      payload: { buildId: build.buildId, passed: attempt.tests.passed, failed: attempt.tests.failed, skipped: 0, failing: attempt.tests.failing },
      gap: 40,
    })
    if (attempt.repair) {
      steps.push({ type: 'build.repair', payload: { buildId: build.buildId, attempt: i + 1, reason: attempt.repair.reason }, gap: 3 })
      for (const s of attempt.repair.steps) steps.push(buildStep(build, s.text, s.file, s.diff))
    }
  })
  if (build.outcome === 'failed') {
    steps.push({ type: 'notification.sent', payload: { kind: 'build_failed', toPersonId: PEOPLE[spec.requester].personId, channel: 'slack_dm' }, gap: 2 })
    steps.push({ type: 'build.failed', payload: { buildId: build.buildId, reason: build.failReason ?? 'failed_after_repairs' }, gap: 1 })
    steps.push(state('Building', 'Needs attention', build.failReason ?? 'failed_after_repairs'))
    return steps
  }
  steps.push({ type: 'build.passed', payload: { buildId: build.buildId, headSha: build.headSha }, gap: 3 })
  if (spec.pr) {
    steps.push({ type: 'notification.sent', payload: { kind: 'pr_ready', toPersonId: PEOPLE[spec.requester].personId, channel: 'slack_dm' }, gap: 6 })
    steps.push({ type: 'pr.opened', payload: { number: spec.pr.number, url: spec.pr.url, headSha: spec.pr.headSha }, gap: 1 })
    steps.push(state('Building', 'PR ready for review', 'pr_opened'))
  }
  return steps
}

export function prApprovalSteps(spec: RequestSpec, by: PersonKey, surface: 'slack' | 'ui'): Step[] {
  if (!spec.pr) return []
  return [
    approvalStep('pr', spec.pr.headSha, by, surface),
    { type: 'pr.approved', payload: { headSha: spec.pr.headSha, by: person(by), surface }, actor: 'person', surface, gap: 1 },
    { type: 'writeback.done', payload: { counts: spec.writeback ?? { prs: 1, commits: 1, functions: 1, procedures: 0 } }, gap: 12 },
    state('PR ready for review', 'Done', 'pr_approved'),
    { type: 'request.done', payload: { outcome: 'approved' }, gap: 0 },
  ]
}

export function cancelSteps(from: State, by: PersonKey, surface: 'slack' | 'ui', reason: string): Step[] {
  return [
    { type: 'request.cancelled', payload: { reason, by: person(by) }, actor: surface === 'slack' ? 'slack' : 'person', surface, gap: 300 },
    state(from, 'Cancelled', 'cancelled'),
  ]
}

export function answerReadySteps(spec: RequestSpec): Step[] {
  return [
    { type: 'answer.ready', payload: { answerRef: `answer_${spec.id}` }, gap: 6 },
    state('Investigating', 'Done', 'answered'),
    { type: 'request.done', payload: { outcome: 'answered' }, gap: 0 },
  ]
}

/** Recorded history: steps → envelopes with gap-free seq and timestamps from `start`. */
export function materialize(requestId: string, steps: Step[], start: string, firstId: number): EventEnvelope[] {
  let t = Date.parse(start)
  return steps.map((s, i) => {
    t += (s.gap ?? 1) * 1000
    return envelope(requestId, s, i + 1, firstId + i, new Date(i === 0 ? Date.parse(start) : t).toISOString())
  })
}

export function envelope(requestId: string, s: Step, seq: number, id: number, at: string): EventEnvelope {
  return {
    id,
    requestId,
    seq,
    type: s.type,
    at,
    actor: s.actor ?? 'actron',
    surface: s.surface ?? 'system',
    payload: s.payload,
  }
}
