import { stateStyle, labelStyle, sentenceCase, toneVar, type AnyState, type Tone } from '@/lib/states'
import type { Label } from '@/lib/api/types'
import { cx } from '../ui/cx'

const toneDot: Record<Tone, string> = {
  running: 'bg-state-running',
  ok: 'bg-state-ok',
  conflict: 'bg-state-conflict',
  possible: 'bg-state-possible',
  idle: 'bg-state-idle',
  needs_you: 'bg-accent',
}

const toneText: Record<Tone, string> = {
  running: 'text-state-running',
  ok: 'text-state-ok',
  conflict: 'text-state-conflict',
  possible: 'text-state-possible',
  idle: 'text-fg-2',
  needs_you: 'text-accent',
}

export function Chip({
  tone,
  text,
  className,
  pulse = false,
  title,
}: {
  tone: Tone
  text: string
  className?: string
  pulse?: boolean
  title?: string
}) {
  return (
    <span
      title={title}
      data-tone={tone}
      className={cx(
        'inline-flex h-6 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-sm border px-2 text-caption font-medium tabular',
        'transition-[color,border-color] duration-2 ease-standard',
        toneText[tone],
        className,
      )}
      style={{ borderColor: `color-mix(in srgb, ${toneVar(tone)} 45%, transparent)` }}
    >
      <span aria-hidden className={cx('inline-block size-1.5 rounded-full', toneDot[tone], pulse && 'motion-safe:animate-pulse')} />
      {sentenceCase(text)}
    </span>
  )
}

/** Outlined state chip; names and colours come from the map shared with Slack (C-AC-10). */
export function StateChip({ state, className, live = false }: { state: AnyState; className?: string; live?: boolean }) {
  const style = stateStyle(state)
  const running = style.tone === 'running'
  return <Chip tone={style.tone} text={style.text} className={className} pulse={live && running} />
}

export function LabelChip({ label, className }: { label: Label; className?: string }) {
  const style = labelStyle(label)
  return <Chip tone={style.tone} text={style.text} className={className} />
}
