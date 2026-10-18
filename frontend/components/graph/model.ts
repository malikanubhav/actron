/** Pure graph-canvas logic: shapes, link styles, path tracing, hit testing and keyboard traversal. */
import type { GraphLink, GraphNode, NodeGroup, Subgraph } from '@/lib/api/types'
import { DUR } from '@/lib/motion'
import { formatNumber } from '@/lib/format'
import { typeName } from '@/lib/type-names'
import type { Positions } from './layout'

/**
 * Shapes per type (spec C2). `file` is a portrait page with a cut corner, so a file never reads as the square
 * request; `pill` (a wide capsule) marks test code, including the aggregated test cluster.
 */
export type NodeShape = 'square' | 'diamond' | 'triangle' | 'hexagon' | 'circle' | 'ring' | 'speech' | 'file' | 'pill'

/** Node shape encodes type; colour encodes source (PROMPT 8.8 D). */
export function shapeFor(type: string): NodeShape {
  const t = type.toLowerCase()
  if (t === 'request' || t === 'investigation' || (t.endsWith('request') && !t.includes('pull'))) return 'square'
  if (t.includes('decision')) return 'diamond'
  if (t.includes('pullrequest') || t.includes('commit') || t.includes('review') || t.includes('filechange')) return 'triangle'
  if (t.includes('issue') || t.includes('ticket')) return 'hexagon'
  if (t.includes('person') || t.includes('user') || t.includes('member') || t.includes('author') || t.includes('identity')) return 'ring'
  if (t.includes('slack') || t.includes('message') || t.includes('thread')) return 'speech'
  if (t === 'codefile' || t === 'file' || t.endsWith('document')) return 'file'
  return 'circle'
}

const CORE_TYPES = new Set(['Workspace', 'Person', 'Identity', 'Team', 'Reference', 'Feature', 'Decision', 'Procedure', 'Request', 'Investigation', 'BuildRun', 'Evidence'])
const GROUPS: readonly NodeGroup[] = ['code', 'github', 'slack', 'linear', 'core']

/** The source a node is coloured by: core types always count as core, unknown groups fall back to core. */
export function groupOf(node: Pick<GraphNode, 'type' | 'group'>): NodeGroup {
  if (CORE_TYPES.has(node.type)) return 'core'
  return GROUPS.includes(node.group) ? node.group : 'core'
}

/** The file path inside a code node id (`code:fn:owner/repo:src/a.ts::name` → `src/a.ts`), or null. */
export function codePath(id: string): string | null {
  const m = /^code:[a-z]+:[^:]+:(.+?)(?:::|#|$)/.exec(id)
  return m ? (m[1] as string) : null
}

/** Test files by name: a.test.ts, a-test.ts, a_test.go, a.spec.js, test_a.py. A test folder alone is not enough. */
const TEST_FILE = /(^test_|[._-](test|spec)\.[a-z0-9]+$)/i

/**
 * Test code: the aggregated test cluster, a node the API flags isTest, or a function or class in a test file
 * (by file name) or named like a test case ("suite > case"). A helper in a test-utilities folder stays a function.
 */
export function isTestNode(node: Pick<GraphNode, 'id' | 'type'> & { props?: Record<string, unknown> | null }): boolean {
  if (node.id.startsWith('group:') && node.id.endsWith(':test')) return true
  if (typeof node.props?.isTest === 'boolean') return node.props.isTest
  if (!/function|class|method/i.test(node.type)) return false
  const name = node.id.split('::').pop() ?? ''
  if (name.includes(' > ')) return true
  const path = codePath(node.id)
  const file = path?.split('/').pop() ?? ''
  return TEST_FILE.test(file)
}

export interface NodeKind {
  /** Stable key for the legend: one entry per kind on screen. */
  key: string
  /** Plain singular name, e.g. "Function", "Test function", "Pull request". */
  name: string
  shape: NodeShape
}

export function kindOf(node: Pick<GraphNode, 'id' | 'type'> & { props?: Record<string, unknown> | null }): NodeKind {
  if (isTestNode(node)) {
    const base = typeName(node.type, 1).toLowerCase()
    return { key: 'test', name: `Test ${base}`, shape: 'pill' }
  }
  return { key: node.type, name: plainTypeName(node.type, 1), shape: shapeFor(node.type) }
}

export const isCluster = (node: Pick<GraphNode, 'count'>): boolean => (node.count ?? 0) > 1

/** "194 test functions", "21 functions": the count and the type in words, for an aggregated cluster. */
export function clusterLabel(node: Pick<GraphNode, 'id' | 'type' | 'count'>): string {
  const count = node.count ?? 0
  const words = typeName(node.type, count).toLowerCase()
  return `${formatNumber(count)} ${isTestNode(node) ? `test ${words}` : words}`
}

/** What a numbered disc stands for, for its hover card. */
export function clusterDescription(node: Pick<GraphNode, 'id' | 'type' | 'count'>): string {
  return `A group of ${clusterLabel(node)} linked to this request. Switch to Expanded to see each one.`
}

/** Plain type names for people: `typeName` plus the irregular plural it cannot know ("People", not "Persons"). */
const PRECISE_NAMES: Record<string, [string, string]> = {
  Person: ['Person', 'People'],
  CodeRepository: ['Git repository', 'Git repositories'],
  GithubRepository: ['GitHub repository', 'GitHub repositories'],
  GitAuthor: ['Git author', 'Git authors'],
  GithubUser: ['GitHub user', 'GitHub users'],
  SlackUser: ['Slack user', 'Slack users'],
  LinearUser: ['Linear user', 'Linear users'],
  Identity: ['Linked identity', 'Linked identities'],
  GitBranch: ['Git branch', 'Git branches'],
  GithubBranch: ['GitHub branch', 'GitHub branches'],
  GithubIssue: ['GitHub issue', 'GitHub issues'],
  LinearIssue: ['Linear issue', 'Linear issues'],
}

/**
 * Plain type names for people: `typeName`, plus the irregular plural it cannot know ("People") and the source for
 * types that exist in more than one source ("Git authors" and "GitHub users", not "Authors" and "Users").
 */
export function plainTypeName(type: string, count = 2): string {
  const precise = PRECISE_NAMES[type]
  if (precise) return count === 1 ? precise[0] : precise[1]
  return typeName(type, count)
}

/**
 * The text drawn next to a node: the precise label for an aggregated cluster; a file's base name; and for nodes
 * whose label is only their id ("git:commit:owner/repo:4c76dd3…"), the type and a short id.
 */
export function displayLabel(node: Pick<GraphNode, 'id' | 'type' | 'count' | 'label'>): string {
  if (node.id.startsWith('group:') && isCluster(node)) return clusterLabel(node)
  const label = node.label || node.id
  if (shapeFor(node.type) === 'file' && label.includes('/')) return label.split('/').slice(-2).join('/')
  if (/^[a-z]+:[a-z_]+:/.test(label)) {
    const tail = (label.split(/[:/]/).pop() ?? '').slice(0, 8)
    return `${typeName(node.type, 1)} ${tail}`
  }
  return label
}

const clip = (text: string, max: number) => (text.length > max ? `${text.slice(0, max - 1)}…` : text)

/** Cuts the middle so the end (a file name) survives: "suite/jack-in-…-test.ts". */
export function clipMiddle(text: string, max: number): string {
  if (text.length <= max) return text
  const tail = Math.ceil((max - 1) * 0.6)
  return `${text.slice(0, max - 1 - tail)}…${text.slice(text.length - tail)}`
}

/** Shapes roomy enough to carry a cluster's count inside; other shapes put the count in the label. */
export function countFitsInside(shape: NodeShape): boolean {
  return shape === 'circle' || shape === 'ring' || shape === 'pill' || shape === 'square'
}

export function compactCount(count: number): string {
  return count > 999 ? `${Math.round(count / 100) / 10}k` : String(count)
}

/**
 * Short canvas labels that can be told apart. Test titles ("suite > case") keep only their last part, the part that
 * differs; files show their name (with the folder when two share a name), cut in the middle; labels that are still
 * equal get the file name after them ("textNotation… · format-test.ts"). Counts that do not fit inside their shape
 * follow the label ("File changes · 3.7k").
 */
export function canvasLabels(nodes: readonly Pick<GraphNode, 'id' | 'type' | 'count' | 'label'>[], max = 28, countsInLabels = false): Map<string, string> {
  const base = new Map<string, string>()
  const fileNames = new Map<string, number>()
  for (const n of nodes) {
    if (shapeFor(n.type) === 'file' && n.label.includes('/')) {
      const name = n.label.split('/').pop() as string
      fileNames.set(name, (fileNames.get(name) ?? 0) + 1)
    }
  }
  for (const n of nodes) {
    const text = displayLabel(n)
    const parts = text.split(' > ')
    let label = parts.length > 1 ? (parts[parts.length - 1] as string).trim() : text
    if (shapeFor(n.type) === 'file' && n.label.includes('/')) {
      const name = n.label.split('/').pop() as string
      label = clipMiddle((fileNames.get(name) ?? 0) > 1 ? n.label.split('/').slice(-2).join('/') : name, max)
    }
    if (countsInLabels && (n.count ?? 0) >= 1) label = `${clip(label, max - 7)} · ${compactCount(n.count ?? 0)}`
    else if (isCluster(n) && !countFitsInside(kindOf(n).shape)) label = `${clip(label, max - 7)} · ${compactCount(n.count ?? 0)}`
    base.set(n.id, label)
  }
  const seen = new Map<string, number>()
  for (const n of nodes) {
    const key = clip(base.get(n.id) as string, max)
    seen.set(key, (seen.get(key) ?? 0) + 1)
  }
  const out = new Map<string, string>()
  for (const n of nodes) {
    const text = base.get(n.id) as string
    const short = clip(text, max)
    const path = codePath(n.id)
    if ((seen.get(short) ?? 0) > 1 && path) {
      const file = path.split('/').pop() as string
      // One name, then its file in parentheses: "textNotationFrom… (toggle-…-test.ts)".
      out.set(n.id, `${clip(text, Math.max(12, max - 6))} (${clipMiddle(file, 20)})`)
    } else out.set(n.id, short)
  }
  return out
}

const SIDE_DIRECTION: Record<LabelSide, [number, number]> = {
  right: [1, 0],
  left: [-1, 0],
  above: [0, -1],
  below: [0, 1],
  'above-start': [0.5, -1],
  'below-start': [0.5, 1],
  'above-end': [-0.5, -1],
  'below-end': [-0.5, 1],
}

/**
 * Label sides per node, ordered so the side facing away from the node's links comes first (labels stay off edges).
 * Computed once per layout, not per frame.
 */
export function sidesAwayFromLinks(
  links: readonly Pick<GraphLink, 'from' | 'to'>[],
  positions: Positions,
  sides: readonly LabelSide[],
): Map<string, LabelSide[]> {
  const sum = new Map<string, [number, number]>()
  const add = (id: string, other: string) => {
    const a = positions[id]
    const b = positions[other]
    if (!a || !b) return
    const dx = b.x - a.x
    const dy = b.y - a.y
    const len = Math.hypot(dx, dy) || 1
    const s = sum.get(id) ?? [0, 0]
    s[0] += dx / len
    s[1] += dy / len
    sum.set(id, s)
  }
  for (const l of links) {
    add(l.from, l.to)
    add(l.to, l.from)
  }
  const out = new Map<string, LabelSide[]>()
  for (const [id, [x, y]] of sum) {
    const score = (side: LabelSide) => {
      const [sx, sy] = SIDE_DIRECTION[side]
      return (sx * x + sy * y) / Math.hypot(sx, sy)
    }
    // Stable: equal scores keep the preferred order (right first).
    out.set(id, [...sides].map((s, i) => ({ s, k: score(s) + i * 1e-3 })).sort((a, b) => a.k - b.k).map((e) => e.s))
  }
  return out
}

/** Splits text at word boundaries into at most `lines` lines of up to `max` characters; the last line ends in "…" when cut. */
export function wrapLabel(text: string, max = 26, lines = 2): string[] {
  const words = text.split(/\s+/).filter(Boolean)
  const out: string[] = []
  let current = ''
  let i = 0
  for (; i < words.length; i++) {
    const word = words[i] as string
    const next = current ? `${current} ${word}` : word
    if (next.length <= max) {
      current = next
      continue
    }
    if (out.length === lines - 1) break
    if (current) out.push(current)
    current = word.length > max ? `${word.slice(0, max - 1)}…` : word
  }
  if (i < words.length) current = `${(current.length >= max ? current.slice(0, max - 1) : current).replace(/…$/, '')}…`
  if (current) out.push(current)
  return out
}

export interface ShapeEntry {
  shape: NodeShape
  /** Plain names of the kinds drawn with this shape, most common first. */
  names: string[]
  /** The source most nodes of this shape belong to; the legend icon takes its colour. */
  group: NodeGroup
  count: number
}

/** One legend entry per shape on screen, naming the kinds that use it; the anchor's shape comes first. */
export function legendShapes(entries: readonly { kind: NodeKind; group: NodeGroup; weight?: number }[], anchorShape?: NodeShape): ShapeEntry[] {
  const byShape = new Map<NodeShape, { names: Map<string, number>; groups: Map<NodeGroup, number>; count: number }>()
  for (const { kind, group, weight = 1 } of entries) {
    const e = byShape.get(kind.shape) ?? { names: new Map(), groups: new Map(), count: 0 }
    e.names.set(kind.name, (e.names.get(kind.name) ?? 0) + weight)
    e.groups.set(group, (e.groups.get(group) ?? 0) + weight)
    e.count += weight
    byShape.set(kind.shape, e)
  }
  const top = <K,>(m: Map<K, number>) => [...m.entries()].sort((a, b) => b[1] - a[1]).map(([k]) => k)
  return [...byShape.entries()]
    .map(([shape, e]) => ({ shape, names: top(e.names), group: top(e.groups)[0] as NodeGroup, count: e.count }))
    .sort((a, b) => Number(b.shape === anchorShape) - Number(a.shape === anchorShape) || b.count - a.count)
}

/** What each shape stands for as a family, for type-level graphs where many types share a shape (follows shapeFor). */
export const SHAPE_FAMILY: Record<NodeShape, string> = {
  circle: 'Functions, classes and records',
  ring: 'People and identities',
  square: "Actron's requests and investigations",
  triangle: 'Changes (commits, file changes, pull requests)',
  file: 'Files and documents',
  pill: 'Test code',
  diamond: 'Decisions',
  hexagon: 'Issues',
  speech: 'Messages',
}

export const COLUMN_ORDER: readonly NodeGroup[] = ['github', 'core', 'code', 'slack', 'linear']
export const COLUMN_HEADING: Record<NodeGroup, string> = {
  github: 'GitHub',
  core: 'Actron (core)',
  code: 'Code',
  slack: 'Slack',
  linear: 'Linear',
}

export interface ColumnLayout {
  /** Node centres in canvas pixels at zoom 1. */
  positions: Positions
  /** Node radius, capped so each stack fits. */
  radius: Map<string, number>
  /** Label boxes, always right of their node (canvas pixels at zoom 1). */
  labels: Map<string, LabelBox>
  /** Column headings, top-left at (x, y). */
  headings: { group: NodeGroup; text: string; x: number; y: number }[]
  /** Each (sub-)column's extent, for tests and hit areas. */
  columns: { group: NodeGroup; x: number; w: number }[]
  /** The view that shows the whole layout: scaled down only when the columns are wider than the canvas. */
  view: View
}

const COLUMN_TOP = 44
const COLUMN_BOTTOM = 16
const MIN_ROW = 30
const MAX_ROW = 64
const COLUMN_GAP = 32
const COLUMN_LABEL_GAP = 6

/**
 * The type-level overview (Connect) as columns by source: one column per source present, nodes stacked by count
 * (largest first) and spread over the height, each label always right of its node, so every label pairs with one
 * node. A column with more nodes than fit splits into two sub-columns. Columns are centred in the canvas.
 */
export function columnLayout(
  nodes: readonly Pick<GraphNode, 'id' | 'type' | 'group' | 'count'>[],
  labelWidth: (id: string) => number,
  width: number,
  height: number,
): ColumnLayout {
  const positions: Positions = {}
  const radius = new Map<string, number>()
  const labels = new Map<string, LabelBox>()
  const headings: ColumnLayout['headings'] = []
  const columns: ColumnLayout['columns'] = []
  const usable = Math.max(MIN_ROW, height - COLUMN_TOP - COLUMN_BOTTOM)
  const fit = Math.max(1, Math.floor(usable / MIN_ROW))
  const byGroup = new Map<NodeGroup, typeof nodes[number][]>()
  for (const n of nodes) {
    const g = groupOf(n)
    byGroup.set(g, [...(byGroup.get(g) ?? []), n])
  }
  // Sub-columns per source, each with its nodes, widest node and widest label.
  const subs: { group: NodeGroup; first: boolean; items: typeof nodes[number][]; rmax: number; lmax: number }[] = []
  for (const g of COLUMN_ORDER) {
    const list = [...(byGroup.get(g) ?? [])].sort((a, b) => (b.count ?? 0) - (a.count ?? 0) || a.id.localeCompare(b.id))
    if (!list.length) continue
    const parts = list.length > fit ? 2 : 1
    const per = Math.ceil(list.length / parts)
    for (let p = 0; p < parts; p++) {
      const items = list.slice(p * per, (p + 1) * per)
      const row = Math.min(MAX_ROW, usable / Math.max(1, items.length))
      // Leave a clear gap between stacked shapes (files and triangles are taller than their radius suggests).
      const cap = Math.max(4, row / 2 - 7)
      const rmax = Math.max(...items.map((n) => Math.min(radiusOf(n), cap)))
      for (const n of items) radius.set(n.id, Math.min(radiusOf(n), cap))
      subs.push({ group: g, first: p === 0, items, rmax, lmax: Math.max(...items.map((n) => labelWidth(n.id))) })
    }
  }
  const widths = subs.map((s) => s.rmax * 2 + COLUMN_LABEL_GAP + s.lmax)
  const total = widths.reduce((a, b) => a + b, 0) + COLUMN_GAP * Math.max(0, subs.length - 1)
  let x = Math.max(16, (width - total) / 2)
  subs.forEach((s, i) => {
    const w = widths[i] as number
    columns.push({ group: s.group, x, w })
    if (s.first) headings.push({ group: s.group, text: COLUMN_HEADING[s.group], x, y: 14 })
    const row = Math.min(MAX_ROW, usable / s.items.length)
    const top = COLUMN_TOP + (usable - row * s.items.length) / 2
    const cx = x + s.rmax
    s.items.forEach((n, j) => {
      const cy = top + row * (j + 0.5)
      const r = radius.get(n.id) ?? s.rmax
      positions[n.id] = { x: cx, y: cy }
      labels.set(n.id, { x: cx + r + COLUMN_LABEL_GAP, y: cy - 8, w: labelWidth(n.id), h: 16 })
    })
    x += w + COLUMN_GAP
  })
  // Wider than the canvas: scale down around the centre so every column shows.
  const k = total + 32 > width ? Math.max(0.5, width / (total + 32)) : 1
  const view = k === 1 ? { x: 0, y: 0, k } : { x: (width - total * k) / 2 - 16 * k, y: (height - height * k) / 2, k }
  return { positions, radius, labels, headings, columns, view }
}

/** "Function", "Function, Class", "Function, Class and 4 more". */
export function shapeEntryLabel(names: readonly string[], max = 2): string {
  if (names.length <= max) return names.join(', ')
  return `${names.slice(0, max).join(', ')} and ${names.length - max} more`
}

export const GROUP_TOKEN: Record<NodeGroup, string> = {
  code: '--node-code',
  github: '--node-github',
  slack: '--node-slack',
  linear: '--node-linear',
  core: '--node-core',
}

export const GROUP_LABEL: Record<NodeGroup, string> = {
  code: 'Code',
  github: 'GitHub',
  slack: 'Slack',
  linear: 'Linear',
  core: 'Core',
}

/** What the Core source means, for titles on legends and filters. */
export const CORE_HINT = 'Requests, investigations, decisions and people Actron creates'

const EXPLICIT_METHODS = new Set(['explicit', 'parsed', 'api', 'git', 'structural', 'import', 'call', 'blame', 'reference'])

/** Solid for explicit links, dashed for inferred ones (model-made, fuzzy match). */
export function isInferred(link: Pick<GraphLink, 'method'>): boolean {
  if (!link.method) return false
  const m = link.method.toLowerCase()
  if (EXPLICIT_METHODS.has(m)) return false
  return m.includes('infer') || m.includes('model') || m.includes('jev') || m.includes('llm') || m.includes('fuzzy') || m.includes('semantic')
}

/** Opacity encodes confidence; never below 0.25 so weak links stay visible. */
export function linkAlpha(link: Pick<GraphLink, 'confidence'>): number {
  const c = link.confidence ?? 1
  return Math.round((0.25 + 0.6 * Math.max(0, Math.min(1, c))) * 100) / 100
}

export const linkKey = (from: string, to: string) => (from < to ? `${from}→${to}` : `${to}→${from}`)

export interface TraceHop {
  from: string
  to: string
  index: number
}

/** The hops of an evidence path, keeping only consecutive pairs that exist on the canvas. */
export function tracePlan(path: readonly string[], nodes: readonly Pick<GraphNode, 'id'>[]): TraceHop[] {
  const present = new Set(nodes.map((n) => n.id))
  const visible = path.filter((id) => present.has(id))
  const hops: TraceHop[] = []
  for (let i = 0; i < visible.length - 1; i++) hops.push({ from: visible[i] as string, to: visible[i + 1] as string, index: i })
  return hops
}

export interface TraceState {
  /** Nodes reached so far (always includes the first node once tracing starts). */
  nodes: Set<string>
  /** Link keys fully traced. */
  links: Set<string>
  /** The hop being drawn and its progress 0..1, or null when done. */
  active: { hop: TraceHop; t: number } | null
  done: boolean
}

/** Where the trace is after `elapsedMs`. Reduced motion jumps to the end (C-AC-13). */
export function traceState(hops: readonly TraceHop[], elapsedMs: number, reduced = false): TraceState {
  const nodes = new Set<string>()
  const links = new Set<string>()
  if (hops.length === 0) return { nodes, links, active: null, done: true }
  nodes.add((hops[0] as TraceHop).from)
  const per = DUR[4]
  // A frame timestamp can be slightly earlier than the trace start; treat it as the start.
  const elapsed = Math.max(0, elapsedMs)
  const completed = reduced ? hops.length : Math.min(hops.length, Math.floor(elapsed / per))
  for (let i = 0; i < completed; i++) {
    const hop = hops[i] as TraceHop
    nodes.add(hop.to)
    links.add(linkKey(hop.from, hop.to))
  }
  if (completed >= hops.length) return { nodes, links, active: null, done: true }
  const hop = hops[completed] as TraceHop
  return { nodes, links, active: { hop, t: (elapsed - completed * per) / per }, done: false }
}

export function radiusOf(node: Pick<GraphNode, 'count'>): number {
  if (!node.count || node.count <= 1) return 7
  return Math.min(22, 8 + Math.sqrt(node.count) * 2.2)
}

export const ANCHOR_RADIUS = 11

/** Hubs every file links to (repository, component, package); they would top any degree ranking and say nothing. */
const HUB_TYPES = new Set(['CodeRepository', 'CodeComponent', 'CodeDependency', 'GithubRepository', 'GithubOrganization', 'Workspace'])

/**
 * The most connected nodes of a sample, counting only links between non-hub nodes, with the links among them:
 * a small starting graph for the explorer before any search.
 */
export function mostConnected(sample: Pick<Subgraph, 'nodes' | 'links'> | null | undefined, limit = 24): Subgraph | null {
  if (!sample?.nodes.length) return null
  const kept = new Map(sample.nodes.filter((n) => !HUB_TYPES.has(n.type)).map((n) => [n.id, n]))
  const degree = new Map<string, number>()
  for (const l of sample.links) {
    if (l.from === l.to || !kept.has(l.from) || !kept.has(l.to)) continue
    degree.set(l.from, (degree.get(l.from) ?? 0) + 1)
    degree.set(l.to, (degree.get(l.to) ?? 0) + 1)
  }
  const top = [...degree.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).slice(0, limit)
  if (top.length < 2) return null
  const ids = new Set(top.map(([id]) => id))
  const nodes = top.map(([id]) => kept.get(id) as GraphNode)
  const seen = new Set<string>()
  const links = sample.links.filter((l) => {
    if (!ids.has(l.from) || !ids.has(l.to) || l.from === l.to) return false
    const key = linkKey(l.from, l.to)
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
  return { mode: 'expanded', nodes, links, truncated: false }
}

/** Named things first, raw code chunks last (search results). */
const RESULT_RANK = ['CodeFunction', 'CodeClass', 'CodeFile', 'Decision', 'Person', 'Request', 'GithubPullRequest', 'LinearIssue', 'GithubIssue', 'SlackMessage', 'GitCommit']

export function resultRank(type: string): number {
  if (type === 'CodeChunk') return RESULT_RANK.length + 2
  const i = RESULT_RANK.indexOf(type)
  return i === -1 ? RESULT_RANK.length : i
}

/** Search results grouped by plain type name, groups in rank order, results keeping the API's order inside. */
export function groupResults<T extends { id: string; type: string }>(results: readonly T[]): { type: string; name: string; items: T[] }[] {
  const groups = new Map<string, T[]>()
  for (const r of results) groups.set(r.type, [...(groups.get(r.type) ?? []), r])
  return [...groups.entries()]
    .sort((a, b) => resultRank(a[0]) - resultRank(b[0]))
    .map(([type, items]) => ({ type, name: plainTypeName(type, items.length), items }))
}

/** A second line that tells same-named results apart: the file path (and line range for code chunks). */
export function resultContext(id: string): string | null {
  const path = codePath(id)
  if (!path) return null
  const lines = /#L(\d+)(?:-L(\d+))?$/.exec(id)
  return lines ? `${path}:${lines[1]}${lines[2] ? `–${lines[2]}` : ''}` : path
}

export interface LabelBox {
  x: number
  y: number
  w: number
  h: number
}

/** Where a label sits: beside the node, centred above or below it, or above or below starting at its left edge. */
export type LabelSide = 'right' | 'left' | 'above' | 'below' | 'above-start' | 'below-start' | 'above-end' | 'below-end'

/** Boxes closer than `m` pixels count as overlapping, so neighbouring labels never touch. */
const overlaps = (a: LabelBox, b: LabelBox, m = 0) => a.x < b.x + b.w + m && a.x + a.w + m > b.x && a.y < b.y + b.h + m && a.y + a.h + m > b.y
const LABEL_GAP = 4

/** The top-left of a label of width w and height h on one side of a node at (x, y) with screen radius r. */
export function labelBox(side: LabelSide, x: number, y: number, r: number, w: number, h: number, gap = 4): LabelBox {
  switch (side) {
    case 'right':
      return { x: x + r + gap, y: y - h / 2, w, h }
    case 'left':
      return { x: x - r - gap - w, y: y - h / 2, w, h }
    case 'above':
      return { x: x - w / 2, y: y - r - gap - h, w, h }
    case 'above-start':
      return { x: x - r, y: y - r - gap - h, w, h }
    case 'above-end':
      return { x: x + r - w, y: y - r - gap - h, w, h }
    case 'below-start':
      return { x: x - r, y: y + r + gap - 2, w, h }
    case 'below-end':
      return { x: x + r - w, y: y + r + gap - 2, w, h }
    default:
      return { x: x - w / 2, y: y + r + gap - 2, w, h }
  }
}

/**
 * Collision-aware label placement: tries right, left, above and below the node and takes the first side that
 * overlaps neither a placed label nor another node; returns null when every side collides (the label is dropped,
 * it still shows on hover and in the list view). `bounds` keeps labels inside the canvas.
 */
export function placeLabel(
  sides: readonly LabelSide[],
  x: number,
  y: number,
  r: number,
  w: number,
  h: number,
  placed: readonly LabelBox[],
  obstacles: readonly LabelBox[],
  bounds: { width: number; height: number },
  skip = -1,
  segments: readonly Segment[] = [],
  gap = 4,
  leader = false,
  nearestOwn = false,
): LabelBox | null {
  for (const side of sides) {
    const box = labelBox(side, x, y, r, w, h, gap)
    if (box.x < 2 || box.y < 2 || box.x + box.w > bounds.width - 2 || box.y + box.h > bounds.height - 2) continue
    let hit = false
    // On overview graphs a label must be closer to its own node than to any other, so it reads as that node's.
    if (nearestOwn && skip >= 0) {
      const own = obstacles[skip]
      const mine = own ? boxGap(box, own) : 0
      for (let i = 0; !hit && i < obstacles.length; i++) if (i !== skip && boxGap(box, obstacles[i] as LabelBox) <= mine) hit = true
    }
    for (const p of placed) {
      if (overlaps(box, p, LABEL_GAP)) {
        hit = true
        break
      }
    }
    for (let i = 0; !hit && i < obstacles.length; i++) if (i !== skip && overlaps(box, obstacles[i] as LabelBox, 2)) hit = true
    for (let i = 0; !hit && i < segments.length; i++) if (segmentHitsBox(segments[i] as Segment, box)) hit = true
    // A label set further out is joined by a leader line, which must not cross other labels or nodes either.
    if (!hit && leader) {
      const end = nearestPointOnBox(x, y, box)
      const len = Math.hypot(end.x - x, end.y - y) || 1
      const line = { x1: x + ((end.x - x) / len) * (r + 1), y1: y + ((end.y - y) / len) * (r + 1), x2: end.x, y2: end.y }
      for (const p of placed) {
        if (segmentHitsBox(line, p)) {
          hit = true
          break
        }
      }
      for (let i = 0; !hit && i < obstacles.length; i++) if (i !== skip && segmentHitsBox(line, obstacles[i] as LabelBox)) hit = true
    }
    if (!hit) return box
  }
  return null
}

/** The empty space between two boxes (0 when they touch or overlap). */
export function boxGap(a: LabelBox, b: LabelBox): number {
  const dx = Math.max(0, b.x - (a.x + a.w), a.x - (b.x + b.w))
  const dy = Math.max(0, b.y - (a.y + a.h), a.y - (b.y + b.h))
  return Math.hypot(dx, dy)
}

export interface Segment {
  x1: number
  y1: number
  x2: number
  y2: number
}

/** Whether a line segment crosses or touches a box (Liang–Barsky clipping). */
export function segmentHitsBox(s: Segment, b: LabelBox): boolean {
  const dx = s.x2 - s.x1
  const dy = s.y2 - s.y1
  let t0 = 0
  let t1 = 1
  const edges: [number, number][] = [
    [-dx, s.x1 - b.x],
    [dx, b.x + b.w - s.x1],
    [-dy, s.y1 - b.y],
    [dy, b.y + b.h - s.y1],
  ]
  for (const [p, q] of edges) {
    if (p === 0) {
      if (q < 0) return false
      continue
    }
    const t = q / p
    if (p < 0) {
      if (t > t1) return false
      if (t > t0) t0 = t
    } else {
      if (t < t0) return false
      if (t < t1) t1 = t
    }
  }
  return t0 <= t1
}

/** The point on a box closest to (x, y): where a leader line from a node meets its label. */
export function nearestPointOnBox(x: number, y: number, b: LabelBox): { x: number; y: number } {
  return { x: Math.max(b.x, Math.min(x, b.x + b.w)), y: Math.max(b.y, Math.min(y, b.y + b.h)) }
}

/** Places a rectangle (a quote card) at the candidate with the least overlap with the given boxes, inside bounds. */
export function leastOverlap(candidates: readonly { x: number; y: number }[], w: number, h: number, boxes: readonly LabelBox[], bounds: { width: number; height: number }): { x: number; y: number } {
  let best = candidates[0] ?? { x: 8, y: 8 }
  let bestScore = Infinity
  for (const c of candidates) {
    const x = Math.max(8, Math.min(c.x, bounds.width - w - 8))
    const y = Math.max(8, Math.min(c.y, bounds.height - h - 8))
    let score = 0
    for (const b of boxes) {
      const ox = Math.min(x + w, b.x + b.w) - Math.max(x, b.x)
      const oy = Math.min(y + h, b.y + b.h) - Math.max(y, b.y)
      if (ox > 0 && oy > 0) score += ox * oy
    }
    if (score < bestScore) {
      bestScore = score
      best = { x, y }
    }
  }
  return best
}

export interface View {
  x: number
  y: number
  k: number
}

export function toScreen(p: { x: number; y: number }, view: View): { x: number; y: number } {
  return { x: p.x * view.k + view.x, y: p.y * view.k + view.y }
}

export function toWorld(p: { x: number; y: number }, view: View): { x: number; y: number } {
  return { x: (p.x - view.x) / view.k, y: (p.y - view.y) / view.k }
}

/** The topmost node under a screen point. */
export function hitTest(
  point: { x: number; y: number },
  nodes: readonly GraphNode[],
  positions: Positions,
  view: View,
  anchorId: string | null = null,
  radius?: ReadonlyMap<string, number>,
): GraphNode | null {
  const world = toWorld(point, view)
  for (let i = nodes.length - 1; i >= 0; i--) {
    const node = nodes[i] as GraphNode
    const p = positions[node.id]
    if (!p) continue
    const r = (node.id === anchorId ? ANCHOR_RADIUS : (radius?.get(node.id) ?? radiusOf(node))) + 4 / view.k
    if ((world.x - p.x) ** 2 + (world.y - p.y) ** 2 <= r * r) return node
  }
  return null
}

/** Fit all positions into the viewport with padding. */
export function fitView(positions: Positions, width: number, height: number, padding = 64, labelRoom = 56): View {
  const pts = Object.values(positions)
  if (pts.length === 0 || width <= 0 || height <= 0) return { x: 0, y: 0, k: 1 }
  const xs = pts.map((p) => p.x)
  const ys = pts.map((p) => p.y)
  const minX = Math.min(...xs)
  const maxX = Math.max(...xs)
  const minY = Math.min(...ys)
  const maxY = Math.max(...ys)
  const w = Math.max(1, maxX - minX)
  const h = Math.max(1, maxY - minY)
  // Labels prefer the right side of nodes, so the right edge keeps some extra room for them.
  const usable = Math.max(1, width - padding * 2 - labelRoom)
  const k = Math.max(0.2, Math.min(2.5, Math.min(usable / w, (height - padding * 2) / h)))
  return { k, x: padding + (usable - w * k) / 2 - minX * k, y: height / 2 - ((minY + maxY) / 2) * k }
}

export type Direction = 'left' | 'right' | 'up' | 'down'

/** Arrow keys move focus along links to the neighbour that lies most in that direction (spec C, C7). */
export function neighbourInDirection(
  fromId: string,
  direction: Direction,
  links: readonly GraphLink[],
  positions: Positions,
): string | null {
  const origin = positions[fromId]
  if (!origin) return null
  const neighbours = new Set<string>()
  for (const l of links) {
    if (l.from === fromId) neighbours.add(l.to)
    if (l.to === fromId) neighbours.add(l.from)
  }
  const want = { left: [-1, 0], right: [1, 0], up: [0, -1], down: [0, 1] }[direction] as [number, number]
  let best: string | null = null
  let bestScore = -Infinity
  for (const id of neighbours) {
    const p = positions[id]
    if (!p) continue
    const dx = p.x - origin.x
    const dy = p.y - origin.y
    const len = Math.hypot(dx, dy) || 1
    const cos = (dx * want[0] + dy * want[1]) / len
    if (cos <= 0.2) continue
    const score = cos * 2 - len / 400
    if (score > bestScore) {
      bestScore = score
      best = id
    }
  }
  return best
}

/** Links incident to any id in the set. */
export function linksTouching(links: readonly GraphLink[], ids: ReadonlySet<string>): GraphLink[] {
  return links.filter((l) => ids.has(l.from) || ids.has(l.to))
}
