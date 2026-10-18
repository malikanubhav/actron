'use client'
import { useMemo, useState } from 'react'
import { CaretDown } from '@phosphor-icons/react/dist/ssr'
import type { Evidence, Revision, TicketContent } from '@/lib/api/types'
import { contentFrom, diffTickets, draftFrom, isDirty, validateDraft, type TicketDraft } from '@/lib/ticket'
import { idTail } from '@/lib/events'
import { shortHash } from '@/lib/format'
import { Button } from '../ui/Button'
import { RelativeTime } from '../core/Formatting'
import { BrandMark } from '../brand/BrandMark'
import { UnsavedChangesGuard } from '../core/UnsavedChangesGuard'
import { cx } from '../ui/cx'

const PLAN_SHOWN = 5

/** Affected functions by name: the same function name in several files shows once. */
export function uniqueFunctions(ids: readonly string[]): { name: string; ids: string[] }[] {
  const byName = new Map<string, string[]>()
  for (const id of ids) {
    const name = idTail(id)
    const list = byName.get(name) ?? []
    if (!list.includes(id)) list.push(id)
    byName.set(name, list)
  }
  return [...byName.entries()].map(([name, list]) => ({ name, ids: list }))
}

/**
 * Test plan entries grouped by consecutive kind, each shown by its command or, when the plan names only a test
 * node, by the test's name. Identical entries show once.
 */
export function testPlanGroups(plan: TicketContent['testPlan']): { kind: 'new' | 'existing'; items: string[] }[] {
  const groups: { kind: 'new' | 'existing'; items: string[] }[] = []
  for (const t of plan) {
    const kind = t.kind === 'new' ? 'new' : 'existing'
    const text = t.command?.trim() || (t.target ? (t.target.split('::').pop() ?? t.target) : '')
    if (!text) continue
    let last = groups[groups.length - 1]
    if (!last || last.kind !== kind) {
      last = { kind, items: [] }
      groups.push(last)
    }
    if (!last.items.includes(text)) last.items.push(text)
  }
  return groups
}

const selectClass =
  'h-8 appearance-none rounded-sm border border-line-2 bg-ink-1 pl-2.5 pr-7 text-caption text-fg-1 hover:border-fg-3/40 focus-visible:border-accent'

/** A native select styled like the other inputs, with its own caret. */
function SelectBox({ children }: { children: React.ReactNode }) {
  return (
    <span className="relative inline-flex items-center">
      {children}
      <CaretDown size={12} aria-hidden className="pointer-events-none absolute right-2 text-fg-3" />
    </span>
  )
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-2 border-t border-line-1 pt-4">
      <h4 className="eyebrow">{label}</h4>
      {children}
    </section>
  )
}

export interface TicketViewProps {
  revision: Revision
  revisions: Revision[]
  evidence?: Evidence[]
  onEdit?: (content: TicketContent) => Promise<unknown> | void
  canEdit?: boolean
  saving?: boolean
  onSelectNode?: (id: string) => void
  /**
   * Written by Actron with no writing model, so the text is a template. 'pending' asks for an edit before
   * approval; 'approved' says, in the past tense, that it was approved as written.
   */
  fromTemplate?: 'pending' | 'approved' | false
}

/** The ticket (spec B, B.C5): sections, revision selector, diff between revisions, and an edit form. */
export function TicketView({ revision, revisions, evidence = [], onEdit, canEdit = false, saving = false, onSelectNode, fromTemplate = false }: TicketViewProps) {
  const [shownN, setShownN] = useState(revision.n)
  const [compareTo, setCompareTo] = useState<number | null>(null)
  const [editing, setEditing] = useState(false)
  const shown = revisions.find((r) => r.n === shownN) ?? revision
  const c = shown.content
  const diff = useMemo(() => {
    if (compareTo === null) return null
    const before = revisions.find((r) => r.n === compareTo)
    return before ? diffTickets(before.content, shown.content) : null
  }, [compareTo, revisions, shown])

  if (editing) {
    return (
      <TicketEditForm
        base={revision.content}
        saving={saving}
        onCancel={() => setEditing(false)}
        onSave={async (content) => {
          await onEdit?.(content)
          setEditing(false)
        }}
      />
    )
  }

  return (
    <div className="flex flex-col gap-4" data-testid="ticket-view">
      <div className="flex flex-wrap items-center gap-2">
        <label className="eyebrow" htmlFor="rev-select">
          Revision
        </label>
        <SelectBox>
          <select
            id="rev-select"
            value={shownN}
            onChange={(e) => {
              setShownN(Number(e.target.value))
              setCompareTo(null)
            }}
            className={selectClass}
          >
            {revisions.map((r) => (
              <option key={r.n} value={r.n}>
                v{r.n}
                {r.n === revision.n ? ' (current)' : ''}
              </option>
            ))}
          </select>
        </SelectBox>
        {revisions.length > 1 ? (
          <>
            <label className="eyebrow" htmlFor="rev-compare">
              Compare with
            </label>
            <SelectBox>
              <select
                id="rev-compare"
                value={compareTo ?? ''}
                onChange={(e) => setCompareTo(e.target.value ? Number(e.target.value) : null)}
                className={selectClass}
              >
                <option value="">None</option>
                {revisions
                  .filter((r) => r.n !== shownN)
                  .map((r) => (
                    <option key={r.n} value={r.n}>
                      v{r.n}
                    </option>
                  ))}
              </select>
            </SelectBox>
          </>
        ) : null}
        <span className="flex-1" />
        {canEdit && shown.n === revision.n ? (
          <Button size="sm" onClick={() => setEditing(true)}>
            Edit ticket
          </Button>
        ) : null}
      </div>

      <p className="text-caption text-fg-3" data-testid="ticket-meta">
        <span className="font-mono tabular">v{shown.n}</span>
        {/* The approval card above already shows the current revision's hash; older revisions show theirs here. */}
        {shown.n !== revision.n ? <span className="font-mono tabular"> · SHA-256 {shortHash(shown.hash)}</span> : null}
        {' · '}by {shown.createdBy === 'actron' ? 'Actron' : shown.createdBy} · <RelativeTime value={shown.createdAt} />
        {shown.linear ? (
          <>
            {' · '}
            <a href={shown.linear.url} target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-1 font-mono text-fg-2 underline">
              <BrandMark name="linear" size={10} decorative />
              {shown.linear.identifier}
            </a>
          </>
        ) : (
          ' · Not synced to Linear'
        )}
        {shown.externalEdit ? ' · edited in Linear' : ''}
      </p>

      {diff ? (
        <div className="flex flex-col gap-3 rounded-md border border-line-1 p-3" data-testid="ticket-diff" aria-label={`Changes from v${compareTo} to v${shown.n}`}>
          <p className="eyebrow">
            Changes · v{compareTo} → v{shown.n}
          </p>
          {diff.length === 0 ? <p className="text-small text-fg-2">No changes.</p> : null}
          {diff.map((d) => (
            <div key={d.field} className="flex flex-col gap-1">
              <p className="text-caption font-medium text-fg-2">{d.label}</p>
              <ul className="flex flex-col gap-0.5 font-mono text-caption">
                {d.lines.map((l, i) => (
                  <li
                    key={i}
                    className={cx(
                      'rounded-sm px-2 py-0.5',
                      l.kind === 'added' && 'bg-state-ok/10 text-state-ok',
                      l.kind === 'removed' && 'bg-state-conflict/10 text-state-conflict line-through',
                      l.kind === 'same' && 'text-fg-3',
                    )}
                  >
                    <span aria-hidden>{l.kind === 'added' ? '+ ' : l.kind === 'removed' ? '− ' : '  '}</span>
                    <span className="sr-only">{l.kind === 'added' ? 'Added: ' : l.kind === 'removed' ? 'Removed: ' : ''}</span>
                    {l.text}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      ) : null}

      {fromTemplate && shown.n === revision.n ? (
        <p className="rounded-sm border border-line-2 px-3 py-2 text-small text-fg-2" data-testid="ticket-template-notice">
          {fromTemplate === 'approved'
            ? 'Approved as written from a template (no writing model was set).'
            : 'Written from a template because no writing model is set. Edit it before you approve.'}
        </p>
      ) : null}

      <section className="flex flex-col gap-2">
        <h4 className="eyebrow">Objective</h4>
        <p className="display text-lead text-fg-1">{c.objective}</p>
        {c.context ? <p className="text-small text-fg-2">{c.context}</p> : null}
      </section>

      <Section label="Acceptance criteria">
        <ol className="flex list-decimal flex-col gap-1.5 pl-5 text-small text-fg-1 marker:font-mono marker:text-fg-3">
          {c.acceptanceCriteria.map((a, i) => (
            <li key={i}>{a}</li>
          ))}
        </ol>
      </Section>

      {c.constraintsToPreserve.length ? (
        <Section label="Constraints to preserve">
          <ul className="flex flex-col gap-2">
            {c.constraintsToPreserve.map((con, i) => (
              <li key={i} className="flex flex-col gap-0.5 text-small text-fg-1">
                <span>{con.text}</span>
                {con.evidenceIds.length ? (
                  <span className="text-caption text-fg-3">
                    From{' '}
                    {con.evidenceIds
                      .map((id) => evidence.find((e) => e.evidenceId === id)?.title ?? idTail(id))
                      .join('; ')}
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
        </Section>
      ) : null}

      {c.affectedFunctions.length ? (
        <Section label="Affected functions">
          <ul className="flex flex-wrap gap-1.5">
            {uniqueFunctions(c.affectedFunctions).map((fn) => (
              <li key={fn.name}>
                <button
                  type="button"
                  onClick={() => onSelectNode?.(fn.ids[0] as string)}
                  title={fn.ids.join('\n')}
                  className="press inline-flex h-7 items-center rounded-sm border border-line-2 px-2 font-mono text-caption text-fg-1 hover:border-fg-3/40"
                >
                  {fn.name}
                  {fn.ids.length > 1 ? <span className="ml-1.5 font-ui text-fg-3">in {fn.ids.length} files</span> : null}
                </button>
              </li>
            ))}
          </ul>
        </Section>
      ) : null}

      <Section label="Test plan">
        <div className="flex flex-col gap-3" data-testid="test-plan">
          {testPlanGroups(c.testPlan).map((g, gi) => (
            <div key={gi} className="flex flex-col gap-1.5">
              <p className={cx('text-caption font-medium', g.kind === 'new' ? 'text-fg-1' : 'text-fg-3')}>
                {g.kind === 'new' ? 'New' : 'Existing'} {g.items.length === 1 ? 'test' : `tests (${g.items.length})`}
              </p>
              <ul className="flex flex-col gap-1">
                {g.items.slice(0, PLAN_SHOWN).map((text) => (
                  <li key={text} className="min-w-0 break-words font-mono text-caption text-fg-1">
                    {text}
                  </li>
                ))}
              </ul>
              {g.items.length > PLAN_SHOWN ? (
                <details className="group">
                  <summary className="cursor-pointer text-caption text-fg-3 hover:text-fg-1">
                    <span className="group-open:hidden">Show {g.items.length - PLAN_SHOWN} more</span>
                    <span className="hidden group-open:inline">Show fewer</span>
                  </summary>
                  <ul className="mt-1 flex flex-col gap-1">
                    {g.items.slice(PLAN_SHOWN).map((text) => (
                      <li key={text} className="min-w-0 break-words font-mono text-caption text-fg-1">
                        {text}
                      </li>
                    ))}
                  </ul>
                </details>
              ) : null}
            </div>
          ))}
        </div>
      </Section>

      {c.outOfScope.length ? (
        <Section label="Out of scope">
          <ul className="flex list-disc flex-col gap-1 pl-5 text-small text-fg-2">
            {c.outOfScope.map((o, i) => (
              <li key={i}>{o}</li>
            ))}
          </ul>
        </Section>
      ) : null}

      <Section label="Target branch">
        <p className="font-mono text-caption text-fg-1">{c.targetBranch}</p>
      </Section>
    </div>
  )
}

const FIELD_HELP: Record<keyof TicketDraft, string> = {
  objective: 'One sentence that says what changes.',
  context: 'What Actron found and why it matters.',
  acceptanceCriteria: 'One criterion per line, ideally "Given … when … then …".',
  constraintsToPreserve: 'One per line. Constraints Actron found keep their evidence links.',
  outOfScope: 'One item per line.',
  targetBranch: 'The branch the pull request will target.',
}

const LABELS: Record<keyof TicketDraft, string> = {
  objective: 'Objective',
  context: 'Context',
  acceptanceCriteria: 'Acceptance criteria',
  constraintsToPreserve: 'Constraints to preserve',
  outOfScope: 'Out of scope',
  targetBranch: 'Target branch',
}

/** Editing creates a new revision; earlier approvals stop counting (C-AC-43 guard, inline validation). */
export function TicketEditForm({
  base,
  onSave,
  onCancel,
  saving = false,
}: {
  base: TicketContent
  onSave: (content: TicketContent) => Promise<void> | void
  onCancel: () => void
  saving?: boolean
}) {
  const original = useMemo(() => draftFrom(base), [base])
  const [draft, setDraft] = useState<TicketDraft>(original)
  const [touched, setTouched] = useState<Partial<Record<keyof TicketDraft, boolean>>>({})
  const errors = validateDraft(draft)
  const valid = Object.keys(errors).length === 0
  const dirty = isDirty(draft, original)

  const field = (key: keyof TicketDraft, multiline: boolean, rows = 3) => {
    const id = `ticket-${key}`
    const error = touched[key] ? errors[key] : undefined
    const common = {
      id,
      value: draft[key],
      onChange: (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setDraft((d) => ({ ...d, [key]: e.target.value })),
      onBlur: () => setTouched((t) => ({ ...t, [key]: true })),
      'aria-invalid': error ? true : undefined,
      'aria-describedby': `${id}-help${error ? ` ${id}-err` : ''}`,
      className: cx(
        'w-full rounded-sm border bg-ink-1 px-3 py-2 text-small text-fg-1 focus-visible:border-accent',
        error ? 'border-state-conflict/70' : 'border-line-2',
        key === 'targetBranch' && 'font-mono',
      ),
    }
    return (
      <div className="flex flex-col gap-1">
        <label htmlFor={id} className="text-caption font-medium text-fg-1">
          {LABELS[key]}
        </label>
        <p id={`${id}-help`} className="text-caption text-fg-3">
          {FIELD_HELP[key]}
        </p>
        {multiline ? <textarea rows={rows} {...common} /> : <input type="text" {...common} />}
        {error ? (
          <p id={`${id}-err`} className="text-caption text-state-conflict">
            {error}
          </p>
        ) : null}
      </div>
    )
  }

  return (
    <form
      data-testid="ticket-edit-form"
      className="flex flex-col gap-4"
      onSubmit={(e) => {
        e.preventDefault()
        setTouched({ objective: true, acceptanceCriteria: true, targetBranch: true })
        if (valid && dirty) void onSave(contentFrom(draft, base))
      }}
    >
      <UnsavedChangesGuard when={dirty && !saving} />
      <p className="rounded-sm border border-state-possible/40 px-3 py-2 text-small text-fg-1">
        Saving creates a new revision. Approvals of earlier revisions stop counting.
      </p>
      {field('objective', true, 2)}
      {field('context', true, 3)}
      {field('acceptanceCriteria', true, 4)}
      {field('constraintsToPreserve', true, 3)}
      {field('outOfScope', true, 2)}
      {field('targetBranch', false)}
      <div className="flex items-center gap-2">
        <Button type="submit" variant="primary" disabled={!valid || !dirty} loading={saving} loadingText="Saving">
          Save as new revision
        </Button>
        <Button variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
        {!dirty ? <span className="text-caption text-fg-3">No changes yet.</span> : null}
      </div>
    </form>
  )
}
