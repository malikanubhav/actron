'use client'
import { useEffect, useRef, useState } from 'react'
import { useReducedMotion } from '@/lib/hooks/useReducedMotion'
import { formatNumber } from '@/lib/format'
import { DUR } from '@/lib/motion'
import { cx } from '../ui/cx'

/**
 * Tabular mono number that rolls to its new value (spec C, C2). Width never changes between digits, so
 * streaming counts cause no layout shift. Reduced motion: the value changes at once.
 */
export function CountTicker({
  value,
  className,
  format = formatNumber,
  label,
}: {
  value: number
  className?: string
  format?: (n: number) => string
  label?: string
}) {
  const reduce = useReducedMotion()
  const [rolling, setRolling] = useState<{ from: number; to: number; shown: number } | null>(null)
  const settled = useRef(value)

  useEffect(() => {
    if (reduce || value === settled.current || typeof requestAnimationFrame === 'undefined') {
      settled.current = value
      return
    }
    const begin = settled.current
    const start = performance.now()
    let frame = requestAnimationFrame(function step(t) {
      const k = Math.min(1, (t - start) / DUR[3])
      const eased = 1 - (1 - k) ** 3
      setRolling(k < 1 ? { from: begin, to: value, shown: Math.round(begin + (value - begin) * eased) } : null)
      if (k < 1) frame = requestAnimationFrame(step)
      else settled.current = value
    })
    return () => {
      cancelAnimationFrame(frame)
      settled.current = value
    }
  }, [value, reduce])

  const shown = rolling && rolling.to === value ? rolling.shown : value
  return (
    <span className={cx('font-mono tabular', className)}>
      {label ? <span className="sr-only">{`${label}: ${format(value)}`}</span> : null}
      <span aria-hidden={label ? true : undefined}>{format(shown)}</span>
    </span>
  )
}
