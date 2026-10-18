// FIXTURE: recorded-style test data for development and tests only; never used in production builds.
// Per-request subgraphs (aggregated and expanded), node details, neighbours, search and paths over the catalog.
import type { EventEnvelope, GraphLink, GraphNode, NodeDetail, SearchResult, Subgraph } from '@/lib/api/types'
import { CATALOG, CATALOG_LINKS, ensureNode, LINEAR_URL } from './graph-catalog'
import { reqNode } from './requests'
import type { RequestSpec } from './spec'

const linkKey = (a: string, b: string) => (a < b ? `${a}|${b}` : `${b}|${a}`)

const catalogPairs = new Set(CATALOG_LINKS.map((l) => linkKey(l.from, l.to)))

function strings(v: unknown): string[] {
  return Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : []
}

/** Nodes and links a request has touched so far, from its events. */
function touched(spec: RequestSpec, events: readonly EventEnvelope[]) {
  const anchor = ensureNode(reqNode(spec.id), 'Request', spec.title, 'core', { title: spec.title, kind: spec.kind, requestId: spec.id })
  const onPath = new Set<string>([anchor])
  const other = new Set<string>()
  const extraLinks: GraphLink[] = []
  for (const e of events) {
    const p = e.payload
    if (e.type === 'evidence.found') {
      const path = strings(p.path)
      path.forEach((id) => onPath.add(id))
      for (let i = 0; i < path.length - 1; i++) {
        const a = path[i] as string
        const b = path[i + 1] as string
        if (!catalogPairs.has(linkKey(a, b))) {
          extraLinks.push({ from: a, to: b, type: i === 0 ? 'SEEDED' : 'RELATES_TO', method: 'jev', confidence: i === 0 ? 0.91 : 0.7 })
        }
      }
    }
    if (e.type === 'tool.result') strings(p.nodeIds).forEach((id) => other.add(id))
    if (e.type === 'ticket.synced') {
      const id = ensureNode(`linear:issue:${String(p.identifier)}`, 'LinearIssue', `${String(p.identifier)} ${spec.title}`, 'linear', {
        identifier: p.identifier,
        url: p.url ?? LINEAR_URL(String(p.identifier)),
      })
      onPath.add(id)
      extraLinks.push({ from: anchor, to: id, type: 'TRACKED_IN', method: 'api', confidence: 1 })
    }
    if (e.type === 'pr.opened' && spec.pr) {
      const id = ensureNode(`github:pr:BetterThanTomorrow/calva#${spec.pr.number}`, 'GithubPullRequest', `PR #${spec.pr.number} ${spec.pr.title}`, 'github', {
        number: spec.pr.number,
        url: spec.pr.url,
        state: 'open',
      })
      onPath.add(id)
      extraLinks.push({ from: anchor, to: id, type: 'DELIVERED_BY', method: 'api', confidence: 1 })
    }
  }
  for (const id of onPath) other.delete(id)
  // A request with no evidence yet still links to what its first tool found.
  if (onPath.size === 1) for (const id of other) extraLinks.push({ from: anchor, to: id, type: 'SEEDED', method: 'jev', confidence: 0.8 })
  return { anchor, onPath, other, extraLinks }
}

function nodeOf(id: string): GraphNode | null {
  const n = CATALOG.get(id)
  return n ? { id: n.id, type: n.type, label: n.label, group: n.group } : null
}

export function subgraphFor(spec: RequestSpec, events: readonly EventEnvelope[], mode: 'aggregated' | 'expanded'): Subgraph {
  const { onPath, other, extraLinks } = touched(spec, events)
  const all = new Set([...onPath, ...other])
  const links = [...CATALOG_LINKS.filter((l) => all.has(l.from) && all.has(l.to)), ...extraLinks.filter((l) => all.has(l.from) && all.has(l.to))]
  if (mode === 'expanded') {
    return { mode, nodes: [...all].map(nodeOf).filter((n): n is GraphNode => n !== null), links, truncated: false }
  }
  const groupId = new Map<string, string>()
  const groups = new Map<string, GraphNode>()
  for (const id of other) {
    const n = nodeOf(id)
    if (!n) continue
    const gid = `agg:${spec.id}:${n.type}`
    groupId.set(id, gid)
    const g = groups.get(gid)
    if (g) g.count = (g.count ?? 1) + 1
    else groups.set(gid, { id: gid, type: n.type, label: n.type, group: n.group, count: 1 })
  }
  for (const g of groups.values()) g.label = `${g.count} ${g.type}${(g.count ?? 1) === 1 ? '' : ' nodes'}`
  const merged = new Map<string, GraphLink>()
  for (const l of links) {
    const from = groupId.get(l.from) ?? l.from
    const to = groupId.get(l.to) ?? l.to
    if (from === to) continue
    const key = `${from}|${to}|${l.type}`
    const existing = merged.get(key)
    if (existing) existing.count = (existing.count ?? 1) + 1
    else merged.set(key, { ...l, from, to, count: 1 })
  }
  const nodes = [...[...onPath].map(nodeOf).filter((n): n is GraphNode => n !== null), ...groups.values()]
  return { mode, nodes, links: [...merged.values()], truncated: false }
}

export function nodeDetail(id: string): NodeDetail | null {
  const n = CATALOG.get(id)
  if (!n) return null
  const url = typeof n.props.url === 'string' ? n.props.url : null
  return {
    node: { id: n.id, type: n.type, label: n.label, group: n.group, props: n.props },
    sources: url ? [{ type: n.group === 'code' ? 'code' : n.group, url }] : [],
    incoming: CATALOG_LINKS.filter((l) => l.to === id),
    outgoing: CATALOG_LINKS.filter((l) => l.from === id),
  }
}

export function neighbours(id: string, types: string | undefined, limit: number): Subgraph | null {
  if (!CATALOG.has(id)) return null
  const wanted = types ? new Set(types.split(',').filter(Boolean)) : null
  const links = CATALOG_LINKS.filter((l) => l.from === id || l.to === id)
  const ids = new Set<string>([id])
  for (const l of links) {
    const other = l.from === id ? l.to : l.from
    const n = CATALOG.get(other)
    if (!n || (wanted && !wanted.has(n.type))) continue
    if (ids.size > limit) break
    ids.add(other)
  }
  return {
    mode: 'expanded',
    nodes: [...ids].map(nodeOf).filter((n): n is GraphNode => n !== null),
    links: CATALOG_LINKS.filter((l) => ids.has(l.from) && ids.has(l.to)),
    truncated: links.length + 1 > ids.size,
  }
}

export function search(q: string, types: string | undefined, limit: number): SearchResult[] {
  const terms = q.toLowerCase().split(/\s+/).filter(Boolean)
  if (terms.length === 0) return []
  const wanted = types ? new Set(types.split(',').filter(Boolean)) : null
  const out: SearchResult[] = []
  for (const n of CATALOG.values()) {
    if (wanted && !wanted.has(n.type)) continue
    const text = [n.label, n.id, ...Object.values(n.props).filter((v): v is string => typeof v === 'string')].join(' ').toLowerCase()
    const hits = terms.filter((t) => text.includes(t)).length
    if (hits === 0) continue
    const snippetSource = String(n.props.text ?? n.props.body ?? n.props.quote ?? n.props.statement ?? n.props.path ?? n.label)
    out.push({
      id: n.id,
      type: n.type,
      label: n.label,
      snippet: snippetSource.length > 160 ? `${snippetSource.slice(0, 159)}…` : snippetSource,
      score: Math.round((hits / terms.length) * (n.label.toLowerCase().includes(terms[0] as string) ? 1 : 0.8) * 100) / 100,
    })
  }
  return out.sort((a, b) => b.score - a.score || a.label.localeCompare(b.label)).slice(0, limit)
}

export function shortestPath(from: string, to: string, maxHops: number): { found: boolean; nodes: GraphNode[]; links: GraphLink[] } {
  if (!CATALOG.has(from) || !CATALOG.has(to)) return { found: false, nodes: [], links: [] }
  const prev = new Map<string, { via: string; link: GraphLink }>()
  const depth = new Map<string, number>([[from, 0]])
  const queue = [from]
  while (queue.length) {
    const id = queue.shift() as string
    if (id === to) break
    const d = depth.get(id) as number
    if (d >= maxHops) continue
    for (const l of CATALOG_LINKS) {
      const next = l.from === id ? l.to : l.to === id ? l.from : null
      if (!next || depth.has(next)) continue
      depth.set(next, d + 1)
      prev.set(next, { via: id, link: l })
      queue.push(next)
    }
  }
  if (!depth.has(to)) return { found: false, nodes: [], links: [] }
  const ids = [to]
  const links: GraphLink[] = []
  let cur = to
  while (cur !== from) {
    const p = prev.get(cur)
    if (!p) break
    links.unshift(p.link)
    cur = p.via
    ids.unshift(cur)
  }
  return { found: true, nodes: ids.map(nodeOf).filter((n): n is GraphNode => n !== null), links }
}
