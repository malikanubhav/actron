'use client'
import { useState } from 'react'
import type { ConnectionView, ConnectorDefinition } from '@/lib/api/types'
import { useDisconnect, useSyncNow } from '@/lib/hooks/mutations'
import { typeName } from '@/lib/type-names'
import { formatNumber } from '@/lib/format'
import { sentenceCase } from '@/lib/states'
import { StateChip, Chip } from '../core/StateChip'
import { CountTicker } from '../core/CountTicker'
import { RelativeTime } from '../core/Formatting'
import { PartialState } from '../states/States'
import { Button } from '../ui/Button'
import { Dialog } from '../ui/Dialog'
import { ConnectorForm, type OAuthReturn } from './ConnectorForm'
import { connectionAbout, connectionName, reasonSentence, syncState, workingBranch } from './form-logic'
import { hasGuide } from './SetupGuide'
import { useGuideStore } from './guide-store'

const STOPS: Record<string, string> = {
  github: 'Actron stops reading new code, pull requests and reviews from this repository, and cannot open pull requests.',
  code: 'Actron stops reading new code, pull requests and reviews from this repository, and cannot open pull requests.',
  slack: 'Actron stops reading new messages and stops posting in Slack. Approvals in Slack stop working.',
  linear: 'Actron stops reading new issues and stops creating tickets in Linear.',
  slack_export: 'Actron stops applying changes from this export.',
}

/** Up to six counts by type, largest first, in a fixed grid so ticking numbers never move the layout. */
export function topCounts(counts: Record<string, number>, max = 6): [string, number][] {
  return Object.entries(counts)
    .filter(([, n]) => n > 0)
    .sort((a, b) => b[1] - a[1])
    .slice(0, max)
}

export interface SourceCardProps {
  def: ConnectorDefinition
  /** The card's combined view: the worst state, used for the chip, Sync now and Disconnect. */
  connection: ConnectionView | undefined
  /** The connection rows behind the card. The repository card has two (code and GitHub API), shown apart. */
  rows?: readonly ConnectionView[]
  oauthReturn?: OAuthReturn | null
}

/**
 * Counts by type that never drop to nothing mid-sync: a new run starts with empty counts, so while it runs the card
 * keeps showing the last non-empty counts it saw for this connection. Kept in component state, never in module
 * state, so the server render never carries counts from another request.
 */
function useStableCounts(connection: ConnectionView): [string, number][] {
  const current = topCounts(connection.sync.counts)
  const [last, setLast] = useState<{ id: string; counts: [string, number][] } | null>(null)
  if (current.length && (last?.id !== connection.id || JSON.stringify(last.counts) !== JSON.stringify(current))) {
    setLast({ id: connection.id, counts: current })
  }
  if (current.length) return current
  return last?.id === connection.id ? last.counts : current
}

/** Counts, read rate, last sync and the partial reason for one connection row. */
function ConnectionDetails({ connection, name, showBranch }: { connection: ConnectionView; name: string; showBranch: boolean }) {
  const state = connection.sync.state
  const counts = useStableCounts(connection)
  const branch = showBranch ? workingBranch(connection) : null
  const synced = Boolean(connection.sync.lastSyncedAt)
  const reason = reasonSentence(connection.provider, connection.sync.reason, connection.sync.counts)
  const openGuide = useGuideStore((s) => s.setOpen)
  return (
    <div className="flex flex-col gap-4">
      {branch ? (
        <p className="text-caption text-fg-3" data-testid="working-branch">
          Branch · <code className="font-mono text-fg-1">{branch}</code>
        </p>
      ) : null}
      {counts.length ? (
        // Sync counts, not graph nodes: records read can merge into fewer nodes (66 GitHub users read, 61 in the graph).
        <div className="flex flex-col gap-2">
          <p className="text-caption text-fg-3">Read by the latest sync</p>
          <dl className="grid grid-cols-3 gap-x-4 gap-y-3" aria-label={`${name}: items read by the latest sync`}>
            {counts.map(([type, n]) => (
              <div key={type} className="flex min-w-0 flex-col gap-0.5">
                <dt className="truncate text-caption text-fg-3" title={type}>
                  {typeName(type, n)}
                </dt>
                <dd>
                  <CountTicker value={n} label={typeName(type, n)} className="text-lead text-fg-1" />
                </dd>
              </div>
            ))}
          </dl>
        </div>
      ) : (
        <p className="text-small text-fg-2">
          {synced ? 'A new sync is reading this source. Counts appear when it finishes.' : 'No items read yet. Counts appear as the backfill reads them.'}
        </p>
      )}
      <p className="flex flex-wrap gap-x-4 gap-y-1 text-caption text-fg-3">
        <span>
          <span className="tabular text-fg-2">{formatNumber(Math.round(connection.sync.perMinute))}</span> items a minute
        </span>
        <span>
          Last synced{' '}
          {connection.sync.lastSyncedAt ? (
            <RelativeTime value={connection.sync.lastSyncedAt} className="text-fg-2" />
          ) : (
            <span className="text-fg-2">not yet</span>
          )}
        </span>
      </p>
      {state === 'PARTIAL' || state === 'FAILED' ? (
        <PartialState
          title={state === 'FAILED' ? `${name} stopped syncing.` : `${name} read only part of its history.`}
          body={reason.text}
          action={
            reason.action === 'add-token' ? (
              <Button size="sm" onClick={() => openGuide('github')}>
                Add a GitHub token
              </Button>
            ) : undefined
          }
        />
      ) : null}
    </div>
  )
}

/** One of several rows in a card: its own name, what it reads, and its own state chip. */
function ConnectionRow({ connection, showBranch }: { connection: ConnectionView; showBranch: boolean }) {
  const name = connectionName(connection.provider)
  const about = connectionAbout(connection.provider)
  const state = connection.sync.state
  return (
    <li className="flex flex-col gap-4 rounded-md border border-line-1 p-4" data-testid={`connection-row-${connection.provider}`} data-state={state}>
      <div className="flex items-start justify-between gap-4">
        <div className="flex min-w-0 flex-col gap-0.5">
          <h3 className="text-body font-medium text-fg-1">{name}</h3>
          {about ? <p className="text-caption text-fg-3">{about}</p> : null}
        </div>
        <StateChip state={state} live />
      </div>
      <ConnectionDetails connection={connection} name={name} showBranch={showBranch} />
    </li>
  )
}

/** One source on the Connect screen (spec C, C2 SourceCard; PROMPT 8.8 B). */
export function SourceCard({ def, connection, rows = [], oauthReturn = null }: SourceCardProps) {
  const state = syncState(connection)
  const connected = state !== 'NOT CONNECTED'
  const sync = useSyncNow()
  const disconnect = useDisconnect()
  const [confirming, setConfirming] = useState(false)
  const openGuide = useGuideStore((s) => s.setOpen)
  const optional = def.provider === 'slack_export'
  const split = rows.length > 1
  // A connected repository card holds local git and the GitHub API, so it is named for the repository, not GitHub.
  const isRepo = def.provider === 'github' && connected
  const repoValue = connection?.config.repository
  const repository = isRepo && typeof repoValue === 'string' && repoValue ? repoValue : null
  const title = isRepo ? 'Repository' : def.title
  // The connector label repeats the title for most sources ("GitHub" over "GitHub"); show it only when it adds something.
  const eyebrow = def.label && def.label.toLowerCase() !== def.title.toLowerCase() ? sentenceCase(def.label) : null

  return (
    <article
      data-testid={`source-card-${def.provider}`}
      data-state={state}
      aria-labelledby={`source-${def.provider}-title`}
      className="flex flex-col gap-4 border-b border-line-1 pb-8 last:border-b-0"
    >
      <header className="flex items-start justify-between gap-4">
        <div className="flex min-w-0 flex-col gap-1">
          {eyebrow ? <span className="eyebrow">{eyebrow}</span> : null}
          <h2 id={`source-${def.provider}-title`} className="display text-title-sm text-fg-1">
            {title}
            {repository ? <span className="font-mono text-small text-fg-2"> · {repository}</span> : null}
          </h2>
        </div>
        {/* A split card shows one chip per row instead, so a state is never named twice. */}
        {optional && !connected ? <Chip tone="idle" text="Optional" /> : split && connected ? null : <StateChip state={state} live />}
      </header>

      {connected && connection ? (
        <div className="flex flex-col gap-4">
          {connection.secretLast4 ? (
            <p className="text-caption text-fg-3" data-testid="secret-last4">
              Secret ending in <span className="font-mono text-fg-2">••••{connection.secretLast4}</span>
            </p>
          ) : null}

          {split ? (
            <ul className="flex flex-col gap-3" aria-label={`${title} connections`}>
              {rows.map((row) => (
                <ConnectionRow key={row.id} connection={row} showBranch={row.provider === 'code'} />
              ))}
            </ul>
          ) : (
            <ConnectionDetails connection={connection} name={title} showBranch />
          )}

          <div className="flex flex-wrap items-center gap-x-2 gap-y-3">
            <Button
              size="sm"
              variant={state === 'FAILED' ? 'primary' : 'secondary'}
              loading={sync.isPending}
              loadingText="Starting"
              disabled={state === 'BACKFILLING' || state === 'SYNCING'}
              onClick={() => void sync.run({ connectionId: connection.id }).catch(() => undefined)}
            >
              {state === 'FAILED' ? 'Retry sync' : 'Sync now'}
            </Button>
            {/* Connected: the guide stays one click away, without a setup count competing with the sync state. */}
            {hasGuide(def.provider) ? (
              <Button size="sm" variant="ghost" onClick={() => openGuide(def.provider)}>
                Set up step by step
              </Button>
            ) : null}
            <span className="flex-1" />
            <Button size="sm" variant="ghost" className="text-state-conflict hover:text-state-conflict" onClick={() => setConfirming(true)}>
              Disconnect
            </Button>
          </div>

          <Dialog
            open={confirming}
            onClose={() => setConfirming(false)}
            label="Disconnect"
            title={`Disconnect ${repository ?? title}?`}
            footer={
              <>
                <Button variant="ghost" onClick={() => setConfirming(false)}>
                  Keep connected
                </Button>
                <Button
                  variant="danger"
                  loading={disconnect.isPending}
                  loadingText="Disconnecting"
                  onClick={() => {
                    void disconnect
                      .run({ connectionId: connection.id })
                      .catch(() => undefined)
                      .finally(() => setConfirming(false))
                  }}
                >
                  Disconnect {repository ? 'repository' : title}
                </Button>
              </>
            }
          >
            <p className="text-small text-fg-1">{STOPS[connection.provider] ?? 'Actron stops reading this source.'}</p>
            <p className="mt-2 text-small text-fg-2">What is already in memory stays in the graph. You can connect again at any time.</p>
          </Dialog>
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          {hasGuide(def.provider) ? (
            <div className="flex items-center justify-between gap-3 rounded-md border border-line-1 px-4 py-3">
              <p className="text-small text-fg-2">New to this? The guide walks through every click and checks each step.</p>
              <Button size="sm" onClick={() => openGuide(def.provider)}>
                Set up step by step
              </Button>
            </div>
          ) : null}
          <ConnectorForm def={def} oauthReturn={oauthReturn} />
        </div>
      )}
    </article>
  )
}
