import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

const css = readFileSync(join(__dirname, '..', '..', 'styles', 'tokens.css'), 'utf8')
const block = css.slice(css.indexOf(':root {'), css.indexOf('}', css.indexOf(':root {')))
const token = (name: string): string => {
  const m = new RegExp(`${name}:\\s*(#[0-9a-fA-F]{6})`).exec(block)
  if (!m) throw new Error(`missing ${name}`)
  return m[1] as string
}

function luminance(hex: string): number {
  const v = hex.replace('#', '')
  const c = [0, 2, 4].map((i) => parseInt(v.slice(i, i + 2), 16) / 255).map((x) => (x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4))
  return 0.2126 * (c[0] as number) + 0.7152 * (c[1] as number) + 0.0722 * (c[2] as number)
}

export function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number]
  return (hi + 0.05) / (lo + 0.05)
}

const surfaces = ['--ink-0', '--ink-1', '--ink-2', '--ink-3']

describe('C-AC-2 contrast', () => {
  it('C-AC-2 the ratio function matches known WCAG values', () => {
    expect(contrast('#000000', '#ffffff')).toBeCloseTo(21, 1)
    expect(contrast('#ffffff', '#ffffff')).toBeCloseTo(1, 5)
    expect(contrast('#777777', '#ffffff')).toBeCloseTo(4.48, 1)
  })

  it.each(['--text-1', '--text-2'])('C-AC-2 %s meets 4.5:1 on every surface', (text) => {
    for (const s of surfaces) expect(contrast(token(text), token(s)), `${text} on ${s}`).toBeGreaterThanOrEqual(4.5)
  })

  it('C-AC-2 --text-3 meets 4.5:1 on ink-0, ink-1 and ink-2', () => {
    for (const s of ['--ink-0', '--ink-1', '--ink-2']) expect(contrast(token('--text-3'), token(s)), s).toBeGreaterThanOrEqual(4.5)
  })

  // The spec default #808080 gave 4.41:1 here; --text-3 was raised to #858585 (DESIGN.md).
  it('C-AC-2 --text-3 on --ink-3 meets 4.5:1', () => {
    expect(contrast(token('--text-3'), token('--ink-3'))).toBeGreaterThanOrEqual(4.5)
  })

  it('C-AC-2 text-1 is about 17:1 and text-2 about 8.5:1 on ink-0', () => {
    expect(contrast(token('--text-1'), token('--ink-0'))).toBeGreaterThan(16)
    expect(contrast(token('--text-2'), token('--ink-0'))).toBeGreaterThan(8)
  })

  it('C-AC-2 accent ink on the accent meets 4.5:1 (primary buttons)', () => {
    expect(contrast(token('--accent-ink'), token('--accent'))).toBeGreaterThanOrEqual(4.5)
  })

  it.each(['--state-ok', '--state-conflict', '--state-possible', '--state-running', '--state-idle', '--accent'])(
    'C-AC-2 %s meets 4.5:1 as chip text on ink-0, ink-1 and ink-2',
    (state) => {
      for (const s of ['--ink-0', '--ink-1', '--ink-2']) expect(contrast(token(state), token(s)), `${state} on ${s}`).toBeGreaterThanOrEqual(4.5)
    },
  )

  it('C-AC-2 strong borders and node colours meet 3:1 as UI components on ink-0', () => {
    for (const n of ['--node-code', '--node-github', '--node-slack', '--node-linear', '--node-core', '--state-idle', '--graph-link', '--graph-link-focus']) {
      expect(contrast(token(n), token('--ink-0')), n).toBeGreaterThanOrEqual(3)
    }
  })

  it('C-AC-2 disabled text is below AA, so it is reserved for disabled controls that also carry a label', () => {
    expect(contrast(token('--text-disabled'), token('--ink-0'))).toBeLessThan(4.5)
    expect(contrast(token('--text-disabled'), token('--ink-0'))).toBeGreaterThan(2.5)
  })
})
