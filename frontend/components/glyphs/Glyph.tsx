import type { ReactNode, SVGProps } from 'react'
import { GLYPH_MOTION, type GlyphName } from './names'

/**
 * Actron glyphs: 24-px grid, 1.5 px stroke, round caps and joins, currentColor only.
 * Elements with className "g-a" carry the animated state (see glyphs.css). Each glyph is drawn for this product;
 * none is a sparkle, robot, wand or brain.
 */

const A = 'g-a'

type Shape = ReactNode

const node = (cx: number, cy: number, r = 2, filled = false, animated = false) => (
  <circle
    key={`n${cx}-${cy}-${r}`}
    cx={cx}
    cy={cy}
    r={r}
    fill={filled ? 'currentColor' : 'none'}
    className={animated ? A : undefined}
    pathLength={animated ? 1 : undefined}
  />
)

const SHAPES: Record<GlyphName, () => Shape> = {
  Request: () => (
    <>
      <path d="M5 4.75h14c.69 0 1.25.56 1.25 1.25v9c0 .69-.56 1.25-1.25 1.25h-7L8 19.25v-3H5c-.69 0-1.25-.56-1.25-1.25V6c0-.69.56-1.25 1.25-1.25Z" />
      <path className={A} pathLength={1} d="M8 9.5h8" />
      <path className={A} pathLength={1} d="M8 12.5h5" />
    </>
  ),
  Investigate: () => (
    <>
      <circle cx="10.5" cy="10.5" r="6" />
      <path d="m15 15 5 5" />
      {node(8.5, 9, 1.1, true, true)}
      {node(12.5, 12, 1.1, true, true)}
      <path className={A} d="m9.4 9.7 2.2 1.6" />
    </>
  ),
  ToolCall: () => (
    <>
      <path d="M8 4.5c-2.6 2.5-2.6 12.5 0 15" />
      <path d="M16 4.5c2.6 2.5 2.6 12.5 0 15" />
      {node(12, 12, 1.75, true, true)}
    </>
  ),
  Search: () => (
    <>
      <circle className={A} pathLength={1} cx="10.5" cy="10.5" r="6.25" />
      <path d="m15.25 15.25 4.5 4.5" />
    </>
  ),
  Callers: () => (
    <>
      {node(17.5, 12, 2.5)}
      <path className={A} pathLength={1} d="M4 6.5 14.9 11" />
      <path className={A} pathLength={1} d="M4 12h10.5" />
      <path className={A} pathLength={1} d="M4 17.5 14.9 13" />
    </>
  ),
  Callees: () => (
    <>
      {node(6.5, 12, 2.5)}
      <path className={A} pathLength={1} d="M9.1 11 20 6.5" />
      <path className={A} pathLength={1} d="M9.5 12H20" />
      <path className={A} pathLength={1} d="M9.1 13 20 17.5" />
    </>
  ),
  Impact: () => (
    <>
      {node(12, 12, 2, true)}
      <circle className={A} cx="12" cy="12" r="5.25" />
      <circle className={A} cx="12" cy="12" r="8.5" />
    </>
  ),
  Criticality: () => (
    <>
      <path d="M4 19.5h16" />
      <path className={A} d="M7 17v-3" />
      <path className={A} d="M12 17V9.5" />
      <path className={A} d="M17 17V5" />
    </>
  ),
  ShortestPath: () => (
    <>
      {node(5, 18, 1.75)}
      {node(19, 6, 1.75, true)}
      {node(10.5, 12, 1)}
      {node(13.5, 14, 1)}
      {node(9, 5.5, 1)}
      <path strokeDasharray="1 2" d="M6 16.5 9 7M10 6l7.6-.1" />
      <path className={A} pathLength={1} d="M6.3 16.8 10.5 12l3 2 4.3-6.6" />
    </>
  ),
  Decisions: () => (
    <>
      <path d="M8 3.75h8.5c.69 0 1.25.56 1.25 1.25v13" />
      <rect x="5.25" y="6.25" width="10.5" height="14" rx="1.25" />
      <path className={A} pathLength={1} d="m8 13.5 1.75 1.75 3.25-3.5" />
    </>
  ),
  Tests: () => (
    <>
      <path className={A} pathLength={1} d="m4.5 7 1.5 1.5L8.75 5.5" />
      <path d="M12 7.25h7.5" />
      <path className={A} pathLength={1} d="m4.5 12.5 1.5 1.5 2.75-3" />
      <path d="M12 12.75h7.5" />
      <path className={A} pathLength={1} d="m4.5 18 1.5 1.5 2.75-3" />
      <path d="M12 18.25h5" />
    </>
  ),
  Owners: () => (
    <>
      <circle className={A} cx="12" cy="8.25" r="3.5" />
      <path d="M5.25 20c0-3.73 3.02-6.75 6.75-6.75s6.75 3.02 6.75 6.75" />
    </>
  ),
  Procedures: () => (
    <>
      {node(6, 5.5, 1.5)}
      {node(6, 12, 1.5)}
      {node(6, 18.5, 1.5, true)}
      <path className={A} pathLength={1} d="M6 7v3.5M6 13.5V17" />
      <path d="M10.5 5.5H19M10.5 12H19M10.5 18.5h5.5" />
    </>
  ),
  Evidence: () => (
    <>
      <rect x="3.75" y="4.25" width="16.5" height="15.5" rx="1.75" />
      <path d="M8 9.5c0-1.5.9-2.4 2.25-2.6M8 9.5v2h2V9.5H8Z" />
      <path d="M13 9.5c0-1.5.9-2.4 2.25-2.6M13 9.5v2h2V9.5h-2Z" />
      <path className={A} pathLength={1} d="M7.5 15.5h9" />
    </>
  ),
  Decision: () => (
    <>
      <path d="M12 3.25 20.75 12 12 20.75 3.25 12 12 3.25Z" />
      <path className={A} pathLength={1} d="m8.75 12.25 2.25 2.25 4.25-4.5" />
    </>
  ),
  Conflict: () => (
    <>
      <path d="M12 3.25 20.75 12 12 20.75 3.25 12 12 3.25Z" />
      <path className={A} pathLength={1} d="m9.5 9.5 5 5" />
      <path className={A} pathLength={1} d="m14.5 9.5-5 5" />
    </>
  ),
  PossibleConflict: () => (
    <>
      <path strokeDasharray="2.2 2.4" d="M12 3.25 20.75 12 12 20.75 3.25 12 12 3.25Z" />
      <path className={A} d="M12 8.25v4.5" />
      <circle className={A} cx="12" cy="15.75" r="0.6" fill="currentColor" />
    </>
  ),
  Question: () => (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M9.6 9.6a2.45 2.45 0 1 1 3.4 2.25c-.6.27-1 .86-1 1.52v.38" />
      <circle className={A} cx="12" cy="16.75" r="0.6" fill="currentColor" />
    </>
  ),
  Ticket: () => (
    <>
      <path d="M3.75 7c0-.69.56-1.25 1.25-1.25h14c.69 0 1.25.56 1.25 1.25v2.6a2.4 2.4 0 0 0 0 4.8V17c0 .69-.56 1.25-1.25 1.25H5c-.69 0-1.25-.56-1.25-1.25v-2.6a2.4 2.4 0 0 0 0-4.8V7Z" />
      <path className={A} pathLength={1} strokeDasharray="1.6 2.2" d="M14.5 6.5v11" />
    </>
  ),
  Approval: () => (
    <>
      <rect x="4" y="4" width="16" height="16" rx="4" />
      <path className={A} pathLength={1} d="m8.25 12.25 2.5 2.5 5-5.25" />
    </>
  ),
  Handoff: () => (
    <>
      <path d="M3.5 7.5v9M3.5 12h3.5" />
      <path d="M20.5 7.5v9M20.5 12H17" />
      <g className={A}>{node(12, 12, 2.25, true)}</g>
    </>
  ),
  Build: () => (
    <>
      <rect x="3.75" y="13" width="7" height="7" rx="1" />
      <rect x="13.25" y="13" width="7" height="7" rx="1" />
      <rect className={A} x="8.5" y="4" width="7" height="7" rx="1" />
    </>
  ),
  TestPass: () => (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path className={A} pathLength={1} d="m8.25 12.25 2.5 2.5 5-5.25" />
    </>
  ),
  TestFail: () => (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path className={A} pathLength={1} d="m9.25 9.25 5.5 5.5" />
      <path className={A} pathLength={1} d="m14.75 9.25-5.5 5.5" />
    </>
  ),
  Repair: () => (
    <>
      <path
        className={A}
        d="M14.6 4.6a4.25 4.25 0 0 0-5.15 5.5L4.6 14.95a1.6 1.6 0 1 0 2.27 2.27l4.85-4.85a4.25 4.25 0 0 0 5.5-5.15l-2.45 2.45-2.2-.6-.6-2.2 2.63-2.27Z"
      />
    </>
  ),
  PullRequest: () => (
    <>
      {node(6.5, 5.75, 2)}
      {node(6.5, 18.25, 2)}
      {node(17.5, 18.25, 2)}
      <path d="M6.5 7.75v8.5" />
      <path className={A} pathLength={1} d="M17.5 16.25V9.5c0-1.1-.9-2-2-2h-4.25" />
      <path d="m13 5.5-2 2 2 2" />
    </>
  ),
  MemoryUpdated: () => (
    <>
      <ellipse cx="11" cy="6.25" rx="6.5" ry="2.5" />
      <path d="M4.5 6.25v11.5c0 1.38 2.91 2.5 6.5 2.5" />
      <path d="M17.5 6.25V11" />
      <path d="M4.5 12c0 1.38 2.91 2.5 6.5 2.5" />
      <path className={A} pathLength={1} d="m14.25 17.25 2 2 3.75-4" />
    </>
  ),
  Graph: () => (
    <>
      {node(6, 7, 2)}
      {node(18, 6, 2)}
      {node(12, 18, 2, true)}
      <path className={A} pathLength={1} d="M8 6.85 16 6.15M7 8.75l4 7.5M17 7.75l-4 8.5" />
    </>
  ),
  Inbox: () => (
    <>
      <path d="M3.75 13.25 6.25 5.75h11.5l2.5 7.5V18c0 .69-.56 1.25-1.25 1.25H5c-.69 0-1.25-.56-1.25-1.25v-4.75Z" />
      <path className={A} d="M3.75 13.25H8.5l1.25 2.25h4.5l1.25-2.25h4.75" />
    </>
  ),
  Connect: () => (
    <>
      <path className={A} pathLength={1} d="m10 14 4-4" />
      <path d="m8.75 11.25-2.1 2.1a3 3 0 0 0 4.24 4.24l2.1-2.1" />
      <path d="m15.25 12.75 2.1-2.1a3 3 0 0 0-4.24-4.24l-2.1 2.1" />
    </>
  ),
  Settings: () => (
    <>
      <path d="M4 7h7.75M16.25 7H20M4 17h2.75M11.25 17H20" />
      <g className={A}>
        <circle cx="14" cy="7" r="2.25" />
      </g>
      <circle cx="9" cy="17" r="2.25" />
    </>
  ),
  Home: () => (
    <>
      <rect x="4" y="4.5" width="16" height="4" rx="1" />
      <path className={A} pathLength={1} d="M4 13h16M4 18h11" />
    </>
  ),
  System: () => (
    <>
      {node(4.5, 12, 1.75)}
      {node(12, 5.5, 1.75)}
      {node(12, 18.5, 1.75)}
      {node(19.5, 12, 1.75, true)}
      <path className={A} pathLength={1} d="M6 11 10.6 6.6M6 13l4.6 4.4M13.4 6.6 18 11M13.4 17.4 18 13" />
    </>
  ),
}

export interface GlyphProps extends Omit<SVGProps<SVGSVGElement>, 'name'> {
  name: GlyphName
  size?: number
  animated?: boolean
  /** Accessible name; omit for decorative use next to text. */
  title?: string
}

export function Glyph({ name, size = 20, animated = false, title, className, ...rest }: GlyphProps) {
  const shape = SHAPES[name]
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      role={title ? 'img' : undefined}
      aria-hidden={title ? undefined : true}
      aria-label={title}
      focusable="false"
      data-glyph={name}
      data-motion={GLYPH_MOTION[name]}
      data-animated={animated ? 'true' : 'false'}
      className={['glyph', className].filter(Boolean).join(' ')}
      {...rest}
    >
      {shape()}
    </svg>
  )
}

export function glyphNames(): GlyphName[] {
  return Object.keys(SHAPES) as GlyphName[]
}
