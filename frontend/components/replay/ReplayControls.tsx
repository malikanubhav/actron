'use client'
import { Pause, Play, SkipBack, SkipForward } from '@phosphor-icons/react/dist/ssr'
import { cx } from '../ui/cx'

export const SPEEDS = [0.5, 1, 2, 4] as const

export interface ReplayControlsProps {
  playing: boolean
  speed: number
  position: number
  total: number
  onPlayPause: () => void
  onStep: (delta: 1 | -1) => void
  onSpeed: (speed: number) => void
  onSeek: (position: number) => void
}

/** Play, pause, step, speed 0.5×–4× and a scrubber (spec C, C2). */
export function ReplayControls({ playing, speed, position, total, onPlayPause, onStep, onSpeed, onSeek }: ReplayControlsProps) {
  const btn = 'press inline-flex size-9 items-center justify-center rounded-md border border-line-2 text-fg-1 hover:bg-ink-3 disabled:text-fg-disabled'
  return (
    <div className="flex flex-wrap items-center gap-3" data-testid="replay-controls" role="group" aria-label="Replay controls">
      <button type="button" className={btn} onClick={() => onStep(-1)} disabled={position <= 0} aria-label="Step back">
        <SkipBack size={16} aria-hidden />
      </button>
      <button
        type="button"
        className="press inline-flex h-9 w-24 items-center justify-center gap-2 rounded-md bg-accent text-accent-ink hover:bg-accent/90"
        onClick={onPlayPause}
        data-testid="replay-play"
      >
        {playing ? <Pause size={16} weight="fill" aria-hidden /> : <Play size={16} weight="fill" aria-hidden />}
        <span className="text-small font-medium">{playing ? 'Pause' : position >= total ? 'Again' : 'Play'}</span>
      </button>
      <button type="button" className={btn} onClick={() => onStep(1)} disabled={position >= total} aria-label="Step forward">
        <SkipForward size={16} aria-hidden />
      </button>
      <div role="radiogroup" aria-label="Speed" className="inline-flex rounded-md border border-line-2 p-0.5">
        {SPEEDS.map((s) => (
          <button
            key={s}
            type="button"
            role="radio"
            aria-checked={speed === s}
            onClick={() => onSpeed(s)}
            className={cx('h-7 rounded-sm px-2 font-mono text-eyebrow tabular', speed === s ? 'bg-ink-3 text-fg-1' : 'text-fg-3 hover:text-fg-1')}
          >
            {s}×
          </button>
        ))}
      </div>
      <label className="flex min-w-48 flex-1 items-center gap-3">
        <span className="sr-only">Position</span>
        <input
          type="range"
          min={0}
          max={total}
          value={position}
          onChange={(e) => onSeek(Number(e.target.value))}
          className="flex-1 accent-accent"
          aria-valuetext={`Step ${position} of ${total}`}
        />
        <span className="font-mono text-eyebrow text-fg-3 tabular" data-testid="replay-position">
          {position} / {total}
        </span>
      </label>
    </div>
  )
}
