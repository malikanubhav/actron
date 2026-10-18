'use client'
import { ArrowSquareOut } from '@phosphor-icons/react/dist/ssr'
import type { Evidence, Label, Tier } from '@/lib/api/types'
import { labelStyle, sentenceCase, tierBars, tierFor, toneVar } from '@/lib/states'
import { shortDate } from '@/lib/format'
import { BrandMark, type BrandName } from '../brand/BrandMark'
import { Glyph } from '../glyphs/Glyph'
import { Tooltip } from '../ui/Tooltip'
import { Button } from '../ui/Button'
import { cx } from '../ui/cx'

const TIER_HELP: Record<Tier, string> = {
  HIGH: 'Confidence 0.80 or more. Several sources agree.',
  MEDIUM: 'Confidence between 0.60 and 0.80. Check the source before relying on it.',
  POSSIBLE: 'Confidence below 0.60, or flagged by a check. Shown so nothing is hidden; treat it as a lead.',
}

const TIER_TEXT: Record<Tier, string> = {
  HIGH: 'High confidence',
  MEDIUM: 'Medium confidence',
  POSSIBLE: 'Possible lead',
}

/** HIGH (≥ 0.8), MEDIUM (0.6–0.8), POSSIBLE (flagged or < 0.6), with the number in a tooltip (spec C, C2). */
export function ConfidenceTier({ value, flag = false, className }: { value: number; flag?: boolean; className?: string }) {
  const tier = tierFor(value, flag)
  const bars = tierBars(tier)
  return (
    <Tooltip content={`${TIER_HELP[tier]} Score ${value.toFixed(2)}.`}>
      <span
        tabIndex={0}
        data-tier={tier}
        aria-label={`Confidence ${tier.toLowerCase()}, ${value.toFixed(2)}`}
        className={cx(
          'inline-flex h-6 items-center gap-2 rounded-sm px-2 text-caption font-medium',
          // High is the normal case and stays quiet; lower tiers draw the eye.
          tier === 'POSSIBLE'
            ? 'border border-dashed border-state-possible/60 text-state-possible'
            : tier === 'MEDIUM'
              ? 'border border-line-2 text-fg-2'
              : 'border border-transparent text-fg-3',
          className,
        )}
      >
        <span aria-hidden className="flex items-end gap-px">
          {[1, 2, 3].map((i) => (
            <span
              key={i}
              className={cx('w-0.5 rounded-full', i === 1 ? 'h-1.5' : i === 2 ? 'h-2' : 'h-2.5', i <= bars ? 'bg-current' : 'bg-line-2')}
            />
          ))}
        </span>
        {TIER_TEXT[tier]}
      </span>
    </Tooltip>
  )
}

const LABEL_SENTENCE: Record<Label, string> = {
  conflict: 'An earlier decision conflicts with this request.',
  possible_conflict: 'An earlier decision may conflict with this request.',
  nothing_found: 'No earlier decision touches this request. The evidence below is the code it reaches.',
  clear: 'Nothing here conflicts with this request.',
}

/** The findings label with one sentence (spec C, C2). */
export function LabelBanner({
  label,
  sentence,
  resolved = false,
  action,
}: {
  label: Label
  sentence?: string
  resolved?: boolean
  /** Ways to reach what the label is about, such as the conflicting decision. */
  action?: React.ReactNode
}) {
  // After a request finishes, a conflict that was handled reads as resolved, not as an open warning.
  const base = labelStyle(label)
  const style = resolved ? { tone: 'ok' as const, text: `Resolved · ${sentenceCase(base.text).toLowerCase()}` } : { tone: base.tone, text: sentenceCase(base.text) }
  const glyph = label === 'conflict' ? 'Conflict' : label === 'possible_conflict' ? 'PossibleConflict' : label === 'clear' ? 'Approval' : 'Search'
  return (
    <div
      data-testid="label-banner"
      data-label={label}
      className="flex items-start gap-3 rounded-md border px-4 py-3"
      style={{ borderColor: `color-mix(in srgb, ${toneVar(style.tone)} 45%, transparent)` }}
    >
      <span className="mt-0.5" style={{ color: toneVar(style.tone) }}>
        <Glyph name={glyph} size={20} />
      </span>
      <div className="flex flex-col gap-0.5">
        <span className="text-caption font-medium" style={{ color: toneVar(style.tone) }}>
          {style.text}
        </span>
        <p className="text-small text-fg-1">{sentence ?? LABEL_SENTENCE[label]}</p>
        {action ? <div className="mt-2 flex flex-wrap items-center gap-2">{action}</div> : null}
      </div>
    </div>
  )
}

export const ROLE_LABEL: Record<Evidence['role'], string> = {
  conflict: 'Conflict',
  constraint: 'Constraint',
  impact: 'Impact',
  similar_work: 'Similar work',
  owner: 'Owner',
  test: 'Test',
}

export const ROLE_ORDER: Evidence['role'][] = ['conflict', 'constraint', 'impact', 'similar_work', 'owner', 'test']

export function sortEvidence(items: readonly Evidence[]): Evidence[] {
  return [...items].sort((a, b) => ROLE_ORDER.indexOf(a.role) - ROLE_ORDER.indexOf(b.role) || b.confidence - a.confidence)
}

/** Source type → brand mark and plain name. */
export function sourceBrand(type: string): { brand: BrandName | null; name: string } {
  const t = type.toLowerCase()
  if (t.startsWith('slack')) return { brand: 'slack', name: 'Slack' }
  if (t.includes('review')) return { brand: 'github', name: 'Review' }
  if (t.includes('pullrequest') || t.includes('github_pr') || t === 'pr') return { brand: 'github', name: 'PR' }
  if (t.includes('commit')) return { brand: 'github', name: 'Commit' }
  if (t.startsWith('github')) return { brand: 'github', name: 'GitHub' }
  if (t.startsWith('linear')) return { brand: 'linear', name: 'Ticket' }
  if (t.startsWith('code') || t.includes('function') || t.includes('file')) return { brand: null, name: 'Code' }
  if (t.includes('decision')) return { brand: null, name: 'Decision' }
  return { brand: null, name: type }
}

export function SourceChip({ type, author, at }: { type: string; author: string | null; at: string | null }) {
  const { brand, name } = sourceBrand(type)
  return (
    <span className="inline-flex min-w-0 items-center gap-2 text-caption text-fg-3">
      <span className="inline-flex h-5 items-center gap-1.5 rounded-sm border border-line-2 px-1.5 font-medium text-fg-2">
        {brand ? (
          <BrandMark name={brand} size={11} decorative />
        ) : (
          // The graph's node colour for the source, matching the canvas legend.
          <span aria-hidden className={cx('size-2 rounded-full', name === 'Code' ? 'bg-node-code' : name === 'Decision' ? 'bg-node-core' : 'bg-fg-3')} />
        )}
        {name}
      </span>
      {author ? <span className="truncate text-fg-2">{author}</span> : null}
      {at ? <span className="font-mono tabular">{shortDate(at)}</span> : null}
    </span>
  )
}

export interface EvidenceCardProps {
  evidence: Evidence
  onShowPath?: (evidence: Evidence) => void
  tracing?: boolean
  /** False for graph facts found without a model: they are certain, so no confidence tier is shown. */
  showTier?: boolean
}

/**
 * Evidence: role label, the quote set in the display face with a hanging quotation mark, the source chip with
 * author and date, the confidence tier, and "Show path" / "Open source" (PROMPT 8.8 D).
 */
export function EvidenceCard({ evidence, onShowPath, tracing = false, showTier = true }: EvidenceCardProps) {
  const roleTone =
    evidence.role === 'conflict' ? 'text-state-conflict' : evidence.role === 'constraint' ? 'text-state-possible' : 'text-fg-3'
  return (
    <article
      data-testid="evidence-card"
      data-role={evidence.role}
      aria-labelledby={`ev-${evidence.evidenceId}`}
      className={cx(
        'flex flex-col gap-3 rounded-md border bg-ink-1 p-4 transition-colors duration-2',
        tracing ? 'border-accent/70' : 'border-line-1',
      )}
    >
      <header className="flex items-center justify-between gap-2">
        <span className={cx('text-caption font-medium', roleTone)}>{ROLE_LABEL[evidence.role]}</span>
        {showTier ? <ConfidenceTier value={evidence.confidence} flag={evidence.tier === 'POSSIBLE' && evidence.confidence >= 0.6} /> : null}
      </header>
      <h3 id={`ev-${evidence.evidenceId}`} className="text-small font-medium text-fg-1">
        {evidence.title}
      </h3>
      {evidence.quote ? (
        <blockquote className="relative">
          <span aria-hidden className="display absolute -left-3 -top-1 text-title text-fg-3 select-none">
            “
          </span>
          <p className="display text-lead text-fg-1">
            <span className={cx(tracing && 'quote-highlight')}>{evidence.quote}</span>
          </p>
        </blockquote>
      ) : null}
      <SourceChip type={evidence.source.type} author={evidence.source.author} at={evidence.source.at} />
      <footer className="flex items-center gap-2 pt-1">
        {evidence.path.length > 1 && onShowPath ? (
          <Button
            size="sm"
            // Repeated on every card, so it stays quiet until it is the path being traced.
            variant={tracing ? 'primary' : 'ghost'}
            onClick={() => onShowPath(evidence)}
            aria-pressed={tracing}
            icon={<Glyph name="ShortestPath" size={14} animated={tracing} />}
          >
            {tracing ? 'Tracing path' : 'Show path'}
          </Button>
        ) : null}
        {evidence.source.url ? (
          <a
            href={evidence.source.url}
            target="_blank"
            rel="noreferrer noopener"
            className="press inline-flex h-7 items-center gap-1.5 rounded-md px-2 text-caption text-fg-2 hover:bg-ink-3 hover:text-fg-1"
          >
            Open source
            <ArrowSquareOut size={12} aria-hidden />
            <span className="sr-only">(opens in a new tab)</span>
          </a>
        ) : null}
      </footer>
    </article>
  )
}
