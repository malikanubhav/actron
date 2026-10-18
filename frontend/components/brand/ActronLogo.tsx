/**
 * Actron mark: the evidence path. A request (hollow node) traced hop by hop through the graph to the exact place
 * it lands (the highlighted node). Same geometry as public/actron-brand/logo.svg.
 */
export const MARK_PATH = 'M6 25 13 14.5l6 5L26 7.5'
export const MARK_NODES = [
  { cx: 6, cy: 25, r: 3, kind: 'start' },
  { cx: 13, cy: 14.5, r: 2.1, kind: 'hop' },
  { cx: 19, cy: 19.5, r: 2.1, kind: 'hop' },
  { cx: 26, cy: 7.5, r: 3.6, kind: 'end' },
] as const

export interface ActronMarkProps {
  size?: number
  className?: string
  title?: string
  /** Draw the path once on mount (sign-in screen). */
  drawOnce?: boolean
}

export function ActronMark({ size = 24, className, title, drawOnce = false }: ActronMarkProps) {
  return (
    <svg
      viewBox="0 0 32 32"
      width={size}
      height={size}
      fill="none"
      role={title ? 'img' : undefined}
      aria-label={title}
      aria-hidden={title ? undefined : true}
      focusable="false"
      data-draw={drawOnce ? 'true' : undefined}
      className={['actron-mark shrink-0', className].filter(Boolean).join(' ')}
    >
      <path
        d={MARK_PATH}
        pathLength={1}
        stroke="currentColor"
        strokeWidth={2.25}
        strokeLinecap="round"
        strokeLinejoin="round"
        className="actron-mark-path"
      />
      {MARK_NODES.map((n) =>
        n.kind === 'start' ? (
          <circle key={`${n.cx}`} cx={n.cx} cy={n.cy} r={n.r} fill="var(--ink-0)" stroke="currentColor" strokeWidth={2} />
        ) : n.kind === 'end' ? (
          <circle key={`${n.cx}`} cx={n.cx} cy={n.cy} r={n.r} fill="var(--accent)" className="actron-mark-end" />
        ) : (
          <circle key={`${n.cx}`} cx={n.cx} cy={n.cy} r={n.r} fill="currentColor" />
        ),
      )}
    </svg>
  )
}

export function ActronWordmark({ size = 24, className }: { size?: number; className?: string }) {
  return (
    <span className={['inline-flex items-center gap-2 text-fg-1', className].filter(Boolean).join(' ')}>
      <ActronMark size={size} />
      <span className="display text-title-sm leading-none" style={{ fontSize: size * 0.92 }}>
        Actron
      </span>
    </span>
  )
}
