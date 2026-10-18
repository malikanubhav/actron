// FIXTURE: recorded-style test data for development and tests only; never used in production builds.
// The recorded event log of each fixture request (gap-free seq, timestamps on 16 and 17 Oct 2026).
import type { EventEnvelope } from '@/lib/api/types'
import { FIXTURE_IDS } from './ids'
import {
  answerReadySteps,
  answerStep,
  approvalStep,
  buildSteps,
  cancelSteps,
  createdSteps,
  investigationSteps,
  materialize,
  prApprovalSteps,
  questionSteps,
  state,
  ticketHash,
  ticketSteps,
  type Step,
} from './lifecycle'
import {
  answeredSpec,
  buildingSpec,
  cancelledSpec,
  doneSpec,
  failedSpec,
  liveSpec,
  nothingSpec,
  prReadySpec,
  staleSpec,
} from './requests'
import type { RequestSpec } from './spec'

function answers(spec: RequestSpec): Step[] {
  return spec.questions.flatMap((q) => (q.answer ? [answerStep(q.questionId, q.answer.value, q.answer.by, q.answer.surface)] : []))
}

function v1Hash(spec: RequestSpec): string {
  const first = spec.tickets[0]
  return first ? ticketHash(spec.id, first.content) : ''
}

function throughTicket(spec: RequestSpec): Step[] {
  const fromState = spec.questions.length ? ('Needs your input' as const) : ('Investigating' as const)
  return [...createdSteps(spec), ...investigationSteps(spec), ...questionSteps(spec), ...answers(spec), ...ticketSteps(spec, 1, fromState)]
}

const SCRIPTS: Record<string, { spec: RequestSpec; steps: Step[] }> = {
  [FIXTURE_IDS.live]: { spec: liveSpec, steps: createdSteps(liveSpec) },
  [FIXTURE_IDS.done]: {
    spec: doneSpec,
    steps: [
      ...throughTicket(doneSpec),
      approvalStep('ticket', v1Hash(doneSpec), 'priya', 'slack'),
      ...buildSteps(doneSpec),
      ...prApprovalSteps(doneSpec, 'sam', 'ui'),
    ],
  },
  [FIXTURE_IDS.stale]: {
    spec: staleSpec,
    steps: [
      ...throughTicket(staleSpec),
      approvalStep('ticket', v1Hash(staleSpec), 'dana', 'ui'),
      state('Awaiting approval', 'Building', 'ticket_approved'),
      { type: 'handoff.created', payload: { investigationId: `inv_${staleSpec.id}`, buildId: 'bld_stale_01', evidenceCount: 1 }, gap: 1 },
      { type: 'build.queued', payload: { buildId: 'bld_stale_01', position: 1 }, gap: 1 },
      { type: 'build.started', payload: { buildId: 'bld_stale_01', branch: 'actron/connect-timeout-setting', baseSha: 'a41c9e27b3d0f5e1c8a24f6b9d0e3c7a15b2f8d4' }, gap: 6 },
      { type: 'build.step', payload: { buildId: 'bld_stale_01', step: 'read', text: 'Reading connect and getConfig through the graph', file: 'src/nrepl/connect.ts' }, gap: 20 },
      {
        type: 'judgment.made',
        payload: { job: 'is_scope_change', provider: 'jev', count: 1, what: 'proposed changes' },
        gap: 30,
      },
      { type: 'build.failed', payload: { buildId: 'bld_stale_01', reason: 'scope_change' }, gap: 2 },
      state('Building', 'Needs attention', 'scope_change'),
      { type: 'notification.sent', payload: { kind: 'build_failed', toPersonId: 'actron:person:mateo-ruiz', channel: 'ui' }, gap: 1 },
      ...ticketSteps(staleSpec, 2, 'Needs attention', 'Mateo Ruiz').map((s) => (s.type === 'ticket.revised' ? { ...s, gap: 1800 } : s)),
    ],
  },
  [FIXTURE_IDS.building]: {
    spec: buildingSpec,
    steps: [...throughTicket(buildingSpec), approvalStep('ticket', v1Hash(buildingSpec), 'dana', 'ui'), ...buildSteps(buildingSpec, 'steps')],
  },
  [FIXTURE_IDS.failed]: {
    spec: failedSpec,
    steps: [...throughTicket(failedSpec), approvalStep('ticket', v1Hash(failedSpec), 'sam', 'slack'), ...buildSteps(failedSpec)],
  },
  [FIXTURE_IDS.prReady]: {
    spec: prReadySpec,
    steps: [...throughTicket(prReadySpec), approvalStep('ticket', v1Hash(prReadySpec), 'priya', 'ui'), ...buildSteps(prReadySpec)],
  },
  [FIXTURE_IDS.cancelled]: {
    spec: cancelledSpec,
    steps: [
      ...createdSteps(cancelledSpec),
      ...investigationSteps(cancelledSpec),
      ...questionSteps(cancelledSpec),
      ...cancelSteps('Needs your input', 'mateo', 'slack', 'Agreed with the decision; keeping the name'),
    ],
  },
  [FIXTURE_IDS.answered]: {
    spec: answeredSpec,
    steps: [...createdSteps(answeredSpec), ...investigationSteps(answeredSpec), ...answerReadySteps(answeredSpec)],
  },
  [FIXTURE_IDS.nothing]: { spec: nothingSpec, steps: throughTicket(nothingSpec) },
}

/** Fresh copies of every recorded log, keyed by request id. */
export function recordedHistory(): Map<string, { spec: RequestSpec; events: EventEnvelope[] }> {
  const out = new Map<string, { spec: RequestSpec; events: EventEnvelope[] }>()
  Object.entries(SCRIPTS).forEach(([id, script], i) => {
    out.set(id, { spec: script.spec, events: materialize(id, script.steps, script.spec.createdAt, 1000 * (i + 1)) })
  })
  return out
}
