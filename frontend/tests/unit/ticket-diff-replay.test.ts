import { describe, expect, it } from 'vitest'
import { contentFrom, diffTickets, draftFrom, isDirty, validateDraft } from '@/lib/ticket'
import { countChanges, parsePatch, shikiLang } from '@/lib/diff'
import { baseDetail, detailAt, stepDelay, subgraphFromFindings } from '@/lib/replay'
import type { SharedQuery } from '@/lib/api/types'
import { makeEvent, makeRequestDetail, TICKET } from './helpers/render'

describe('ticket helpers (spec B, B.C5; C-AC-43)', () => {
  it('diffTickets reports only changed fields with added and removed lines', () => {
    const after = { ...TICKET, acceptanceCriteria: [...TICKET.acceptanceCriteria, 'Results clear on edit.'], targetBranch: 'main' }
    const diff = diffTickets(TICKET, after)
    expect(diff.map((d) => d.field)).toEqual(['acceptanceCriteria', 'targetBranch'])
    expect(diff[0]?.lines).toEqual([
      { kind: 'same', text: TICKET.acceptanceCriteria[0] },
      { kind: 'added', text: 'Results clear on edit.' },
    ])
    expect(diff[1]?.lines).toEqual([
      { kind: 'removed', text: 'dev' },
      { kind: 'added', text: 'main' },
    ])
    expect(diffTickets(TICKET, TICKET)).toEqual([])
  })

  it('test plan and constraints diff by their text', () => {
    const after = { ...TICKET, testPlan: [{ kind: 'new' as const, target: 't', command: 'npm test -- inline' }] }
    const lines = diffTickets(TICKET, after)[0]?.lines ?? []
    expect(lines).toContainEqual({ kind: 'added', text: 'New: npm test -- inline' })
    expect(lines).toContainEqual({ kind: 'removed', text: 'Existing: npm test -- evaluate' })
  })

  it('draft round trip keeps evidence links for unchanged constraints', () => {
    const draft = draftFrom(TICKET)
    expect(contentFrom(draft, TICKET)).toEqual(TICKET)
    const edited = contentFrom({ ...draft, constraintsToPreserve: `${draft.constraintsToPreserve}\nNew constraint`, acceptanceCriteria: ' a \n\n b ' }, TICKET)
    expect(edited.constraintsToPreserve).toEqual([...TICKET.constraintsToPreserve, { text: 'New constraint', evidenceIds: [] }])
    expect(edited.acceptanceCriteria).toEqual(['a', 'b'])
  })

  it('C-AC-43 validation explains each problem in plain words', () => {
    const draft = draftFrom(TICKET)
    expect(validateDraft(draft)).toEqual({})
    expect(validateDraft({ ...draft, objective: 'short' }).objective).toMatch(/one full sentence/)
    expect(validateDraft({ ...draft, objective: 'x'.repeat(301) }).objective).toMatch(/300 characters/)
    expect(validateDraft({ ...draft, acceptanceCriteria: ' \n ' }).acceptanceCriteria).toMatch(/at least one/)
    expect(validateDraft({ ...draft, targetBranch: 'bad branch' }).targetBranch).toMatch(/branch name/)
  })

  it('isDirty compares every field', () => {
    const d = draftFrom(TICKET)
    expect(isDirty(d, d)).toBe(false)
    expect(isDirty({ ...d, context: 'changed' }, d)).toBe(true)
  })
})

describe('unified diff parsing', () => {
  const patch = ['diff --git a/x b/x', '--- a/x', '+++ b/x', '@@ -10,3 +10,4 @@ fn', ' keep', '-old', '+new', '+added', ' tail', '\\ No newline at end of file', ''].join('\n')

  it('numbers old and new lines', () => {
    const rows = parsePatch(patch)
    expect(rows.map((r) => [r.kind, r.oldNo, r.newNo])).toEqual([
      ['hunk', null, null],
      ['ctx', 10, 10],
      ['del', 11, null],
      ['add', null, 11],
      ['add', null, 12],
      ['ctx', 12, 13],
    ])
    expect(countChanges(rows)).toEqual({ additions: 2, deletions: 1 })
  })

  it('handles CRLF and several hunks', () => {
    const rows = parsePatch('@@ -1 +1 @@\r\n-a\r\n+b\r\n@@ -20,1 +20,1 @@\r\n-c\r\n+d')
    expect(rows.filter((r) => r.kind === 'hunk')).toHaveLength(2)
    expect(rows.at(-1)).toMatchObject({ kind: 'add', newNo: 20, text: 'd' })
  })

  it('maps file extensions to highlighter languages', () => {
    expect(shikiLang('src/evaluate.ts')).toBe('typescript')
    expect(shikiLang('src/calva/fmt.cljs')).toBe('clojure')
    expect(shikiLang('package.json')).toBe('json')
    expect(shikiLang('Makefile')).toBe('text')
  })
})

describe('replay (C-AC-24 logic)', () => {
  const final = makeRequestDetail({
    state: 'Done',
    label: 'conflict',
    outcome: 'approved',
    pipelineStep: 6,
    allowedActions: ['cancel'],
    pr: { number: 18, url: 'u', headSha: 'f', state: 'merged', targetBranch: 'dev' },
  })
  const events = [
    makeEvent('request.created', { requester: { name: 'Dana' }, source: 'slack' }, 1),
    makeEvent('investigation.completed', { label: 'conflict' }, 2),
    makeEvent('request.state_changed', { to: 'Needs your input' }, 3),
    makeEvent('request.state_changed', { to: 'Done' }, 4),
  ]

  it('baseDetail empties everything events fill in', () => {
    const b = baseDetail(final)
    expect(b).toMatchObject({ state: 'Investigating', label: null, pr: null, outcome: null, evidence: [], approvals: [], allowedActions: [] })
    expect(b.title).toBe(final.title)
  })

  it('detailAt rebuilds intermediate views and ends in the recorded final view', () => {
    expect(detailAt(final, events, 0).state).toBe('Investigating')
    const mid = detailAt(final, events, 3)
    expect(mid.state).toBe('Needs your input')
    expect(mid.label).toBe('conflict')
    expect(detailAt(final, events, events.length)).toEqual({ ...final, allowedActions: [] })
  })

  it('stepDelay clamps the real gap and divides by speed', () => {
    const e = (at: string, seq: number) => makeEvent('x', {}, seq, at)
    const evs = [e('2026-10-17T09:00:00Z', 1), e('2026-10-17T09:00:00.100Z', 2), e('2026-10-17T09:05:00Z', 3), e('2026-10-17T09:05:00.800Z', 4)]
    expect(stepDelay(evs, 1, 1)).toBe(260)
    expect(stepDelay(evs, 2, 1)).toBe(1400)
    expect(stepDelay(evs, 3, 2)).toBe(400)
    expect(stepDelay(evs, 0, 4)).toBe(150)
  })

  it('public replays build the canvas from the findings graph', () => {
    const findings = {
      graph: {
        nodes: [
          { id: 'r', type: 'Request', label: 'R' },
          { id: 'f', type: 'CodeFunction', label: 'f' },
          { id: 's', type: 'SlackMessage', label: 's' },
        ],
        edges: [{ from: 'r', to: 'f', type: 'TOUCHES' }],
      },
    } as unknown as SharedQuery
    const sub = subgraphFromFindings(findings)
    expect(sub?.nodes.map((n) => n.group)).toEqual(['core', 'code', 'slack'])
    expect(sub?.links[0]).toEqual({ from: 'r', to: 'f', type: 'TOUCHES', method: null, confidence: null })
    expect(subgraphFromFindings(null)).toBeNull()
  })
})
