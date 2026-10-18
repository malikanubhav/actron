import { Glyph } from '../glyphs/Glyph'
import { cx } from '../ui/cx'

export interface TestResult {
  name: string
  status: 'pass' | 'fail' | 'skip'
  output?: string
  durationMs?: number
}

const ORDER = { fail: 0, pass: 1, skip: 2 } as const

/** Grouped pass/fail/skip, failing first, output folded (spec C, C2). */
export function TestList({
  results,
  className,
  totals,
}: {
  results: TestResult[]
  className?: string
  /** Counts from the build record; the list may hold only the tests the report names. */
  totals?: { passed: number; failed: number }
}) {
  const sorted = [...results].sort((a, b) => ORDER[a.status] - ORDER[b.status] || a.name.localeCompare(b.name))
  const counts = { pass: 0, fail: 0, skip: 0 }
  for (const r of results) counts[r.status] += 1
  if (results.length === 0) return <p className="text-small text-fg-3">No test results yet.</p>
  return (
    <div className={cx('flex flex-col gap-2', className)} data-testid="test-list">
      <p className="text-caption text-fg-3 tabular">
        <span className="text-state-ok">{totals?.passed ?? counts.pass} passed</span>
        {' · '}
        <span className={(totals?.failed ?? counts.fail) ? 'text-state-conflict' : undefined}>{totals?.failed ?? counts.fail} failed</span>
        {' · '}
        {counts.skip} skipped
      </p>
      {totals && results.length < totals.passed + totals.failed ? (
        <p className="text-caption text-fg-3">
          The report names {results.length} of {totals.passed + totals.failed} tests; the rest passed without notes.
        </p>
      ) : null}
      <ul className="flex flex-col">
        {sorted.map((r) => (
          <li key={r.name} data-status={r.status} className="border-b border-line-1 last:border-b-0">
            {r.status === 'fail' && r.output ? (
              <details className="group py-1.5">
                <summary className="flex cursor-pointer list-none items-center gap-2 text-small text-fg-1">
                  <span className="text-state-conflict">
                    <Glyph name="TestFail" size={14} />
                  </span>
                  <span className="min-w-0 flex-1 truncate font-mono text-caption">{r.name}</span>
                  <span className="text-caption text-fg-3 group-open:hidden">Show output</span>
                  <span className="hidden text-caption text-fg-3 group-open:inline">Hide output</span>
                </summary>
                <pre tabIndex={0} className="mt-2 max-h-64 overflow-auto rounded-sm bg-ink-2 p-3 font-mono text-caption text-fg-2 whitespace-pre-wrap">
                  {r.output}
                </pre>
              </details>
            ) : (
              <div className="flex items-center gap-2 py-1.5 text-small">
                <span className={r.status === 'pass' ? 'text-state-ok' : r.status === 'fail' ? 'text-state-conflict' : 'text-fg-3'}>
                  <Glyph name={r.status === 'fail' ? 'TestFail' : 'TestPass'} size={14} />
                </span>
                <span className={cx('min-w-0 flex-1 truncate font-mono text-caption', r.status === 'skip' ? 'text-fg-3' : 'text-fg-1')}>
                  {r.name}
                </span>
                <span className="sr-only">{r.status === 'pass' ? 'passed' : r.status === 'fail' ? 'failed' : 'skipped'}</span>
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}
