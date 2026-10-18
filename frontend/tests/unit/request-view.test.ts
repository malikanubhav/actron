import { describe, expect, it } from 'vitest'
import { STATES, type Build, type Revision, type RequestDetail } from '@/lib/api/types'
import { applyEvent, applyEvents, currentRevision, deriveHeadline, derivePurpose, latestBuild, primaryTab, ticketApprovalState } from '@/lib/request-view'
import { makeEvent, makeRequestDetail, PERSON, TICKET } from './helpers/render'

const build = (patch: Partial<Build> = {}): Build => ({
  id: 'b1',
  status: 'running',
  queuePosition: null,
  branch: 'actron/x',
  baseSha: 'abc',
  headSha: null,
  testsPassed: 0,
  testsFailed: 0,
  attempts: 0,
  startedAt: '2026-10-17T09:00:00Z',
  finishedAt: null,
  stopReason: null,
  tokens: { input: 0, output: 0 },
  costUsd: 0,
  report: null,
  ...patch,
})
const rev = (n: number, hash: string): Revision => ({ n, hash, content: TICKET, createdBy: 'Actron', createdAt: '2026-10-17T09:00:00Z', linear: null, externalEdit: false })

describe('applyEvent', () => {
  const d0 = makeRequestDetail({ updatedAt: '2026-10-17T08:00:00.000Z' })

  it('state changes update state, needsYou and the pipeline step', () => {
    const d = applyEvent(d0, makeEvent('request.state_changed', { from: 'Investigating', to: 'Awaiting approval' }))
    expect(d.state).toBe('Awaiting approval')
    expect(d.needsYou).toBe(true)
    expect(d.pipelineStep).toBe(4)
    expect(d.lastEvent).toBeNull()
  })

  it('needs attention keeps the step where it stopped', () => {
    const d = applyEvent({ ...d0, pipelineStep: 5 }, makeEvent('request.state_changed', { to: 'Needs attention' }))
    expect(d.pipelineStep).toBe(5)
  })

  it('investigator tool calls count; Pi tool calls do not', () => {
    let d = applyEvent(d0, makeEvent('tool.called', { tool: 'search', by: 'investigator' }, 1))
    d = applyEvent(d, makeEvent('tool.called', { tool: 'tests_for', by: 'pi' }, 2))
    expect(d.investigation?.toolCalls).toBe(1)
    expect(d.lastEvent?.sentence).toMatch(/^Called tests_for/)
  })

  it('evidence is added once with a computed tier', () => {
    const e = makeEvent('evidence.found', { evidenceId: 'e1', role: 'conflict', nodeId: 'n', nodeType: 'Decision', quote: 'q', source: { type: 'SlackMessage' }, confidence: 0.7, path: ['a', 'b'] })
    const d = applyEvents(d0, [e, e])
    expect(d.evidence).toHaveLength(1)
    expect(d.evidence[0]).toMatchObject({ role: 'conflict', tier: 'MEDIUM', path: ['a', 'b'], quote: 'q' })
    const flagged = applyEvent(d0, makeEvent('evidence.found', { evidenceId: 'e2', confidence: 0.9, flag: true }))
    expect(flagged.evidence[0]?.tier).toBe('POSSIBLE')
  })

  it('questions are added once; string and object options normalise; answers attach', () => {
    const q = makeEvent('question.asked', { questionId: 'q1', text: 'Which branch?', options: ['dev', { value: 'main', label: 'main', note: 'protected' }] })
    let d = applyEvents(d0, [q, q])
    expect(d.questions).toHaveLength(1)
    expect(d.questions[0]?.kind).toBe('choice')
    expect(d.questions[0]?.options).toEqual([
      { value: 'dev', label: 'dev' },
      { value: 'main', label: 'main', note: 'protected', preselected: false },
    ])
    d = applyEvent(d, makeEvent('answer.received', { questionId: 'q1', value: 'dev', by: PERSON, surface: 'slack' }))
    expect(d.questions[0]?.answer).toMatchObject({ value: 'dev', surface: 'slack', by: { name: 'Dana Ilić' } })
    const textQ = applyEvent(d0, makeEvent('question.asked', { questionId: 'q2', text: 'Why?' }))
    expect(textQ.questions[0]?.kind).toBe('text')
  })

  it('label, revision, approvals (deduped), builds, PR and outcome', () => {
    let d = applyEvents(d0, [
      makeEvent('investigation.completed', { label: 'conflict' }, 1),
      makeEvent('ticket.revised', { n: 2, hash: 'h2' }, 2),
      makeEvent('approval.recorded', { kind: 'ticket', target: 'h2', by: PERSON, surface: 'ui' }, 3),
      makeEvent('build.queued', { buildId: 'b1', position: 2 }, 4),
      makeEvent('build.started', { buildId: 'b1', branch: 'actron/x', baseSha: 'abc' }, 5),
      makeEvent('tests.result', { buildId: 'b1', passed: 3, failed: 1 }, 6),
      makeEvent('build.repair', { buildId: 'b1', attempt: 1 }, 7),
      makeEvent('build.passed', { buildId: 'b1', headSha: 'f00' }, 8),
      makeEvent('pr.opened', { number: 18, url: 'u', headSha: 'f00' }, 9),
      makeEvent('pr.updated', { number: 18, headSha: 'f01' }, 10),
    ])
    expect(d.label).toBe('conflict')
    expect(d.currentRevision).toEqual({ n: 2, hash: 'h2' })
    expect(d.approvals).toHaveLength(1)
    expect(d.builds[0]).toMatchObject({ status: 'passed', branch: 'actron/x', testsPassed: 3, testsFailed: 1, attempts: 1, headSha: 'f00' })
    expect(d.pr).toMatchObject({ number: 18, headSha: 'f01', state: 'open' })
    d = applyEvent(d, makeEvent('request.done', { outcome: 'approved' }, 11))
    expect(d.outcome).toBe('approved')
    expect(d.pr?.state).toBe('merged')
    const again = applyEvent(d, { ...makeEvent('approval.recorded', { kind: 'ticket', target: 'h2', by: PERSON, surface: 'ui' }, 3), id: 999 })
    expect(again.approvals).toHaveLength(1)
  })

  it('failures, refusals and cancellation', () => {
    const d = applyEvents(d0, [
      makeEvent('build.failed', { buildId: 'b1', reason: 'timeout' }, 1),
      makeEvent('approval.refused', { kind: 'pr', target: 'x', reason: 'stale_head', by: PERSON }, 2),
      makeEvent('request.cancelled', { reason: 'no', by: PERSON }, 3),
    ])
    expect(d.builds[0]).toMatchObject({ status: 'failed', stopReason: 'timeout' })
    expect(d.approvals[0]).toMatchObject({ kind: 'pr', status: 'refused', reason: 'stale_head' })
    expect(d.outcome).toBe('cancelled')
  })

  it('updatedAt only moves forward and unknown events only touch lastEvent', () => {
    const later = applyEvent(d0, makeEvent('mystery.event', {}, 1, '2026-10-17T10:00:00.000Z'))
    expect(later.updatedAt).toBe('2026-10-17T10:00:00.000Z')
    expect(later.evidence).toBe(d0.evidence)
    const earlier = applyEvent(later, makeEvent('mystery.event', {}, 2, '2026-10-17T07:00:00.000Z'))
    expect(earlier.updatedAt).toBe('2026-10-17T10:00:00.000Z')
  })
})

describe('headlines (PROMPT 8.8 D)', () => {
  const h = (o: Partial<RequestDetail>) => deriveHeadline(makeRequestDetail(o))
  const ev = (role: 'conflict' | 'constraint', id: string) => ({
    evidenceId: id,
    role,
    nodeId: id,
    nodeType: 'Decision',
    title: 't',
    quote: null,
    source: { type: 'SlackMessage', id, url: null, author: null, at: null },
    confidence: 0.9,
    tier: 'HIGH' as const,
    path: [],
  })

  it('Investigating counts graph queries', () => {
    expect(h({ investigation: { mode: 'agent', toolCalls: 4, tokens: { input: 0, output: 0 }, costUsd: 0, stub: false } })).toBe('Investigating. 4 graph queries so far.')
    expect(h({ investigation: { mode: 'agent', toolCalls: 1, tokens: { input: 0, output: 0 }, costUsd: 0, stub: false } })).toBe('Investigating. 1 graph query so far.')
    expect(h({})).toBe('Investigating. Reading your memory.')
  })
  it('Needs your input names the decisions or the questions', () => {
    expect(h({ state: 'Needs your input', label: 'conflict', evidence: [ev('conflict', 'a'), ev('constraint', 'b')] })).toBe('Two earlier decisions affect this request.')
    expect(h({ state: 'Needs your input', label: 'possible_conflict', evidence: [ev('conflict', 'a')] })).toBe('One earlier decision affects this request.')
    expect(h({ state: 'Needs your input', label: 'clear' })).toBe('One question before the ticket.')
  })
  it('Ticket ready, awaiting approval, building', () => {
    expect(h({ state: 'Ticket ready', label: 'nothing_found' })).toBe('Nothing in your history touches this. Safe to continue.')
    expect(h({ state: 'Ticket ready', label: 'conflict' })).toBe('The ticket is written. Saving it now.')
    expect(h({ state: 'Awaiting approval', currentRevision: { n: 2, hash: 'h' } })).toBe('Ticket v2 is ready for your approval.')
    expect(h({ state: 'Building', builds: [build({ testsPassed: 3, testsFailed: 11 })] })).toBe('Building. 3 of 14 tests passed.')
    expect(h({ state: 'Building', builds: [build({ status: 'queued', queuePosition: 2 })] })).toBe('Queued for a build. Position 2.')
    expect(h({ state: 'Building', builds: [build({ status: 'waiting_budget' })] })).toBe('The build is waiting. The daily model budget is spent.')
    expect(h({ state: 'Building', builds: [build()] })).toBe('Building. Pi is making the change.')
    expect(h({ state: 'Building' })).toBe('Building. Preparing the container.')
  })
  it('Needs attention, PR ready, done, cancelled', () => {
    expect(h({ state: 'Needs attention', builds: [build({ status: 'failed', attempts: 2 })] })).toBe('The build failed after two repairs. Here is why.')
    expect(h({ state: 'Needs attention', builds: [build({ status: 'stopped', stopReason: 'missing_fork' })] })).toBe('There is no push target. Add a fork in Connect.')
    expect(h({ state: 'PR ready for review', pr: { number: 18, url: 'u', headSha: 'x', state: 'open', targetBranch: 'dev' } })).toBe('PR #18 is ready for review.')
    expect(h({ state: 'Done' })).toBe('Done. Merged scope recorded in memory.')
    expect(h({ state: 'Done', outcome: 'answered' })).toBe('Answered. The sources are below.')
    expect(h({ state: 'Cancelled' })).toBe('Cancelled. Nothing else will run.')
    expect(h({ state: 'Changes requested' })).toBe('Rebuilding with the review feedback.')
  })
  it('every state has a headline and a purpose line without hype or exclamation marks', () => {
    for (const state of STATES) {
      const d = makeRequestDetail({ state })
      expect(deriveHeadline(d).length).toBeGreaterThan(5)
      expect(derivePurpose(d)).toMatch(/^[A-Z].+\.$/)
      expect(`${deriveHeadline(d)}${derivePurpose(d)}`).not.toContain('!')
    }
  })
})

describe('tabs and approvals', () => {
  it('primaryTab points at the main action', () => {
    const t = (state: RequestDetail['state'], questions = 0) =>
      primaryTab({ state, questions: Array.from({ length: questions }, () => makeRequestDetail().questions[0] ?? ({} as never)) })
    expect(t('Needs your input', 1)).toBe('questions')
    expect(t('Needs your input', 0)).toBe('evidence')
    expect(t('Awaiting approval')).toBe('ticket')
    expect(t('Building')).toBe('build')
    expect(t('PR ready for review')).toBe('pr')
    expect(t('Investigating')).toBe('evidence')
  })

  it('ticketApprovalState detects approvals of an earlier revision (stale)', () => {
    const base = makeRequestDetail({ revisions: [rev(1, 'h1'), rev(2, 'h2')], currentRevision: { n: 2, hash: 'h2' } })
    const approval = (target: string) => ({ id: target, kind: 'ticket' as const, target, status: 'accepted' as const, reason: null, by: PERSON, surface: 'ui' as const, at: 'x' })
    expect(ticketApprovalState(base)).toEqual({ approvedN: null, stale: false })
    expect(ticketApprovalState({ ...base, approvals: [approval('h1')] })).toEqual({ approvedN: 1, stale: true })
    expect(ticketApprovalState({ ...base, approvals: [approval('h1'), approval('h2')] })).toEqual({ approvedN: 2, stale: false })
    expect(currentRevision(base)?.n).toBe(2)
    expect(latestBuild({ builds: [build({ id: 'a' }), build({ id: 'b' })] })?.id).toBe('b')
    expect(latestBuild({ builds: [] })).toBeNull()
  })
})
