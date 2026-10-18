import type { GraphLink, GraphNode, Subgraph } from './api/types'

/** Merge two subgraphs by node id and link (from, to, type), keeping the first copy. */
export function mergeSubgraphs(a: Subgraph | null, b: Subgraph): Subgraph {
  if (!a) return b
  const nodes = new Map<string, GraphNode>(a.nodes.map((n) => [n.id, n]))
  for (const n of b.nodes) if (!nodes.has(n.id)) nodes.set(n.id, n)
  const key = (l: GraphLink) => `${l.from}|${l.to}|${l.type}`
  const links = new Map<string, GraphLink>(a.links.map((l) => [key(l), l]))
  for (const l of b.links) if (!links.has(key(l))) links.set(key(l), l)
  return { mode: 'expanded', nodes: [...nodes.values()], links: [...links.values()], truncated: a.truncated || b.truncated }
}

export function filterSubgraph(g: Subgraph | null, types: ReadonlySet<string>, groups: ReadonlySet<string>): Subgraph | null {
  if (!g) return g
  if (types.size === 0 && groups.size === 0) return g
  const nodes = g.nodes.filter((n) => (types.size === 0 || types.has(n.type)) && (groups.size === 0 || groups.has(n.group)))
  const ids = new Set(nodes.map((n) => n.id))
  return { ...g, nodes, links: g.links.filter((l) => ids.has(l.from) && ids.has(l.to)) }
}

/** Links grouped by relationship type, for the inspector. */
export function groupLinks(links: readonly GraphLink[]): [string, GraphLink[]][] {
  const out = new Map<string, GraphLink[]>()
  for (const l of links) {
    const list = out.get(l.type) ?? []
    list.push(l)
    out.set(l.type, list)
  }
  return [...out.entries()].sort((x, y) => y[1].length - x[1].length)
}
