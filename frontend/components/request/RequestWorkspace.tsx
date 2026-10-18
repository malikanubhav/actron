'use client'
import dynamic from 'next/dynamic'
import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { CaretDown, CaretUp } from '@phosphor-icons/react/dist/ssr'
import type { EventEnvelope, Evidence, PersonRef, RequestDetail, Subgraph } from '@/lib/api/types'
import { useUi, readStrip, type RequestTab } from '@/lib/store'
import { isFinal } from '@/lib/states'
import { deriveHeadline, derivePurpose, latestBuild } from '@/lib/request-view'
import { shortRequestId } from '@/lib/format'
import { ScreenHeader } from '../core/ScreenHeader'
import { Pipeline } from '../core/Pipeline'
import { Chip, StateChip } from '../core/StateChip'
import { CostBadge, RelativeTime } from '../core/Formatting'
import { pipelineStatus } from '../home/RequestRow'
import { SystemMap, reduceSystemMap } from '../system/SystemMap'
import { ACTOR_LABEL } from '@/lib/events'
import { Timeline } from './Timeline'
import { Tabs, type TabItem } from '../ui/Tabs'
import { EvidencePanel } from './tabs/EvidencePanel'
import { QuestionsPanel } from './tabs/QuestionsPanel'
import { TicketPanel } from './tabs/TicketPanel'
import { PrPanel } from './tabs/PrPanel'
import { BuildTheatre } from './BuildTheatre'
import { sourceBrand } from './Evidence'
import { SkeletonCanvas } from '../states/Skeleton'
import type { TraceQuote } from '../graph/GraphCanvas'
import { endpoints } from '@/lib/api/endpoints'
import { cx } from '../ui/cx'

const GraphCanvas = dynamic(() => import('../graph/GraphCanvas').then((m) => m.GraphCanvas), {
  ssr: false,
  loading: () => <SkeletonCanvas />,
})

export const QUESTION_STEPS = [
  { n: 1, text: 'Investigate' },
  { n: 2, text: 'Answer' },
]

/** The answer under the headline. A long one is cut to five lines so the three columns keep their room; the toggle shows all of it. */
function AnswerBlock({ answer }: { answer: NonNullable<RequestDetail['answer']> }) {
  const [open, setOpen] = useState(false)
  const long = answer.text.length > 420
  return (
    <blockquote className="max-w-measure border-l-2 border-accent pl-4" data-testid="answer-block">
      <p className={cx('display text-lead text-fg-1', long && !open && 'line-clamp-5')}>{answer.text}</p>
      <p className="mt-1 flex items-center gap-3 text-caption text-fg-3">
        <span>
          {answer.citations.length} {answer.citations.length === 1 ? 'source' : 'sources'} · see Answer and sources
        </span>
        {long ? (
          <button type="button" aria-expanded={open} onClick={() => setOpen((v) => !v)} className="underline hover:text-fg-1">
            {open ? 'Show less' : 'Show full answer'}
          </button>
        ) : null}
      </p>
    </blockquote>
  )
}

export function tabsFor(detail: RequestDetail): TabItem<RequestTab>[] {
  // Questions to Actron (Q&A) have no ticket, build or pull request.
  if (detail.kind === 'question') return [{ id: 'evidence', label: 'Answer and sources' }]
  const open = isFinal(detail.state) ? 0 : detail.questions.filter((q) => !q.answer).length
  const count = detail.evidence.length
  const items: TabItem<RequestTab>[] = [
    {
      id: 'evidence',
      label: 'Evidence',
      badge: count ? <span className="font-mono text-caption font-normal text-fg-3 tabular">{count}</span> : undefined,
      hint: count ? `${count} ${count === 1 ? 'piece' : 'pieces'} of evidence` : undefined,
    },
  ]
  // The tab set stays the same for every request; the Questions panel says when there are none.
  items.push({
    id: 'questions',
    label: 'Questions',
    badge: open ? <span className="font-mono text-caption font-normal text-accent tabular">{open}</span> : undefined,
    hint: open ? `${open} ${open === 1 ? 'question' : 'questions'} waiting for an answer` : undefined,
  })
  items.push({ id: 'ticket', label: 'Ticket' }, { id: 'build', label: 'Build' }, { id: 'pr', label: 'PR' })
  return items
}

export function quotesForTrace(evidence: readonly Evidence[], path: readonly string[]): Record<string, TraceQuote> {
  const out: Record<string, TraceQuote> = {}
  const onPath = new Set(path)
  for (const e of evidence) {
    if (!e.quote || !onPath.has(e.nodeId)) continue
    const { brand, name } = sourceBrand(e.source.type)
    out[e.nodeId] = { quote: e.quote, source: name, author: e.source.author, brand }
  }
  return out
}

export interface RequestWorkspaceProps {
  detail: RequestDetail
  events: readonly EventEnvelope[]
  subgraph: Subgraph | null
  me: PersonRef
  tab: RequestTab
  onTabChange: (tab: RequestTab) => void
  mode?: 'live' | 'replay'
  actions?: ReactNode
  banner?: ReactNode
  caption?: ReactNode
  /** Eyebrow override (replay pages). */
  eyebrow?: string
  headline?: string
  purpose?: ReactNode
  /** Bumped after the approve shortcut switched to the right tab; opens the approval confirmation. */
  approveSignal?: number
  /** Replays show a neutral chip such as "REPLAY · STEP 12 OF 55" instead of the live state. */
  replayLabel?: string
  onApproveHandled?: () => void
}

/** Header, system strip and the three columns of the Request page, shared by the live page and replays. */
export function RequestWorkspace({
  detail,
  events,
  subgraph,
  me,
  tab,
  onTabChange,
  mode = 'live',
  actions,
  banner,
  caption,
  eyebrow,
  headline,
  purpose,
  approveSignal = 0,
  replayLabel,
  onApproveHandled,
}: RequestWorkspaceProps) {
  const readOnly = mode === 'replay'
  const canvasMode = useUi((s) => s.canvasMode)
  const setCanvasMode = useUi((s) => s.setCanvasMode)
  const canvasView = useUi((s) => s.canvasView)
  const setCanvasView = useUi((s) => s.setCanvasView)
  const hover = useUi((s) => s.hoverNodeIds)
  const setHover = useUi((s) => s.setHover)
  const pinned = useUi((s) => s.pinnedNodeIds)
  const togglePinned = useUi((s) => s.togglePinned)
  const selected = useUi((s) => s.selectedNodeId)
  const setSelected = useUi((s) => s.setSelectedNode)
  const trace = useUi((s) => s.pathToTrace)
  const tracePath = useUi((s) => s.tracePath)
  const clearTrace = useUi((s) => s.clearTrace)
  const stripOpen = useUi((s) => s.systemStripOpen)
  const setStrip = useUi((s) => s.setSystemStripOpen)

  useEffect(() => {
    if (readStrip()) setStrip(true)
  }, [setStrip])
  const systemSteps = useMemo(() => reduceSystemMap(events).steps, [events])
  const lastStep = systemSteps[systemSteps.length - 1]
  // "Actron UI" is an internal actor name; to the person on this page it is simply Actron.
  const lastActor = lastStep ? (lastStep.step.active === 'ui' ? 'Actron' : ACTOR_LABEL[lastStep.step.active]) : ''

  // Leaving the request clears canvas selections.
  useEffect(
    () => () => {
      clearTrace()
      setHover([])
      setSelected(null)
    },
    [detail.id, clearTrace, setHover, setSelected],
  )

  const items = tabsFor(detail)
  const activeTab = items.some((i) => i.id === tab) ? tab : 'evidence'
  const highlight = useMemo(() => Array.from(new Set([...hover, ...pinned])), [hover, pinned])
  const build = latestBuild(detail)
  const anchorId = `actron:request:${detail.id}`

  // The top evidence item's path is drawn by default, until the user picks another or hides it.
  const [defaultHidden, setDefaultHidden] = useState(false)
  const defaultPath = useMemo(() => detail.evidence.find((e) => e.path.length > 1)?.path ?? null, [detail.evidence])
  const shownPath = trace?.path ?? (defaultHidden ? null : defaultPath)
  const quotes = useMemo(() => (shownPath ? quotesForTrace(detail.evidence, shownPath) : {}), [shownPath, detail.evidence])

  const onShowPath = (e: Evidence) => {
    if (trace?.evidenceId === e.evidenceId) {
      clearTrace()
      setDefaultHidden(true)
    } else {
      setCanvasMode('expanded')
      tracePath(e.evidenceId, e.path)
    }
  }

  return (
    <div className="flex flex-col gap-5" data-testid="request-workspace" data-state={detail.state}>
      <ScreenHeader
        size="md"
        eyebrow={eyebrow ?? `Request · ${detail.kind.charAt(0).toUpperCase()}${detail.kind.slice(1)}`}
        headline={headline ?? deriveHeadline(detail)}
        headlineKey={detail.state}
        purpose={purpose ?? derivePurpose(detail)}
        actions={
          <>
            {mode === 'replay' ? <Chip tone="idle" text={replayLabel ?? 'REPLAY'} /> : <StateChip state={detail.state} live />}
            {actions}
          </>
        }
        notice={
          <div className="flex flex-col gap-3">
          {detail.answer ? <AnswerBlock answer={detail.answer} /> : null}
          {/* The request itself, prominent under the situation headline, so requests with the same headline differ. */}
          <div className="flex flex-col gap-1" data-testid="request-quote">
            <p className="max-w-measure text-lead text-fg-1">“{detail.title}”</p>
            {/* Who started it, and the costs once there is something to count (replays reveal them at the end): one row. */}
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-caption text-fg-3">
              <span>
                <span className="font-mono tabular">{shortRequestId(detail.id)}</span> · started by {detail.requester.name} in{' '}
                {detail.source === 'slack' ? 'Slack' : 'Actron'} · <RelativeTime value={detail.createdAt} />
              </span>
              {detail.investigation && detail.investigation.tokens.input + detail.investigation.tokens.output > 0 ? (
                <span className="inline-flex items-center gap-2">
                  Investigation
                  <CostBadge tokens={detail.investigation.tokens} costUsd={detail.investigation.costUsd} />
                </span>
              ) : null}
              {build && build.tokens.input + build.tokens.output > 0 ? (
                <span className="inline-flex items-center gap-2">
                  Build
                  <CostBadge tokens={build.tokens} costUsd={build.costUsd} />
                </span>
              ) : null}
            </div>
          </div>
          </div>
        }
        pipeline={
          detail.kind === 'question' ? (
            <Pipeline steps={QUESTION_STEPS} current={detail.state === 'Done' ? 2 : 1} status={pipelineStatus(detail)} />
          ) : (
            <Pipeline current={detail.pipelineStep} status={pipelineStatus(detail)} />
          )
        }
      />
      {banner}

      <section aria-label="System map" className="rounded-lg border border-line-1">
        <div className="flex items-center gap-3 px-4 py-1.5">
          <span className="eyebrow shrink-0">Last step:</span>
          {/* Collapsed (the default) the strip is one line: who acted last and what it did. */}
          <p className="min-w-0 flex-1 truncate text-small text-fg-1" aria-live="polite" data-testid="system-line" title={lastStep ? `${lastActor} · ${lastStep.step.caption}` : undefined}>
            {lastStep ? (
              <>
                <span className="font-medium">{lastActor}</span>
                <span aria-hidden className="text-fg-3"> · </span>
                {lastStep.step.caption}
              </>
            ) : (
              <span className="text-fg-3">Waiting for activity.</span>
            )}
          </p>
          <button
            type="button"
            onClick={() => setStrip(!stripOpen)}
            aria-expanded={stripOpen}
            className="inline-flex shrink-0 items-center gap-1 rounded-sm px-2 py-1 text-caption font-medium text-fg-3 hover:bg-ink-2 hover:text-fg-1"
          >
            {stripOpen ? 'Hide system map' : 'Show system map'}
            {stripOpen ? <CaretUp size={12} aria-hidden /> : <CaretDown size={12} aria-hidden />}
          </button>
        </div>
        {stripOpen ? (
          <div className="border-t border-line-1 px-4 pb-2 pt-3">
            <SystemMap events={events} compact />
          </div>
        ) : null}
      </section>

      {caption}

      <div className="request-columns grid grid-cols-1 gap-gutter lg:grid-cols-12">
        <section aria-label="Timeline" className="flex max-h-[32rem] min-h-0 flex-col rounded-lg border border-line-1 lg:col-span-3 lg:max-h-none">
          <div className="flex flex-wrap items-baseline gap-x-3 border-b border-line-1 px-4 py-3">
            <span className="eyebrow">Timeline</span>
            <h2 className="display text-title-sm text-fg-1">What happened</h2>
          </div>
          <div className="relative min-h-0 flex-1 overflow-y-auto overscroll-contain px-2 py-2">
            <Timeline events={events} pinnedIds={pinned} onHighlight={setHover} onPin={togglePinned} />
          </div>
        </section>

        <section aria-label="Graph" className="flex h-96 min-h-0 flex-col overflow-hidden rounded-lg border border-line-1 lg:col-span-5 lg:h-auto">
          <div className="flex flex-wrap items-baseline gap-x-3 border-b border-line-1 px-4 py-3">
            <span className="eyebrow">Graph · the agent&apos;s path</span>
            <h2 className="display text-title-sm text-fg-1">{trace ? 'Evidence path' : 'From this request to the code'}</h2>
          </div>
          <GraphCanvas
            className="min-h-0 flex-1"
            graph={subgraph}
            mode={canvasMode}
            onModeChange={setCanvasMode}
            view={canvasView}
            onViewChange={setCanvasView}
            anchorId={anchorId}
            highlight={highlight}
            selectedId={selected}
            onSelect={(n) => setSelected(n?.id ?? null)}
            pathToTrace={shownPath}
            quotes={quotes}
            label="Request graph"
            empty={<p className="text-small text-fg-3">{detail.state === 'Investigating' ? 'Nodes appear as the agent reads the graph.' : 'No graph for this request.'}</p>}
          />
        </section>

        <section aria-label="Details" className="flex max-h-[32rem] min-h-0 flex-col rounded-lg border border-line-1 lg:col-span-4 lg:max-h-none">
          <Tabs items={items} value={activeTab} onChange={onTabChange} label="Request details" className="h-full">
            <div className={cx('relative h-full overflow-y-auto overscroll-contain p-4')}>
              {activeTab === 'evidence' ? <EvidencePanel detail={detail} tracingId={trace?.evidenceId ?? null} onShowPath={onShowPath} /> : null}
              {activeTab === 'questions' ? <QuestionsPanel detail={detail} me={me} readOnly={readOnly} /> : null}
              {activeTab === 'ticket' ? <TicketPanel detail={detail} me={me} approveSignal={approveSignal} onApproveHandled={onApproveHandled} readOnly={readOnly} /> : null}
              {activeTab === 'build' ? (
                <BuildTheatre build={build} events={events} onLoadLog={readOnly || !build ? undefined : () => endpoints.buildLog(detail.id, build.id)} />
              ) : null}
              {activeTab === 'pr' ? <PrPanel detail={detail} me={me} approveSignal={approveSignal} onApproveHandled={onApproveHandled} readOnly={readOnly} /> : null}
            </div>
          </Tabs>
        </section>
      </div>
    </div>
  )
}
