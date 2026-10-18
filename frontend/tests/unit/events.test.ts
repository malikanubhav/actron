import { describe, expect, it } from 'vitest'
import {
  ALL_EVENT_TYPES,
  eventGlyph,
  eventNodeIds,
  eventSentence,
  idTail,
  isKnownEventType,
  shortArgs,
  sourceName,
  stopReasonText,
  surfaceName,
  systemStep,
  toolCallLabel,
  toolGlyph,
  type SystemContext,
} from '@/lib/events'
import { GLYPH_NAMES } from '@/components/glyphs/names'
import { reduceSystemMap } from '@/components/system/SystemMap'
import { makeEvent } from './helpers/render'

import { PAYLOADS } from './helpers/payloads'

describe('C-AC-9 every event type has a sentence and a glyph', () => {
  it('the payload table covers every event type', () => {
    expect(Object.keys(PAYLOADS).sort()).toEqual([...ALL_EVENT_TYPES].sort())
  })

  it.each([...ALL_EVENT_TYPES])('C-AC-9 %s: plain sentence and a valid glyph', (type) => {
    const e = makeEvent(type, PAYLOADS[type])
    const s = eventSentence(e)
    expect(s.length).toBeGreaterThan(5)
    expect(s).not.toMatch(/undefined|NaN|\[object Object\]|!$/)
    expect(GLYPH_NAMES).toContain(eventGlyph(e))
  })

  it('C-AC-9 sentences survive empty payloads without leaking undefined', () => {
    for (const type of ALL_EVENT_TYPES) {
      const s = eventSentence(makeEvent(type, {}))
      expect(s, type).not.toMatch(/undefined|NaN|\[object Object\]/)
      expect(s.length, type).toBeGreaterThan(3)
    }
  })

  it('B-AC-35 a skipped Linear sync says the ticket stayed in Actron and why', () => {
    const e = makeEvent('ticket.synced', { n: 2, skipped: true, reason: 'Linear did not accept the ticket (RetryableProviderError)' })
    expect(eventSentence(e)).toBe('Ticket v2 kept in Actron. Not in Linear: Linear did not accept the ticket (RetryableProviderError).')
    expect(eventSentence(makeEvent('ticket.synced', { n: 1, skipped: true, reason: 'Linear not connected' }))).toContain('Linear not connected')
  })

  it('unknown event types still get a sentence', () => {
    expect(eventSentence(makeEvent('approval.requested', {}))).toBe('approval requested.')
    expect(isKnownEventType('approval.requested')).toBe(false)
    expect(isKnownEventType('tool.called')).toBe(true)
  })

  it('key sentences read as plain language', () => {
    const s = (t: string) => eventSentence(makeEvent(t, PAYLOADS[t]))
    expect(s('request.created')).toBe('Dana Ilić asked in Slack.')
    expect(s('tool.called')).toBe('Called callers(evaluateCode, depth 3).')
    expect(s('tests.result')).toBe('12 of 14 tests passed. 2 failed.')
    expect(s('writeback.done')).toBe('Memory updated: 1 PR, 2 commits, 3 functions.')
    expect(s('handoff.created')).toBe('Handed 5 pieces of evidence to the build.')
    expect(s('approval.refused')).toBe('Approval refused: the ticket changed after this approval was started.')
    expect(s('budget.reached')).toBe('The daily model budget is spent ($20.00 of $20.00). The build waits.')
  })

  it('glyph choices follow the event meaning', () => {
    expect(eventGlyph(makeEvent('tests.result', { passed: 3, failed: 0 }))).toBe('TestPass')
    expect(eventGlyph(makeEvent('tests.result', { passed: 3, failed: 1 }))).toBe('TestFail')
    expect(eventGlyph(makeEvent('evidence.found', { role: 'conflict' }))).toBe('Conflict')
    expect(eventGlyph(makeEvent('handoff.created', {}))).toBe('Handoff')
    expect(toolGlyph('shortest_path')).toBe('ShortestPath')
    expect(toolGlyph('impact')).toBe('Impact')
    expect(toolGlyph('get_code')).toBe('ToolCall')
  })
})

describe('C-AC-14 system map steps (spec B, B.C2a)', () => {
  const step = (type: string, payload?: Record<string, unknown>, ctx?: SystemContext) => systemStep(makeEvent(type, payload ?? PAYLOADS[type]), ctx)

  it.each([
    ['request.created', 'slack', 'actron', 'New request from Dana Ilić'],
    ['tool.called', 'actron', 'falkordb', 'callers(evaluateCode, depth 3)'],
    ['judgment.made', 'actron', 'jev', 'Judging 3 decisions'],
    ['question.asked', 'actron', 'slack', 'Asked: Which branch should this change go into?'],
    ['ticket.synced', 'actron', 'linear', 'Ticket CAL-214 v1'],
    ['approval.recorded', 'slack', 'actron', 'Approved by Dana Ilić'],
    ['handoff.created', 'actron', 'pi', 'Evidence handed to the build'],
    ['build.step', 'pi', 'pi', 'Editing src/evaluate.ts'],
    ['tests.result', 'pi', 'actron', '12/14 tests passed'],
    ['pr.opened', 'actron', 'github', 'PR #18 opened'],
    ['writeback.done', 'actron', 'falkordb', 'Memory updated'],
    ['memory.refreshing', 'github', 'falkordb', 'Syncing merged code'],
  ])('C-AC-14 %s: %s → %s with caption "%s"', (type, from, to, caption) => {
    expect(step(type)).toMatchObject({ from, to, caption })
  })

  it('C-AC-14 a Pi tool call goes from Pi to FalkorDB and its result back to Pi', () => {
    expect(step('tool.called', { ...PAYLOADS['tool.called'], by: 'pi', callId: 'p9' })).toMatchObject({ from: 'pi', to: 'falkordb' })
    const ctx: SystemContext = { callers: new Map([['p9', { by: 'pi', tool: 'tests_for', args: { ids: ['code:fn:a'] } }]]) }
    expect(step('tool.result', { callId: 'p9', ok: true, summary: '3 tests' }, ctx)).toMatchObject({ from: 'falkordb', to: 'pi', caption: 'tests_for(a) · 3 tests' })
  })

  it('C-AC-14 an investigator result returns to Actron with its summary', () => {
    const ctx: SystemContext = { callers: new Map([['c1', { by: 'investigator', tool: 'callers', args: { functionId: 'x#evaluateCode' } }]]) }
    expect(step('tool.result', undefined, ctx)).toMatchObject({ from: 'falkordb', to: 'actron', caption: 'callers(evaluateCode) · Found 12 callers in 5 files' })
  })

  it('C-AC-14 an approval from the UI starts at the UI actor; LLM judgments go to the LLM', () => {
    expect(step('approval.recorded', { ...PAYLOADS['approval.recorded'], surface: 'ui' })).toMatchObject({ from: 'ui' })
    expect(step('judgment.made', { provider: 'llm', count: 2, what: 'links' })).toMatchObject({ to: 'llm', caption: 'Judging 2 links' })
  })

  it('C-AC-14 state changes drive no edge', () => {
    expect(step('request.state_changed')).toBeNull()
  })

  it('C-AC-14 ingestion events come from their source', () => {
    expect(step('ingestion.progress')).toMatchObject({ from: 'slack', to: 'falkordb' })
    expect(step('ingestion.partial')).toMatchObject({ from: 'linear' })
    expect(step('ingestion.started')).toMatchObject({ from: 'github' })
  })

  it('C-AC-14 reduceSystemMap keeps the latest caption per actor and the active edge, only from real events', () => {
    expect(reduceSystemMap([])).toEqual({ captions: {}, active: null, edges: {}, steps: [] })
    const events = [
      makeEvent('request.created', PAYLOADS['request.created'], 1),
      makeEvent('tool.called', PAYLOADS['tool.called'], 2),
      makeEvent('tool.result', PAYLOADS['tool.result'], 3),
    ]
    const state = reduceSystemMap(events)
    expect(state.steps).toHaveLength(3)
    expect(state.captions.falkordb).toBe('callers(evaluateCode, depth 3) · Found 12 callers in 5 files')
    expect(state.active?.actor).toBe('falkordb')
    expect(Object.keys(state.edges).sort()).toEqual(['actron-falkordb', 'actron-slack'])
  })
})

describe('event helpers', () => {
  it('idTail picks the readable end of an id', () => {
    expect(idTail('code:fn:src/evaluate.ts#evaluateCode')).toBe('evaluateCode')
    expect(idTail('github:pr:1296')).toBe('1296')
    expect(idTail('plain')).toBe('plain')
  })
  it('shortArgs abbreviates ids, quotes queries, names numbers and collapses long lists', () => {
    expect(shortArgs({ functionId: 'code:fn:a.ts#run', depth: 3 })).toBe('run, depth 3')
    expect(shortArgs({ query: 'inline results' })).toBe('"inline results"')
    expect(shortArgs({ ids: ['a:x', 'a:y', 'a:z', 'a:w'] })).toBe('x, y +2')
    expect(shortArgs({ includeSuperseded: true })).toBe('include superseded true')
    expect(shortArgs(null)).toBe('')
    expect(toolCallLabel('search', { query: 'q' })).toBe('search("q")')
  })
  it('eventNodeIds collects nodeIds, nodeId and path without duplicates', () => {
    expect(eventNodeIds(makeEvent('x', { nodeIds: ['a', 'b'], nodeId: 'b', path: ['c', 'a'] }))).toEqual(['a', 'b', 'c'])
    expect(eventNodeIds(makeEvent('x', {}))).toEqual([])
  })
  it('names surfaces, sources and stop reasons in plain words', () => {
    expect(surfaceName('slack')).toBe('Slack')
    expect(surfaceName('ui')).toBe('Actron')
    expect(sourceName('code')).toBe('GitHub')
    expect(sourceName('slack_export')).toBe('Slack')
    expect(sourceName('jira')).toBe('Jira')
    expect(stopReasonText('missing_fork')).toBe('There is no push target. Add a fork in Connect.')
    expect(stopReasonText(null)).toBe('The build stopped.')
    expect(stopReasonText('custom reason')).toBe('custom reason')
  })
})
