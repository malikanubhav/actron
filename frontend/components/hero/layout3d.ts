/**
 * Deterministic 3D layout for the landing hero (spec C, C6). Runs in a web worker in the browser and directly in
 * the brand-asset script and the Open Graph image, so the fallback image is the same scene.
 * Nodes start on shells around a centre per source, then relax with link springs, (sampled) repulsion and a pull
 * toward their source centre.
 */

export type HeroGroup = 'code' | 'github' | 'slack' | 'linear' | 'core'

export interface HeroNode {
  id: string
  group: HeroGroup
  label?: string
  type?: string
}

export interface HeroLink {
  from: string
  to: string
}

export interface HeroGraph {
  nodes: HeroNode[]
  links: HeroLink[]
  /** Node ids of the evidence path, in order. */
  path: string[]
  /** Where the data came from, for the accessible label. */
  source: 'sample' | 'ontology'
}

export const GROUPS: HeroGroup[] = ['core', 'code', 'github', 'slack', 'linear']

const CENTRES: Record<HeroGroup, [number, number, number]> = {
  core: [0, 0, 0],
  code: [7, -1.5, 2],
  github: [-6, 2, 3.5],
  slack: [-3, -5, -5],
  linear: [3.5, 5.5, -4.5],
}

export function hashSeed(text: string): number {
  let h = 2166136261
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return h >>> 0
}

export function mulberry32(seed: number): () => number {
  let a = seed >>> 0
  return () => {
    a = (a + 0x6d2b79f5) >>> 0
    let t = a
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

export function asGroup(value: string): HeroGroup {
  return (GROUPS as string[]).includes(value) ? (value as HeroGroup) : 'core'
}

/** Positions as a flat [x, y, z, x, y, z, …] array in node order, scaled to fit a radius of about 10. */
export function layout3d(nodes: HeroNode[], links: HeroLink[], iterations = 160): Float32Array {
  const n = nodes.length
  const pos = new Float32Array(n * 3)
  if (n === 0) return pos
  const rand = mulberry32(hashSeed(`${n}:${links.length}:${nodes[0]?.id ?? ''}`))
  const index = new Map(nodes.map((node, i) => [node.id, i]))
  const spread = Math.max(1.6, Math.cbrt(n) * 0.55)
  for (let i = 0; i < n; i++) {
    const c = CENTRES[nodes[i]?.group ?? 'core']
    const u = rand() * 2 - 1
    const theta = rand() * Math.PI * 2
    const r = spread * Math.cbrt(rand())
    const s = Math.sqrt(1 - u * u)
    pos[i * 3] = c[0] + r * s * Math.cos(theta)
    pos[i * 3 + 1] = c[1] + r * s * Math.sin(theta)
    pos[i * 3 + 2] = c[2] + r * u
  }
  const edges: [number, number][] = []
  for (const l of links) {
    const a = index.get(l.from)
    const b = index.get(l.to)
    if (a !== undefined && b !== undefined && a !== b) edges.push([a, b])
  }
  const disp = new Float32Array(n * 3)
  const exact = n <= 500
  const samples = 24
  const rest = 1.4
  for (let it = 0; it < iterations; it++) {
    const cool = 1 - it / iterations
    disp.fill(0)
    // Repulsion.
    for (let i = 0; i < n; i++) {
      const count = exact ? n : samples
      for (let k = 0; k < count; k++) {
        const j = exact ? k : Math.floor(rand() * n)
        if (j === i) continue
        const dx = pos[i * 3]! - pos[j * 3]!
        const dy = pos[i * 3 + 1]! - pos[j * 3 + 1]!
        const dz = pos[i * 3 + 2]! - pos[j * 3 + 2]!
        const d2 = dx * dx + dy * dy + dz * dz + 0.01
        const f = (exact ? 0.35 : 0.35 * (n / samples)) / (d2 * Math.sqrt(d2))
        disp[i * 3] = disp[i * 3]! + dx * f
        disp[i * 3 + 1] = disp[i * 3 + 1]! + dy * f
        disp[i * 3 + 2] = disp[i * 3 + 2]! + dz * f
      }
    }
    // Springs.
    for (const [a, b] of edges) {
      const dx = pos[b * 3]! - pos[a * 3]!
      const dy = pos[b * 3 + 1]! - pos[a * 3 + 1]!
      const dz = pos[b * 3 + 2]! - pos[a * 3 + 2]!
      const d = Math.sqrt(dx * dx + dy * dy + dz * dz) + 1e-6
      const f = ((d - rest) / d) * 0.05
      disp[a * 3] = disp[a * 3]! + dx * f
      disp[a * 3 + 1] = disp[a * 3 + 1]! + dy * f
      disp[a * 3 + 2] = disp[a * 3 + 2]! + dz * f
      disp[b * 3] = disp[b * 3]! - dx * f
      disp[b * 3 + 1] = disp[b * 3 + 1]! - dy * f
      disp[b * 3 + 2] = disp[b * 3 + 2]! - dz * f
    }
    // Pull toward the source centre, then move with a capped step.
    for (let i = 0; i < n; i++) {
      const c = CENTRES[nodes[i]?.group ?? 'core']
      for (let d = 0; d < 3; d++) {
        const k = i * 3 + d
        let v = disp[k]! + (c[d]! - pos[k]!) * 0.05
        const cap = 0.6 * cool + 0.02
        if (v > cap) v = cap
        if (v < -cap) v = -cap
        pos[k] = pos[k]! + v
      }
    }
  }
  // Normalise so the 92nd-percentile distance from the centre is 9, and pull stragglers in to 11.
  const radii: number[] = []
  for (let i = 0; i < n; i++) radii.push(Math.hypot(pos[i * 3]!, pos[i * 3 + 1]!, pos[i * 3 + 2]!))
  const sorted = [...radii].sort((a, b) => a - b)
  const ref = sorted[Math.min(n - 1, Math.floor(n * 0.92))] || 1
  const scale = 9 / ref
  for (let i = 0; i < n; i++) {
    const r = radii[i]! * scale
    const shrink = r > 11 ? 11 / r : 1
    for (let d = 0; d < 3; d++) pos[i * 3 + d] = pos[i * 3 + d]! * scale * shrink
  }
  return pos
}

/**
 * An evidence path through the graph: from the request (or the best-connected core node) to a code function,
 * at most six hops, found by breadth-first search.
 */
export function pickEvidencePath(nodes: HeroNode[], links: HeroLink[]): string[] {
  if (nodes.length === 0) return []
  const adjacency = new Map<string, string[]>()
  for (const node of nodes) adjacency.set(node.id, [])
  for (const l of links) {
    adjacency.get(l.from)?.push(l.to)
    adjacency.get(l.to)?.push(l.from)
  }
  const name = (node: HeroNode) => `${node.type ?? ''} ${node.id}`.toLowerCase()
  const start =
    nodes.find((node) => /(^|\W)request(\W|$)/.test(name(node)) && !name(node).includes('pull')) ??
    [...nodes].filter((node) => node.group === 'core').sort((a, b) => (adjacency.get(b.id)?.length ?? 0) - (adjacency.get(a.id)?.length ?? 0))[0] ??
    nodes[0]
  if (!start) return []
  const prev = new Map<string, string | null>([[start.id, null]])
  const depth = new Map<string, number>([[start.id, 0]])
  const queue = [start.id]
  while (queue.length) {
    const id = queue.shift() as string
    const d = depth.get(id) as number
    if (d >= 6) continue
    for (const next of adjacency.get(id) ?? []) {
      if (prev.has(next)) continue
      prev.set(next, id)
      depth.set(next, d + 1)
      queue.push(next)
    }
  }
  const byId = new Map(nodes.map((node) => [node.id, node]))
  // Prefer the story route: request → decision → pull request → file → function.
  const waypoints = [/decision/, /pullrequest/, /codefile|(^|\W)file(\W|$)/, /function/]
  const routed: string[] = [start.id]
  let from = start.id
  for (const pattern of waypoints) {
    const used = new Set(routed)
    const candidates = nodes.filter((node) => pattern.test(name(node)) && !used.has(node.id))
    const leg = shortestLeg(adjacency, from, new Set(candidates.map((c) => c.id)), used)
    if (!leg) continue
    routed.push(...leg)
    from = routed[routed.length - 1] as string
  }
  if (routed.length >= 4 && /function/.test(name(byId.get(from) as HeroNode))) return routed
  const reached = [...depth.keys()]
  const target =
    reached.filter((id) => /function/.test(name(byId.get(id) as HeroNode))).sort((a, b) => (depth.get(b) ?? 0) - (depth.get(a) ?? 0))[0] ??
    reached.sort((a, b) => (depth.get(b) ?? 0) - (depth.get(a) ?? 0))[0]
  if (!target || target === start.id) return [start.id]
  const path: string[] = []
  let cur: string | null | undefined = target
  while (cur) {
    path.unshift(cur)
    cur = prev.get(cur)
  }
  return path
}

/** Shortest path (excluding `from`) to any target, avoiding used nodes; at most 3 hops. */
function shortestLeg(adjacency: Map<string, string[]>, from: string, targets: Set<string>, used: Set<string>): string[] | null {
  if (targets.size === 0) return null
  const prev = new Map<string, string | null>([[from, null]])
  const queue: [string, number][] = [[from, 0]]
  while (queue.length) {
    const [id, d] = queue.shift() as [string, number]
    if (id !== from && targets.has(id)) {
      const leg: string[] = []
      let cur: string | null | undefined = id
      while (cur && cur !== from) {
        leg.unshift(cur)
        cur = prev.get(cur)
      }
      return leg
    }
    if (d >= 3) continue
    for (const next of adjacency.get(id) ?? []) {
      if (prev.has(next) || used.has(next)) continue
      prev.set(next, id)
      queue.push([next, d + 1])
    }
  }
  return null
}

export interface OntologySnapshotLike {
  types: { type: string; group: string }[]
  relationships: { from: string; to: string }[]
}

/** The ontology's type graph as a hero graph (real data available without a backend). */
export function graphFromOntology(snapshot: OntologySnapshotLike): HeroGraph {
  const nodes: HeroNode[] = snapshot.types.map((t) => ({ id: t.type, type: t.type, label: t.type, group: asGroup(t.group) }))
  const seen = new Set<string>()
  const links: HeroLink[] = []
  for (const r of snapshot.relationships) {
    if (r.from === r.to) continue
    const key = r.from < r.to ? `${r.from}|${r.to}` : `${r.to}|${r.from}`
    if (seen.has(key)) continue
    seen.add(key)
    links.push({ from: r.from, to: r.to })
  }
  return { nodes, links, path: pickEvidencePath(nodes, links), source: 'ontology' }
}

/** Fixed-angle orthographic projection for static renderings (fallback image, Open Graph). */
export function project(
  positions: Float32Array,
  width: number,
  height: number,
  angle = 0.6,
  tilt = 0.35,
  padding = 24,
): { x: number; y: number; z: number }[] {
  const out: { x: number; y: number; z: number }[] = []
  const ca = Math.cos(angle)
  const sa = Math.sin(angle)
  const ct = Math.cos(tilt)
  const st = Math.sin(tilt)
  for (let i = 0; i < positions.length / 3; i++) {
    const x = positions[i * 3]!
    const y = positions[i * 3 + 1]!
    const z = positions[i * 3 + 2]!
    const x1 = x * ca + z * sa
    const z1 = -x * sa + z * ca
    const y1 = y * ct - z1 * st
    const z2 = y * st + z1 * ct
    out.push({ x: x1, y: y1, z: z2 })
  }
  const xs = out.map((p) => p.x)
  const ys = out.map((p) => p.y)
  const minX = Math.min(...xs)
  const maxX = Math.max(...xs)
  const minY = Math.min(...ys)
  const maxY = Math.max(...ys)
  const k = Math.min((width - padding * 2) / Math.max(1e-6, maxX - minX), (height - padding * 2) / Math.max(1e-6, maxY - minY))
  return out.map((p) => ({
    x: padding + (p.x - minX) * k + (width - padding * 2 - (maxX - minX) * k) / 2,
    y: padding + (maxY - p.y) * k + (height - padding * 2 - (maxY - minY) * k) / 2,
    z: p.z,
  }))
}
