'use client'
import { useMemo, useState } from 'react'
import type { Build, EventEnvelope } from '@/lib/api/types'
import { readBuildReport } from '@/lib/build-report'
import { useNow } from '@/lib/hooks/useNow'
import { stopReasonText } from '@/lib/events'
import { formatDuration, shortSha, truncateMiddle } from '@/lib/format'
import { Glyph } from '../glyphs/Glyph'
import { BrandMark, languageFor } from '../brand/BrandMark'
import { CountTicker } from '../core/CountTicker'
import { CopyButton, CostBadge, RelativeTime } from '../core/Formatting'
import { TestList, type TestResult } from './TestList'
import { buildTimelineRows } from './Timeline'
import { ToolCallCard } from './ToolCallCard'
import { cx } from '../ui/cx'

type Payload = Record<string, unknown>

export interface BuildTheatreProps {
  build: Build | null
  events: readonly EventEnvelope[]
  onLoadLog?: () => Promise<string>
  /** Replay and public pages have no live clock. */
  now?: number
}

/** What the person does next for stops caused by setup, not by the change. */
const NEXT_STEP: Record<string, string> = {
  missing_identity: 'set ACTRON_BOT_NAME and ACTRON_BOT_EMAIL in the server’s .env, restart Actron, then Retry.',
  missing_fork: 'add a fork to push to in Connect, then Retry.',
  missing_branch: 'choose an existing working branch in Settings, then Retry.',
}

/** Prose in the UI font with environment variable names (ACTRON_BOT_NAME) set in mono. */
function withCode(text: string) {
  return text.split(/\b([A-Z][A-Z0-9]*_[A-Z0-9_]+)\b/).map((part, i) =>
    i % 2 === 1 ? (
      <code key={i} className="font-mono text-caption text-fg-1">
        {part}
      </code>
    ) : (
      part
    ),
  )
}

function eventsFor(events: readonly EventEnvelope[], buildId: string | undefined) {
  return events.filter((e) => {
    const p = e.payload as Payload
    if (e.type === 'tool.called' || e.type === 'tool.result') return true
    return buildId ? p.buildId === buildId : true
  })
}

function DiffPreview({ text }: { text: string }) {
  return (
    <pre tabIndex={0} aria-label="Latest change" className="max-h-48 overflow-auto rounded-sm bg-ink-2 p-3 font-mono text-caption leading-5" data-testid="live-diff">
      {text.split('\n').map((line, i) => (
        <span
          key={i}
          className={cx('block', line.startsWith('+') ? 'text-state-ok' : line.startsWith('-') ? 'text-state-conflict' : 'text-fg-2')}
        >
          {line || ' '}
        </span>
      ))}
    </pre>
  )
}

/**
 * The build theatre (PROMPT 8.8a item 3): current step in plain words, the file being edited with its language
 * mark, a live diff preview, tests streaming as pass and fail counters, repair attempts, the MCP tools Pi called,
 * folded failing output and the raw log.
 */
export function BuildTheatre({ build, events, onLoadLog }: BuildTheatreProps) {
  const now = useNow(1000)
  const [log, setLog] = useState<string | null>(null)
  const [logError, setLogError] = useState<string | null>(null)
  const scoped = useMemo(() => eventsFor(events, build?.id), [events, build?.id])
  const steps = scoped.filter((e) => e.type === 'build.step')
  const lastStep = steps[steps.length - 1]
  const lastFileStep = [...steps].reverse().find((e) => typeof (e.payload as Payload).file === 'string')
  const diffStep = [...steps].reverse().find((e) => typeof ((e.payload as Payload).detail as Payload | undefined)?.diff === 'string')
  const repairs = scoped.filter((e) => e.type === 'build.repair')
  const lastTests = [...scoped].reverse().find((e) => e.type === 'tests.result')
  const piCalls = buildTimelineRows(scoped).filter((r) => r.kind === 'tool' && r.call.by === 'pi')
  const report = readBuildReport(build?.report)

  if (!build) {
    return (
      <div className="flex flex-col gap-2 py-6" data-testid="build-theatre" data-state="none">
        <span className="text-fg-3">
          <Glyph name="Build" size={20} />
        </span>
        <p className="display text-title-sm text-fg-1">No build yet.</p>
        <p className="text-small text-fg-2">The build starts when the ticket is approved. Pi then works in a container with only the checkout.</p>
      </div>
    )
  }

  const passed = Number((lastTests?.payload as Payload | undefined)?.passed ?? build.testsPassed)
  const failed = Number((lastTests?.payload as Payload | undefined)?.failed ?? build.testsFailed)
  const failing: TestResult[] = Array.isArray((lastTests?.payload as Payload | undefined)?.failing)
    ? (((lastTests?.payload as Payload).failing as Payload[]).map((f) => ({
        name: String(f.name ?? 'failing test'),
        status: 'fail' as const,
        output: typeof f.output === 'string' ? f.output : undefined,
      })) satisfies TestResult[])
    : []
  const tests = report.tests.length ? report.tests : failing
  const running = build.status === 'running'
  const testsReported = Boolean(lastTests) || build.testsPassed + build.testsFailed > 0
  const file = lastFileStep ? String((lastFileStep.payload as Payload).file) : null
  const lang = file ? languageFor(file) : null
  const elapsed = (build.finishedAt ? Date.parse(build.finishedAt) : now) - Date.parse(build.startedAt)
  const ended = build.status === 'stopped' || build.status === 'failed'
  // A build that ended before Pi did anything has no steps, tests or repairs to show; say so once instead.
  const neverStarted = ended && steps.length === 0 && !testsReported && repairs.length === 0 && build.attempts === 0 && !file
  const failedEvent = [...scoped].reverse().find((e) => e.type === 'build.failed')
  const errorLine = String((failedEvent?.payload as Payload | undefined)?.message ?? '').split('\n')[0]?.trim() ?? ''

  return (
    <div className="flex flex-col gap-5" data-testid="build-theatre" data-state={build.status}>
      <div className="flex flex-col gap-2">
        <div className="flex items-center gap-2">
          <BrandMark name="pi" size={16} />
          <span className="eyebrow">Pi coding agent, in a sandboxed container</span>
        </div>
        {build.branch ? (
          <p className="flex min-w-0 items-center gap-1" data-testid="build-branch">
            <span className="min-w-0 truncate font-mono text-caption text-fg-2" title={build.branch}>
              {truncateMiddle(build.branch, 36)}
            </span>
            <CopyButton value={build.branch} label="Copy branch" />
          </p>
        ) : null}
        {build.status === 'queued' ? (
          <p className="display text-title-sm text-fg-1">Queued at position {build.queuePosition ?? 1}. Pi starts when a slot is free.</p>
        ) : build.status === 'waiting_budget' ? (
          <p className="display text-title-sm text-state-possible">Waiting: the daily model budget is spent. Raise it in Settings to resume.</p>
        ) : build.status === 'stopped' ? (
          <div className="flex items-start gap-2" data-testid="build-status">
            <span className="mt-0.5 text-state-conflict">
              <Glyph name="TestFail" size={16} />
            </span>
            <div className="flex min-w-0 flex-col gap-1">
              <p className="text-small font-medium text-fg-1">{neverStarted ? 'Stopped before the build started' : 'Stopped'}</p>
              <p className="text-small text-fg-2">{stopReasonText(build.stopReason)}</p>
              {errorLine ? <p className="text-small text-fg-2">{withCode(errorLine)}</p> : null}
              {build.stopReason && NEXT_STEP[build.stopReason] ? (
                <p className="mt-1 text-small text-fg-1" data-testid="build-next-step">
                  <span className="text-fg-3">Next: </span>
                  {withCode(NEXT_STEP[build.stopReason] as string)}
                </p>
              ) : null}
            </div>
          </div>
        ) : build.status === 'failed' ? (
          <div className="flex flex-col gap-2" data-testid="failure-cause">
            <div className="flex items-start gap-2">
              <span className="mt-0.5 text-state-conflict">
                <Glyph name="TestFail" size={16} />
              </span>
              <div className="flex min-w-0 flex-col gap-1">
                <p className="text-small font-medium text-fg-1">{neverStarted ? 'Failed before the build started' : 'Failed'}</p>
                <p className="text-small text-fg-2">{stopReasonText(build.stopReason)}</p>
                {errorLine ? <p className="text-small text-fg-2">{withCode(errorLine)}</p> : null}
              </div>
            </div>
            {failing.length ? (
              <p className="text-small text-fg-1">
                Still failing: <code className="font-mono text-caption">{failing.map((f) => f.name).join(', ')}</code>
                {failing[0]?.output ? (
                  <span className="mt-1 block truncate font-mono text-caption text-fg-3" title={failing[0].output}>
                    {failing[0].output.split('\n')[0]}
                  </span>
                ) : null}
              </p>
            ) : null}
            {repairs.length ? (
              <p className="text-caption text-fg-3">Last repair: {String((repairs[repairs.length - 1]?.payload as Payload).reason ?? '')}</p>
            ) : null}
          </div>
        ) : build.status === 'passed' ? (
          <p className="display text-title-sm text-fg-1">Passed at {shortSha(build.headSha ?? '')}. The pull request is next.</p>
        ) : (
          <p className="display text-title-sm text-fg-1" aria-live="polite" data-testid="current-step">
            {lastStep ? String((lastStep.payload as Payload).text ?? 'Working') : 'Preparing the container.'}
          </p>
        )}
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-caption text-fg-3">
          <span suppressHydrationWarning>
            {running ? 'Running for' : 'Took'} <span className="font-mono text-fg-2 tabular">{formatDuration(Math.max(0, elapsed))}</span>
          </span>
          <span>
            Started <RelativeTime value={build.startedAt} className="text-fg-2" />
          </span>
          {build.baseSha ? (
            <span className="whitespace-nowrap">
              from <span className="font-mono text-fg-2 tabular">{shortSha(build.baseSha)}</span>
            </span>
          ) : null}
          <span className="inline-flex items-center gap-2">
            Cost
            <CostBadge tokens={build.tokens} costUsd={build.costUsd} />
          </span>
        </div>
      </div>

      {neverStarted ? null : (
      <div className="grid grid-cols-3 gap-px overflow-hidden rounded-md border border-line-1 bg-line-1" data-testid="test-tickers">
        <div className="flex flex-col gap-1 bg-ink-0 px-4 py-3">
          <span className="eyebrow">Tests passed</span>
          {testsReported ? (
            <CountTicker value={passed} label="Tests passed" className="text-title text-state-ok" />
          ) : (
            <span className="font-mono text-title text-fg-3">
              <span aria-hidden>—</span>
              <span className="sr-only">No test results yet</span>
            </span>
          )}
        </div>
        <div className="flex flex-col gap-1 bg-ink-0 px-4 py-3">
          <span className="eyebrow">Tests failed</span>
          {testsReported ? (
            <CountTicker value={failed} label="Tests failed" className={cx('text-title', failed ? 'text-state-conflict' : 'text-fg-2')} />
          ) : (
            <span aria-hidden className="font-mono text-title text-fg-3">
              —
            </span>
          )}
        </div>
        <div className="flex flex-col gap-1 bg-ink-0 px-4 py-3">
          <span className="eyebrow">Repair attempts</span>
          <CountTicker value={Math.max(build.attempts, repairs.length)} label="Repair attempts" className="text-title text-fg-2" />
        </div>
      </div>
      )}

      {file ? (
        <section className="flex flex-col gap-2" aria-label="File being edited">
          <div className="flex items-center gap-2">
            <span className="eyebrow">{running ? 'Editing' : 'Last edit'}</span>
            {lang ? <BrandMark name={lang} size={13} /> : null}
            <code className="min-w-0 truncate font-mono text-caption text-fg-1" title={file}>
              {file}
            </code>
          </div>
          {diffStep ? <DiffPreview text={String(((diffStep.payload as Payload).detail as Payload).diff)} /> : null}
        </section>
      ) : null}

      {neverStarted ? null : (
      <section className="flex flex-col gap-2" aria-label="Build steps">
        <h4 className="eyebrow">Steps</h4>
        <ol className="flex flex-col">
          {steps.map((s, i) => (
            <li key={s.seq ?? s.id} className="flex items-start gap-3 border-b border-line-1 py-1.5 last:border-b-0">
              <span className="mt-0.5 font-mono text-eyebrow text-fg-3 tabular">{String(i + 1).padStart(2, '0')}</span>
              <span className={cx('min-w-0 flex-1 text-small', i === steps.length - 1 && running ? 'text-fg-1' : 'text-fg-2')}>
                {String((s.payload as Payload).text ?? '')}
              </span>
            </li>
          ))}
          {steps.length === 0 ? <li className="text-small text-fg-3">{ended ? 'Pi reported no steps.' : 'No steps reported yet.'}</li> : null}
        </ol>
      </section>
      )}

      {repairs.length ? (
        <section className="flex flex-col gap-2" aria-label="Repair attempts">
          <h4 className="eyebrow">Repair attempts</h4>
          <ul className="flex flex-col gap-1">
            {repairs.map((r) => (
              <li key={r.seq ?? r.id} className="flex items-start gap-2 text-small text-fg-2">
                <span className="text-state-possible">
                  <Glyph name="Repair" size={14} />
                </span>
                Attempt {String((r.payload as Payload).attempt ?? '')}: {String((r.payload as Payload).reason ?? '')}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {neverStarted ? null : (
        <section className="flex flex-col gap-2" aria-label="Tests">
          <h4 className="eyebrow">Tests</h4>
          <TestList results={tests} totals={testsReported ? { passed, failed } : undefined} />
        </section>
      )}

      {piCalls.length ? (
        <section className="flex flex-col gap-2" aria-label="Graph tools Pi called">
          <h4 className="eyebrow">Graph tools Pi called</h4>
          <ul className="flex flex-col gap-2">
            {piCalls.map((row) =>
              row.kind === 'tool' ? (
                <li key={row.key}>
                  <ToolCallCard call={row.call} result={row.result} />
                </li>
              ) : null,
            )}
          </ul>
        </section>
      ) : null}

      {report.procedures.length ? (
        <section className="flex flex-col gap-2" aria-label="Procedures used">
          <h4 className="eyebrow">Procedures used</h4>
          <ul className="flex flex-col gap-1">
            {report.procedures.map((p) => (
              <li key={p.title} className="flex flex-col text-small">
                <span className="text-fg-1">{p.title}</span>
                <code className="font-mono text-caption text-fg-3">{p.testCommand}</code>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {onLoadLog ? (
        <details
          className="rounded-md border border-line-1"
          onToggle={(e) => {
            if ((e.target as HTMLDetailsElement).open && log === null) {
              onLoadLog()
                .then(setLog)
                .catch(() => setLogError('The raw log could not be loaded. Try again in a moment.'))
            }
          }}
        >
          <summary className="cursor-pointer px-3 py-2 text-caption font-medium text-fg-3 hover:text-fg-1">Raw log</summary>
          <pre tabIndex={0} className="max-h-96 overflow-auto border-t border-line-1 p-3 font-mono text-caption text-fg-2 whitespace-pre-wrap" data-testid="raw-log">
            {logError ?? log ?? 'Loading the log…'}
          </pre>
        </details>
      ) : null}
    </div>
  )
}
