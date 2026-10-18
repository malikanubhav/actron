/**
 * Motion tokens for JavaScript animation (motion/react, canvas). Mirrors --dur-* and --ease-* in
 * styles/tokens.css; tests/unit/tokens.test.ts keeps them equal.
 */
export const DUR = {
  1: 120,
  2: 200,
  3: 320,
  4: 520,
  5: 900,
} as const

export const EASE = {
  standard: [0.2, 0, 0, 1] as [number, number, number, number],
  emphasized: [0.3, 0, 0, 1] as [number, number, number, number],
  exit: [0.4, 0, 1, 1] as [number, number, number, number],
}

export const sec = (ms: number) => ms / 1000

/** Evidence path: 520 ms per hop, plus 300 ms to settle (C-AC-13). */
export function pathTraceBudgetMs(hops: number): number {
  return hops * DUR[4] + 300
}

/** Cubic bezier evaluation for canvas animation that must match the CSS easing. */
export function cubicBezier(p1x: number, p1y: number, p2x: number, p2y: number) {
  const cx = 3 * p1x
  const bx = 3 * (p2x - p1x) - cx
  const ax = 1 - cx - bx
  const cy = 3 * p1y
  const by = 3 * (p2y - p1y) - cy
  const ay = 1 - cy - by
  const sampleX = (t: number) => ((ax * t + bx) * t + cx) * t
  const sampleY = (t: number) => ((ay * t + by) * t + cy) * t
  const sampleDX = (t: number) => (3 * ax * t + 2 * bx) * t + cx
  return (x: number): number => {
    if (x <= 0) return 0
    if (x >= 1) return 1
    let t = x
    for (let i = 0; i < 8; i++) {
      const err = sampleX(t) - x
      if (Math.abs(err) < 1e-5) break
      const d = sampleDX(t)
      if (Math.abs(d) < 1e-6) break
      t -= err / d
    }
    return sampleY(Math.min(1, Math.max(0, t)))
  }
}

export const easeEmphasized = cubicBezier(...EASE.emphasized)
export const easeStandard = cubicBezier(...EASE.standard)
