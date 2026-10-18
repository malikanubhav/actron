'use client'
import { useRef, useState } from 'react'
import type { Approval } from '@/lib/api/types'
import { shortHash, shortSha } from '@/lib/format'
import { surfaceName } from '@/lib/events'
import { Glyph } from '../glyphs/Glyph'
import { Button } from '../ui/Button'
import { Dialog } from '../ui/Dialog'
import { RelativeTime } from '../core/Formatting'
import { cx } from '../ui/cx'

export interface ApprovalTarget {
  /** Revision number for tickets, PR number for pull requests. */
  n: number
  /** SHA-256 of the revision, or the PR head SHA. */
  value: string
}

export interface ApprovalCardProps {
  kind: 'ticket' | 'pr'
  /** What would be approved now (the current revision or head). */
  current: ApprovalTarget
  /** The latest accepted approval, if any, and the revision or head it was for. */
  approval?: (Approval & { n?: number }) | null
  onApprove?: (target: string) => void
  canApprove?: boolean
  pending?: boolean
  /** The server's reason after a refusal (409), shown inline. */
  error?: string | null
  /** Changes when the `a` shortcut or the palette asks to approve; opens the confirmation. */
  openSignal?: number
  /** Called when a confirmation opened by the signal closes, so the parent can clear the pending request. */
  onSignalHandled?: () => void
}

export function isStale(approval: Pick<Approval, 'target'> | null | undefined, current: ApprovalTarget): boolean {
  return Boolean(approval && approval.target !== current.value)
}

/** Label words in the UI font; the revision, number and hash in mono. */
function TargetLabel({ kind, t }: { kind: 'ticket' | 'pr'; t: ApprovalTarget }) {
  return kind === 'ticket' ? (
    <>
      Revision <span className="font-mono tabular">v{t.n}</span> · SHA-256 <span className="font-mono tabular">{shortHash(t.value)}</span>
    </>
  ) : (
    <>
      PR <span className="font-mono tabular">#{t.n}</span> · head <span className="font-mono tabular">{shortSha(t.value)}</span>
    </>
  )
}

/**
 * Approval bound to an exact revision hash or head SHA (spec C, C2; C-AC-11). Shows the stale state when the
 * approved target differs from the current one, confirms with a dialog naming the target, and shows 409 reasons.
 */
export function ApprovalCard({ kind, current, approval, onApprove, canApprove = true, pending = false, error, openSignal = 0, onSignalHandled }: ApprovalCardProps) {
  const [opened, setOpened] = useState(false)
  // The signal seen when the card mounted or last closed; a newer one (the `a` shortcut) opens the confirmation.
  // A signal above zero is a pending request to confirm; it is cleared by the parent once handled.
  const [handledSignal, setHandledSignal] = useState(0)
  const confirmRef = useRef<HTMLButtonElement>(null)
  const stale = isStale(approval, current)
  const approvedHere = approval && !stale
  const eligible = !approvedHere && canApprove && Boolean(onApprove)
  const confirming = opened || (eligible && openSignal > 0 && openSignal !== handledSignal)
  const setConfirming = (open: boolean) => {
    setOpened(open)
    if (!open) {
      setHandledSignal(openSignal)
      if (openSignal > 0) onSignalHandled?.()
    }
  }
  const noun = kind === 'ticket' ? `ticket v${current.n}` : `PR #${current.n}`

  return (
    <section
      data-testid="approval-card"
      data-state={approvedHere ? 'approved' : stale ? 'stale' : 'open'}
      aria-label={kind === 'ticket' ? 'Ticket approval' : 'Pull request approval'}
      className={cx(
        'flex flex-col gap-3 rounded-md border p-4',
        approvedHere ? 'border-state-ok/40' : stale ? 'border-state-possible/50' : 'border-accent/50',
      )}
    >
      <div className="flex items-center gap-2">
        <span className={approvedHere ? 'text-state-ok' : stale ? 'text-state-possible' : 'text-accent'}>
          <Glyph name="Approval" size={16} />
        </span>
        <span className="text-caption text-fg-2" data-testid="approval-target">
          <TargetLabel kind={kind} t={current} />
        </span>
      </div>

      {approvedHere ? (
        <p className="text-small text-fg-1">
          Approved by {approval.by.name} in {surfaceName(approval.surface)} <RelativeTime value={approval.at} />.
        </p>
      ) : stale ? (
        <p className="text-small text-fg-1" data-testid="stale-text">
          {kind === 'ticket'
            ? `You approved v${approval?.n ?? '?'}. This is v${current.n}. Approve again to build.`
            : `You approved head ${shortSha(approval?.target ?? '')}. The PR now has head ${shortSha(current.value)}. Approve again to finish.`}
        </p>
      ) : (
        <p className="text-small text-fg-2">
          {kind === 'ticket'
            ? 'Approving starts the build for exactly this revision. Any later edit needs a new approval.'
            : 'Approving records this exact head as reviewed and writes the change back to memory.'}
        </p>
      )}

      {error ? (
        <p role="alert" className="rounded-sm border border-state-conflict/40 px-3 py-2 text-small text-state-conflict">
          {error}
        </p>
      ) : null}

      {!approvedHere && onApprove ? (
        <div className="flex items-center gap-2">
          <Button
            variant="secondary"
            onClick={() => setConfirming(true)}
            disabled={!canApprove}
            loading={pending}
            loadingText="Approving"
            shortcut="A"
          >
            {`Approve ${noun}`}
          </Button>
          {!canApprove ? <span className="text-caption text-fg-3">Not available in this state.</span> : null}
        </div>
      ) : null}

      <Dialog
        open={confirming}
        onClose={() => setConfirming(false)}
        label="Confirm approval"
        title={`Approve ${noun}?`}
        initialFocus={confirmRef}
        footer={
          <>
            <Button variant="ghost" onClick={() => setConfirming(false)}>
              Keep reviewing
            </Button>
            <Button
              ref={confirmRef}
              variant="primary"
              onClick={() => {
                setConfirming(false)
                onApprove?.(current.value)
              }}
            >
              Approve {noun}
            </Button>
          </>
        }
      >
        <p className="text-small text-fg-2">
          {kind === 'ticket' ? 'You are approving exactly this revision:' : 'You are approving exactly this head commit:'}
        </p>
        <p className="mt-2 rounded-sm bg-ink-3 px-3 py-2 font-mono text-caption text-fg-1 break-all" data-testid="confirm-target">
          {kind === 'ticket' ? `v${current.n} · ${current.value}` : `#${current.n} · ${current.value}`}
        </p>
        <p className="mt-3 text-small text-fg-2">
          {kind === 'ticket' ? 'Pi starts building in a container right after.' : 'Actron records the change in memory right after.'}
        </p>
      </Dialog>
    </section>
  )
}
