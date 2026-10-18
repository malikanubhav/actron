'use client'
import { useRef } from 'react'
import type { NotificationItem, RequestSummary } from '@/lib/api/types'
import { useConnections, useNotifications, useRequests } from '@/lib/hooks/queries'
import { useListKeys } from '@/lib/hooks/useListKeys'
import { reasonText } from '@/lib/api'
import { ScreenHeader } from '../core/ScreenHeader'
import { StateGroup } from './StateGroup'
import { GROUP_COPY, rowFact, waitingOnYouCount } from './ask'
import { OnboardingChecklist, onboardingSteps } from '../core/OnboardingChecklist'
import { EmptyState, ErrorState } from '../states/States'
import { SkeletonRows } from '../states/Skeleton'
import { PageFrame } from '../shell/PageFrame'
import { RequestComposer } from './RequestComposer'
import { RequestRow } from './RequestRow'
import { LinkButton, Button } from '../ui/Button'
import { Glyph } from '../glyphs/Glyph'

/**
 * "Need you" counts the requests whose current ask is addressed to you (the same count and words as the Inbox);
 * `others` are requests waiting on someone else.
 */
export function homeHeadline(needsYou: number, building: number, running: number, total: number, others = 0): string {
  if (total === 0) return 'No requests yet.'
  const parts: string[] = []
  if (needsYou > 0) parts.push(`${needsYou} ${needsYou === 1 ? 'request needs' : 'requests need'} you.`)
  if (others > 0) parts.push(`${others}${needsYou > 0 ? ' more' : ''} ${others === 1 ? 'waits' : 'wait'} on someone else.`)
  if (building > 0) parts.push(`${building} ${building === 1 ? 'is' : 'are'} building.`)
  else if (running > 0) parts.push(`${running} ${running === 1 ? 'is' : 'are'} running.`)
  if (parts.length === 0) return 'Nothing needs you right now.'
  return parts.join(' ')
}

function Rows({ requests, notifications }: { requests: RequestSummary[]; notifications: readonly NotificationItem[] | null }) {
  return (
    <ul className="flex flex-col">
      {requests.map((r) => (
        <RequestRow key={r.id} request={r} fact={rowFact(r, notifications ?? [], notifications !== null)} />
      ))}
    </ul>
  )
}

/** Home (PROMPT 8.8 C): what needs you, what is running, what is done; start a request. */
export function HomeScreen() {
  const listRef = useRef<HTMLDivElement>(null)
  useListKeys(listRef)
  const needs = useRequests('needs_you')
  const running = useRequests('running')
  const done = useRequests('done', 20)
  const connections = useConnections()
  const notifications = useNotifications()

  const needsList = [...(needs.data?.requests ?? [])].sort((a, b) => a.createdAt.localeCompare(b.createdAt))
  const runningList = running.data?.requests ?? []
  const doneList = done.data?.requests ?? []
  const counts = needs.data?.counts ?? running.data?.counts ?? done.data?.counts
  const total = counts ? counts.needsYou + counts.running + counts.done : needsList.length + runningList.length + doneList.length
  const building = runningList.filter((r) => r.state === 'Building' || r.state === 'Changes requested').length
  const loading = needs.isPending || running.isPending || done.isPending
  const error = needs.error ?? running.error ?? done.error
  const conns = connections.data?.connections ?? []
  const repoConnected = conns.some((c) => (c.provider === 'github' || c.provider === 'code') && c.status === 'connected')
  const steps = onboardingSteps(conns, total > 0)
  const finished = doneList.find((r) => r.state === 'Done')
  const slackConnected = conns.some((c) => (c.provider === 'slack' || c.provider === 'slack_export') && c.status === 'connected')
  const firstRun = connections.isSuccess && !repoConnected && !loading && !error && total === 0

  const notes = notifications.data?.notifications ?? []
  const rowNotes = notifications.isSuccess ? notes : null
  const waitingList = needsList.filter((r) => r.state !== 'Needs attention')
  const stoppedList = needsList.filter((r) => r.state === 'Needs attention')
  const needsCount = counts?.needsYou ?? needsList.length
  // Without the inbox, every request that needs someone is counted as yours, as before.
  const mine = notifications.isSuccess ? waitingOnYouCount(notes, needsList) : needsCount
  const headline =
    loading || notifications.isPending
      ? 'Loading your requests…'
      : error
        ? 'Actron cannot reach its server.'
        : homeHeadline(mine, building, counts?.running ?? runningList.length, total, Math.max(0, needsCount - mine))

  return (
    <PageFrame>
      <ScreenHeader
        eyebrow="Requests"
        headline={headline}
        purpose={
          error ? (
            'Requests and answers come back as soon as the connection returns.'
          ) : firstRun ? (
            'Connect a repository to start asking.'
          ) : slackConnected ? (
            <>
              Ask in Slack with <code className="font-mono text-fg-1">/actron</code> or start here.
            </>
          ) : (
            'Start a request here. Slack requests work once Slack is connected.'
          )
        }
        actions={
          finished ? (
            <LinkButton href={`/app/requests/${finished.id}/replay`} variant="secondary" icon={<Glyph name="ShortestPath" size={16} />}>
              Watch a replay
            </LinkButton>
          ) : null
        }
      />

      {firstRun ? (
        <OnboardingChecklist
          steps={steps}
          body="Actron needs your code and its history before it can check a request. Connect the repository your team merges into; Slack and Linear add the decisions behind it."
          action={
            <LinkButton href="/app/connect" variant="primary">
              Connect a repository
            </LinkButton>
          }
        />
      ) : (
        <>
          <RequestComposer
            disabledReason={
              error ? 'Actron cannot reach its server right now. Your text is kept; try again in a moment.' : connections.isSuccess && !repoConnected ? 'Connect a repository first so Actron has code to check against.' : null
            }
          />
          {connections.isSuccess && steps.some((s) => !s.done) ? <OnboardingChecklist steps={steps} compact={total > 0} /> : null}
        </>
      )}

      {error ? (
        <ErrorState
          title="Requests could not be loaded."
          body={reasonText(error)}
          action={
            <Button
              onClick={() => {
                void needs.refetch()
                void running.refetch()
                void done.refetch()
              }}
            >
              Retry
            </Button>
          }
        />
      ) : firstRun ? null : !loading && total === 0 ? (
        repoConnected ? (
          <EmptyState
            size="page"
            glyph="Request"
            title="No requests yet."
            body="Ask for a change above, or type /actron followed by what you need in Slack. Actron checks your history first, then asks before it builds."
          />
        ) : (
          <EmptyState
            size="page"
            glyph="Connect"
            title="Connect a repository, then ask."
            body="Actron needs your code and its history before it can check a request. Connect the repository your team merges into; Slack and Linear add the decisions behind it."
            action={<LinkButton href="/app/connect" variant="primary">Connect a repository</LinkButton>}
          />
        )
      ) : (
        <div ref={listRef} className="flex flex-col gap-8">
          {loading ? (
            <SkeletonRows rows={3} />
          ) : (
            <>
              <StateGroup
                testId="group-needs-you"
                tone="needs_you"
                title={GROUP_COPY.waiting.title}
                count={waitingList.length}
                description={GROUP_COPY.waiting.description}
                empty={GROUP_COPY.waiting.empty}
              >
                <Rows requests={waitingList} notifications={rowNotes} />
              </StateGroup>
              <StateGroup
                testId="group-stopped"
                tone="conflict"
                title={GROUP_COPY.stopped.title}
                count={stoppedList.length}
                description={GROUP_COPY.stopped.description}
                empty={GROUP_COPY.stopped.empty}
              >
                <Rows requests={stoppedList} notifications={rowNotes} />
              </StateGroup>
              <StateGroup
                testId="group-running"
                tone="running"
                title="In progress"
                count={runningList.length}
                description="Actron is investigating, writing the ticket or building. Nothing to do yet."
                empty="Nothing is running."
              >
                <Rows requests={runningList} notifications={rowNotes} />
              </StateGroup>
              <StateGroup
                testId="group-done"
                tone="ok"
                title="Finished recently"
                count={doneList.length}
                description="Done or cancelled, newest first."
                empty="Finished requests appear here."
              >
                <Rows requests={doneList} notifications={rowNotes} />
              </StateGroup>
            </>
          )}
        </div>
      )}
    </PageFrame>
  )
}
