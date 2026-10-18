'use client'
import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import type { EventEnvelope, RequestDetail } from '@/lib/api/types'
import { endpoints } from '@/lib/api/endpoints'
import { qk } from '@/lib/query-keys'
import { detailAt, stepDelay, subgraphFromFindings } from '@/lib/replay'
import { eventSentence } from '@/lib/events'
import { clockTime } from '@/lib/format'
import { reasonText, ApiError } from '@/lib/api'
import { useSubgraph, NOBODY } from '@/lib/hooks/queries'
import { useUi, type RequestTab } from '@/lib/store'
import { RequestWorkspace } from '../request/RequestWorkspace'
import { ReplayControls } from './ReplayControls'
import { PageFrame } from '../shell/PageFrame'
import { ErrorState, EmptyState } from '../states/States'
import { SkeletonHeader } from '../states/Skeleton'
import { LinkButton } from '../ui/Button'

/** Which tab fits the event being played, so the right panel follows the story. */
export function tabForEvent(event: EventEnvelope | undefined): RequestTab | null {
  if (!event) return null
  if (event.type === 'evidence.found' || event.type === 'investigation.completed') return 'evidence'
  if (event.type === 'question.asked' || event.type === 'answer.received') return 'questions'
  if (event.type.startsWith('ticket.') || event.type === 'approval.recorded') return 'ticket'
  if (event.type.startsWith('build.') || event.type === 'tests.result' || event.type === 'handoff.created') return 'build'
  if (event.type.startsWith('pr.') || event.type === 'writeback.done') return 'pr'
  return null
}

export function ReplayPlayer({ request, events, isPublic = false }: { request: RequestDetail; events: EventEnvelope[]; isPublic?: boolean }) {
  const [position, setPosition] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(1)
  const [manualTab, setTab] = useState<RequestTab | null>(null)
  const canvasMode = useUi((s) => s.canvasMode)
  const sub = useSubgraph(isPublic ? '' : request.id, canvasMode)
  const subgraph = isPublic ? subgraphFromFindings(request.findings) : (sub.data ?? null)
  const shown = useMemo(() => events.slice(0, position), [events, position])
  const detail = useMemo(() => detailAt(request, events, position), [request, events, position])
  const current = events[position - 1]
  // The right panel follows the story unless the viewer picked a tab; pressing play hands control back.
  const autoTab = useMemo(() => {
    for (let i = position - 1; i >= 0; i--) {
      const t = tabForEvent(events[i])
      if (t) return t
    }
    return 'evidence' as RequestTab
  }, [events, position])
  const tab = manualTab ?? autoTab

  useEffect(() => {
    if (!playing || position >= events.length) return
    const t = setTimeout(() => {
      const next = Math.min(events.length, position + 1)
      setPosition(next)
      if (next >= events.length) setPlaying(false)
    }, stepDelay(events, position, speed))
    return () => clearTimeout(t)
  }, [playing, position, speed, events])

  return (
    <RequestWorkspace
      mode="replay"
      detail={detail}
      events={shown}
      subgraph={subgraph}
      me={NOBODY}
      tab={tab}
      onTabChange={setTab}
      eyebrow={`Replay · ${request.kind.charAt(0).toUpperCase()}${request.kind.slice(1)}`}
      replayLabel={position >= events.length ? 'REPLAY · DONE' : `REPLAY · STEP ${position} OF ${events.length}`}
      headline={`Replay: ${request.title}.`}
      purpose="Watch how Actron handled this request, step by step."
      caption={
        <div className="flex flex-col gap-3 rounded-lg border border-line-1 px-4 py-3" data-testid="replay-caption">
          <ReplayControls
            playing={playing}
            speed={speed}
            position={position}
            total={events.length}
            onPlayPause={() => {
              if (!playing && position >= events.length) setPosition(0)
              if (!playing) setTab(null)
              setPlaying((p) => !p)
            }}
            onStep={(d) => {
              setPlaying(false)
              setPosition((p) => Math.max(0, Math.min(events.length, p + d)))
            }}
            onSpeed={setSpeed}
            onSeek={(p) => {
              setPlaying(false)
              setPosition(p)
            }}
          />
          <p aria-live="polite" className="flex items-baseline gap-3 text-body text-fg-1">
            {current ? (
              <>
                <span className="font-mono text-eyebrow text-fg-3 tabular">{clockTime(current.at)}</span>
                <span data-testid="replay-sentence">{eventSentence(current)}</span>
              </>
            ) : (
              <span className="text-fg-2">Press play to start. Each step is a real recorded event.</span>
            )}
          </p>
        </div>
      }
    />
  )
}

export function ReplayScreen({ id, isPublic = false }: { id: string; isPublic?: boolean }) {
  const replay = useQuery({
    queryKey: [...qk.replay(id), isPublic],
    queryFn: () => (isPublic ? endpoints.publicReplay(id) : endpoints.replay(id)),
    staleTime: Infinity,
  })
  useEffect(() => {
    if (replay.data) document.title = `Replay: ${replay.data.request.title} · Actron`
  }, [replay.data])
  if (replay.isPending)
    return (
      <PageFrame wide>
        <SkeletonHeader />
      </PageFrame>
    )
  if (replay.isError) {
    const e = replay.error
    const notFinished = e instanceof ApiError && e.code === 'not_finished'
    const notFound = e instanceof ApiError && e.status === 404
    return (
      <PageFrame>
        {notFound ? (
          <EmptyState size="page" glyph="Search" title="This replay is not available." body="The request does not exist, or its workspace does not allow public replays." />
        ) : (
          <ErrorState
            size="page"
            title={notFinished ? 'This request is still running.' : 'The replay could not be loaded.'}
            body={reasonText(e)}
            action={!isPublic ? <LinkButton href={`/app/requests/${id}`}>Open the live request</LinkButton> : undefined}
          />
        )}
      </PageFrame>
    )
  }
  return (
    <PageFrame wide dense fill={!isPublic}>
      <ReplayPlayer request={replay.data.request} events={replay.data.events} isPublic={isPublic} />
    </PageFrame>
  )
}
