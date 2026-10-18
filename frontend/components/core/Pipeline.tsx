import { PIPELINE } from '@/lib/states'
import type { PipelineStep } from '@/lib/api/types'
import { cx } from '../ui/cx'
import { Glyph } from '../glyphs/Glyph'

export type PipelineStatus = 'active' | 'failed' | 'done' | 'cancelled' | 'waiting'

export interface PipelineProps {
  steps?: { n: number; text: string }[]
  current: PipelineStep
  status?: PipelineStatus
  /** Compact segments for list rows. */
  mini?: boolean
  className?: string
}

const pad = (n: number) => String(n).padStart(2, '0')

function stepState(n: number, current: number, status: PipelineStatus): 'done' | 'current' | 'failed' | 'todo' {
  if (status === 'done') return 'done'
  if (n < current) return 'done'
  if (n === current) return status === 'failed' ? 'failed' : status === 'cancelled' ? 'todo' : 'current'
  return 'todo'
}

/** Visible short label for a row: "Step 2 of 6 · Clarify", or "All 6 steps done". */
export function pipelineStepLabel(current: PipelineStep, status: PipelineStatus = 'active', steps: { n: number; text: string }[] = PIPELINE): string {
  if (status === 'done') return `All ${steps.length} steps done`
  return `Step ${current} of ${steps.length} · ${steps[current - 1]?.text ?? ''}`
}

/** Numbered pipeline 01 Investigate · 02 Clarify · 03 Ticket · 04 Approve · 05 Build · 06 Review (PROMPT 8.8 C, D). */
export function Pipeline({ steps = PIPELINE, current, status = 'active', mini = false, className }: PipelineProps) {
  const label = `Step ${current} of ${steps.length}: ${steps[current - 1]?.text ?? ''}${status === 'failed' ? ', stopped' : ''}`
  if (mini) {
    return (
      <ol aria-label={label} title={steps.map((s) => `${s.n} ${s.text}`).join(' · ')} className={cx('flex items-center gap-1', className)} data-testid="pipeline-mini">
        {steps.map((step) => {
          const s = stepState(step.n, current, status)
          return (
            <li
              key={step.n}
              title={`${pad(step.n)} ${step.text}`}
              data-state={s}
              className={cx(
                'h-1 w-4 rounded-full transition-colors duration-2',
                s === 'done' && 'bg-fg-3',
                s === 'current' && 'bg-accent',
                s === 'failed' && 'bg-state-conflict',
                s === 'todo' && 'bg-line-2',
              )}
            >
              <span className="sr-only">
                {pad(step.n)} {step.text} {s === 'done' ? 'done' : s === 'current' ? 'current' : s === 'failed' ? 'stopped' : ''}
              </span>
            </li>
          )
        })}
      </ol>
    )
  }
  return (
    <ol aria-label={label} className={cx('flex flex-wrap items-stretch', className)} data-testid="pipeline">
      {steps.map((step, i) => {
        const s = stepState(step.n, current, status)
        return (
          <li
            key={step.n}
            data-state={s}
            aria-current={s === 'current' || s === 'failed' ? 'step' : undefined}
            className="flex items-center"
          >
            <span
              className={cx(
                'relative flex items-baseline gap-2 py-2 text-caption font-medium',
                'transition-colors duration-2',
                s === 'done' && 'text-fg-2',
                s === 'current' && 'text-fg-1',
                s === 'failed' && 'text-state-conflict',
                s === 'todo' && 'text-fg-3',
              )}
            >
              {s === 'done' ? (
                <span className="inline-flex w-4 justify-center self-center text-state-ok" aria-hidden>
                  <Glyph name="TestPass" size={12} />
                </span>
              ) : null}
              {/* UI face with tabular figures: mono numbers beside the names made the whole row read as mono. */}
              <span className={cx('tabular', s === 'current' && 'text-accent')}>{pad(step.n)}</span>
              {s === 'done' ? <span className="sr-only">done</span> : null}
              <span>{step.text}</span>
              <span
                aria-hidden
                className={cx(
                  'absolute inset-x-0 -bottom-px h-0.5 rounded-full transition-colors duration-2',
                  s === 'current' ? 'bg-accent' : s === 'failed' ? 'bg-state-conflict' : 'bg-transparent',
                )}
              />
            </span>
            {i < steps.length - 1 ? (
              <span aria-hidden className={cx('mx-3 h-px w-6', s === 'done' ? 'bg-fg-3' : 'bg-line-2')} />
            ) : null}
          </li>
        )
      })}
    </ol>
  )
}
