'use client'
import dynamic from 'next/dynamic'
import { useDeferredValue, useEffect, useMemo, useState } from 'react'
import { usePathname, useRouter, useSearchParams } from 'next/navigation'
import { useQuery } from '@tanstack/react-query'
import { MagnifyingGlass } from '@phosphor-icons/react/dist/ssr'
import type { GraphNode, NodeGroup, Subgraph } from '@/lib/api/types'
import { endpoints } from '@/lib/api/endpoints'
import { qk } from '@/lib/query-keys'
import { useGraphStats } from '@/lib/hooks/queries'
import { useUi } from '@/lib/store'
import { filterSubgraph, mergeSubgraphs } from '@/lib/subgraph'
import { formatNumber } from '@/lib/format'
import { idTail } from '@/lib/events'
import { reasonText } from '@/lib/api'
import { ScreenHeader } from '../core/ScreenHeader'
import { PageFrame } from '../shell/PageFrame'
import { EmptyState, ErrorState } from '../states/States'
import { SkeletonCanvas } from '../states/Skeleton'
import { NodeInspector, type QuickQuery } from './NodeInspector'
import { CORE_HINT, GROUP_LABEL, GROUP_TOKEN, groupOf, groupResults, mostConnected, plainTypeName, resultContext } from './model'
import { cx } from '../ui/cx'

const GraphCanvas = dynamic(() => import('./GraphCanvas').then((m) => m.GraphCanvas), { ssr: false, loading: () => <SkeletonCanvas /> })

const GROUPS: NodeGroup[] = ['code', 'github', 'slack', 'linear', 'core']
export const NODE_BUDGET = 300

export function explorerHeadline(stats: { nodeTypes: number; nodes: number; links: number } | undefined): string {
  if (!stats) return 'Your memory, as a graph.'
  if (stats.nodes === 0) return 'The graph is empty. Connect a source to fill it.'
  return `${formatNumber(stats.nodeTypes)} node types, ${formatNumber(stats.nodes)} nodes, ${formatNumber(stats.links)} links.`
}

type QuickResult = { title: string; lines: { id?: string; text: string }[] }

function asLines(tool: QuickQuery, data: unknown): QuickResult['lines'] {
  if (!Array.isArray(data)) return []
  return data.slice(0, 20).map((row) => {
    const r = (row ?? {}) as Record<string, unknown>
    if (tool === 'owners') return { text: `${String(r.name ?? '')} · ${(Array.isArray(r.basis) ? r.basis : []).join(', ')}` }
    if (tool === 'decisions_for') return { id: String(r.decisionId ?? ''), text: `${String(r.statement ?? '')} (${String(r.status ?? '')})` }
    return { id: String(r.id ?? ''), text: `${String(r.label ?? idTail(String(r.id ?? '')))}${r.depth ? ` · depth ${String(r.depth)}` : ''}` }
  })
}

/** Graph explorer (PROMPT 8.8 E): search, filters, focused subgraph within a node budget, inspector with provenance. */
export function GraphExplorer() {
  const search = useSearchParams()
  const router = useRouter()
  const pathname = usePathname()
  const [query, setQuery] = useState('')
  const deferred = useDeferredValue(query.trim())
  const [graph, setGraph] = useState<Subgraph | null>(null)
  const [focus, setFocus] = useState<string | null>(search?.get('node') ?? null)
  const [previous, setPrevious] = useState<string | null>(null)
  const [types, setTypes] = useState<Set<string>>(new Set())
  const [groups, setGroups] = useState<Set<string>>(new Set())
  const [trace, setTrace] = useState<string[] | null>(null)
  const [highlight, setHighlight] = useState<string[]>([])
  const [quick, setQuick] = useState<QuickResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const view = useUi((s) => s.canvasView)
  const setView = useUi((s) => s.setCanvasView)
  const stats = useGraphStats()
  const results = useQuery({
    queryKey: qk.graphSearch(deferred, [...types].join(',')),
    queryFn: () => endpoints.search(deferred, [...types].join(',') || undefined, 20),
    enabled: deferred.length >= 2,
  })
  const grouped = useMemo(() => groupResults(results.data?.results ?? []), [results.data])
  // Before a search: the most connected nodes of the workspace sample, so the canvas starts with something real.
  const sample = useQuery({
    queryKey: ['graph-sample', 3000],
    queryFn: () => endpoints.sample(3000),
    enabled: graph === null && stats.data?.nodes !== 0,
    staleTime: 300_000,
  })
  const start = useMemo(() => mostConnected(sample.data), [sample.data])
  const sourceCounts = useMemo(() => {
    const out: Record<NodeGroup, number> = { code: 0, github: 0, slack: 0, linear: 0, core: 0 }
    for (const t of stats.data?.byType ?? []) out[groupOf(t)] += t.count
    return out
  }, [stats.data])
  const notConnected =stats.data ? GROUPS.filter((g) => g !== 'core' && sourceCounts[g] === 0) : []

  const open = async (id: string, merge = false) => {
    setError(null)
    setPrevious(focus)
    setFocus(id)
    const params = new URLSearchParams(search?.toString() ?? '')
    params.set('node', id)
    router.replace(`${pathname}?${params.toString()}`, { scroll: false })
    try {
      const sub = await endpoints.neighbours(id, undefined, 60)
      setGraph((g) => (merge ? mergeSubgraphs(g, sub) : sub))
    } catch (e) {
      setError(reasonText(e))
    }
  }

  useEffect(() => {
    const initial = search?.get('node')
    if (!initial) return
    let cancelled = false
    endpoints
      .neighbours(initial, undefined, 60)
      .then((sub) => {
        if (!cancelled) setGraph((g) => g ?? sub)
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(reasonText(e))
      })
    return () => {
      cancelled = true
    }
    // Only on first load with a deep link.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const runQuick = async (tool: QuickQuery) => {
    if (!focus) return
    setError(null)
    try {
      if (tool === 'shortest_path' && previous) {
        const path = await endpoints.path(previous, focus)
        if (!path.found) {
          setQuick({ title: 'No path found within 6 hops.', lines: [] })
          return
        }
        setGraph((g) => mergeSubgraphs(g, { mode: 'expanded', nodes: path.nodes, links: path.links, truncated: false }))
        setTrace(path.nodes.map((n) => n.id))
        setQuick({ title: `Shortest path: ${path.nodes.length - 1} hops.`, lines: path.nodes.map((n) => ({ id: n.id, text: `${n.type} · ${n.label}` })) })
        return
      }
      const data = await endpoints.quick(tool, [focus], tool === 'callers' ? 3 : undefined)
      const lines = asLines(tool, data)
      setHighlight(lines.map((l) => l.id).filter((x): x is string => Boolean(x)))
      const title = { callers: 'Callers to depth 3', owners: 'Who knows this', decisions_for: 'Decisions on this', shortest_path: 'Shortest path' }[tool]
      setQuick({ title: `${title}: ${lines.length} found.`, lines })
    } catch (e) {
      setError(reasonText(e))
    }
  }

  const shown = useMemo(() => filterSubgraph(graph, types, groups), [graph, types, groups])
  const canvasGroups = useMemo(() => new Set(((shown && shown.nodes.length ? shown : start)?.nodes ?? []).map((n) => groupOf(n))), [shown, start])
  const availableTypes = useMemo(() => [...new Set((graph?.nodes ?? []).map((n) => n.type))].sort(), [graph])
  const toggle = (set: Set<string>, value: string, update: (s: Set<string>) => void) => {
    const next = new Set(set)
    if (next.has(value)) next.delete(value)
    else next.add(value)
    update(next)
  }

  return (
    <PageFrame>
      <ScreenHeader
        eyebrow="Graph"
        headline={explorerHeadline(stats.data)}
        purpose="Search anything. Expand neighbours. Every link shows where it came from."
      />
      <div className="grid grid-cols-12 gap-gutter">
        <aside className="col-span-3 flex flex-col gap-4" aria-label="Search and filters">
          <label className="flex h-10 items-center gap-2 rounded-md border border-line-2 bg-ink-1 px-3 focus-within:border-accent">
            <MagnifyingGlass size={16} aria-hidden className="text-fg-3" />
            <span className="sr-only">Search the graph</span>
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Functions, files, decisions, people…"
              className="h-full min-w-0 flex-1 bg-transparent text-small text-fg-1 outline-none placeholder:text-fg-3"
              data-testid="graph-search"
            />
          </label>
          <fieldset className="flex flex-col gap-1.5">
            <legend className="eyebrow mb-1">Source</legend>
            <div className="flex flex-nowrap gap-1">
              {GROUPS.map((g) => {
                const empty = stats.data ? sourceCounts[g] === 0 : false
                const on = groups.has(g)
                // Without a filter, a chip looks lit only when its source is on the canvas now.
                const onCanvas = groups.size ? on : canvasGroups.has(g)
                return (
                  <button
                    key={g}
                    type="button"
                    aria-pressed={on}
                    disabled={empty}
                    title={empty ? 'Not connected' : g === 'core' ? CORE_HINT : onCanvas ? undefined : 'Nothing from this source on the canvas now'}
                    onClick={() => toggle(groups, g, setGroups)}
                    className={cx(
                      'inline-flex h-7 items-center gap-1.5 whitespace-nowrap rounded-sm border px-1.5 text-caption font-medium',
                      on ? 'border-fg-2 bg-ink-3 text-fg-1' : onCanvas ? 'border-line-2 text-fg-1 hover:border-fg-3' : 'border-line-1 text-fg-3 hover:text-fg-1',
                      'disabled:cursor-not-allowed disabled:border-line-1 disabled:bg-transparent disabled:text-fg-disabled',
                    )}
                  >
                    <span aria-hidden className={cx('inline-block size-2 rounded-full', (empty || !onCanvas) && 'opacity-40')} style={{ background: `var(${GROUP_TOKEN[g]})` }} />
                    {GROUP_LABEL[g]}
                  </button>
                )
              })}
            </div>
            {notConnected.length ? (
              <p className="text-caption text-fg-3" data-testid="sources-not-connected">
                {notConnected.map((g) => GROUP_LABEL[g]).join(' and ')} {notConnected.length === 1 ? 'is' : 'are'} not connected.
              </p>
            ) : null}
          </fieldset>
          {availableTypes.length ? (
            <fieldset className="flex flex-col gap-1.5">
              <legend className="eyebrow mb-1">Type</legend>
              <div className="flex flex-wrap gap-1.5">
                {availableTypes.map((t) => (
                  <button
                    key={t}
                    type="button"
                    aria-pressed={types.has(t)}
                    onClick={() => toggle(types, t, setTypes)}
                    title={t}
                    className={cx('h-7 rounded-sm border px-2 text-caption font-medium', types.has(t) ? 'border-fg-2 text-fg-1' : 'border-line-1 text-fg-3 hover:text-fg-1')}
                  >
                    {plainTypeName(t, 2)}
                  </button>
                ))}
              </div>
            </fieldset>
          ) : null}
          <section aria-label="Search results" className="flex flex-col gap-1">
            <h2 className="eyebrow">{deferred.length < 2 && start ? 'Start here' : 'Results'}</h2>
            {deferred.length < 2 ? (
              start ? (
                <>
                  <p className="text-caption text-fg-3">Type two or more characters to search, or open one of the most connected files.</p>
                  <ul className="flex flex-col" data-testid="graph-start-list">
                    {start.nodes.slice(0, 8).map((n) => (
                      <li key={n.id}>
                        <button type="button" onClick={() => void open(n.id)} className="flex w-full flex-col rounded-sm px-2 py-1.5 text-left hover:bg-ink-2" title={n.label}>
                          <span className="truncate text-small text-fg-1">{n.label.split('/').pop()}</span>
                          <span className="truncate text-caption text-fg-3">{n.label}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                </>
              ) : (
                <p className="text-caption text-fg-3">Type two or more characters.</p>
              )
            ) : results.isPending ? (
              <p className="text-caption text-fg-3">Searching…</p>
            ) : results.isError ? (
              <p className="text-caption text-state-conflict">{reasonText(results.error)}</p>
            ) : results.data.results.length === 0 ? (
              <p className="text-caption text-fg-3">No matches for “{deferred}”.</p>
            ) : (
              <div className="flex flex-col gap-3" data-testid="graph-results">
                {grouped.map((g) => (
                  <section key={g.type} aria-label={g.name}>
                    <h3 className="mb-0.5 px-2 text-caption font-medium text-fg-3">
                      {g.name} · <span className="font-mono tabular">{g.items.length}</span>
                    </h3>
                    <ul className="flex flex-col">
                      {g.items.map((r) => {
                        const context = resultContext(r.id)
                        return (
                          <li key={r.id}>
                            <button
                              type="button"
                              onClick={() => void open(r.id)}
                              title={r.label}
                              className={cx('flex w-full flex-col rounded-sm px-2 py-1.5 text-left hover:bg-ink-2', focus === r.id && 'bg-ink-2')}
                            >
                              <span className={cx('truncate text-small text-fg-1', r.type.startsWith('Code') && r.type !== 'CodeChunk' && 'font-mono')}>{r.label}</span>
                              {context ? <span className="truncate text-caption text-fg-3">{context}</span> : null}
                            </button>
                          </li>
                        )
                      })}
                    </ul>
                  </section>
                ))}
              </div>
            )}
          </section>
        </aside>

        <section aria-label="Graph" className="col-span-6 flex h-[70vh] min-h-96 flex-col overflow-hidden rounded-lg border border-line-1">
          {error ? <ErrorState title="The graph did not answer." body={error} className="px-4" /> : null}
          {shown && shown.nodes.length ? (
            <GraphCanvas
              className="min-h-0 flex-1"
              graph={shown}
              showModeToggle={false}
              anchorId={focus}
              selectedId={focus}
              highlight={highlight}
              pathToTrace={trace}
              onSelect={(n: GraphNode | null) => {
                if (n) {
                  setPrevious(focus)
                  setFocus(n.id)
                }
              }}
              onExpand={(n) => void open(n.id, true)}
              view={view}
              onViewChange={setView}
              budget={NODE_BUDGET}
              label="Graph explorer"
            />
          ) : !graph && start ? (
            <>
              <div className="flex items-baseline justify-between gap-4 border-b border-line-1 px-4 py-3">
                <p className="text-small text-fg-2">
                  The {start.nodes.length} most connected files and how they import each other. Click one to open it.
                </p>
              </div>
              <GraphCanvas
                className="min-h-0 flex-1"
                graph={start}
                showModeToggle={false}
                onSelect={(n: GraphNode | null) => {
                  if (n) void open(n.id)
                }}
                view={view}
                onViewChange={setView}
                label="Most connected files"
              />
            </>
          ) : (
            <div className="flex flex-1 items-center justify-center p-8">
              <EmptyState
                glyph="Search"
                title={stats.data?.nodes === 0 ? 'Nothing in memory yet.' : 'Search to start.'}
                body={stats.data?.nodes === 0 ? 'Connect a repository on the Connect screen; nodes appear here as they are read.' : 'Pick a result to see it with its neighbours. Double-click a node to expand it.'}
              />
            </div>
          )}
        </section>

        <aside className="relative col-span-3 flex min-h-0 flex-col gap-4 overflow-y-auto" aria-label="Inspector">
          {focus ? (
            <NodeInspector id={focus} onOpen={(id) => void open(id, true)} onQuick={(t) => void runQuick(t)} pathFrom={previous} />
          ) : (
            <div className="flex flex-col gap-2 rounded-lg border border-line-1 p-5" data-testid="inspector-empty">
              <h2 className="text-small font-medium text-fg-1">No node selected</h2>
              <p className="text-small text-fg-2">
                {start ? 'Click a file on the canvas or a search result' : 'Pick a search result'} to see what it is, where it came from and what it links to.
              </p>
            </div>
          )}
          {quick ? (
            <section aria-label="Query result" className="flex flex-col gap-2 rounded-md border border-line-1 p-3" data-testid="quick-result">
              <p className="text-small text-fg-1">{quick.title}</p>
              <ul className="flex flex-col gap-0.5">
                {quick.lines.map((l, i) => (
                  <li key={i} className="truncate text-caption text-fg-2">
                    {l.id ? (
                      <button type="button" className="hover:underline" onClick={() => void open(l.id as string, true)}>
                        {l.text}
                      </button>
                    ) : (
                      l.text
                    )}
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
        </aside>
      </div>
    </PageFrame>
  )
}
