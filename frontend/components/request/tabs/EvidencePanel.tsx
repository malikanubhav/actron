'use client'
import type { Evidence, RequestDetail, SharedQuery } from '@/lib/api/types'
import { formatNumber, formatPercent, truncateMiddle } from '@/lib/format'
import { idTail } from '@/lib/events'
import { EvidenceCard, LabelBanner, sortEvidence } from '../Evidence'
import { EmptyState } from '../../states/States'
import { CostBadge } from '../../core/Formatting'
import { Button } from '../../ui/Button'
import { Glyph } from '../../glyphs/Glyph'

/** Graph queries return at most this many rows (backend MAX_ROWS); a count at the cap is a lower bound. */
export const LIST_CAP = 200

export function cappedCount(n: number): string {
  return n >= LIST_CAP ? `${formatNumber(LIST_CAP)}+` : formatNumber(n)
}

export function impactSummary(detail: RequestDetail) {
  const f = detail.findings
  if (!f) return null
  return {
    callers: f.impact.callers.length,
    tests: f.impact.tests.length,
    criticality: [...f.impact.criticality].sort((a, b) => b.percentile - a.percentile),
  }
}

/** Roles read straight from the graph; without a model there is no judgment to rate. */
const STRUCTURAL = new Set<Evidence['role']>(['impact', 'test', 'owner'])

type Decision = SharedQuery['decisions'][number]

/** The decision behind a conflict label: the most likely flagged one in the findings. */
export function conflictDecision(detail: RequestDetail): Decision | null {
  const flagged = (detail.findings?.decisions ?? []).filter((d) => d.conflict.label !== 'none')
  return [...flagged].sort((a, b) => b.conflict.probability - a.conflict.probability)[0] ?? null
}

/** Names the decision, or says plainly that none could be named. */
export function conflictSentence(decision: Decision | null, withoutModel: boolean, definite = false, approved = false): string {
  if (decision) return `Decision: “${truncateMiddle(decision.statement.replace(/[.\s]+$/, ''), 120)}”`
  const what = definite ? 'a conflict' : 'a possible conflict'
  const why = withoutModel ? 'could not name a decision without a model' : 'could not name the decision'
  // After approval the advice to check first is out of date; say what happened instead.
  const next = approved ? 'The ticket was approved with this flag open.' : 'Check the evidence below before you approve.'
  return `Actron flagged ${what} but ${why}. ${next}`
}

/** The evidence item for a decision, or a stand-in so its path can be traced. */
function decisionEvidence(detail: RequestDetail, decision: Decision): Evidence {
  return (
    detail.evidence.find((e) => e.nodeId === decision.id) ??
    ({ evidenceId: decision.id, nodeId: decision.id, path: decision.path } as unknown as Evidence)
  )
}

/** How the investigation ran, in plain words. */
export function investigationText(inv: NonNullable<RequestDetail['investigation']>): string {
  if (inv.stub) return 'Investigated without a model (no key set)'
  return inv.mode === 'agent' ? 'Investigated by the agent model' : 'Investigated with the standard graph checks'
}

export function EvidencePanel({
  detail,
  tracingId,
  onShowPath,
}: {
  detail: RequestDetail
  tracingId: string | null
  onShowPath: (e: Evidence) => void
}) {
  const items = sortEvidence(detail.evidence)
  const impact = impactSummary(detail)
  const withoutModel = Boolean(detail.investigation?.stub)
  const conflictLabel = detail.label === 'conflict' || detail.label === 'possible_conflict'
  const decision = conflictDecision(detail)
  return (
    <div className="flex flex-col gap-4" data-testid="evidence-panel">
      {detail.answer && detail.kind !== 'question' ? (
        <section className="flex flex-col gap-2 rounded-md border border-line-1 p-4">
          <span className="eyebrow">Answer</span>
          <p className="display text-lead text-fg-1">{detail.answer.text}</p>
        </section>
      ) : null}
      {detail.label ? (
        <LabelBanner
          label={detail.label}
          resolved={detail.state === 'Done' && conflictLabel}
          sentence={
            detail.label === 'nothing_found' && items.length === 0
              ? 'Nothing in your history touches this request.'
              : detail.state === 'Done' && conflictLabel
                ? 'Reviewed before approval: the ticket kept the earlier decision as a constraint.'
                : conflictLabel
                  ? conflictSentence(decision, withoutModel, detail.label === 'conflict', detail.pipelineStep >= 5)
                  : undefined
          }
          action={
            conflictLabel && decision ? (
              <>
                {decision.path.length > 1 ? (
                  <Button
                    size="sm"
                    variant={tracingId === decisionEvidence(detail, decision).evidenceId ? 'primary' : 'ghost'}
                    icon={<Glyph name="ShortestPath" size={14} />}
                    onClick={() => onShowPath(decisionEvidence(detail, decision))}
                  >
                    Show path
                  </Button>
                ) : null}
                {decision.source.url ? (
                  <a
                    href={decision.source.url}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="press inline-flex h-7 items-center gap-1.5 rounded-md px-2 text-caption text-fg-2 hover:bg-ink-3 hover:text-fg-1"
                  >
                    Open the decision
                    <span className="sr-only">(opens in a new tab)</span>
                  </a>
                ) : null}
              </>
            ) : undefined
          }
        />
      ) : null}
      {impact && detail.kind !== 'question' ? (
        <section aria-label="Impact" className="grid grid-cols-2 gap-px overflow-hidden rounded-md border border-line-1 bg-line-1">
          <div className="flex flex-col gap-1 bg-ink-0 px-3 py-2">
            <span className="eyebrow">Callers</span>
            <span className="font-mono text-title-sm text-fg-1 tabular">{cappedCount(impact.callers)}</span>
          </div>
          <div className="flex flex-col gap-1 bg-ink-0 px-3 py-2" title="Tests that reach this code, directly or through other functions. The graph groups the test functions it could place.">
            <span className="eyebrow">Tests that reach it</span>
            <span className="font-mono text-title-sm text-fg-1 tabular">{cappedCount(impact.tests)}</span>
          </div>
          {impact.callers >= LIST_CAP || impact.tests >= LIST_CAP ? (
            <p className="col-span-2 bg-ink-0 px-3 py-1.5 text-caption text-fg-3" data-testid="list-cap-note">
              Graph lists stop at {formatNumber(LIST_CAP)} items, so the real number is higher. The graph groups the ones it could place.
            </p>
          ) : null}
          {impact.criticality.slice(0, 3).map((c) => (
            <div key={c.id} className="col-span-2 flex items-center justify-between gap-2 bg-ink-0 px-3 py-1.5">
              <span className="min-w-0 truncate font-mono text-caption text-fg-2" title={c.id}>
                {truncateMiddle(idTail(c.id), 26)}
              </span>
              <span className="shrink-0 whitespace-nowrap text-caption text-fg-3 tabular" title={`Criticality percentile ${formatPercent(c.percentile, 1)}`}>
                {c.percentile >= 50 ? `top ${formatPercent(Math.max(1, 100 - Math.round(c.percentile)))} most depended-on` : 'rarely depended-on'}
              </span>
            </div>
          ))}
        </section>
      ) : null}
      {impact && detail.kind !== 'question' && impact.tests === 0 && impact.callers > 0 ? (
        <p className="rounded-sm border border-state-possible/40 px-3 py-2 text-small text-fg-1" data-testid="no-tests-warning">
          No test covers this code yet. Check that the ticket&apos;s test plan adds one before you approve.
        </p>
      ) : null}
      {detail.investigation ? (
        <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-caption text-fg-3" data-testid="investigation-meta">
          <span>{investigationText(detail.investigation)}</span>
          <CostBadge tokens={detail.investigation.tokens} costUsd={detail.investigation.costUsd} />
        </p>
      ) : null}
      {items.length === 0 ? (
        detail.state === 'Investigating' ? (
          <EmptyState glyph="Investigate" title="Looking for evidence." body="Evidence appears here as Actron finds it in the graph." />
        ) : (
          <EmptyState glyph="Search" title="No evidence for this request." body="Nothing in your history touches it. Actron continues to the ticket." />
        )
      ) : (
        <ul className="flex flex-col gap-3">
          {items.map((e) => (
            <li key={e.evidenceId}>
              <EvidenceCard
                evidence={e}
                onShowPath={onShowPath}
                tracing={tracingId === e.evidenceId}
                showTier={!(withoutModel && STRUCTURAL.has(e.role))}
              />
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
