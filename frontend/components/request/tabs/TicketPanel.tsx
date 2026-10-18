'use client'
import { useState } from 'react'
import type { PersonRef, RequestDetail } from '@/lib/api/types'
import { currentRevision, ticketApprovalState } from '@/lib/request-view'
import { useApprove, useReviseTicket } from '@/lib/hooks/mutations'
import { ApiError, reasonText } from '@/lib/api'
import { useUi } from '@/lib/store'
import { ApprovalCard } from '../ApprovalCard'
import { TicketView } from '../TicketView'
import { EmptyState } from '../../states/States'

export function TicketPanel({ detail, me, approveSignal, onApproveHandled, readOnly = false }: { detail: RequestDetail; me: PersonRef; approveSignal: number; onApproveHandled?: () => void; readOnly?: boolean }) {
  const revise = useReviseTicket(detail.id)
  const approve = useApprove(detail.id, me)
  const [error, setError] = useState<string | null>(null)
  const setSelected = useUi((s) => s.setSelectedNode)
  const setHover = useUi((s) => s.setHover)
  const rev = currentRevision(detail)
  if (!rev || !detail.currentRevision) {
    return (
      <EmptyState
        glyph="Ticket"
        title="No ticket yet."
        body={detail.state === 'Needs your input' ? 'Answer the questions first; Actron writes the ticket right after.' : 'Actron writes the ticket after the investigation.'}
      />
    )
  }
  const { approvedN } = ticketApprovalState(detail)
  const accepted = detail.approvals.filter((a) => a.kind === 'ticket' && a.status === 'accepted')
  const last = accepted[accepted.length - 1] ?? null
  return (
    <div className="flex flex-col gap-5" data-testid="ticket-panel">
      <ApprovalCard
        kind="ticket"
        current={{ n: detail.currentRevision.n, value: detail.currentRevision.hash }}
        approval={last ? { ...last, n: approvedN ?? undefined } : null}
        canApprove={!readOnly && detail.allowedActions.includes('approve_ticket')}
        pending={approve.isPending}
        error={error}
        openSignal={approveSignal}
        onSignalHandled={onApproveHandled}
        onApprove={
          readOnly
            ? undefined
            : (target) => {
                setError(null)
                approve.run({ kind: 'ticket', target }).catch((e: unknown) => {
                  if (e instanceof ApiError && e.isConflict) setError(reasonText(e))
                })
              }
        }
      />
      <TicketView
        revision={rev}
        revisions={detail.revisions}
        evidence={detail.evidence}
        canEdit={!readOnly && detail.allowedActions.includes('edit_ticket')}
        fromTemplate={Boolean(detail.investigation?.stub) && rev.createdBy.toLowerCase() === 'actron' ? (approvedN === detail.currentRevision.n ? 'approved' : 'pending') : false}
        saving={revise.isPending}
        onEdit={(content) => revise.run({ content })}
        onSelectNode={(id) => {
          setSelected(id)
          setHover([id])
        }}
      />
    </div>
  )
}
