'use client'
import { useMemo, useState } from 'react'
import dynamic from 'next/dynamic'
import type { GraphStats, IngestionStatus, NodeGroup } from '@/lib/api/types'
import { formatNumber } from '@/lib/format'
import { CountTicker } from '../core/CountTicker'
import { PanelLabelTitle } from '../core/PanelLabelTitle'
import { EmptyState } from '../states/States'
import { SkeletonCanvas } from '../states/Skeleton'
import { GROUP_LABEL, GROUP_TOKEN } from '../graph/model'
import { countsByGroup, memoryGraph } from './memory-graph'

const GraphCanvas = dynamic(() => import('../graph/GraphCanvas').then((m) => m.GraphCanvas), {
  ssr: false,
  loading: () => <SkeletonCanvas />,
})

const GROUP_ORDER: NodeGroup[] = ['code', 'github', 'slack', 'linear', 'core']

export function LinkingProgress({ linking }: { linking: IngestionStatus['linking'] | undefined }) {
  const rows: [string, number, string][] = [
    ['References resolved', linking?.referencesResolved ?? 0, 'Mentions of tickets, PRs and code that now point at their node.'],
    ['Decisions found', linking?.decisions ?? 0, 'Decisions read from Slack, reviews and tickets.'],
    ['Identities matched', linking?.identities ?? 0, 'People matched across GitHub, Slack and Linear.'],
    ['Waiting for a source', linking?.pending ?? 0, 'References that resolve when the source they point to is connected.'],
    ['Links kept', linking?.linksKept ?? 0, 'Model-made links at or above the keep threshold.'],
    ['Links dropped', linking?.linksDropped ?? 0, 'Model-made links below the threshold, kept out of memory.'],
  ]
  return (
    <section aria-labelledby="linking-title" className="flex flex-col gap-4" data-testid="linking-progress">
      <PanelLabelTitle label="Linking" title="How sources join up" id="linking-title" as="h3" />
      <dl className="grid grid-cols-3 gap-px overflow-hidden rounded-md border border-line-1 bg-line-1">
        {rows.map(([label, value, help]) => (
          <div key={label} className="flex flex-col gap-1 bg-ink-0 px-4 py-3" title={help}>
            <dt className="eyebrow">{label}</dt>
            <dd>
              <CountTicker value={value} label={label} className="text-title-sm text-fg-1" />
            </dd>
          </div>
        ))}
      </dl>
    </section>
  )
}

/** Right side of Connect: the memory graph filling as data arrives, its counts and linking progress. */
export function MemoryPanel({
  stats,
  ingestion,
  loading,
  hasConnections,
}: {
  stats: GraphStats | undefined
  ingestion: IngestionStatus | undefined
  loading: boolean
  hasConnections: boolean
}) {
  const graph = useMemo(() => memoryGraph(stats), [stats])
  const groups = countsByGroup(stats)
  const [view, setView] = useState<'canvas' | 'list'>('canvas')
  const totals = ingestion?.totals ?? { nodes: stats?.nodes ?? 0, links: stats?.links ?? 0 }
  return (
    <div className="flex flex-col gap-8">
      <section aria-labelledby="memory-title" className="flex flex-col gap-4">
        <PanelLabelTitle
          label="Memory graph"
          title="What Actron has read so far"
          id="memory-title"
          aside={
            <span className="text-caption text-fg-3" data-testid="memory-totals">
              <span className="font-mono tabular text-fg-2">{formatNumber(totals.nodes)}</span> nodes ·{' '}
              <span className="font-mono tabular text-fg-2">{formatNumber(totals.links)}</span> links
            </span>
          }
        />
        {/* Sized so the whole panel, legend included, fits above the status bar at 1440×900. */}
        <div className="h-[max(24rem,calc(100dvh-25rem))] overflow-hidden rounded-lg border border-line-1">
          {loading ? (
            <SkeletonCanvas />
          ) : graph.nodes.length === 0 ? (
            <div className="flex h-full items-center justify-center p-8">
              <EmptyState
                glyph="Graph"
                title={hasConnections ? 'The first items are on their way.' : 'Memory is empty.'}
                body={
                  hasConnections
                    ? 'Node types appear here as the backfill reads them, grouped by source.'
                    : 'Connect the repository first. Its code, history and pull requests become the first nodes here.'
                }
              />
            </div>
          ) : (
            <GraphCanvas
              graph={graph}
              showModeToggle={false}
              typeOverview
              view={view}
              onViewChange={setView}
              label="Memory graph by node type"
              className="h-full"
            />
          )}
        </div>
        <ul className="grid grid-cols-5 gap-px overflow-hidden rounded-md border border-line-1 bg-line-1" aria-label="Nodes by source" data-testid="count-strip">
          {GROUP_ORDER.map((g) => (
            <li key={g} className="flex flex-col gap-1 bg-ink-0 px-3 py-2">
              <span className="flex items-center gap-1.5 text-caption font-medium text-fg-3">
                <span aria-hidden className="inline-block size-2 rounded-full" style={{ background: `var(${GROUP_TOKEN[g]})` }} />
                {GROUP_LABEL[g]}
              </span>
              <CountTicker value={groups[g]} label={`${GROUP_LABEL[g]} nodes`} className="text-lead text-fg-1" />
            </li>
          ))}
        </ul>
      </section>
      <LinkingProgress linking={ingestion?.linking} />
    </div>
  )
}
