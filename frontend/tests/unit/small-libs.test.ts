import { describe, expect, it } from 'vitest'
import { qk } from '@/lib/query-keys'
import { detectKind, KIND_LABEL } from '@/lib/kind'
import { mergeSubgraphs, filterSubgraph, groupLinks } from '@/lib/subgraph'
import { readBuildReport } from '@/lib/build-report'
import type { Subgraph } from '@/lib/api/types'

describe('query keys (spec C, C4)', () => {
  it('match the documented shapes', () => {
    expect(qk.requests({ group: 'done', limit: 20 })).toEqual(['requests', { group: 'done', limit: 20 }])
    expect(qk.request('r1')).toEqual(['request', 'r1'])
    expect(qk.events('r1')).toEqual(['events', 'r1'])
    expect(qk.subgraph('r1', 'expanded')).toEqual(['subgraph', 'r1', 'expanded'])
    expect(qk.ingestion()).toEqual(['ingestion'])
    expect(qk.connections()).toEqual(['connections'])
    expect(qk.notifications()).toEqual(['notifications'])
    expect(qk.settings()).toEqual(['settings'])
    expect(qk.graphSearch('eval')).toEqual(['graph-search', 'eval', ''])
    expect(qk.node('n1')).toEqual(['node', 'n1'])
  })

  it('prefix keys invalidate their children', () => {
    expect(qk.subgraph('r1', 'aggregated').slice(0, 2)).toEqual([...qk.subgraphAll('r1')])
    expect(qk.requests().slice(0, 1)).toEqual([...qk.requestsAll()])
    expect(qk.revisions('r1').slice(0, 2)).toEqual([...qk.request('r1')])
  })
})

describe('request kind detection', () => {
  it.each([
    ['Why does evaluate trim comments?', 'question'],
    ['how is the REPL started', 'question'],
    ['Formatting crashes on reader conditionals', 'bug'],
    ['Paredit no longer works in strings', 'bug'],
    ['Show evaluation results inline', 'feature'],
    ['', 'feature'],
  ])('%s → %s', (text, kind) => {
    expect(detectKind(text)).toBe(kind)
  })
  it('labels', () => expect(KIND_LABEL).toEqual({ feature: 'FEATURE', bug: 'BUG', question: 'QUESTION' }))
})

const g = (ids: string[], links: [string, string, string][] = []): Subgraph => ({
  mode: 'expanded',
  truncated: false,
  nodes: ids.map((id) => ({ id, type: id.startsWith('f') ? 'CodeFunction' : 'Decision', label: id, group: id.startsWith('f') ? 'code' : 'core' })),
  links: links.map(([from, to, type]) => ({ from, to, type, method: null, confidence: null })),
})

describe('subgraph helpers', () => {
  it('merge keeps unique nodes and links', () => {
    const m = mergeSubgraphs(g(['f1', 'd1'], [['f1', 'd1', 'A']]), g(['d1', 'f2'], [['f1', 'd1', 'A'], ['d1', 'f2', 'B']]))
    expect(m.nodes.map((n) => n.id)).toEqual(['f1', 'd1', 'f2'])
    expect(m.links).toHaveLength(2)
    expect(mergeSubgraphs(null, g(['x'])).nodes).toHaveLength(1)
  })
  it('filter by type and group drops dangling links', () => {
    const base = g(['f1', 'd1'], [['f1', 'd1', 'A']])
    const onlyCode = filterSubgraph(base, new Set(), new Set(['code']))
    expect(onlyCode?.nodes.map((n) => n.id)).toEqual(['f1'])
    expect(onlyCode?.links).toEqual([])
    expect(filterSubgraph(base, new Set(), new Set())).toBe(base)
    expect(filterSubgraph(null, new Set(['x']), new Set())).toBeNull()
  })
  it('groups links by type, largest first', () => {
    const groups = groupLinks(g([], [['a', 'b', 'X'], ['a', 'c', 'Y'], ['a', 'd', 'Y']]).links)
    expect(groups.map(([t, l]) => [t, l.length])).toEqual([
      ['Y', 2],
      ['X', 1],
    ])
  })
})

describe('build report reading', () => {
  it('reads tests, constraints, files and procedures', () => {
    const r = readBuildReport({
      tests: [{ name: 't1', status: 'fail', output: 'boom' }, { name: 't2', status: 'weird' }],
      constraints: [{ text: 'c', status: 'holds', proof: { kind: 'evidence', label: 'PR #12', url: 'u' } }, { text: 'd' }],
      filesChanged: [{ path: 'src/a.ts', additions: 3, deletions: 1 }],
      procedures: [{ title: 'Run tests', testCommand: 'npm test' }],
    })
    expect(r.tests).toEqual([
      { name: 't1', status: 'fail', output: 'boom', durationMs: undefined },
      { name: 't2', status: 'pass', output: undefined, durationMs: undefined },
    ])
    expect(r.constraints[0]?.proof).toEqual({ kind: 'evidence', label: 'PR #12', url: 'u' })
    expect(r.constraints[1]).toEqual({ text: 'd', status: 'unverified', proof: null })
    expect(r.filesChanged[0]?.additions).toBe(3)
    expect(r.procedures[0]?.testCommand).toBe('npm test')
  })
  it('missing or malformed reports render as empty, never guessed', () => {
    expect(readBuildReport(null)).toEqual({ tests: [], constraints: [], filesChanged: [], procedures: [] })
    expect(readBuildReport({ tests: 'nope' }).tests).toEqual([])
  })
})
