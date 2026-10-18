import { describe, expect, it } from 'vitest'
import type { Build, Run } from '@/lib/api/types'
import { eventSentence, plainReason, plainSummary, systemStep } from '@/lib/events'
import { setupFixFor } from '@/components/request/RequestScreen'
import { cappedCount, conflictDecision, conflictSentence, investigationText } from '@/components/request/tabs/EvidencePanel'
import { collapseActivity, lastActivity, nowLine, runEdgeStates, runText, unavailableActors } from '@/components/system/SystemScreen'
import { routeEdges } from '@/components/system/SystemMap'
import { testPlanGroups, uniqueFunctions } from '@/components/request/TicketView'
import { makeEvent, makeRequestDetail } from '../helpers/render'

const build = (over: Partial<Build> = {}): Build => ({
  id: 'b1',
  status: 'stopped',
  queuePosition: null,
  branch: 'actron/x',
  baseSha: 'abc1234',
  headSha: null,
  testsPassed: 0,
  testsFailed: 0,
  attempts: 0,
  startedAt: '2026-10-17T09:00:00Z',
  finishedAt: '2026-10-17T09:00:01Z',
  stopReason: 'missing_identity',
  tokens: { input: 0, output: 0 },
  costUsd: 0,
  report: {},
  ...over,
})

describe('plain timeline sentences', () => {
  it('judgments made without a model say so plainly', () => {
    expect(eventSentence(makeEvent('judgment.made', { job: 'rank_candidates', what: 'candidates', count: 20, provider: 'stub' }))).toBe(
      'Ranked 20 candidates without a model (no key set).',
    )
    expect(eventSentence(makeEvent('judgment.made', { job: 'needs_question', what: 'findings', count: 1, provider: 'stub' }))).toBe(
      'Checked whether to ask about 1 finding without a model (no key set).',
    )
    expect(eventSentence(makeEvent('judgment.made', { job: 'rank_candidates', what: 'candidates', count: 3, provider: 'jev' }))).toBe('Jev ranked 3 candidates.')
  })
  it('no internal words or class names leak', () => {
    expect(eventSentence(makeEvent('investigation.started', { mode: 'pipeline' }))).not.toMatch(/pipeline|stub/)
    expect(eventSentence(makeEvent('memory.unverified', { reason: 'Could not reach the repository (ExternalError).' }))).toBe(
      'Memory could not be checked: Could not reach the repository.',
    )
    expect(plainReason('AuthError: GitHub rejected the token: Requires authentication')).toBe('GitHub rejected the token: Requires authentication')
    expect(eventSentence(makeEvent('ingestion.finished', { source: 'github', status: 'failed', reason: 'AuthError: bad token' }))).toBe('GitHub sync failed: bad token.')
  })
  it('notifications name what needs attention', () => {
    const e = makeEvent('notification.sent', { kind: 'build_failed', channel: 'ui' })
    expect(eventSentence(e)).toBe('Sent an inbox notice: the build needs attention.')
    expect(systemStep(e)?.caption).toBe('Sent an inbox notice: the build needs attention')
  })
  it('tool summaries count in the singular for one', () => {
    expect(plainSummary('1 results')).toBe('1 result')
    expect(plainSummary('11 results')).toBe('11 results')
    expect(plainSummary('1 matches')).toBe('1 match')
  })
})

describe('request header for setup stops', () => {
  it('a setup stop reason sends the primary action to the fix', () => {
    const detail = makeRequestDetail({ state: 'Needs attention', builds: [build()] })
    expect(setupFixFor(detail)?.href).toBe('/app/settings#bot-identity')
    expect(setupFixFor(makeRequestDetail({ state: 'Needs attention', builds: [build({ stopReason: 'missing_fork' })] }))?.href).toBe('/app/connect')
    expect(setupFixFor(makeRequestDetail({ state: 'Needs attention', builds: [build({ stopReason: 'scope_change' })] }))).toBeNull()
  })
  it('the investigation line says how it ran in plain words', () => {
    expect(investigationText({ mode: 'pipeline', stub: true } as never)).toBe('Investigated without a model (no key set)')
  })
})

describe('system idle line', () => {
  const run = (over: Partial<Run> = {}): Run => ({
    id: 'r',
    source: 'code',
    mode: 'incremental',
    status: 'done',
    startedAt: '2026-10-18T03:00:00Z',
    finishedAt: '2026-10-18T03:00:30Z',
    items: {},
    errors: [],
    ...over,
  })
  const now = Date.parse('2026-10-18T03:10:30Z')
  it('says nothing runs and names the last activity', () => {
    expect(runText(run())).toBe('Code sync finished')
    expect(lastActivity([], [run()], [])?.text).toBe('Code sync finished')
    const line = nowLine({ events: [], runs: [run()], requests: [], runningRequests: 0, now })
    expect(line).toEqual({ idle: true, text: 'Nothing is running right now. Last activity 10 min ago: Code sync finished.' })
  })
  it('a running sync or request is not idle', () => {
    expect(nowLine({ events: [], runs: [run({ status: 'running', finishedAt: null })], requests: [], runningRequests: 0, now }).idle).toBe(false)
    expect(nowLine({ events: [], runs: [], requests: [], runningRequests: 2, now }).idle).toBe(false)
  })
})

describe('round 2: ticket template, system state and log', () => {
  it('affected functions show once per name; the test plan groups and de-duplicates', () => {
    expect(uniqueFunctions(['code:fn:r:a.ts::foo', 'code:fn:r:b.ts::foo', 'code:fn:r:c.ts::bar'])).toEqual([
      { name: 'foo', ids: ['code:fn:r:a.ts::foo', 'code:fn:r:b.ts::foo'] },
      { name: 'bar', ids: ['code:fn:r:c.ts::bar'] },
    ])
    const plan = [
      { kind: 'existing' as const, target: 'code:fn:r:t.ts::suite > a', command: '' },
      { kind: 'existing' as const, target: 'code:fn:r:t.ts::suite > a', command: '' },
      { kind: 'existing' as const, target: 'code:fn:r:t.ts::suite > b', command: '' },
      { kind: 'new' as const, target: 't', command: 'npm test -- inline' },
    ]
    expect(testPlanGroups(plan)).toEqual([
      { kind: 'existing', items: ['suite > a', 'suite > b'] },
      { kind: 'new', items: ['npm test -- inline'] },
    ])
  })
  it('identical consecutive log rows fold into one with a count', () => {
    const rows = collapseActivity([
      { key: '1', text: 'Code sync finished', at: '2026-10-18T03:00:00Z' },
      { key: '2', text: 'Code sync finished', at: '2026-10-18T02:45:00Z' },
      { key: '3', text: 'Request X: now needs attention', at: '2026-10-18T02:40:00Z', requestId: 'r' },
    ])
    expect(rows.map((r) => [r.text, r.count])).toEqual([
      ['Code sync finished', 2],
      ['Request X: now needs attention', 1],
    ])
    expect(rows[0]?.firstAt).toBe('2026-10-18T02:45:00Z')
  })
  it('actors that cannot work now are named with the reason', () => {
    const settings = { jobs: [{ job: 'x', primitive: 'p', provider: 'stub', status: 'stub' }], models: { decision: '', writing: '', agent: '', coding: '' } } as never
    expect(unavailableActors(['code', 'github'], settings)).toEqual({ slack: 'not connected', linear: 'not connected', jev: 'no key', llm: 'no key', pi: 'no key' })
    expect(unavailableActors(null, null)).toEqual({})
  })
})

describe('round 4: conflict banner names the decision or says it could not', () => {
  const decision = {
    id: 'd1',
    statement: 'Keep LF line endings in test fixtures.',
    status: 'approved' as const,
    quote: 'q',
    source: { id: 's', type: 'SlackMessage', url: 'https://x' },
    conflict: { label: 'possible_conflict' as const, probability: 0.7 },
    path: ['a', 'd1'],
  }
  it('names the most likely flagged decision', () => {
    const detail = makeRequestDetail({ findings: { decisions: [decision, { ...decision, id: 'd0', conflict: { label: 'none', probability: 0.9 } }] } as never })
    expect(conflictDecision(detail)?.id).toBe('d1')
    expect(conflictSentence(conflictDecision(detail), false)).toBe('Decision: “Keep LF line endings in test fixtures”')
  })
  it('without a decision it says so plainly', () => {
    expect(conflictDecision(makeRequestDetail({ findings: { decisions: [] } as never }))).toBeNull()
    expect(conflictSentence(null, true)).toMatch(/could not name a decision without a model\. Check the evidence below before you approve\./)
    expect(conflictSentence(null, true, false, true)).toMatch(/The ticket was approved with this flag open\.$/)
  })
})

describe('impact counts at the graph list cap', () => {
  it('shows a count at the 200-row cap as a lower bound', () => {
    expect(cappedCount(23)).toBe('23')
    expect(cappedCount(200)).toBe('200+')
  })
})

describe('round 11: syncs light the map, one line per pair', () => {
  it('a source-to-graph step travels through Actron on drawn links', () => {
    expect(routeEdges('github', 'falkordb')).toEqual([
      ['github', 'actron'],
      ['actron', 'falkordb'],
    ])
    expect(routeEdges('actron', 'falkordb')).toEqual([['actron', 'falkordb']])
  })
  it('recent and running syncs mark their links used and active', () => {
    const now = Date.parse('2026-10-18T10:00:00Z')
    const run = (over: Partial<Run>): Run => ({ id: 'r', source: 'code', mode: 'incremental', status: 'done', startedAt: '', finishedAt: '2026-10-18T09:55:00Z', items: {}, errors: [], ...over })
    expect(runEdgeStates([run({})], now)).toEqual({ 'actron-github': 'used', 'actron-falkordb': 'used' })
    expect(runEdgeStates([run({ finishedAt: '2026-10-18T09:00:00Z' })], now)).toEqual({})
    expect(runEdgeStates([run({ source: 'linear', status: 'running', finishedAt: null }), run({})], now)).toEqual({
      'actron-linear': 'active',
      'actron-falkordb': 'active',
      'actron-github': 'used',
    })
  })
})
