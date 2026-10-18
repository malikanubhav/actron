import { describe, expect, it } from 'vitest'
import { computeLayout, depths, nodeRadius } from '@/components/graph/layout'
import {
  canvasLabels,
  clipMiddle,
  columnLayout,
  leastOverlap,
  nearestPointOnBox,
  segmentHitsBox,
  SHAPE_FAMILY,
  clusterLabel,
  sidesAwayFromLinks,
  codePath,
  displayLabel,
  fitView,
  groupOf,
  groupResults,
  hitTest,
  isCluster,
  isInferred,
  kindOf,
  legendShapes,
  linkAlpha,
  linkKey,
  linksTouching,
  mostConnected,
  neighbourInDirection,
  placeLabel,
  plainTypeName,
  radiusOf,
  resultContext,
  shapeEntryLabel,
  shapeFor,
  toScreen,
  toWorld,
  tracePlan,
  traceState,
  wrapLabel,
  type LabelBox,
} from '@/components/graph/model'
import { pathTraceBudgetMs, DUR, cubicBezier } from '@/lib/motion'
import type { GraphLink, GraphNode } from '@/lib/api/types'

const node = (id: string, extra: Partial<GraphNode> = {}): GraphNode => ({ id, type: 'CodeFunction', label: id, group: 'code', ...extra })
const link = (from: string, to: string, extra: Partial<GraphLink> = {}): GraphLink => ({ from, to, type: 'CALLS', method: null, confidence: null, ...extra })

describe('graph model', () => {
  it.each([
    ['Request', 'square'],
    ['Decision', 'diamond'],
    ['GithubPullRequest', 'triangle'],
    ['GitCommit', 'triangle'],
    ['LinearIssue', 'hexagon'],
    ['Person', 'ring'],
    ['SlackMessage', 'speech'],
    ['CodeFunction', 'circle'],
    ['CodeClass', 'circle'],
    ['CodeFile', 'file'],
    ['CodeDocument', 'file'],
    ['GitFileChange', 'triangle'],
    ['GithubUser', 'ring'],
    ['GitAuthor', 'ring'],
    ['Investigation', 'square'],
  ])('shape for %s is %s', (type, shape) => {
    expect(shapeFor(type)).toBe(shape)
  })

  it('test code and the aggregated test cluster are pills named in words', () => {
    const cluster = node('group:CodeFunction:test', { count: 194 })
    expect(kindOf(cluster)).toEqual({ key: 'test', name: 'Test function', shape: 'pill' })
    expect(kindOf(node('code:fn:o/r:src/extension-test/unit/a-test.ts::helper')).shape).toBe('pill')
    expect(kindOf(node('code:fn:o/r:src/extension-test/unit/common/text-notation.ts::docFromTextNotation')).shape).toBe('circle')
    expect(kindOf(node('code:fn:o/r:src/x.ts::suite > case')).shape).toBe('pill')
    expect(kindOf({ ...node('code:fn:o/r:src/a.test.ts::f'), props: { isTest: false } }).shape).toBe('circle')
    expect(kindOf(node('code:fn:o/r:src/a.ts::helper'))).toEqual({ key: 'CodeFunction', name: 'Function', shape: 'circle' })
    expect(clusterLabel(cluster)).toBe('194 test functions')
    expect(clusterLabel(node('group:CodeFunction', { count: 21 }))).toBe('21 functions')
    expect(displayLabel({ ...cluster, label: '194 tests' })).toBe('194 test functions')
    expect(isCluster(cluster)).toBe(true)
  })

  it('core types are coloured as core whatever group the API sends', () => {
    expect(groupOf({ type: 'Request', group: 'code' })).toBe('core')
    expect(groupOf({ type: 'Decision', group: 'slack' })).toBe('core')
    expect(groupOf({ type: 'CodeFunction', group: 'code' })).toBe('code')
    expect(groupOf({ type: 'Odd', group: 'nope' as never })).toBe('core')
  })

  it('labels show plain text: file base paths, short ids, "People"', () => {
    expect(displayLabel(node('f', { type: 'CodeFile', label: 'src/nrepl/index.ts' }))).toBe('nrepl/index.ts')
    expect(displayLabel(node('c', { type: 'GitCommit', label: 'git:commit:o/r:4c76dd351ef0' }))).toBe('Commit 4c76dd35')
    expect(plainTypeName('Person')).toBe('People')
    expect(plainTypeName('CodeFunction', 1)).toBe('Function')
    expect(codePath('code:chunk:o/r:src/a.ts#L4-L9')).toBe('src/a.ts')
    expect(resultContext('code:chunk:o/r:src/a.ts#L4-L9')).toBe('src/a.ts:4–9')
    expect(resultContext('git:commit:o/r:abc')).toBeNull()
  })

  it('canvas labels can be told apart: test titles keep their last part, equal names get the file', () => {
    const labels = canvasLabels([
      node('code:fn:o/r:src/f-test.ts::a', { label: 'formatter trimming > formatter does not trim trailing space' }),
      node('code:fn:o/r:src/f-test.ts::b', { label: 'formatter trimming > formatter trims trailing space' }),
      node('code:fn:o/r:src/format-test.ts::t', { label: 'textNotationFromDocAndSelections' }),
      node('code:fn:o/r:src/toggle-test.ts::t', { label: 'textNotationFromDocAndSelections' }),
    ])
    expect(labels.get('code:fn:o/r:src/f-test.ts::a')).toBe('formatter does not trim tra…')
    expect(labels.get('code:fn:o/r:src/f-test.ts::b')).toBe('formatter trims trailing sp…')
    expect(labels.get('code:fn:o/r:src/format-test.ts::t')).toBe('textNotationFromDocAn… (format-test.ts)')
    expect(labels.get('code:fn:o/r:src/toggle-test.ts::t')).toMatch(/ \(toggle-test\.ts\)$/)
    expect(new Set(labels.values()).size).toBe(4)
    expect(plainTypeName('GitAuthor')).toBe('Git authors')
    expect(plainTypeName('GithubRepository', 1)).toBe('GitHub repository')
    expect(plainTypeName('CodeRepository', 1)).toBe('Git repository')
  })

  it('counts that do not fit their shape go in the label; files keep their name; labels face away from links', () => {
    const labels = canvasLabels([
      node('type:GitFileChange', { type: 'GitFileChange', label: 'File changes', count: 3699 }),
      node('type:CodeFunction', { label: 'Functions', count: 5533 }),
      node('f', { type: 'CodeFile', label: 'src/extension-test/e2e/suite/jack-in-and-connect-test.ts' }),
    ])
    expect(labels.get('type:GitFileChange')).toBe('File changes · 3.7k')
    expect(labels.get('type:CodeFunction')).toBe('Functions')
    expect(labels.get('f')).toMatch(/^jack-in.*connect-test\.ts$/)
    expect(clipMiddle('suite/jack-in-and-connect-test.ts', 20)).toMatch(/…nect-test\.ts$/)
    const sides = sidesAwayFromLinks([link('a', 'b')], { a: { x: 0, y: 0 }, b: { x: 100, y: 0 } }, ['right', 'left', 'above', 'below'])
    expect(sides.get('a')?.[0]).toBe('left')
    expect(sides.get('b')?.[0]).toBe('right')
  })

  it('labels keep off the evidence path; quote cards take the spot covering the least', () => {
    const box = { x: 10, y: 10, w: 20, h: 10 }
    expect(segmentHitsBox({ x1: 0, y1: 15, x2: 50, y2: 15 }, box)).toBe(true)
    expect(segmentHitsBox({ x1: 0, y1: 0, x2: 50, y2: 0 }, box)).toBe(false)
    expect(segmentHitsBox({ x1: 15, y1: 12, x2: 16, y2: 13 }, box)).toBe(true)
    const bounds = { width: 400, height: 400 }
    const path = [{ x1: 100, y1: 100, x2: 300, y2: 100 }]
    expect(placeLabel(['right', 'below'], 100, 100, 5, 50, 16, [], [], bounds, -1, path)?.y).toBeGreaterThan(100)
    const at = leastOverlap([{ x: 0, y: 0 }, { x: 200, y: 200 }], 100, 50, [{ x: 0, y: 0, w: 150, h: 80 }], bounds)
    expect(at).toEqual({ x: 200, y: 200 })
    expect(nearestPointOnBox(0, 0, { x: 10, y: 10, w: 5, h: 5 })).toEqual({ x: 10, y: 10 })
    expect(Object.keys(SHAPE_FAMILY)).toHaveLength(9)
    const labels = canvasLabels([node('type:CodeFunction', { label: 'Functions', count: 5533 })], 24, true)
    expect(labels.get('type:CodeFunction')).toBe('Functions · 5.5k')
  })

  it('type overview: columns by source, sorted by count, every label right of its node and inside its column', () => {
    const types = [
      ['CodeFunction', 'code', 5533],
      ['CodeFile', 'code', 1108],
      ['GitCommit', 'code', 2000],
      ['GithubUser', 'github', 61],
      ['GithubBranch', 'github', 14],
      ['Request', 'core', 4],
      ['Person', 'core', 137],
    ] as const
    const nodes = types.map(([type, group, count]) => node(`type:${type}`, { type, group, count }))
    const layout = columnLayout(nodes, (id) => id.length * 7, 760, 420)
    expect(layout.headings.map((h) => h.text)).toEqual(['GitHub', 'Actron (core)', 'Code'])
    const code = ['type:CodeFunction', 'type:GitCommit', 'type:CodeFile'].map((id) => layout.positions[id]?.y as number)
    expect(code[0]).toBeLessThan(code[1] as number)
    expect(code[1]).toBeLessThan(code[2] as number)
    for (const n of nodes) {
      const p = layout.positions[n.id] as { x: number; y: number }
      const box = layout.labels.get(n.id) as LabelBox
      const r = layout.radius.get(n.id) as number
      expect(box.x).toBeGreaterThan(p.x + r)
      const col = layout.columns.find((c) => p.x >= c.x && p.x <= c.x + c.w) as { x: number; w: number }
      expect(col).toBeDefined()
      expect(box.x + box.w).toBeLessThanOrEqual(col.x + col.w + 0.001)
      for (const other of nodes) {
        if (other.id === n.id) continue
        const q = layout.positions[other.id] as { x: number; y: number }
        const rq = layout.radius.get(other.id) as number
        const inside = q.x + rq > box.x && q.x - rq < box.x + box.w && q.y + rq > box.y && q.y - rq < box.y + box.h
        expect(inside).toBe(false)
      }
    }
  })

  it('wraps a long anchor title onto two lines at word boundaries', () => {
    expect(wrapLabel('Make docFromTextNotation in the test utilities accept Windows line endings')).toEqual([
      'Make docFromTextNotation',
      'in the test utilities…',
    ])
    expect(wrapLabel('Short title')).toEqual(['Short title'])
  })

  it('places a label on the first free side and drops it when every side collides', () => {
    const bounds = { width: 400, height: 400 }
    const right = placeLabel(['right', 'left'], 100, 100, 5, 50, 16, [], [], bounds)
    expect(right).toEqual({ x: 109, y: 92, w: 50, h: 16 })
    const left = placeLabel(['right', 'left'], 100, 100, 5, 50, 16, [right as LabelBox], [], bounds)
    expect(left?.x).toBe(41)
    const own = { x: 95, y: 95, w: 10, h: 10 }
    expect(placeLabel(['right'], 100, 100, 5, 50, 16, [], [own], bounds, 0)).not.toBeNull()
    const wall = { x: 0, y: 0, w: 400, h: 400 }
    expect(placeLabel(['right', 'left', 'above', 'below'], 100, 100, 5, 50, 16, [], [wall], bounds)).toBeNull()
    expect(placeLabel(['right'], 390, 100, 5, 50, 16, [], [], bounds)).toBeNull()
  })

  it('legend: one entry per shape on screen, anchor shape first, names by weight', () => {
    const entries = [
      { kind: kindOf(node('a')), group: 'code' as const, weight: 21 },
      { kind: kindOf(node('b', { type: 'CodeClass' })), group: 'code' as const, weight: 50 },
      { kind: kindOf(node('r', { type: 'Request' })), group: 'core' as const, weight: 1 },
    ]
    const shapes = legendShapes(entries, 'square')
    expect(shapes.map((s) => s.shape)).toEqual(['square', 'circle'])
    expect(shapes[1]?.names).toEqual(['Class', 'Function'])
    expect(shapeEntryLabel(['A', 'B', 'C', 'D'])).toBe('A, B and 2 more')
  })

  it('explorer start graph: the most connected non-hub nodes and the links among them', () => {
    const sample = {
      nodes: [node('repo', { type: 'CodeRepository' }), node('a', { type: 'CodeFile' }), node('b', { type: 'CodeFile' }), node('c', { type: 'CodeFile' }), node('d', { type: 'CodeFile' })],
      links: [link('a', 'repo'), link('b', 'repo'), link('a', 'b'), link('a', 'c'), link('b', 'a'), link('c', 'd')],
    }
    const g = mostConnected(sample, 3)
    expect(g?.nodes.map((n) => n.id)).toEqual(['a', 'b', 'c'])
    expect(g?.links).toHaveLength(2)
    expect(mostConnected({ nodes: [], links: [] })).toBeNull()
  })

  it('search results: named things first, chunks last, grouped by plain type', () => {
    const groups = groupResults([
      { id: '1', type: 'CodeChunk' },
      { id: '2', type: 'CodeFunction' },
      { id: '3', type: 'GitCommit' },
      { id: '4', type: 'CodeFunction' },
    ])
    expect(groups.map((g) => g.name)).toEqual(['Functions', 'Commit', 'Code chunk'])
    expect(groups[0]?.items.map((i) => i.id)).toEqual(['2', '4'])
  })

  it('explicit links are solid, inferred links dashed', () => {
    expect(isInferred({ method: null })).toBe(false)
    expect(isInferred({ method: 'parsed' })).toBe(false)
    expect(isInferred({ method: 'jev' })).toBe(true)
    expect(isInferred({ method: 'model:conflict' })).toBe(true)
    expect(isInferred({ method: 'fuzzy_match' })).toBe(true)
    expect(isInferred({ method: 'unknown' })).toBe(false)
  })

  it('link opacity follows confidence and stays visible', () => {
    expect(linkAlpha({ confidence: null })).toBe(0.85)
    expect(linkAlpha({ confidence: 0 })).toBe(0.25)
    expect(linkAlpha({ confidence: 0.5 })).toBe(0.55)
    expect(linkAlpha({ confidence: 5 })).toBe(0.85)
  })

  it('link keys are direction independent', () => {
    expect(linkKey('a', 'b')).toBe(linkKey('b', 'a'))
    expect(linksTouching([link('a', 'b'), link('c', 'd')], new Set(['b']))).toHaveLength(1)
  })

  it('C-AC-13 tracePlan keeps consecutive hops present on the canvas', () => {
    const nodes = ['r', 'd', 'f', 'c'].map((id) => node(id))
    expect(tracePlan(['r', 'd', 'x', 'f'], nodes)).toEqual([
      { from: 'r', to: 'd', index: 0 },
      { from: 'd', to: 'f', index: 1 },
    ])
    expect(tracePlan(['r'], nodes)).toEqual([])
  })

  it('C-AC-13 the trace highlights exactly the path and finishes within hops × 520 ms + 300 ms', () => {
    const hops = tracePlan(['r', 'd', 'f', 'c'], ['r', 'd', 'f', 'c'].map((id) => node(id)))
    const start = traceState(hops, 0)
    expect([...start.nodes]).toEqual(['r'])
    expect(start.active?.hop.to).toBe('d')
    const mid = traceState(hops, DUR[4] * 1.5)
    expect([...mid.nodes]).toEqual(['r', 'd'])
    expect([...mid.links]).toEqual([linkKey('r', 'd')])
    expect(mid.active?.t).toBeCloseTo(0.5)
    const end = traceState(hops, pathTraceBudgetMs(hops.length))
    expect(end.done).toBe(true)
    expect([...end.nodes].sort()).toEqual(['c', 'd', 'f', 'r'])
    expect(end.links.size).toBe(3)
    expect(pathTraceBudgetMs(3)).toBe(3 * 520 + 300)
  })

  it('C-AC-13 a frame timestamp just before the trace start reads as the start, not a missing hop', () => {
    const hops = tracePlan(['r', 'd'], ['r', 'd'].map((id) => node(id)))
    const s = traceState(hops, -4)
    expect(s.active?.hop.from).toBe('r')
    expect(s.active?.t).toBe(0)
  })

  it('C-AC-13 reduced motion shows the whole path immediately', () => {
    const hops = tracePlan(['r', 'd', 'f'], ['r', 'd', 'f'].map((id) => node(id)))
    const s = traceState(hops, 0, true)
    expect(s.done).toBe(true)
    expect(s.nodes.size).toBe(3)
    expect(traceState([], 0).done).toBe(true)
  })

  it('hit testing, screen/world transforms and fit', () => {
    const nodes = [node('a'), node('b', { count: 50 })]
    const positions = { a: { x: 0, y: 0 }, b: { x: 100, y: 0 } }
    const view = { x: 10, y: 20, k: 2 }
    expect(toScreen({ x: 1, y: 1 }, view)).toEqual({ x: 12, y: 22 })
    expect(toWorld({ x: 12, y: 22 }, view)).toEqual({ x: 1, y: 1 })
    expect(hitTest({ x: 10, y: 20 }, nodes, positions, view)?.id).toBe('a')
    expect(hitTest({ x: 210, y: 20 }, nodes, positions, view)?.id).toBe('b')
    expect(hitTest({ x: 110, y: 20 }, nodes, positions, view)).toBeNull()
    expect(radiusOf({ count: 50 })).toBeGreaterThan(radiusOf({}))
    expect(nodeRadius(50)).toBe(radiusOf({ count: 50 }))
    const fit = fitView(positions, 400, 300)
    expect(toScreen(positions.a, fit).x).toBeGreaterThanOrEqual(47)
    expect(toScreen(positions.b, fit).x).toBeLessThanOrEqual(353)
    expect(fitView({}, 400, 300)).toEqual({ x: 0, y: 0, k: 1 })
  })

  it('C-AC-32 arrow keys move to the neighbour that lies in that direction', () => {
    const links = [link('c', 'r'), link('c', 'l'), link('c', 'u'), link('c', 'd'), link('x', 'y')]
    const p = { c: { x: 0, y: 0 }, r: { x: 50, y: 5 }, l: { x: -50, y: 0 }, u: { x: 0, y: -50 }, d: { x: 3, y: 50 }, x: { x: 500, y: 0 } }
    expect(neighbourInDirection('c', 'right', links, p)).toBe('r')
    expect(neighbourInDirection('c', 'left', links, p)).toBe('l')
    expect(neighbourInDirection('c', 'up', links, p)).toBe('u')
    expect(neighbourInDirection('c', 'down', links, p)).toBe('d')
    expect(neighbourInDirection('r', 'right', links, p)).toBeNull()
    expect(neighbourInDirection('missing', 'right', links, p)).toBeNull()
  })

  it('cubic bezier easing hits its end points and is monotonic', () => {
    const ease = cubicBezier(0.3, 0, 0, 1)
    expect(ease(0)).toBe(0)
    expect(ease(1)).toBe(1)
    expect(ease(0.5)).toBeGreaterThan(ease(0.25))
  })
})

describe('layout (spec C, C2 GraphCanvas)', () => {
  const nodes = ['r', 'd1', 'd2', 'f1', 'f2', 'c1'].map((id) => ({ id, group: 'code' }))
  const links = [
    { from: 'r', to: 'd1' },
    { from: 'r', to: 'd2' },
    { from: 'd1', to: 'f1' },
    { from: 'd2', to: 'f2' },
    { from: 'f1', to: 'c1' },
  ]

  it('depths are BFS hops from the anchor; unreachable nodes go last', () => {
    const d = depths([...nodes, { id: 'lonely', group: 'core' }], links, 'r')
    expect(d.get('r')).toBe(0)
    expect(d.get('d1')).toBe(1)
    expect(d.get('c1')).toBe(3)
    expect(d.get('lonely')).toBe(4)
    expect(depths(nodes, links, null).get('r')).toBe(1)
  })

  it('the anchor sits at the left edge and hops unfold to the right within bounds', () => {
    const pos = computeLayout({ nodes, links, width: 800, height: 400, anchorId: 'r' })
    expect(pos.r).toEqual({ x: 56, y: 200 })
    const x = (id: string) => (pos[id] as { x: number }).x
    expect(x('d1')).toBeGreaterThan(x('r'))
    expect(x('f1')).toBeGreaterThan(x('d1'))
    expect(x('c1')).toBeGreaterThan(x('f1'))
    for (const p of Object.values(pos)) {
      expect(p.x).toBeGreaterThanOrEqual(28)
      expect(p.x).toBeLessThanOrEqual(772)
      expect(p.y).toBeGreaterThanOrEqual(28)
      expect(p.y).toBeLessThanOrEqual(372)
    }
  })

  it('existing nodes stay close when new ones arrive', () => {
    const first = computeLayout({ nodes, links, width: 800, height: 400, anchorId: 'r' })
    const second = computeLayout({
      nodes: [...nodes, { id: 'c2', group: 'code' }],
      links: [...links, { from: 'f2', to: 'c2' }],
      width: 800,
      height: 400,
      anchorId: 'r',
      previous: first,
    })
    for (const id of ['d1', 'f1']) {
      const a = first[id] as { x: number; y: number }
      const b = second[id] as { x: number; y: number }
      expect(Math.hypot(a.x - b.x, a.y - b.y)).toBeLessThan(120)
    }
    expect(second.c2).toBeDefined()
  })

  it('empty input gives no positions; self links and dangling links are ignored', () => {
    expect(computeLayout({ nodes: [], links: [], width: 100, height: 100 })).toEqual({})
    const pos = computeLayout({ nodes: [{ id: 'a', group: 'x' }], links: [{ from: 'a', to: 'a' }, { from: 'a', to: 'zz' }], width: 200, height: 200 })
    expect(Object.keys(pos)).toEqual(['a'])
  })
})
