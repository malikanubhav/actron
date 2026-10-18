/**
 * Graph layout with d3-force (runs in a web worker; also callable directly in tests and as a fallback).
 * The request (anchor) sits at the left edge and hops unfold to the right: each node's x is pulled toward its
 * BFS distance from the anchor, so the agent's path reads left to right (PROMPT 8.8 D).
 */
import { forceCollide, forceLink, forceManyBody, forceSimulation, forceX, forceY, type SimulationNodeDatum } from 'd3-force'

export interface LayoutInputNode {
  id: string
  group: string
  count?: number
}

export interface LayoutInputLink {
  from: string
  to: string
}

export interface LayoutRequest {
  nodes: LayoutInputNode[]
  links: LayoutInputLink[]
  width: number
  height: number
  anchorId?: string | null
  /** Positions from the previous layout so existing nodes stay put when new ones arrive. */
  previous?: Record<string, { x: number; y: number }>
  ticks?: number
}

export type Positions = Record<string, { x: number; y: number }>

interface SimNode extends SimulationNodeDatum {
  id: string
  depth: number
  r: number
}

export function nodeRadius(count?: number): number {
  if (!count || count <= 1) return 7
  return Math.min(22, 8 + Math.sqrt(count) * 2.2)
}

/** Hop distance from the anchor over undirected links; unreachable nodes get the max depth + 1. */
export function depths(nodes: LayoutInputNode[], links: LayoutInputLink[], anchorId?: string | null): Map<string, number> {
  const adjacency = new Map<string, string[]>()
  for (const n of nodes) adjacency.set(n.id, [])
  for (const l of links) {
    adjacency.get(l.from)?.push(l.to)
    adjacency.get(l.to)?.push(l.from)
  }
  const out = new Map<string, number>()
  const start = anchorId && adjacency.has(anchorId) ? anchorId : null
  if (start) {
    out.set(start, 0)
    const queue = [start]
    while (queue.length) {
      const id = queue.shift() as string
      const d = out.get(id) as number
      for (const next of adjacency.get(id) ?? []) {
        if (!out.has(next)) {
          out.set(next, d + 1)
          queue.push(next)
        }
      }
    }
  }
  const max = Math.max(0, ...out.values())
  for (const n of nodes) if (!out.has(n.id)) out.set(n.id, start ? max + 1 : 1)
  return out
}

export function computeLayout(req: LayoutRequest): Positions {
  const { nodes, links, width, height, anchorId, previous = {}, ticks = 220 } = req
  if (nodes.length === 0) return {}
  const depthMap = depths(nodes, links, anchorId)
  const hasAnchor = Boolean(anchorId && nodes.some((n) => n.id === anchorId))
  if (!hasAnchor && nodes.length <= 40) return overviewLayout(req)
  const maxDepth = Math.max(1, ...depthMap.values())
  const margin = 56
  const columnX = (d: number) => margin + (d / maxDepth) * Math.max(1, width - margin * 2)
  if (nodes.length <= 40) return smallPathLayout(req, depthMap, maxDepth, margin)

  const simNodes: SimNode[] = nodes.map((n, i) => {
    const prev = previous[n.id]
    const depth = depthMap.get(n.id) ?? 1
    const angle = (i / nodes.length) * Math.PI * 2
    return {
      id: n.id,
      depth,
      // The anchor keeps a wider berth so its two-line label has room underneath.
      r: n.id === anchorId && nodes.length <= 80 ? 36 : nodeRadius(n.count),
      x: prev?.x ?? (hasAnchor ? columnX(depth) + Math.cos(angle) * 12 : width / 2 + Math.cos(angle) * Math.min(width / 3, 40 + nodes.length * 3)),
      y: prev?.y ?? height / 2 + Math.sin(angle) * Math.min(height / 3, 40 + nodes.length),
      ...(n.id === anchorId ? { fx: margin, fy: height / 2 } : {}),
    }
  })
  const index = new Map(simNodes.map((n) => [n.id, n]))
  const simLinks = links
    .filter((l) => index.has(l.from) && index.has(l.to) && l.from !== l.to)
    .map((l) => ({ source: l.from, target: l.to }))

  const settledShare = Object.keys(previous).length / nodes.length
  // Small graphs (an aggregated request, a type overview) can afford room for every label.
  const small = nodes.length <= 30
  const sim = forceSimulation(simNodes)
    .force(
      'link',
      forceLink<SimNode, { source: string; target: string }>(simLinks)
        .id((d) => d.id)
        .distance(84)
        .strength(0.4),
    )
    // Small overview graphs (no anchor) spread wider so every node's label fits beside it.
    .force('charge', forceManyBody<SimNode>().strength(!hasAnchor && nodes.length <= 40 ? -480 : -220).distanceMax(hasAnchor ? 360 : 520))
    // With an anchor, hops unfold left to right and alternate slightly up and down so a chain reads as a path,
    // not a line of overlapping labels. Without one (memory overview), nodes settle around the centre.
    .force('x', hasAnchor ? forceX<SimNode>((d) => columnX(d.depth)).strength(0.55) : forceX<SimNode>(width / 2).strength(0.07))
    .force(
      'y',
      hasAnchor
        ? forceY<SimNode>((d) => (d.depth === 0 ? height / 2 : height / 2 + (d.depth % 2 ? -1 : 1) * Math.min(70, height / 6))).strength(small ? 0.05 : 0.12)
        : forceY<SimNode>(height / 2).strength(0.1),
    )
    // Small graphs get generous spacing so each node's label fits beside it; large ones must still fit the canvas.
    // Radius × 1.4 leaves room for the wide pill shape used for tests.
    // Overview graphs (no anchor) leave room for a label of about a hundred pixels beside every node.
    .force('collide', forceCollide<SimNode>((d) => d.r * 1.4 + (nodes.length > 80 ? 6 : small ? (hasAnchor ? 24 : 46) : 18)))
    .alpha(settledShare > 0.5 ? 0.35 : 1)
    .stop()

  for (let i = 0; i < ticks; i++) sim.tick()

  const out: Positions = {}
  for (const n of simNodes) {
    out[n.id] = {
      x: Math.max(margin / 2, Math.min(width - margin / 2, n.x ?? 0)),
      y: Math.max(margin / 2, Math.min(height - margin / 2, n.y ?? 0)),
    }
  }
  return out
}

/**
 * Small request graphs (an aggregated request, about 16 nodes): the same left-to-right hops as the large layout, but
 * simulated in a space squeezed horizontally by LABEL_ASPECT (as in overviewLayout) so each node keeps a label's
 * width of room beside it instead of lining up in a tight row. Positions are not clamped (nodes would pile up along
 * the edge); the canvas fits the result to the view.
 */
function smallPathLayout(req: LayoutRequest, depthMap: Map<string, number>, maxDepth: number, margin: number): Positions {
  const { nodes, links, width, height, anchorId, previous = {}, ticks = 220 } = req
  const s = LABEL_ASPECT
  const columnX = (d: number) => (margin + (d / maxDepth) * Math.max(1, width - margin * 2)) / s
  const simNodes: SimNode[] = nodes.map((n, i) => {
    const prev = previous[n.id]
    const depth = depthMap.get(n.id) ?? 1
    const angle = (i / nodes.length) * Math.PI * 2
    return {
      id: n.id,
      depth,
      // The anchor keeps a wider berth so its two-line label has room underneath.
      r: n.id === anchorId ? 30 : nodeRadius(n.count),
      x: prev ? prev.x / s : columnX(depth) + Math.cos(angle) * 6,
      y: prev?.y ?? height / 2 + Math.sin(angle) * Math.min(height / 3, 40 + nodes.length * 2),
      ...(n.id === anchorId ? { fx: margin / s, fy: height / 2 } : {}),
    }
  })
  const index = new Map(simNodes.map((n) => [n.id, n]))
  const simLinks = links.filter((l) => index.has(l.from) && index.has(l.to) && l.from !== l.to).map((l) => ({ source: l.from, target: l.to }))
  const sim = forceSimulation(simNodes)
    .force('link', forceLink<SimNode, { source: string; target: string }>(simLinks).id((d) => d.id).distance(40).strength(0.2))
    .force('charge', forceManyBody<SimNode>().strength(-200).distanceMax(360))
    .force('x', forceX<SimNode>((d) => columnX(d.depth)).strength(0.4))
    .force('y', forceY<SimNode>(height / 2).strength(0.04))
    // Radius × 1.4 leaves room for the wide test pills.
    .force('collide', forceCollide<SimNode>((d) => d.r * 1.4 + 20).strength(1))
    .alpha(Object.keys(previous).length / nodes.length > 0.5 ? 0.35 : 1)
    .stop()
  for (let i = 0; i < ticks; i++) sim.tick()
  const out: Positions = {}
  for (const n of simNodes) {
    out[n.id] = n.id === anchorId ? { x: margin, y: height / 2 } : { x: (n.x ?? 0) * s, y: n.y ?? 0 }
  }
  return out
}

/** How much wider than tall the room around each overview node is: labels sit to the right and are wide, not tall. */
const LABEL_ASPECT = 2.2

/**
 * Small overview graphs (Connect's type graph, the explorer's start view): every node gets its label beside it, so
 * the simulation runs in a space squeezed horizontally by LABEL_ASPECT and is stretched back afterwards. Circles in
 * the squeezed space become wide ellipses on screen, leaving a label's width to the right of each node. Positions
 * are not clamped; the canvas fits them to the view.
 */
function overviewLayout(req: LayoutRequest): Positions {
  const { nodes, links, width, height, previous = {}, ticks = 220 } = req
  const w = width / LABEL_ASPECT
  const simNodes: SimNode[] = nodes.map((n, i) => {
    const prev = previous[n.id]
    const angle = (i / nodes.length) * Math.PI * 2
    return {
      id: n.id,
      depth: 1,
      r: nodeRadius(n.count),
      x: prev ? prev.x / LABEL_ASPECT : w / 2 + Math.cos(angle) * Math.min(w / 3, 30 + nodes.length * 2),
      y: prev?.y ?? height / 2 + Math.sin(angle) * Math.min(height / 3, 40 + nodes.length),
    }
  })
  const index = new Map(simNodes.map((n) => [n.id, n]))
  const simLinks = links.filter((l) => index.has(l.from) && index.has(l.to) && l.from !== l.to).map((l) => ({ source: l.from, target: l.to }))
  const sim = forceSimulation(simNodes)
    .force('link', forceLink<SimNode, { source: string; target: string }>(simLinks).id((d) => d.id).distance(40).strength(0.15))
    .force('charge', forceManyBody<SimNode>().strength(-260).distanceMax(400))
    .force('x', forceX<SimNode>(w / 2).strength(0.04))
    .force('y', forceY<SimNode>(height / 2).strength(0.05))
    .force('collide', forceCollide<SimNode>((d) => d.r + 24).strength(1))
    .alpha(Object.keys(previous).length / nodes.length > 0.5 ? 0.35 : 1)
    .stop()
  for (let i = 0; i < ticks; i++) sim.tick()
  const out: Positions = {}
  for (const n of simNodes) out[n.id] = { x: (n.x ?? 0) * LABEL_ASPECT, y: n.y ?? 0 }
  return out
}
