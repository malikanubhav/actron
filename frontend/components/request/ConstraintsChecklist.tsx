import { Glyph } from '../glyphs/Glyph'
import { cx } from '../ui/cx'

export interface ConstraintProof {
  text: string
  status: 'holds' | 'broken' | 'unverified'
  proof: { kind: 'test' | 'evidence'; label: string; url?: string | null } | null
}

const STATUS_TEXT = { holds: 'Holds', broken: 'Broken', unverified: 'Not verified' } as const

/** Each preserved constraint with the test or evidence that proves it still holds (PROMPT 8.8 D, PR tab). */
export function ConstraintsChecklist({ constraints }: { constraints: ConstraintProof[] }) {
  if (constraints.length === 0) return <p className="text-small text-fg-3">This ticket listed no constraints to preserve.</p>
  return (
    <ul className="flex flex-col gap-2" data-testid="constraints-checklist">
      {constraints.map((c, i) => (
        <li key={i} data-status={c.status} className="flex items-start gap-3 rounded-md border border-line-1 px-3 py-2">
          <span
            className={cx(
              'mt-0.5',
              c.status === 'holds' ? 'text-state-ok' : c.status === 'broken' ? 'text-state-conflict' : 'text-state-possible',
            )}
          >
            <Glyph name={c.status === 'holds' ? 'TestPass' : c.status === 'broken' ? 'TestFail' : 'PossibleConflict'} size={16} />
          </span>
          <div className="flex min-w-0 flex-1 flex-col gap-0.5">
            <p className="text-small text-fg-1">{c.text}</p>
            {c.proof ? (
              <p className="text-caption text-fg-3">
                {c.proof.kind === 'test' ? 'Proved by test ' : 'Backed by '}
                {c.proof.url ? (
                  <a href={c.proof.url} target="_blank" rel="noreferrer noopener" className="font-mono text-fg-2 underline">
                    {c.proof.label}
                  </a>
                ) : (
                  <code className="font-mono text-fg-2">{c.proof.label}</code>
                )}
              </p>
            ) : (
              <p className="text-caption text-fg-3">No test proves this yet.</p>
            )}
          </div>
          <span
            className={cx(
              'shrink-0 text-caption font-medium',
              c.status === 'holds' ? 'text-state-ok' : c.status === 'broken' ? 'text-state-conflict' : 'text-state-possible',
            )}
          >
            {STATUS_TEXT[c.status]}
          </span>
        </li>
      ))}
    </ul>
  )
}
