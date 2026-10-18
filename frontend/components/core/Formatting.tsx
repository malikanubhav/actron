'use client'
import { useEffect, useState } from 'react'
import { Check, Copy } from '@phosphor-icons/react/dist/ssr'
import { exactTime, formatCompact, formatUsd, relativeTime, truncateMiddle } from '@/lib/format'
import { Tooltip } from '../ui/Tooltip'
import { useNow } from '@/lib/hooks/useNow'
import { cx } from '../ui/cx'

/** "4 min ago" with the exact local time on hover and focus (PRD 13.9b). Re-renders each minute. */
export function RelativeTime({
  value,
  className,
  short = false,
  focusable = true,
}: {
  value: string
  className?: string
  short?: boolean
  /** Inside links and buttons the time must not be a separate focus stop; the exact time shows as a title. */
  focusable?: boolean
}) {
  // Server and first client render use their own clock (a few seconds apart at most); suppressHydrationWarning
  // covers that difference, and the label never jumps between formats.
  const now = useNow()
  const label = relativeTime(value, now)
  if (!focusable) {
    return (
      <time dateTime={value} title={exactTime(value)} suppressHydrationWarning className={cx('tabular whitespace-nowrap', short && 'font-mono', className)}>
        {label}
      </time>
    )
  }
  return (
    <Tooltip content={exactTime(value)}>
      <time
        dateTime={value}
        tabIndex={0}
        suppressHydrationWarning
        className={cx('tabular whitespace-nowrap', short && 'font-mono', className)}
      >
        {label}
      </time>
    </Tooltip>
  )
}

export function useCopy(timeoutMs = 1600) {
  const [copied, setCopied] = useState(false)
  useEffect(() => {
    if (!copied) return
    const t = setTimeout(() => setCopied(false), timeoutMs)
    return () => clearTimeout(t)
  }, [copied, timeoutMs])
  const copy = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
    } catch {
      setCopied(false)
    }
  }
  return { copied, copy }
}

export function CopyButton({ value, label = 'Copy', className }: { value: string; label?: string; className?: string }) {
  const { copied, copy } = useCopy()
  return (
    <button
      type="button"
      onClick={() => void copy(value)}
      className={cx(
        'press inline-flex h-6 shrink-0 items-center gap-1 rounded-sm px-1.5 text-caption font-medium text-fg-3 hover:bg-ink-3 hover:text-fg-1',
        copied && 'text-state-ok hover:text-state-ok',
        className,
      )}
    >
      {copied ? <Check size={12} aria-hidden /> : <Copy size={12} aria-hidden />}
      <span aria-live="polite">{copied ? 'Copied' : label}</span>
    </button>
  )
}

/** Long ids and paths: middle truncation, full text on hover, copy button (PRD 13.9b). */
export function TruncatedText({
  text,
  max = 32,
  copy = true,
  className,
}: {
  text: string
  max?: number
  copy?: boolean
  className?: string
}) {
  const short = truncateMiddle(text, max)
  return (
    <span className={cx('inline-flex min-w-0 items-center gap-1', className)}>
      <Tooltip content={<span className="font-mono break-all">{text}</span>}>
        <span tabIndex={short === text ? undefined : 0} className="truncate font-mono" aria-label={text}>
          {short}
        </span>
      </Tooltip>
      {copy ? <CopyButton value={text} label="Copy" /> : null}
    </span>
  )
}

/** Model tokens and estimated cost (PRD 13.9b; C-AC-46). */
export function CostBadge({
  tokens,
  costUsd,
  label,
  className,
}: {
  tokens: { input: number; output: number }
  costUsd: number
  label?: string
  className?: string
}) {
  return (
    <span
      className={cx('inline-flex items-center gap-1.5 text-caption text-fg-3', className)}
      data-testid="cost-badge"
    >
      {label ? <span className="font-medium">{label}</span> : null}
      <span className="text-fg-2">
        <span className="font-mono tabular">{formatCompact(tokens.input + tokens.output)}</span> tokens
      </span>
      <span aria-hidden>·</span>
      <span className="text-fg-2">
        <span className="sr-only">estimated cost </span>
        <span className="font-mono tabular">{formatUsd(costUsd)}</span>
      </span>
    </span>
  )
}
