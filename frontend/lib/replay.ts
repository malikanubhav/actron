/** Replay helpers (spec C, C5.3): rebuild the request view from its recorded events, and step timing. */
import type { EventEnvelope, RequestDetail, Subgraph, SharedQuery, NodeGroup } from './api/types'
import { applyEvents } from './request-view'

/** The request as it was before its first event: everything that events fill in is empty. */
export function baseDetail(final: RequestDetail): RequestDetail {
  return {
    ...final,
    state: 'Investigating',
    label: null,
    pipelineStep: 1,
    needsYou: false,
    lastEvent: null,
    evidence: [],
    questions: [],
    currentRevision: null,
    approvals: [],
    builds: [],
    pr: null,
    // Findings and costs appear when the replay reaches the end, not before the first step.
    findings: null,
    investigation: null,
    outcome: null,
    answer: null,
    allowedActions: [],
    updatedAt: '',
  }
}

/** The view after the first `position` events. At the end it is the recorded final request (C-AC-24). */
export function detailAt(final: RequestDetail, events: readonly EventEnvelope[], position: number): RequestDetail {
  if (position >= events.length) return { ...final, allowedActions: [] }
  return applyEvents(baseDetail(final), events.slice(0, position))
}

/** Delay before the next event: the real gap, clamped so long waits stay watchable, divided by speed. */
export function stepDelay(events: readonly EventEnvelope[], position: number, speed: number): number {
  const prev = events[position - 1]
  const next = events[position]
  if (!prev || !next) return 600 / speed
  const gap = Date.parse(next.at) - Date.parse(prev.at)
  const clamped = Math.min(1400, Math.max(260, Number.isFinite(gap) ? gap : 600))
  return clamped / speed
}

const groupFor = (type: string): NodeGroup => {
  const t = type.toLowerCase()
  if (t.startsWith('code')) return 'code'
  if (t.startsWith('github') || t.startsWith('git')) return 'github'
  if (t.startsWith('slack')) return 'slack'
  if (t.startsWith('linear')) return 'linear'
  return 'core'
}

/** Public replays carry only the findings graph; turn it into a subgraph for the canvas. */
export function subgraphFromFindings(findings: SharedQuery | null): Subgraph | null {
  if (!findings) return null
  return {
    mode: 'expanded',
    truncated: false,
    nodes: findings.graph.nodes.map((n) => ({ id: n.id, type: n.type, label: n.label, group: groupFor(n.type) })),
    links: findings.graph.edges.map((e) => ({ from: e.from, to: e.to, type: e.type, method: null, confidence: null })),
  }
}
