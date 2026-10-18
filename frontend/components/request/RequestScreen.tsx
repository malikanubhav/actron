'use client'
import { useEffect, useState } from 'react'
import { usePathname, useRouter, useSearchParams } from 'next/navigation'
import type { RequestDetail } from '@/lib/api/types'
import { useEvents, useMe, useRequest, useSubgraph, NOBODY } from '@/lib/hooks/queries'
import { useRequestStream } from '@/lib/hooks/useRequestStream'
import { useLifecycle } from '@/lib/hooks/mutations'
import { useUi, type RequestTab } from '@/lib/store'
import { latestBuild, primaryTab } from '@/lib/request-view'
import { ApiError, reasonText } from '@/lib/api'
import { isFinal } from '@/lib/states'
import { RequestWorkspace } from './RequestWorkspace'
import { ReconnectingBanner, OfflineBanner, ErrorState, EmptyState } from '../states/States'
import { SkeletonColumn, SkeletonHeader, SkeletonCanvas } from '../states/Skeleton'
import { PageFrame } from '../shell/PageFrame'
import { Button, LinkButton } from '../ui/Button'
import { Dialog } from '../ui/Dialog'
import { Glyph } from '../glyphs/Glyph'

const TABS: RequestTab[] = ['evidence', 'questions', 'ticket', 'build', 'pr']

export function parseTab(value: string | null): RequestTab | null {
  return value && (TABS as string[]).includes(value) ? (value as RequestTab) : null
}

/** What stops when a request is cancelled, named in the confirmation (PRD 13.6). */
export function cancelConsequence(detail: RequestDetail): string {
  switch (detail.state) {
    case 'Investigating':
      return 'The investigation stops. Nothing is written to Linear or GitHub.'
    case 'Building':
    case 'Changes requested':
      return 'The running build stops and its container is removed. No pull request is opened.'
    case 'PR ready for review':
      return 'The request is cancelled. The pull request stays open on GitHub until you close it.'
    default:
      return 'Actron stops working on this request. The ticket stays in Linear.'
  }
}

/**
 * Stop reasons that are a setup problem, not a ticket problem: the fix lives in Settings or Connect. The header
 * links there next to Retry, which stays the primary action.
 */
export const SETUP_FIX: Record<string, { label: string; href: string; purpose: string }> = {
  // Builds read the bot name and email from the server's environment, not from a saved setting.
  missing_identity: {
    label: 'How to set the bot identity',
    href: '/app/settings#bot-identity',
    purpose: 'Set the bot name and email for commits on the server, then retry. Settings shows how.',
  },
  missing_fork: { label: 'Add a fork', href: '/app/connect', purpose: 'Add a fork to push to in Connect, then retry.' },
  missing_branch: { label: 'Choose a branch', href: '/app/settings', purpose: 'Choose an existing working branch in Settings, then retry.' },
}

export function setupFixFor(detail: RequestDetail): (typeof SETUP_FIX)[string] | null {
  if (detail.state !== 'Needs attention') return null
  const reason = latestBuild(detail)?.stopReason
  return (reason && SETUP_FIX[reason]) || null
}

function LoadingRequest() {
  return (
    <PageFrame wide>
      <SkeletonHeader />
      <div className="request-columns grid grid-cols-12 gap-gutter">
        <div className="col-span-3 rounded-lg border border-line-1 p-4">
          <SkeletonColumn items={6} />
        </div>
        <div className="col-span-6">
          <SkeletonCanvas />
        </div>
        <div className="col-span-3 rounded-lg border border-line-1 p-4">
          <SkeletonColumn items={3} />
        </div>
      </div>
    </PageFrame>
  )
}

/** The hero screen (PROMPT 8.8 D): live data, stream, tabs with deep links, actions. */
export function RequestScreen({ id }: { id: string }) {
  const router = useRouter()
  const pathname = usePathname()
  const search = useSearchParams()
  const request = useRequest(id)
  const events = useEvents(id)
  const me = useMe()
  const canvasMode = useUi((s) => s.canvasMode)
  const subgraph = useSubgraph(id, canvasMode)
  const { status } = useRequestStream(id)
  const storedTab = useUi((s) => s.tabByRequest[id])
  const setTab = useUi((s) => s.setTab)
  const approveSignal = useUi((s) => s.approveSignal)
  const requestApprove = useUi((s) => s.requestApprove)
  const [localApprove, setLocalApprove] = useState(0)
  const [cancelling, setCancelling] = useState(false)
  const cancel = useLifecycle(id, 'cancel')
  const retry = useLifecycle(id, 'retry')
  const detail = request.data?.request

  const urlTab = parseTab(search?.get('tab') ?? null)
  const tab: RequestTab = urlTab ?? storedTab ?? (detail ? primaryTab(detail) : 'evidence')

  const changeTab = (next: RequestTab) => {
    setTab(id, next)
    const params = new URLSearchParams(search?.toString() ?? '')
    params.set('tab', next)
    router.replace(`${pathname}?${params.toString()}`, { scroll: false })
  }

  // `a` shortcut or palette: switch to the tab with the approval, then open its confirmation.
  const firstApprove = useState(approveSignal)[0]
  useEffect(() => {
    if (approveSignal === firstApprove || !detail) return
    const target: RequestTab | null = detail.allowedActions.includes('approve_ticket') ? 'ticket' : detail.allowedActions.includes('approve_pr') ? 'pr' : null
    if (!target) return
    changeTab(target)
    const t = setTimeout(() => setLocalApprove((n) => n + 1), 0)
    return () => clearTimeout(t)
    // changeTab is stable enough for this one-shot reaction.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [approveSignal])

  useEffect(() => {
    if (detail) document.title = `${detail.title} · Actron`
  }, [detail])

  if (request.isPending) return <LoadingRequest />
  if (request.isError || !detail) {
    const notFound = request.error instanceof ApiError && request.error.status === 404
    return (
      <PageFrame>
        {notFound ? (
          <EmptyState
            size="page"
            glyph="Search"
            title="This request isn’t in Actron’s memory."
            body="It may belong to another workspace, or the link is wrong."
            action={<LinkButton href="/app">Back to requests</LinkButton>}
          />
        ) : (
          <ErrorState size="page" title="The request could not be loaded." body={reasonText(request.error)} action={<Button onClick={() => void request.refetch()}>Retry</Button>} />
        )}
      </PageFrame>
    )
  }

  const can = (a: RequestDetail['allowedActions'][number]) => detail.allowedActions.includes(a)
  const fix = setupFixFor(detail)
  const editIsPrimary = !fix && can('edit_ticket') && detail.state === 'Needs attention'
  const banner =
    status === 'reconnecting' ? (
      <ReconnectingBanner />
    ) : status === 'offline' ? (
      <OfflineBanner action={<Button size="sm" onClick={() => window.location.reload()}>Reload</Button>} />
    ) : detail.state === 'Cancelled' ? (
      <div role="status" className="flex items-center gap-3 rounded-md border border-line-2 px-4 py-3 text-small text-fg-2" data-testid="cancelled-banner">
        <Glyph name="TestFail" size={16} />
        {detail.outcome === 'closed' ? 'The pull request was closed. The timeline below is the full record.' : 'This request was cancelled. The timeline below is the full record.'}
      </div>
    ) : null

  return (
    <PageFrame wide dense fill>
      <RequestWorkspace
        detail={detail}
        events={events.data ?? []}
        subgraph={subgraph.data ?? null}
        me={me.data?.user ?? NOBODY}
        tab={tab}
        onTabChange={changeTab}
        banner={banner}
        approveSignal={localApprove}
        onApproveHandled={() => setLocalApprove(0)}
        purpose={fix?.purpose}
        actions={
          <>
            {can('approve_ticket') && detail.currentRevision ? (
              <Button variant="primary" onClick={() => requestApprove()} data-testid="header-approve">
                Approve ticket v{detail.currentRevision.n}
              </Button>
            ) : null}
            {can('approve_pr') && detail.pr ? (
              <Button variant="primary" onClick={() => requestApprove()} data-testid="header-approve">
                Approve PR #{detail.pr.number}
              </Button>
            ) : null}
            {can('pr_feedback') && detail.pr ? (
              <Button
                variant="secondary"
                onClick={() => {
                  changeTab('pr')
                  setTimeout(() => document.getElementById('pr-feedback')?.focus(), 50)
                }}
              >
                Request changes
              </Button>
            ) : null}
            {can('answer') && detail.questions.some((q) => !q.answer) ? (
              <Button variant="secondary" onClick={() => changeTab('questions')}>
                Answer {detail.questions.filter((q) => !q.answer).length === 1 ? 'the question' : 'the questions'}
              </Button>
            ) : null}
            {detail.state === 'Done' && detail.pr ? (
              <LinkButton href={detail.pr.url} external variant="primary" icon={<Glyph name="PullRequest" size={16} />}>
                Open PR #{detail.pr.number}
              </LinkButton>
            ) : null}
            {fix ? (
              <LinkButton href={fix.href} variant="secondary" data-testid="header-setup-fix">
                {fix.label}
              </LinkButton>
            ) : null}
            {editIsPrimary ? (
              <Button variant="primary" onClick={() => changeTab('ticket')}>
                Edit ticket
              </Button>
            ) : null}
            {can('retry') ? (
              // For a setup stop Retry is the action that moves the request on; the fix link explains what to set first.
              <Button variant={editIsPrimary ? 'secondary' : 'primary'} loading={retry.isPending} onClick={() => void retry.run({})}>
                Retry
              </Button>
            ) : null}
            {detail.state === 'Done' ? (
              <LinkButton href={`/app/requests/${id}/replay`} icon={<Glyph name="ShortestPath" size={16} />}>
                Replay
              </LinkButton>
            ) : null}
            {can('cancel') && !isFinal(detail.state) ? (
              <Button variant="ghost" onClick={() => setCancelling(true)}>
                Cancel
              </Button>
            ) : null}
          </>
        }
      />
      <Dialog
        open={cancelling}
        onClose={() => setCancelling(false)}
        label="Cancel request"
        title="Cancel this request?"
        footer={
          <>
            <Button variant="ghost" onClick={() => setCancelling(false)}>
              Keep it running
            </Button>
            <Button
              variant="danger"
              loading={cancel.isPending}
              onClick={() => {
                void cancel.run({ reason: 'Cancelled from Actron' }).finally(() => setCancelling(false))
              }}
            >
              Cancel request
            </Button>
          </>
        }
      >
        <p className="text-small text-fg-2">{cancelConsequence(detail)}</p>
      </Dialog>
    </PageFrame>
  )
}
