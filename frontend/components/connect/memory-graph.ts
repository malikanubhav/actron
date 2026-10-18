import { plainTypeName } from '../graph/model'
/**
 * The Connect canvas: one node per node type that has data (count from GET /api/graph/stats), linked by the
 * type-level relationships of the frozen ontology (lib/ontology-snapshot.json). Nothing is invented: with no
 * data there are no nodes.
 */
import type { GraphLink, GraphNode, GraphStats, NodeGroup, Subgraph } from '@/lib/api/types'
import snapshot from '@/lib/ontology-snapshot.json'

interface Snapshot {
  types: { type: string; group: string }[]
  relationships: { name: string; from: string; to: string }[]
}

const GROUPS: NodeGroup[] = ['code', 'github', 'slack', 'linear', 'core']

export function memoryGraph(stats: Pick<GraphStats, 'byType'> | null | undefined, onto: Snapshot = snapshot as Snapshot): Subgraph {
  const present = (stats?.byType ?? []).filter((t) => t.count > 0)
  const nodes: GraphNode[] = present.map((t) => ({
    id: `type:${t.type}`,
    type: t.type,
    label: plainTypeName(t.type, t.count),
    group: GROUPS.includes(t.group) ? t.group : 'core',
    count: t.count,
  }))
  const ids = new Set(nodes.map((n) => n.id))
  const seen = new Set<string>()
  const links: GraphLink[] = []
  for (const rel of onto.relationships) {
    const from = `type:${rel.from}`
    const to = `type:${rel.to}`
    if (from === to || !ids.has(from) || !ids.has(to)) continue
    const key = from < to ? `${from}|${to}` : `${to}|${from}`
    if (seen.has(key)) continue
    seen.add(key)
    links.push({ from, to, type: rel.name, method: null, confidence: null })
  }
  // Types with no relationship to any other present type float alone and read as noise on the canvas; their counts
  // stay in the per-source strip below it.
  const linked = new Set(links.flatMap((l) => [l.from, l.to]))
  const shown = nodes.length > 1 ? nodes.filter((n) => linked.has(n.id)) : nodes
  return { mode: 'aggregated', nodes: shown, links, truncated: false }
}

export function countsByGroup(stats: Pick<GraphStats, 'byType'> | null | undefined): Record<NodeGroup, number> {
  const out: Record<NodeGroup, number> = { code: 0, github: 0, slack: 0, linear: 0, core: 0 }
  for (const t of stats?.byType ?? []) out[GROUPS.includes(t.group) ? t.group : 'core'] += t.count
  return out
}
