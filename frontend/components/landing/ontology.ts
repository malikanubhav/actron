/** Summaries of the ontology snapshot for the landing page (real data from ../ontology/*.json). */
import snapshot from '@/lib/ontology-snapshot.json'
import type { GraphStats, NodeGroup } from '@/lib/api/types'

export interface SnapshotLike {
  types: { type: string; group: string; description?: string }[]
  relationships: { name: string; from: string; to: string; group?: string }[]
}

export const ONTOLOGY = snapshot as unknown as SnapshotLike

export const SOURCE_ORDER: NodeGroup[] = ['code', 'github', 'slack', 'linear', 'core']

export const SOURCE_NAME: Record<NodeGroup, string> = {
  code: 'Code',
  github: 'GitHub',
  slack: 'Slack',
  linear: 'Linear',
  core: 'Core',
}

export const SOURCE_LINE: Record<NodeGroup, string> = {
  code: 'Repositories, files, classes, functions, calls, tests and docs, parsed with tree-sitter.',
  github: 'Pull requests, reviews, issues, comments and commits, with who wrote what.',
  slack: 'Channels, threads and messages where decisions were actually made.',
  linear: 'Issues, comments, projects and cycles, including earlier versions.',
  core: 'People across tools, decisions, features, procedures, and every Actron request.',
}

export interface SourceSummary {
  group: NodeGroup
  typeCount: number
  examples: string[]
  /** Nodes of this source in the live workspace, when the API answered. */
  nodeCount: number | null
}

const asGroup = (g: string): NodeGroup => (SOURCE_ORDER as string[]).includes(g) ? (g as NodeGroup) : 'core'

/** Types per source from the snapshot, plus node counts per source from GET /api/graph/stats when available. */
export function summariseOntology(snap: SnapshotLike = ONTOLOGY, stats: GraphStats | null = null): SourceSummary[] {
  return SOURCE_ORDER.map((group) => {
    const types = snap.types.filter((t) => asGroup(t.group) === group)
    const nodeCount = stats ? stats.byType.filter((b) => b.group === group).reduce((sum, b) => sum + b.count, 0) : null
    return { group, typeCount: types.length, examples: types.slice(0, 6).map((t) => t.type), nodeCount }
  })
}

export function ontologyTotals(snap: SnapshotLike = ONTOLOGY): { types: number; relationships: number } {
  return { types: snap.types.length, relationships: snap.relationships.length }
}

/** "Ontology: 96 node types, 507 relationships" */
export function ontologyLabel(snap: SnapshotLike = ONTOLOGY): string {
  const t = ontologyTotals(snap)
  return `Ontology: ${t.types} node types, ${t.relationships} relationships`
}

export const CYPHER_EXAMPLES: { title: string; explanation: string; query: string }[] = [
  {
    title: 'Who calls this function, three hops back',
    explanation:
      'Impact before a change. FalkorDB walks CALLS links backwards to depth three, so Actron knows every caller a change can reach.',
    query: `MATCH (caller:CodeFunction)-[:CALLS*1..3]->(f:CodeFunction {id: $function})
RETURN DISTINCT caller.qualifiedName`,
  },
  {
    title: 'Which decisions constrain it, and where they were made',
    explanation:
      'The earlier decisions that bind this code, each with the Slack message, review or ticket it came from, so every finding carries its quote.',
    query: `MATCH (d:Decision)-[:CONSTRAINS]->(f:CodeFunction {id: $function})
WHERE d.status IN ['approved', 'proposed']
OPTIONAL MATCH (d)-[:EXTRACTED_FROM]->(src)
RETURN d.statement, labels(src)[0] AS source, src.url`,
  },
  {
    title: 'How a request connects to the code',
    explanation:
      'The evidence path you see on the canvas: the shortest route from the request to the function, in either direction, at most six hops.',
    query: `MATCH (r:Request {id: $request}), (f:CodeFunction {id: $function})
CALL algo.SPpaths({sourceNode: r, targetNode: f, relDirection: 'both', maxLen: 6})
YIELD path
RETURN path`,
  },
]
