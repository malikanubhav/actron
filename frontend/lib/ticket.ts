/** Ticket helpers (spec B, B.C5): field labels, revision diffs and edit-form validation. */
import type { TicketContent } from './api/types'

export const TICKET_FIELDS: { key: keyof TicketContent; label: string }[] = [
  { key: 'objective', label: 'Objective' },
  { key: 'context', label: 'Context' },
  { key: 'acceptanceCriteria', label: 'Acceptance criteria' },
  { key: 'constraintsToPreserve', label: 'Constraints to preserve' },
  { key: 'affectedFunctions', label: 'Affected functions' },
  { key: 'testPlan', label: 'Test plan' },
  { key: 'outOfScope', label: 'Out of scope' },
  { key: 'targetBranch', label: 'Target branch' },
]

export type DiffLine = { kind: 'same' | 'added' | 'removed'; text: string }
export interface FieldDiff {
  field: keyof TicketContent
  label: string
  lines: DiffLine[]
}

function asLines(value: TicketContent[keyof TicketContent]): string[] {
  if (typeof value === 'string') return value ? [value] : []
  if (!Array.isArray(value)) return []
  return value.map((item) => {
    if (typeof item === 'string') return item
    if ('text' in item) return item.text
    if ('command' in item) return `${item.kind === 'new' ? 'New' : 'Existing'}: ${item.command}`
    return JSON.stringify(item)
  })
}

/** Line-level diff per field between two revisions. Only changed fields are returned. */
export function diffTickets(before: TicketContent, after: TicketContent): FieldDiff[] {
  const out: FieldDiff[] = []
  for (const { key, label } of TICKET_FIELDS) {
    const a = asLines(before[key])
    const b = asLines(after[key])
    if (a.length === b.length && a.every((line, i) => line === b[i])) continue
    const bSet = new Set(b)
    const aSet = new Set(a)
    const lines: DiffLine[] = [
      ...a.map((text) => ({ kind: bSet.has(text) ? ('same' as const) : ('removed' as const), text })),
      ...b.filter((text) => !aSet.has(text)).map((text) => ({ kind: 'added' as const, text })),
    ]
    out.push({ field: key, label, lines })
  }
  return out
}

export interface TicketDraft {
  objective: string
  context: string
  acceptanceCriteria: string
  constraintsToPreserve: string
  outOfScope: string
  targetBranch: string
}

export function draftFrom(content: TicketContent): TicketDraft {
  return {
    objective: content.objective,
    context: content.context,
    acceptanceCriteria: content.acceptanceCriteria.join('\n'),
    constraintsToPreserve: content.constraintsToPreserve.map((c) => c.text).join('\n'),
    outOfScope: content.outOfScope.join('\n'),
    targetBranch: content.targetBranch,
  }
}

const lines = (text: string) =>
  text
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean)

export function contentFrom(draft: TicketDraft, base: TicketContent): TicketContent {
  const constraintTexts = lines(draft.constraintsToPreserve)
  return {
    ...base,
    objective: draft.objective.trim(),
    context: draft.context.trim(),
    acceptanceCriteria: lines(draft.acceptanceCriteria),
    constraintsToPreserve: constraintTexts.map(
      (text) => base.constraintsToPreserve.find((c) => c.text === text) ?? { text, evidenceIds: [] },
    ),
    outOfScope: lines(draft.outOfScope),
    targetBranch: draft.targetBranch.trim(),
  }
}

export type DraftErrors = Partial<Record<keyof TicketDraft, string>>

export function validateDraft(draft: TicketDraft): DraftErrors {
  const errors: DraftErrors = {}
  if (draft.objective.trim().length < 10) errors.objective = 'Write the objective as one full sentence.'
  if (draft.objective.trim().length > 300) errors.objective = 'Keep the objective to one sentence (300 characters at most).'
  if (lines(draft.acceptanceCriteria).length === 0) errors.acceptanceCriteria = 'Add at least one acceptance criterion, one per line.'
  if (!/^[A-Za-z0-9._/-]+$/.test(draft.targetBranch.trim())) errors.targetBranch = 'Use a branch name such as dev or feature/inline-results.'
  return errors
}

export function isDirty(draft: TicketDraft, original: TicketDraft): boolean {
  return (Object.keys(draft) as (keyof TicketDraft)[]).some((k) => draft[k] !== original[k])
}
