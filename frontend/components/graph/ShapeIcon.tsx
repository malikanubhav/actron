import type { NodeShape } from './model'

function polygonPoints(c: number, r: number, sides: number, offset: number): string {
  return Array.from({ length: sides }, (_, i) => {
    const a = ((Math.PI * 2) / sides) * i + offset
    return `${c + Math.cos(a) * r},${c + Math.sin(a) * r}`
  }).join(' ')
}

/** Shape glyph for the DOM legend, list view and inspector; the same shapes the canvas draws. */
export function ShapeIcon({ shape, color, size = 12 }: { shape: NodeShape; color: string; size?: number }) {
  const s = size
  const c = s / 2
  const r = s * 0.38
  const common = { fill: shape === 'ring' ? 'none' : color, stroke: color, strokeWidth: shape === 'ring' ? 1.5 : 0 }
  let el: React.ReactNode
  switch (shape) {
    case 'square':
      el = <rect x={c - r} y={c - r} width={r * 2} height={r * 2} rx={1} {...common} />
      break
    case 'diamond':
      el = <path d={`M${c} ${c - r * 1.2}L${c + r * 1.2} ${c}L${c} ${c + r * 1.2}L${c - r * 1.2} ${c}Z`} {...common} />
      break
    case 'triangle':
      el = <path d={`M${c} ${c - r * 1.1}L${c + r * 1.1} ${c + r * 0.85}L${c - r * 1.1} ${c + r * 0.85}Z`} {...common} />
      break
    case 'hexagon':
      el = <polygon points={polygonPoints(c, r * 1.08, 6, Math.PI / 6)} {...common} />
      break
    case 'pill':
      el = <rect x={c - r * 1.3} y={c - r * 0.75} width={r * 2.6} height={r * 1.5} rx={r * 0.75} {...common} />
      break
    case 'speech':
      el = (
        <path
          d={`M${c - r} ${c - r * 0.9}H${c + r}V${c + r * 0.5}H${c - r * 0.05}L${c - r * 0.7} ${c + r * 1.05}L${c - r * 0.55} ${c + r * 0.5}H${c - r}Z`}
          {...common}
        />
      )
      break
    case 'file': {
      const w = r * 0.8
      const k = r * 0.5
      el = <path d={`M${c - w} ${c - r}L${c + w - k} ${c - r}L${c + w} ${c - r + k}L${c + w} ${c + r}L${c - w} ${c + r}Z`} {...common} />
      break
    }
    default:
      el = <circle cx={c} cy={c} r={r} {...common} />
  }
  return (
    <svg width={s} height={s} viewBox={`0 0 ${s} ${s}`} aria-hidden className="shrink-0">
      {el}
    </svg>
  )
}
