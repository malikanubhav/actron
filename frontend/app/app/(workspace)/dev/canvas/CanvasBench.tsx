'use client'
import { useMemo } from 'react'
import type { NodeGroup, Subgraph } from '@/lib/api/types'
import { GraphCanvas } from '@/components/graph/GraphCanvas'
import { PageFrame } from '@/components/shell/PageFrame'

const GROUPS: NodeGroup[] = ['code', 'github', 'slack', 'linear', 'core']

/** A deterministic synthetic graph (test harness only, never product data). */
export function benchGraph(nodes = 300, links = 600): Subgraph {
  let seed = 7
  const rand = () => {
    seed = (seed * 16807) % 2147483647
    return seed / 2147483647
  }
  const ns = Array.from({ length: nodes }, (_, i) => ({
    id: `bench:${i}`,
    type: ['CodeFunction', 'GithubPullRequest', 'SlackMessage', 'LinearIssue', 'Decision'][i % 5] as string,
    label: `node ${i}`,
    group: GROUPS[i % 5] as NodeGroup,
  }))
  const ls = Array.from({ length: links }, (_, i) => {
    const from = i < nodes - 1 ? i + 1 : Math.floor(rand() * nodes)
    const to = i < nodes - 1 ? Math.floor(rand() * (i + 1)) : Math.floor(rand() * nodes)
    return { from: `bench:${from}`, to: `bench:${to}`, type: 'LINK', method: i % 3 === 0 ? 'inferred' : 'explicit', confidence: 0.4 + rand() * 0.6 }
  })
  return { mode: 'expanded', nodes: ns, links: ls, truncated: false }
}

export function CanvasBench() {
  const graph = useMemo(() => benchGraph(), [])
  return (
    <PageFrame wide>
      <p className="eyebrow">Dev · Canvas benchmark · Synthetic graph</p>
      <div className="h-[70vh] rounded-lg border border-line-1" data-testid="bench">
        <GraphCanvas className="h-full" graph={graph} anchorId="bench:0" label="Benchmark graph" showModeToggle={false} />
      </div>
    </PageFrame>
  )
}
