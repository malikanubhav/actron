'use client'
import { useState } from 'react'
import dynamic from 'next/dynamic'
import { useQuery } from '@tanstack/react-query'
import { ArrowSquareOut } from '@phosphor-icons/react/dist/ssr'
import type { Approval, PersonRef, RequestDetail } from '@/lib/api/types'
import { endpoints } from '@/lib/api/endpoints'
import { qk } from '@/lib/query-keys'
import { readBuildReport } from '@/lib/build-report'
import { latestBuild } from '@/lib/request-view'
import { useApprove, useFeedback, useLifecycle } from '@/lib/hooks/mutations'
import { ApiError, reasonText } from '@/lib/api'
import { shortSha } from '@/lib/format'
import { sentenceCase } from '@/lib/states'
import { ApprovalCard } from '../ApprovalCard'
import { TestList } from '../TestList'
import { ConstraintsChecklist } from '../ConstraintsChecklist'
import { EmptyState } from '../../states/States'
import { Button } from '../../ui/Button'
import { Dialog } from '../../ui/Dialog'
import { BrandMark } from '../../brand/BrandMark'
import { SkeletonText } from '../../states/Skeleton'

const DiffViewer = dynamic(() => import('../DiffViewer').then((m) => m.DiffViewer), {
  ssr: false,
  loading: () => <SkeletonText lines={6} />,
})

export function PrPanel({ detail, me, approveSignal, onApproveHandled, readOnly = false }: { detail: RequestDetail; me: PersonRef; approveSignal: number; onApproveHandled?: () => void; readOnly?: boolean }) {
  const pr = detail.pr
  const diff = useQuery({ queryKey: qk.prDiff(detail.id), queryFn: () => endpoints.prDiff(detail.id), enabled: Boolean(pr) && !readOnly })
  const approve = useApprove(detail.id, me)
  const feedback = useFeedback(detail.id)
  const close = useLifecycle(detail.id, 'close-pr')
  const [text, setText] = useState('')
  const [closing, setClosing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (!pr) {
    return <EmptyState glyph="PullRequest" title="No pull request yet." body="The pull request opens on your fork after the build passes." />
  }
  const report = readBuildReport(latestBuild(detail)?.report)
  const accepted = detail.approvals.filter((a: Approval) => a.kind === 'pr' && a.status === 'accepted')
  const last = accepted[accepted.length - 1] ?? null
  const can = (a: RequestDetail['allowedActions'][number]) => !readOnly && detail.allowedActions.includes(a)

  return (
    <div className="flex flex-col gap-5" data-testid="pr-panel">
      <div className="flex items-center gap-2">
        <BrandMark name="github" size={16} />
        <a href={pr.url} target="_blank" rel="noreferrer noopener" className="display text-title-sm text-fg-1 underline decoration-line-2 underline-offset-4 hover:decoration-fg-2">
          PR #{pr.number}
        </a>
        <ArrowSquareOut size={14} aria-hidden className="text-fg-3" />
        <span className="flex-1" />
        <span className="text-caption text-fg-3">
          {sentenceCase(pr.state)} · head <span className="font-mono tabular">{shortSha(pr.headSha)}</span> · into <span className="font-mono">{pr.targetBranch}</span>
        </span>
      </div>

      <ApprovalCard
        kind="pr"
        current={{ n: pr.number, value: pr.headSha }}
        approval={last}
        canApprove={can('approve_pr')}
        pending={approve.isPending}
        error={error}
        openSignal={approveSignal}
        onSignalHandled={onApproveHandled}
        onApprove={
          readOnly
            ? undefined
            : (target) => {
                setError(null)
                approve.run({ kind: 'pr', target }).catch((e: unknown) => {
                  if (e instanceof ApiError && e.isConflict) setError(reasonText(e))
                })
              }
        }
      />

      <section className="flex flex-col gap-2" aria-label="Constraints">
        <h4 className="eyebrow">Constraints still hold</h4>
        <ConstraintsChecklist constraints={report.constraints} />
      </section>

      <section className="flex flex-col gap-2" aria-label="Tests on the head">
        <h4 className="eyebrow">
          Tests on head <span className="font-mono tabular">{shortSha(pr.headSha)}</span>
        </h4>
        <TestList
          results={report.tests}
          totals={latestBuild(detail) ? { passed: latestBuild(detail)!.testsPassed, failed: latestBuild(detail)!.testsFailed } : undefined}
        />
      </section>

      <section className="flex flex-col gap-2" aria-label="Diff">
        <h4 className="eyebrow">Diff</h4>
        {readOnly ? (
          <p className="text-small text-fg-3">The diff is on GitHub.</p>
        ) : diff.isPending ? (
          <SkeletonText lines={6} />
        ) : diff.isError ? (
          <p className="text-small text-state-conflict">{reasonText(diff.error)}</p>
        ) : (
          <DiffViewer files={diff.data.files} />
        )}
      </section>

      {can('pr_feedback') ? (
        <form
          className="flex flex-col gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            if (text.trim().length < 3) return
            void feedback.run({ text: text.trim(), headSha: pr.headSha }).then(() => setText(''))
          }}
        >
          <label htmlFor="pr-feedback" className="eyebrow">
            Request changes
          </label>
          <textarea
            id="pr-feedback"
            rows={3}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="What should change? Actron rebuilds on the same branch."
            className="w-full rounded-sm border border-line-2 bg-ink-1 px-3 py-2 text-small text-fg-1 focus-visible:border-accent"
          />
          <div className="flex items-center gap-2">
            <Button type="submit" disabled={text.trim().length < 3} loading={feedback.isPending} loadingText="Sending">
              Request changes
            </Button>
            {can('close_pr') ? (
              <Button variant="danger" onClick={() => setClosing(true)}>
                Close PR
              </Button>
            ) : null}
          </div>
        </form>
      ) : null}

      <Dialog
        open={closing}
        onClose={() => setClosing(false)}
        label="Close pull request"
        title={`Close PR #${pr.number}?`}
        footer={
          <>
            <Button variant="ghost" onClick={() => setClosing(false)}>
              Keep it open
            </Button>
            <Button
              variant="danger"
              loading={close.isPending}
              onClick={() => {
                void close.run({ reason: 'Closed from Actron' }).finally(() => setClosing(false))
              }}
            >
              Close PR #{pr.number}
            </Button>
          </>
        }
      >
        <p className="text-small text-fg-2">The pull request is closed on GitHub and the request is cancelled. The branch stays on your fork.</p>
      </Dialog>
    </div>
  )
}
