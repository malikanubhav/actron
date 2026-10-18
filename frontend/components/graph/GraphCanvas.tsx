'use client'
import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react'
import { ArrowsOut, Minus, Plus, ListBullets, Graph as GraphIcon } from '@phosphor-icons/react/dist/ssr'
import type { GraphLink, GraphNode, NodeGroup, Subgraph } from '@/lib/api/types'
import { DUR, easeEmphasized } from '@/lib/motion'
import { formatNumber, plural } from '@/lib/format'
import { useLayout } from './useLayout'
import {
  ANCHOR_RADIUS,
  columnLayout,
  CORE_HINT,
  GROUP_LABEL,
  GROUP_TOKEN,
  SHAPE_FAMILY,
  canvasLabels,
  leastOverlap,
  nearestPointOnBox,
  type Segment,
  clusterLabel,
  compactCount,
  countFitsInside,
  sidesAwayFromLinks,
  displayLabel,
  fitView,
  groupOf,
  hitTest,
  isCluster,
  isInferred,
  kindOf,
  legendShapes,
  linkAlpha,
  linkKey,
  neighbourInDirection,
  placeLabel,
  radiusOf,
  shapeEntryLabel,
  toScreen,
  wrapLabel,
  tracePlan,
  traceState,
  type Direction,
  type LabelBox,
  type LabelSide,
  type NodeKind,
  type NodeShape,
  type View,
} from './model'
import { ShapeIcon } from './ShapeIcon'
import { cx } from '../ui/cx'
import { BrandMark, type BrandName } from '../brand/BrandMark'

export interface TraceQuote {
  quote: string
  source: string
  author?: string | null
  brand?: BrandName | null
}

export interface GraphCanvasProps {
  graph: Subgraph | null
  mode?: 'aggregated' | 'expanded'
  onModeChange?: (mode: 'aggregated' | 'expanded') => void
  anchorId?: string | null
  highlight?: readonly string[]
  selectedId?: string | null
  onSelect?: (node: GraphNode | null) => void
  onExpand?: (node: GraphNode) => void
  pathToTrace?: readonly string[] | null
  quotes?: Record<string, TraceQuote>
  onTraceDone?: () => void
  view?: 'canvas' | 'list'
  onViewChange?: (view: 'canvas' | 'list') => void
  label?: string
  className?: string
  /** Shown when the graph has no nodes. */
  empty?: React.ReactNode
  /** Maximum nodes drawn before the user is asked (explorer budget). */
  budget?: number
  showLegend?: boolean
  /**
   * A type-level graph (Connect): every node is one type with a count. Counts follow the labels instead of sitting
   * inside shapes, and the legend explains shapes by family, since many types share a shape.
   */
  typeOverview?: boolean
  showModeToggle?: boolean
}

type Palette = Record<NodeGroup | 'text1' | 'text2' | 'link' | 'linkFocus' | 'accent' | 'ink0' | 'fontMono' | 'fontUi', string>

function readPalette(): Palette {
  const css = typeof window === 'undefined' ? null : getComputedStyle(document.documentElement)
  const get = (token: string, fallback: string) => css?.getPropertyValue(token).trim() || fallback
  return {
    code: get(GROUP_TOKEN.code, 'grey'),
    github: get(GROUP_TOKEN.github, 'grey'),
    slack: get(GROUP_TOKEN.slack, 'grey'),
    linear: get(GROUP_TOKEN.linear, 'grey'),
    core: get(GROUP_TOKEN.core, 'grey'),
    text1: get('--text-1', 'white'),
    text2: get('--text-2', 'silver'),
    link: get('--graph-link', 'grey'),
    linkFocus: get('--graph-link-focus', 'silver'),
    accent: get('--accent', 'yellow'),
    ink0: get('--ink-0', 'black'),
    fontMono: get('--font-mono', 'monospace'),
    // The family list the page body actually uses (next/font's generated names), so canvas text is the UI font.
    fontUi: (typeof document !== 'undefined' && getComputedStyle(document.body).fontFamily) || get('--font-ui', 'sans-serif'),
  }
}

const NO_DASH: number[] = []
const NO_BOXES: LabelBox[] = []
const LEADER_DASH = [1, 3]
/** Off: the type overview is a mesh. The column layout stays in model.ts, covered by its own test. */
const COLUMN_OVERVIEW = false
/** Overview labels hang below their node on a short line (then above, right, left). */
const DROP_SIDES: readonly LabelSide[] = ['below', 'above', 'right', 'left']
const DROP_GAP = 14
// Quote card size in px (w-64, three clamped lines plus the caption), used to place cards clear of labels.
const CARD_W = 256
const CARD_H = 96
// The fixed status bar at the bottom of the app shell.
const FOOTER_PX = 34
const LEGEND_GROUP_ORDER: NodeGroup[] = ['core', 'code', 'github', 'slack', 'linear']
const LABEL_H = 16
// Labels stay next to their node; one that fits nowhere adjacent is dropped (hover and list view still show it).
// Small graphs also try the corners above and below the node, aligned to its edge.
const SIDES: readonly LabelSide[] = ['right', 'left', 'above', 'below']
const OVERVIEW_SIDES: readonly LabelSide[] = ['right', 'left', 'below', 'above']
const SMALL_GRAPH_SIDES: readonly LabelSide[] = ['right', 'left', 'above', 'below', 'above-start', 'below-start', 'above-end', 'below-end']
const ANCHOR_SIDES: readonly LabelSide[] = ['below-start', 'above-start', 'below', 'above', 'right', 'left']

interface LabelCandidate {
  id: string
  lines: readonly string[]
  /** A narrower wrap of the same text, tried when `lines` fits nowhere (the request's title). */
  altLines?: readonly string[]
  x: number
  y: number
  r: number
  alpha: number
  color: string
  anchor: boolean
  /** Index of this node's own box in the obstacle list, skipped when placing its label. */
  own: number
  priority: number
}

function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true
}

function drawShape(ctx: CanvasRenderingContext2D, shape: NodeShape, x: number, y: number, r: number) {
  ctx.beginPath()
  switch (shape) {
    case 'square':
      ctx.roundRect(x - r, y - r, r * 2, r * 2, Math.min(3, r / 3))
      break
    case 'diamond':
      ctx.moveTo(x, y - r * 1.2)
      ctx.lineTo(x + r * 1.2, y)
      ctx.lineTo(x, y + r * 1.2)
      ctx.lineTo(x - r * 1.2, y)
      ctx.closePath()
      break
    case 'triangle':
      ctx.moveTo(x, y - r * 1.15)
      ctx.lineTo(x + r * 1.1, y + r * 0.85)
      ctx.lineTo(x - r * 1.1, y + r * 0.85)
      ctx.closePath()
      break
    case 'hexagon':
      for (let i = 0; i < 6; i++) {
        const a = (Math.PI / 3) * i + Math.PI / 6
        const px = x + Math.cos(a) * r * 1.08
        const py = y + Math.sin(a) * r * 1.08
        if (i === 0) ctx.moveTo(px, py)
        else ctx.lineTo(px, py)
      }
      ctx.closePath()
      break
    case 'speech':
      ctx.roundRect(x - r, y - r * 0.9, r * 2, r * 1.5, r * 0.45)
      ctx.moveTo(x - r * 0.55, y + r * 0.5)
      ctx.lineTo(x - r * 0.7, y + r * 1.05)
      ctx.lineTo(x - r * 0.05, y + r * 0.5)
      ctx.closePath()
      break
    case 'file': {
      const w = r * 0.8
      const c = r * 0.5
      ctx.moveTo(x - w, y - r)
      ctx.lineTo(x + w - c, y - r)
      ctx.lineTo(x + w, y - r + c)
      ctx.lineTo(x + w, y + r)
      ctx.lineTo(x - w, y + r)
      ctx.closePath()
      break
    }
    case 'pill':
      ctx.roundRect(x - r * 1.35, y - r * 0.8, r * 2.7, r * 1.6, r * 0.8)
      break
    default:
      ctx.arc(x, y, r, 0, Math.PI * 2)
  }
}

export { ShapeIcon }

declare global {
  interface Window {
    __actronMeasure?: boolean
    __actronFrames?: number[]
  }
}

/**
 * The graph canvas (spec C, C2): d3-force layout in a worker, Canvas 2D drawing, shapes per type, colours per
 * source, solid explicit and dashed inferred links with opacity by confidence, zoom, pan and fit, hover card,
 * keyboard traversal along links, a list-view alternative, and the evidence path traced hop by hop.
 */
export function GraphCanvas({
  graph,
  mode = 'aggregated',
  onModeChange,
  anchorId = null,
  highlight = [],
  selectedId = null,
  onSelect,
  onExpand,
  pathToTrace = null,
  quotes = {},
  onTraceDone,
  view = 'canvas',
  onViewChange,
  label = 'Graph',
  className,
  empty,
  budget = 300,
  showLegend = true,
  typeOverview = false,
  showModeToggle = true,
}: GraphCanvasProps) {
  const liveId = useId()
  const wrapRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [size, setSize] = useState({ width: 0, height: 0 })
  const [hover, setHover] = useState<{ node: GraphNode; x: number; y: number } | null>(null)
  const [focusId, setFocusId] = useState<string | null>(null)
  const [overBudget, setOverBudget] = useState(true)
  const [hoverHint, setHoverHint] = useState(false)
  const palette = useRef<Palette | null>(null)
  const viewRef = useRef<View>({ x: 0, y: 0, k: 1 })
  const userMoved = useRef(false)
  const appearAt = useRef(new Map<string, number>())
  const traceStart = useRef<number | null>(null)
  const traceDoneFired = useRef(false)
  // Nodes reached by the current trace and the view they were drawn in; quote cards are placed from this.
  // `boxes` are the labels and nodes on screen at that moment, so quote cards can avoid covering them.
  const [traceInfo, setTraceInfo] = useState<{ path: readonly string[] | null; reached: string[]; view: View; boxes: LabelBox[]; visible: number }>({
    path: null,
    reached: [],
    view: { x: 0, y: 0, k: 1 },
    boxes: [],
    visible: 0,
  })
  // The quote cards' boxes from the last render, so labels drawn on the canvas keep clear of them.
  const cardBoxes = useRef<LabelBox[]>([])
  const [, force] = useState(0)
  // The latest draw function, so a trace that starts later can run its own animation loop.
  const drawRef = useRef<(now: number) => boolean>(() => false)
  const rerender = useCallback(() => force((n) => n + 1), [])

  const allNodes = useMemo(() => graph?.nodes ?? [], [graph])
  const limited = allNodes.length > budget && overBudget
  const nodes = useMemo(() => (limited ? allNodes.slice(0, budget) : allNodes), [allNodes, limited, budget])
  const nodeIds = useMemo(() => new Set(nodes.map((n) => n.id)), [nodes])
  const links = useMemo(() => (graph?.links ?? []).filter((l) => nodeIds.has(l.from) && nodeIds.has(l.to)), [graph, nodeIds])
  const byId = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes])
  // In dense graphs only the twelve largest clusters carry labels until the user zooms in or focuses a node.
  const labelled = useMemo(
    () => new Set([...nodes].sort((a, b) => (b.count ?? 1) - (a.count ?? 1)).slice(0, 12).map((n) => n.id)),
    [nodes],
  )
  // Per-node drawing facts, computed once per graph rather than every frame (C-AC-12).
  const look = useMemo(() => {
    const short = canvasLabels(nodes, 24, typeOverview)
    const long = canvasLabels(nodes, 32, typeOverview)
    return new Map(
      nodes.map((n) => {
        const text = displayLabel(n)
        const label = short.get(n.id) ?? text
        const full = long.get(n.id) ?? label
        // The anchor keeps more of its title, wrapped onto two short lines (three narrower ones as a fallback).
        // Other labels try up to 32 characters where there is room beside the node, then 24.
        const lines = n.id === anchorId ? wrapLabel(text, 26, 2) : [full]
        const altLines = n.id === anchorId ? wrapLabel(text, 20, 3) : full !== label ? [label] : undefined
        return [n.id, { kind: kindOf(n), group: groupOf(n), label, lines, altLines }] as const
      }),
    )
  }, [nodes, anchorId, typeOverview])
  const textWidth = useRef(new Map<string, number>())
  const hoverId = hover?.node.id ?? null

  // The type-level overview (Connect) is a force mesh like every other graph; each node's name hangs from it on a short
  // line. The fixed column layout (`columnLayout`) was tried and dropped: the mesh shows how types connect.
  const columns = useMemo(() => {
    if (!COLUMN_OVERVIEW || !typeOverview || size.width === 0 || nodes.length === 0) return null
    const ctx = typeof document !== 'undefined' ? document.createElement('canvas').getContext('2d') : null
    if (ctx) ctx.font = `12px ${getComputedStyle(document.body).fontFamily}`
    const width = (id: string) => (ctx ? ctx.measureText(look.get(id)?.lines[0] ?? '').width : 120) + 4
    return columnLayout(nodes, width, size.width, size.height)
  }, [typeOverview, nodes, look, size.width, size.height])
  const layoutRequest = useMemo(
    () =>
      size.width > 0 && nodes.length > 0 && !columns
        ? {
            nodes: nodes.map((n) => ({ id: n.id, group: n.group, count: n.count })),
            links: links.map((l) => ({ from: l.from, to: l.to })),
            width: size.width,
            height: size.height,
            anchorId,
          }
        : null,
    [nodes, links, size.width, size.height, anchorId, columns],
  )
  const forceLayout = useLayout(layoutRequest)
  const positions = columns ? columns.positions : forceLayout.positions
  const ready = columns ? true : forceLayout.ready

  // Corner positions only on overview graphs: on a request graph a label at a corner can read as another node's.
  const defaultSides = !anchorId && nodes.length <= 40 ? SMALL_GRAPH_SIDES : SIDES
  const sideOrder = useMemo(() => sidesAwayFromLinks(links, positions, defaultSides), [links, positions, defaultSides])
  // Better-connected nodes get their labels first.
  const degree = useMemo(() => {
    const out = new Map<string, number>()
    for (const l of links) {
      out.set(l.from, (out.get(l.from) ?? 0) + 1)
      out.set(l.to, (out.get(l.to) ?? 0) + 1)
    }
    return out
  }, [links])
  const hops = useMemo(() => (pathToTrace ? tracePlan(pathToTrace, nodes) : []), [pathToTrace, nodes])
  const highlightSet = useMemo(() => new Set(highlight), [highlight])

  // Size tracking. The canvas wrapper exists only once there are nodes, so re-attach when the graph stops being
  // empty (data that arrives after the first render would otherwise never be measured or laid out).
  const hasNodes = nodes.length > 0
  useEffect(() => {
    const el = wrapRef.current
    if (!el) return
    const measure = () => setSize({ width: el.clientWidth, height: el.clientHeight })
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    return () => ro.disconnect()
  }, [view, hasNodes])

  // Node entrance timing: nodes that arrive after the first layout fade in.
  useEffect(() => {
    const now = performance.now()
    const first = appearAt.current.size === 0
    for (const n of nodes) if (!appearAt.current.has(n.id)) appearAt.current.set(n.id, first ? now - DUR[3] : now)
  }, [nodes])

  // Fit when the layout changes, unless the user has panned or zoomed.
  useEffect(() => {
    if (!ready || userMoved.current) return
    viewRef.current = columns ? columns.view : fitView(positions, size.width, size.height)
    rerender()
  }, [ready, positions, size.width, size.height, rerender, columns])

  // Start a new trace whenever the path changes, once the layout is ready so the user sees it drawn.
  useEffect(() => {
    if (!ready && pathToTrace) return
    traceStart.current = pathToTrace && pathToTrace.length > 1 ? performance.now() : null
    traceDoneFired.current = false
    let raf = 0
    const loop = (now: number) => {
      if (drawRef.current(now)) raf = requestAnimationFrame(loop)
    }
    raf = requestAnimationFrame(loop)
    return () => cancelAnimationFrame(raf)
  }, [pathToTrace, ready])

  const draw = useCallback(
    (now: number): boolean => {
      const canvas = canvasRef.current
      const ctx = canvas?.getContext('2d')
      if (!canvas || !ctx || size.width === 0) return false
      if (!palette.current) palette.current = readPalette()
      const pal = palette.current
      const dpr = window.devicePixelRatio || 1
      if (canvas.width !== Math.round(size.width * dpr) || canvas.height !== Math.round(size.height * dpr)) {
        canvas.width = Math.round(size.width * dpr)
        canvas.height = Math.round(size.height * dpr)
      }
      const v = viewRef.current
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      ctx.clearRect(0, 0, size.width, size.height)
      ctx.setTransform(dpr * v.k, 0, 0, dpr * v.k, dpr * v.x, dpr * v.y)

      const reduced = prefersReducedMotion()
      const trace = traceStart.current !== null ? traceState(hops, now - traceStart.current, reduced) : null
      // Nodes the user is looking at: hovered, keyboard-focused, selected or highlighted. Their links brighten.
      const active = new Set<string>(highlightSet)
      if (selectedId) active.add(selectedId)
      if (focusId) active.add(focusId)
      if (hoverId) active.add(hoverId)
      const focusSet = new Set<string>(active)
      if (trace) for (const id of trace.nodes) focusSet.add(id)
      // The direct neighbours of the selected, focused or hovered node stay at full strength too.
      if (selectedId || focusId || hoverId) {
        for (const l of links) {
          if (l.from === selectedId || l.from === focusId || l.from === hoverId) focusSet.add(l.to)
          if (l.to === selectedId || l.to === focusId || l.to === hoverId) focusSet.add(l.from)
        }
      }
      const dimOthers = focusSet.size > 0
      // A path shown on its own (the default evidence path) dims the rest gently; a selection dims it more.
      const dimNode = active.size > 0 ? 0.3 : 0.75
      const dimLabel = active.size > 0 ? 0.45 : 0.85
      // Dense graphs (the memory overview) keep resting links quieter so the structure does not turn into a hairball.
      const rest = links.length > nodes.length * 1.5 ? 0.4 : 1
      const dash = [6 / v.k, 4 / v.k]
      let animating = false

      // Links at rest and links touching the active nodes; the evidence path is drawn after, on top.
      for (const link of links) {
        if (trace?.links.has(linkKey(link.from, link.to))) continue
        const a = positions[link.from]
        const b = positions[link.to]
        if (!a || !b) continue
        const touched = active.has(link.from) || active.has(link.to)
        ctx.beginPath()
        ctx.moveTo(a.x, a.y)
        if (columns) {
          // Column layout: faint curves, bowed so links between neighbours in one column do not run along it.
          const bow = Math.max(24, Math.abs(b.y - a.y) * 0.25)
          ctx.quadraticCurveTo((a.x + b.x) / 2 + (a.x === b.x ? bow : 0), (a.y + b.y) / 2 - (a.x === b.x ? 0 : bow * 0.5), b.x, b.y)
        } else ctx.lineTo(b.x, b.y)
        ctx.setLineDash(isInferred(link) ? dash : NO_DASH)
        ctx.lineWidth = (touched ? 1.6 : 1) / v.k
        ctx.strokeStyle = touched ? pal.linkFocus : pal.link
        ctx.globalAlpha =
          linkAlpha(link) * (touched ? 1 : dimOthers ? (active.size > 0 ? (columns ? 0.15 : 0.35) : 0.6) * rest : columns ? 0.25 : rest)
        ctx.stroke()
      }
      if (trace) {
        ctx.strokeStyle = pal.accent
        ctx.globalAlpha = 1
        ctx.lineWidth = 3 / v.k
        for (const link of links) {
          if (!trace.links.has(linkKey(link.from, link.to))) continue
          const a = positions[link.from]
          const b = positions[link.to]
          if (!a || !b) continue
          ctx.beginPath()
          ctx.moveTo(a.x, a.y)
          ctx.lineTo(b.x, b.y)
          // Always solid: the legend shows the evidence path as one solid yellow line, and a dashed yellow hop
          // read as "inferred, so maybe not evidence".
          ctx.setLineDash(NO_DASH)
          ctx.stroke()
        }
      }
      ctx.setLineDash(NO_DASH)

      // The hop being traced draws progressively.
      if (trace?.active) {
        const a = positions[trace.active.hop.from]
        const b = positions[trace.active.hop.to]
        if (a && b) {
          const t = easeEmphasized(Math.min(1, trace.active.t))
          ctx.beginPath()
          ctx.moveTo(a.x, a.y)
          ctx.lineTo(a.x + (b.x - a.x) * t, a.y + (b.y - a.y) * t)
          ctx.lineWidth = 3 / v.k
          ctx.strokeStyle = pal.accent
          ctx.globalAlpha = 1
          ctx.stroke()
        }
        animating = true
      }

      // Nodes
      const labels: LabelCandidate[] = []
      const obstacles: LabelBox[] = []
      for (const node of nodes) {
        const p = positions[node.id]
        if (!p) continue
        const info = look.get(node.id)
        if (!info) continue
        const isAnchor = node.id === anchorId
        const born = appearAt.current.get(node.id) ?? 0
        const enter = reduced ? 1 : Math.min(1, (now - born) / DUR[3])
        if (enter < 1) animating = true
        const r = (isAnchor ? ANCHOR_RADIUS : (columns?.radius.get(node.id) ?? radiusOf(node))) * (0.6 + 0.4 * easeEmphasized(enter))
        const shape = info.kind.shape
        const color = pal[info.group]
        const inFocus = focusSet.has(node.id)
        const onTrace = trace?.nodes.has(node.id) ?? false
        const cluster = isCluster(node)
        ctx.globalAlpha = enter * (dimOthers && !inFocus ? dimNode : 1)
        drawShape(ctx, shape, p.x, p.y, r)
        if (shape === 'ring') {
          if (cluster) {
            ctx.fillStyle = pal.ink0
            ctx.fill()
          }
          ctx.lineWidth = 2 / v.k
          ctx.strokeStyle = color
          ctx.stroke()
        } else {
          ctx.fillStyle = color
          ctx.fill()
        }
        // The request is the anchor: larger, in the core colour, with a second outline ring. Never the accent.
        if (isAnchor) {
          drawShape(ctx, shape, p.x, p.y, r + 4 / v.k)
          ctx.lineWidth = 1.5 / v.k
          ctx.strokeStyle = color
          ctx.stroke()
        }
        const ringed = node.id === selectedId || node.id === focusId || highlightSet.has(node.id) || (onTrace && !isAnchor)
        if (ringed) {
          drawShape(ctx, shape, p.x, p.y, r + (isAnchor ? 8 : 4) / v.k)
          ctx.lineWidth = (node.id === focusId ? 2 : 1.5) / v.k
          ctx.strokeStyle = onTrace && !isAnchor ? pal.accent : pal.text1
          ctx.globalAlpha = 1
          ctx.stroke()
        }
        // Text is drawn in screen space at its real pixel size, so glyph spacing stays crisp at any zoom.
        const sx = p.x * v.k + v.x
        const sy = p.y * v.k + v.y
        const sr = r * v.k
        const half = shape === 'pill' ? sr * 1.35 : sr
        obstacles.push({ x: sx - half, y: sy - sr, w: half * 2, h: sr * 2 })        // The count goes inside only shapes with room for it (other shapes carry it in their label).
        const countText = cluster ? compactCount(node.count ?? 0) : ''
        const countSize = Math.max(9, Math.min(11, sr * 0.75))
        if (cluster && !typeOverview && countFitsInside(shape) &&countText.length * countSize * 0.62 <= half * 1.7) {
          ctx.save()
          ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
          ctx.globalAlpha = enter
          ctx.fillStyle = shape === 'ring' ? color : pal.ink0
          ctx.font = `600 ${countSize}px ${pal.fontMono}`
          ctx.textAlign = 'center'
          ctx.textBaseline = 'middle'
          ctx.fillText(countText, sx, sy + 0.5)
          ctx.restore()
        }
        // Labels: always for the anchor and anything in focus; every node in small graphs; the largest clusters;
        // everything when zoomed in.
        const showLabel = isAnchor || inFocus || v.k > 1.4 || nodes.length <= 40 || labelled.has(node.id)
        if (showLabel) {
          labels.push({
            id: node.id,
            lines: info.lines,
            altLines: info.altLines,
            x: sx,
            y: sy,
            // Labels clear the selection or path ring, not just the glyph.
            r: half + (ringed ? 5 : 0),
            alpha: enter * (dimOthers && !inFocus && !isAnchor ? dimLabel : 1),
            color: inFocus || isAnchor ? pal.text1 : pal.text2,
            anchor: isAnchor,
            own: obstacles.length - 1,
            priority: isAnchor ? 0 : onTrace || node.id === selectedId || node.id === focusId || node.id === hoverId ? 1 : inFocus ? 2 : cluster ? 2.5 - Math.min(0.49, (node.count ?? 1) / 1e6) : 3 - Math.min(0.49, (degree.get(node.id) ?? 0) / 1000),
          })
        }
      }

      // Labels last, in screen space, most important first. Each tries right, left, above and below its node and
      // is dropped when every side would overlap another label or node (it still shows on hover and in list view).
      ctx.save()
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      ctx.textBaseline = 'middle'
      ctx.textAlign = 'left'
      ctx.lineWidth = 3
      ctx.strokeStyle = pal.ink0
      ctx.lineJoin = 'round'
      // Quote cards are placed first; labels keep clear of them.
      const placed: LabelBox[] = [...cardBoxes.current]
      const bounds = { width: size.width, height: size.height }
      // Small graphs follow one rule set: a consistent side order, each label closest to its own node, and on graphs
      // of 24 nodes or fewer (or overviews of up to 40) every node gets a label, with a leader line as last resort.
      const smallGraph = nodes.length <= 40
      const everyLabel = nodes.length <= 24 || (!anchorId && smallGraph)
      // The traced path in screen space, so labels keep off it.
      const pathSegments: Segment[] = []
      if (trace) {
        for (const link of links) {
          if (!trace.links.has(linkKey(link.from, link.to))) continue
          const a = positions[link.from]
          const b = positions[link.to]
          if (a && b) pathSegments.push({ x1: a.x * v.k + v.x, y1: a.y * v.k + v.y, x2: b.x * v.k + v.x, y2: b.y * v.k + v.y })
        }
        // The hop still being drawn counts too: the label must not sit where the line is about to go.
        if (trace.active) {
          const a = positions[trace.active.hop.from]
          const b = positions[trace.active.hop.to]
          if (a && b) pathSegments.push({ x1: a.x * v.k + v.x, y1: a.y * v.k + v.y, x2: b.x * v.k + v.x, y2: b.y * v.k + v.y })
        }
      }
      if ('letterSpacing' in ctx) ctx.letterSpacing = '0px'
      const regular = `12px ${pal.fontUi}`
      const strong = `500 12px ${pal.fontUi}`
      labels.sort((a, b) => a.priority - b.priority)
      let unlabelled = 0
      const measure = (lines: readonly string[], bold: boolean) => {
        let w = 0
        for (const line of lines) {
          const cacheKey = `${bold ? 'b' : 'r'}${line}`
          let lw = textWidth.current.get(cacheKey)
          if (lw === undefined) {
            lw = ctx.measureText(line).width
            textWidth.current.set(cacheKey, lw)
          }
          w = Math.max(w, lw)
        }
        return w
      }
      for (const l of labels) {
        ctx.font = l.anchor ? strong : regular
        // Overview graphs use one rule everywhere (right, then left, below, above) so labels read the same way.
        const sides = l.anchor ? ANCHOR_SIDES : smallGraph ? OVERVIEW_SIDES : (sideOrder.get(l.id) ?? defaultSides)
        const lr = l.r + (l.anchor ? 4 : 0)
        let box: LabelBox | null = null
        let leader = false
        let lines = l.lines
        // Column layout: the label always sits right of its node; the column was sized to hold it.
        if (columns) box = { x: l.x + l.r + 6, y: l.y - LABEL_H / 2, w: measure(lines, false) + 4, h: LABEL_H }
        // Overview mesh: the name hangs from its node on a short line, so it is never in doubt whose name it is.
        else if (typeOverview && !l.anchor) {
          box = placeLabel(DROP_SIDES, l.x, l.y, lr, measure(lines, false) + 4, LABEL_H, placed, obstacles, bounds, l.own, pathSegments, DROP_GAP, true, true)
          leader = box !== null
        }
        // The request's title may also wrap narrower, onto three lines, to find a free spot.
        for (const variant of box ? [] : l.altLines ? [l.lines, l.altLines] : [l.lines]) {
          const w = measure(variant, l.anchor)
          const h = LABEL_H * variant.length
          lines = variant
          // No label sits on the traced evidence path.
          box = placeLabel(sides, l.x, l.y, lr, w + 4, h, placed, obstacles, bounds, l.own, pathSegments, 4, false, smallGraph)
          // The request, nodes on the path or selected, and every node of a small graph try a spot a little further
          // out with a short dotted leader (at most about 24 px) that crosses no node or label. If that fails too the
          // node stays unlabelled; it shows on hover and in the list view.
          if (!box && (everyLabel || l.priority <= 1)) {
            for (const far of [12, 20]) {
              box = placeLabel(SMALL_GRAPH_SIDES, l.x, l.y, lr, w + 4, h, placed, obstacles, bounds, l.own, pathSegments, far, true)
              if (box) break
            }
            leader = box !== null
          }
          if (box) break
        }
        // Last resort for the request only: keep off the path and other labels, even if a node shows behind it.
        if (!box && l.anchor) {
          lines = l.lines
          const w = measure(lines, true)
          const h = LABEL_H * lines.length
          box = placeLabel(ANCHOR_SIDES, l.x, l.y, lr, w + 4, h, placed, NO_BOXES, bounds, -1, pathSegments) ?? { x: Math.max(2, l.x - l.r), y: l.y + l.r + 8, w: w + 4, h }
        }
        if (!box) {
          unlabelled++
          continue
        }
        placed.push(box)
        if (leader) {
          // Dotted, in the label's own colour, from the plate edge to 3 px short of the node: it cannot read as a link.
          const end = nearestPointOnBox(l.x, l.y, box)
          const len = Math.hypot(end.x - l.x, end.y - l.y) || 1
          const sx = l.x + ((end.x - l.x) / len) * (l.r + 3)
          const sy = l.y + ((end.y - l.y) / len) * (l.r + 3)
          // Later labels keep off this leader line too.
          pathSegments.push({ x1: sx, y1: sy, x2: end.x, y2: end.y })
          ctx.save()
          ctx.lineWidth = 1
          // Overview: a plain thin line from the node to its name. Request graphs keep the faint dotted leader.
          ctx.setLineDash(typeOverview ? NO_DASH : LEADER_DASH)
          ctx.strokeStyle = l.color
          ctx.globalAlpha = (typeOverview ? 0.6 : 0.4) * l.alpha
          ctx.beginPath()
          ctx.moveTo(end.x, end.y)
          ctx.lineTo(sx, sy)
          ctx.stroke()
          ctx.restore()
        }
        // An ink-0 plate behind the text, so links passing under a label disappear behind it.
        ctx.globalAlpha = 0.92 * l.alpha
        ctx.fillStyle = pal.ink0
        ctx.beginPath()
        ctx.roundRect(box.x - 1, box.y + 1, box.w + 2, box.h - 2, 3)
        ctx.fill()
        ctx.globalAlpha = l.alpha
        ctx.fillStyle = l.color
        for (let i = 0; i < lines.length; i++) {
          const line = lines[i] as string
          const ly = box.y + LABEL_H * i + LABEL_H / 2
          ctx.strokeText(line, box.x + 2, ly)
          ctx.fillText(line, box.x + 2, ly)
        }
      }
      // Column headings in the source colour.
      if (columns) {
        ctx.font = strong
        ctx.textBaseline = 'top'
        ctx.globalAlpha = 1
        for (const h of columns.headings) {
          ctx.fillStyle = pal[h.group]
          ctx.fillText(h.text, h.x * v.k + v.x, h.y * v.k + v.y)
        }
      }
      ctx.restore()
      ctx.globalAlpha = 1
      // The legend says "Hover a node for its name" while any node in a small graph goes unlabelled.
      const hint = smallGraph && unlabelled > 0
      if (hint !== hoverHint) setHoverHint(hint)

      if (trace) {
        const reached = [...trace.nodes]
        const same =
          traceInfo.path === pathToTrace &&
          traceInfo.reached.length === reached.length &&
          traceInfo.view.x === v.x &&
          traceInfo.view.y === v.y &&
          traceInfo.view.k === v.k
        // Quote cards are placed (in the DOM) where they cover the fewest labels and nodes.
        // Cards must stay inside the part of the canvas that is on screen (the panel can run under the footer).
        const rect = canvas.getBoundingClientRect()
        const visible = Math.max(CARD_H + 16, Math.min(size.height, window.innerHeight - FOOTER_PX - rect.top))
        if (!same || traceInfo.visible !== visible)
          setTraceInfo({ path: pathToTrace, reached, view: v, boxes: placed.slice(cardBoxes.current.length).concat(obstacles), visible })
        if (trace.done && !traceDoneFired.current) {
          traceDoneFired.current = true
          onTraceDone?.()
        }
      }
      return animating
    },
    [size, positions, links, nodes, hops, highlightSet, selectedId, focusId, hoverId, anchorId, traceInfo, pathToTrace, onTraceDone, labelled, look, sideOrder, defaultSides, degree, typeOverview, hoverHint, columns],
  )

  // Draw time per frame is recorded for the frame-budget test (C-AC-12) when window.__actronMeasure is set.
  const measuredDraw = useCallback(
    (now: number) => {
      const started = performance.now()
      const more = draw(now)
      if (window.__actronMeasure) (window.__actronFrames ??= []).push(performance.now() - started)
      return more
    },
    [draw],
  )
  useEffect(() => {
    drawRef.current = measuredDraw
  }, [measuredDraw])

  // Render loop: draws on change, keeps going only while something animates.
  useEffect(() => {
    if (view !== 'canvas') return
    let raf = 0
    const loop = (now: number) => {
      if (measuredDraw(now)) raf = requestAnimationFrame(loop)
    }
    raf = requestAnimationFrame(loop)
    return () => cancelAnimationFrame(raf)
  }, [measuredDraw, view])

  const redraw = useCallback(() => requestAnimationFrame((t) => measuredDraw(t)), [measuredDraw])

  // Pan and zoom.
  const drag = useRef<{ x: number; y: number; vx: number; vy: number; moved: boolean } | null>(null)
  const onPointerDown = (e: React.PointerEvent<HTMLCanvasElement>) => {
    ;(e.target as HTMLCanvasElement).setPointerCapture?.(e.pointerId)
    drag.current = { x: e.clientX, y: e.clientY, vx: viewRef.current.x, vy: viewRef.current.y, moved: false }
  }
  const localPoint = (e: { clientX: number; clientY: number }) => {
    const rect = canvasRef.current?.getBoundingClientRect()
    return { x: e.clientX - (rect?.left ?? 0), y: e.clientY - (rect?.top ?? 0) }
  }
  const onPointerMove = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const d = drag.current
    if (d) {
      const dx = e.clientX - d.x
      const dy = e.clientY - d.y
      if (Math.abs(dx) + Math.abs(dy) > 3) d.moved = true
      if (d.moved) {
        userMoved.current = true
        viewRef.current = { ...viewRef.current, x: d.vx + dx, y: d.vy + dy }
        setHover(null)
        redraw()
      }
      return
    }
    const pt = localPoint(e)
    const node = hitTest(pt, nodes, positions, viewRef.current, anchorId, columns?.radius)
    setHover((h) => (node ? { node, x: pt.x, y: pt.y } : h ? null : h))
  }
  const onPointerUp = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const d = drag.current
    drag.current = null
    if (d?.moved) return
    const node = hitTest(localPoint(e), nodes, positions, viewRef.current, anchorId, columns?.radius)
    onSelect?.(node)
    if (node) setFocusId(node.id)
  }
  const zoomBy = useCallback(
    (factor: number, center?: { x: number; y: number }) => {
      const v = viewRef.current
      const c = center ?? { x: size.width / 2, y: size.height / 2 }
      const k = Math.max(0.2, Math.min(4, v.k * factor))
      viewRef.current = { k, x: c.x - ((c.x - v.x) / v.k) * k, y: c.y - ((c.y - v.y) / v.k) * k }
      userMoved.current = true
      redraw()
    },
    [size, redraw],
  )
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      const rect = canvas.getBoundingClientRect()
      zoomBy(Math.exp(-e.deltaY * 0.0015), { x: e.clientX - rect.left, y: e.clientY - rect.top })
    }
    canvas.addEventListener('wheel', onWheel, { passive: false })
    return () => canvas.removeEventListener('wheel', onWheel)
  }, [zoomBy, view])

  const fit = () => {
    userMoved.current = false
    viewRef.current = columns ? columns.view : fitView(positions, size.width, size.height)
    redraw()
  }

  // Keyboard traversal.
  const onKeyDown = (e: React.KeyboardEvent) => {
    const keys: Record<string, Direction> = { ArrowLeft: 'left', ArrowRight: 'right', ArrowUp: 'up', ArrowDown: 'down' }
    if (keys[e.key]) {
      e.preventDefault()
      const from = focusId ?? anchorId ?? nodes[0]?.id ?? null
      if (!from) return
      const next = focusId ? neighbourInDirection(from, keys[e.key] as Direction, links, positions) : from
      if (next) setFocusId(next)
    } else if (e.key === 'Enter' && focusId) {
      e.preventDefault()
      onSelect?.(byId.get(focusId) ?? null)
    } else if (e.key === 'Escape') {
      setFocusId(null)
      onSelect?.(null)
    } else if (e.key === '+' || e.key === '=') zoomBy(1.2)
    else if (e.key === '-') zoomBy(1 / 1.2)
    else if (e.key === '0') fit()
  }

  const focused = focusId ? byId.get(focusId) : null
  const focusedDegree = focusId ? links.filter((l) => l.from === focusId || l.to === focusId).length : 0
  const groups = useMemo(() => {
    const out = new Map<string, { kind: NodeKind; group: NodeGroup; nodes: GraphNode[] }>()
    for (const n of nodes) {
      const info = look.get(n.id)
      if (!info) continue
      const entry = out.get(info.kind.key) ?? { kind: info.kind, group: info.group, nodes: [] }
      entry.nodes.push(n)
      out.set(info.kind.key, entry)
    }
    return [...out.values()].sort((a, b) => b.nodes.length - a.nodes.length)
  }, [nodes, look])
  const legendGroups = useMemo(() => {
    const present = new Set([...look.values()].map((l) => l.group))
    return LEGEND_GROUP_ORDER.filter((g) => present.has(g))
  }, [look])
  // Every shape on screen with the kinds it stands for, the anchor's shape first.
  const legendKinds = useMemo(
    () =>
      legendShapes(
        groups.map((g) => ({ kind: g.kind, group: g.group, weight: g.nodes.reduce((sum, n) => sum + Math.max(1, n.count ?? 1), 0) })),
        anchorId ? look.get(anchorId)?.kind.shape : undefined,
      ),
    [groups, look, anchorId],
  )
  const hasClusters = nodes.some(isCluster)
  const hasInferred = links.some(isInferred)
  const palColor = (g: NodeGroup) => `var(${GROUP_TOKEN[g]})`

  // Quote cards on traced hops (positions in screen space).
  const reachedNow = traceInfo.path === pathToTrace ? traceInfo.reached : []
  // Each card tries the spots around its node, then the canvas corners, and takes the one covering the fewest labels,
  // nodes and earlier cards, inside the part of the canvas that is on screen. Labels then keep clear of the cards.
  const quoteCards: { id: string; left: number; top: number; q: TraceQuote }[] = []
  {
    const taken = [...traceInfo.boxes]
    const bottom = traceInfo.visible || size.height
    const bounds = { width: size.width, height: bottom }
    for (const id of reachedNow) {
      const p = positions[id]
      const q = quotes[id]
      if (!p || !q) continue
      const s = toScreen(p, traceInfo.view)
      const spots = [
        { x: s.x + 14, y: s.y - CARD_H - 10 },
        { x: s.x + 14, y: s.y + 14 },
        { x: s.x - CARD_W - 14, y: s.y - CARD_H - 10 },
        { x: s.x - CARD_W - 14, y: s.y + 14 },
        { x: s.x - CARD_W / 2, y: s.y - CARD_H - 18 },
        { x: s.x - CARD_W / 2, y: s.y + 18 },
        { x: s.x + 18, y: s.y - CARD_H / 2 },
        { x: s.x - CARD_W - 18, y: s.y - CARD_H / 2 },
        { x: 8, y: 8 },
        { x: size.width - CARD_W - 8, y: 8 },
        { x: 8, y: bottom - CARD_H - 8 },
        { x: size.width - CARD_W - 8, y: bottom - CARD_H - 8 },
      ]
      const at = leastOverlap(spots, CARD_W, CARD_H, taken, bounds)
      taken.push({ x: at.x, y: at.y, w: CARD_W, h: CARD_H })
      quoteCards.push({ id, left: at.x, top: at.y, q })
    }
  }
  const cardKey = quoteCards.map((c) => `${c.left},${c.top}`).join('|')
  useEffect(() => {
    cardBoxes.current = cardKey ? cardKey.split('|').map((s) => {
      const [x, y] = s.split(',').map(Number)
      return { x: x as number, y: y as number, w: CARD_W, h: CARD_H }
    }) : []
    redraw()
  }, [cardKey, redraw])

  return (
    <div className={cx('relative flex min-h-0 flex-col', className)} data-testid="graph-canvas">
      <div className="flex items-center gap-2 border-b border-line-1 px-3 py-2">
        {showModeToggle && onModeChange ? (
          <div role="radiogroup" aria-label="Graph mode" className="inline-flex rounded-md border border-line-2 p-0.5">
            {(['aggregated', 'expanded'] as const).map((m) => (
              <button
                key={m}
                type="button"
                role="radio"
                aria-checked={mode === m}
                onClick={() => onModeChange(m)}
                className={cx(
                  'h-6 rounded-sm px-2 text-caption font-medium',
                  mode === m ? 'bg-ink-3 text-fg-1' : 'text-fg-3 hover:text-fg-1',
                )}
              >
                {m === 'aggregated' ? 'Aggregated' : 'Expanded'}
              </button>
            ))}
          </div>
        ) : null}
        <span className={cx('hidden whitespace-nowrap font-mono text-caption text-fg-3 tabular', !typeOverview && '2xl:inline')} data-testid="graph-counts">
          {nodes.every((n) => (n.count ?? 0) >= 1)
            ? `${plural(nodes.length, 'group')} · ${plural(links.length, 'link')} between groups`
            : nodes.some((n) => (n.count ?? 0) > 1)
              ? `${plural(nodes.length, 'group')} shown · ${plural(links.length, 'link')}`
              : `${plural(nodes.length, 'node')} · ${plural(links.length, 'link')}`}
        </span>
        <span className="flex-1" />
        {view === 'canvas' ? (
          <>
            <button type="button" onClick={() => zoomBy(1 / 1.25)} aria-label="Zoom out" className="press inline-flex size-7 items-center justify-center rounded-sm text-fg-2 hover:bg-ink-3 hover:text-fg-1">
              <Minus size={14} aria-hidden />
            </button>
            <button type="button" onClick={() => zoomBy(1.25)} aria-label="Zoom in" className="press inline-flex size-7 items-center justify-center rounded-sm text-fg-2 hover:bg-ink-3 hover:text-fg-1">
              <Plus size={14} aria-hidden />
            </button>
            <button type="button" onClick={fit} aria-label="Fit to view" className="press inline-flex size-7 items-center justify-center rounded-sm text-fg-2 hover:bg-ink-3 hover:text-fg-1">
              <ArrowsOut size={14} aria-hidden />
            </button>
          </>
        ) : null}
        {onViewChange ? (
          <button
            type="button"
            onClick={() => onViewChange(view === 'canvas' ? 'list' : 'canvas')}
            aria-pressed={view === 'list'}
            className="press inline-flex h-7 items-center gap-1.5 whitespace-nowrap rounded-sm px-2 text-caption text-fg-2 hover:bg-ink-3 hover:text-fg-1"
          >
            {view === 'canvas' ? <ListBullets size={14} aria-hidden /> : <GraphIcon size={14} aria-hidden />}
            {view === 'canvas' ? 'List view' : 'Canvas view'}
          </button>
        ) : null}
      </div>

      {allNodes.length > budget ? (
        <div role="status" className="flex items-center gap-3 border-b border-line-1 px-3 py-2 text-caption text-fg-2">
          <span>
            {overBudget
              ? `Showing ${formatNumber(budget)} of ${formatNumber(allNodes.length)} nodes to keep the graph readable.`
              : `Showing all ${formatNumber(allNodes.length)} nodes.`}
          </span>
          <button type="button" className="underline" onClick={() => setOverBudget((v) => !v)}>
            {overBudget ? 'Show all' : `Back to ${formatNumber(budget)}`}
          </button>
        </div>
      ) : null}

      {nodes.length === 0 ? (
        <div className="flex flex-1 items-center justify-center p-8">{empty ??<p className="text-small text-fg-3">No nodes yet.</p>}</div>
      ) : view === 'list' ? (
        <div className="relative min-h-0 flex-1 overflow-y-auto p-3" data-testid="graph-list">
          {groups.map(({ kind, group, nodes: list }) => (
            <section key={kind.key} className="mb-4">
              <h3 className="eyebrow mb-1 flex items-center gap-2">
                <ShapeIcon shape={kind.shape} color={palColor(group)} />
                {kind.name} · <span className="font-mono tabular">{list.length}</span>
              </h3>
              <ul className="flex flex-col">
                {list.map((n) => (
                  <li key={n.id}>
                    <button
                      type="button"
                      onClick={() => onSelect?.(n)}
                      aria-current={n.id === selectedId ? 'true' : undefined}
                      className={cx(
                        'flex w-full items-center gap-2 rounded-sm px-2 py-1 text-left text-small',
                        n.id === selectedId || highlightSet.has(n.id) ? 'bg-ink-2 text-fg-1' : 'text-fg-2 hover:bg-ink-2',
                        (pathToTrace ?? []).includes(n.id) && 'text-accent',
                      )}
                    >
                      <span className="min-w-0 flex-1 truncate">{look.get(n.id)?.label ?? n.label}</span>
                      {n.count && n.count > 1 ? <span className="font-mono text-caption text-fg-3 tabular">{formatNumber(n.count)}</span> : null}
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      ) : (
        <div ref={wrapRef} className="relative min-h-0 flex-1 overflow-hidden">
          <canvas
            ref={canvasRef}
            tabIndex={0}
            role="img"
            aria-label={`${label}. ${nodes.length} nodes. Use arrow keys to move along links, Enter to inspect, plus and minus to zoom, or open the list view.`}
            aria-describedby={liveId}
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onPointerLeave={() => setHover(null)}
            onDoubleClick={(e) => {
              const node = hitTest(localPoint(e), nodes, positions, viewRef.current, anchorId, columns?.radius)
              if (node) onExpand?.(node)
            }}
            onKeyDown={onKeyDown}
            className="absolute inset-0 size-full cursor-grab touch-none active:cursor-grabbing"
            style={{ width: size.width || '100%', height: size.height || '100%' }}
          />
          <p id={liveId} className="sr-only" aria-live="polite">
            {focused ? `${look.get(focused.id)?.kind.name ?? focused.type} ${look.get(focused.id)?.label ?? focused.label}, ${focusedDegree} links.` : ''}
          </p>
          {hover ? (
            <div
              role="tooltip"
              className="pointer-events-none absolute z-10 max-w-xs rounded-md border border-line-2 bg-ink-2 px-3 py-2 shadow-overlay"
              style={{ left: Math.min(hover.x + 12, size.width - 240), top: hover.y + 12 }}
            >
              <p className="eyebrow">{look.get(hover.node.id)?.kind.name ?? hover.node.type}</p>
              {isCluster(hover.node) ? (
                <p className="text-small text-fg-1">
                  A group of {clusterLabel(hover.node)}.{onModeChange ? ' Switch to Expanded to see each one.' : ''}
                </p>
              ) : (
                <p className="text-small text-fg-1">{hover.node.label}</p>
              )}
              {onExpand ? <p className="mt-1 text-caption text-fg-3">Double-click to expand.</p> : null}
            </div>
          ) : null}
          {quoteCards.map((c) => (
            <figure
              key={c.id}
              data-testid="trace-quote"
              className="fade-in pointer-events-none absolute z-10 w-64 rounded-md border border-accent/60 bg-ink-2 px-3 py-2 shadow-overlay"
              style={{ left: c.left, top: c.top }}
            >
              <blockquote className="display line-clamp-3 text-small text-fg-1">“{c.q.quote}”</blockquote>
              <figcaption className="mt-1 flex items-center gap-1.5 text-caption text-fg-3">
                {c.q.brand ? <BrandMark name={c.q.brand} size={10} decorative /> : null}
                {c.q.source}
                {c.q.author ? <span>· {c.q.author}</span> : null}
              </figcaption>
            </figure>
          ))}
          {!ready ? <div className="absolute inset-0 flex items-center justify-center text-caption text-fg-3">Laying out the graph…</div> : null}
        </div>
      )}

      {showLegend && nodes.length > 0 ? (
        // At most two rows: sources and links, then shapes (behind a "Shapes" toggle when there are many).
        <div className="flex flex-col gap-0.5 border-t border-line-1 px-3 py-1.5 text-caption text-fg-2" aria-label="Legend" role="group" data-testid="graph-legend">
          <div className="flex flex-wrap items-baseline gap-x-6 gap-y-1">
            <div className="flex items-baseline gap-3">
              <span className="w-12 shrink-0 font-medium text-fg-3">Source</span>
              <ul className="flex flex-wrap items-center gap-x-4 gap-y-1" aria-label="Colour shows the source">
                {legendGroups.map((g) => (
                  <li key={g} className="inline-flex items-center gap-1.5" data-legend-group={g} title={g === 'core' ? CORE_HINT : undefined}>
                    <span aria-hidden className="inline-block size-2.5 rounded-full" style={{ background: palColor(g) }} />
                    {g === 'core' ? "Core (Actron's records)" : GROUP_LABEL[g]}
                  </li>
                ))}
              </ul>
            </div>
            <LinkLegend hasInferred={hasInferred} hasPath={Boolean(pathToTrace)} hint={hoverHint} />
          </div>
          <div className="flex items-baseline gap-3">
            <span className="w-12 shrink-0 font-medium text-fg-3">Type</span>
            {typeOverview ? (
              <ul className="flex flex-wrap items-center gap-x-4 gap-y-1" aria-label="Shape shows the kind of type">
                {legendKinds.map((k) => (
                  <li key={k.shape} className="inline-flex items-center gap-1.5" data-legend-shape={k.shape} title={k.names.join(', ')}>
                    <ShapeIcon shape={k.shape} color="var(--text-2)" />
                    {SHAPE_FAMILY[k.shape]}
                  </li>
                ))}
              </ul>
            ) : (
              <ul className="flex flex-wrap items-center gap-x-4 gap-y-1" aria-label="Shape shows the type">
                {legendKinds.map((k) => (
                  <li key={k.shape} className="inline-flex items-center gap-1.5" data-legend-shape={k.shape} title={k.names.join(', ')}>
                    <ShapeIcon shape={k.shape} color="var(--text-2)" />
                    {shapeEntryLabel(k.names)}
                  </li>
                ))}
                {hasClusters ? (
                  <li className="inline-flex items-center gap-1.5">
                    <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden className="shrink-0">
                      <circle cx="7" cy="7" r="6.5" className="fill-fg-2" />
                      <text x="7" y="7.5" textAnchor="middle" dominantBaseline="middle" className="fill-ink-0 font-mono" fontSize="8" fontWeight="600">
                        9
                      </text>
                    </svg>
                    Group (count inside)
                  </li>
                ) : null}
              </ul>
            )}
          </div>
        </div>
      ) : null}
    </div>
  )
}

/**
 * The legend's link entries: explicit, inferred and, when a path is shown, the evidence path; then, when some nodes
 * go unlabelled, a quiet "Hover for names" at the end of the same row.
 */
function LinkLegend({ hasInferred, hasPath, hint }: { hasInferred: boolean; hasPath: boolean; hint: boolean }) {
  return (
    <div className="flex items-baseline gap-3">
      <span className="shrink-0 font-medium text-fg-3">Links</span>
      <ul className="flex flex-wrap items-center gap-x-4 gap-y-1">
        <li className="inline-flex items-center gap-1.5">
          <svg width="20" height="6" aria-hidden className="text-graph-link-focus">
            <line x1="0" y1="3" x2="20" y2="3" stroke="currentColor" strokeWidth="1.5" />
          </svg>
          Explicit
        </li>
        <li className="inline-flex items-center gap-1.5">
          <svg width="20" height="6" aria-hidden className="text-graph-link-focus">
            <line x1="0" y1="3" x2="20" y2="3" stroke="currentColor" strokeWidth="1.5" strokeDasharray="5 3" />
          </svg>
          Inferred{hasInferred ? null : <span className="text-fg-3"> (none here)</span>}
        </li>
        {hasPath ? (
          <li className="inline-flex items-center gap-1.5 text-accent">
            <svg width="20" height="6" aria-hidden>
              <line x1="0" y1="3" x2="20" y2="3" stroke="currentColor" strokeWidth="2.5" />
            </svg>
            Evidence path
          </li>
        ) : null}
        {hint ? (
          <li className="text-fg-3" data-testid="graph-hover-hint">
            Hover for names
          </li>
        ) : null}
      </ul>
    </div>
  )
}

export type { GraphLink }
