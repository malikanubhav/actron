import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import { describe, expect, it } from 'vitest'
import config, { colors, fontSize, borderRadius, transitionDuration, transitionTimingFunction } from '@/tailwind.config'
import { DUR, EASE } from '@/lib/motion'

const root = join(__dirname, '..', '..')
const tokensCss = readFileSync(join(root, 'styles', 'tokens.css'), 'utf8')

export function cssVars(css: string): Map<string, string> {
  const out = new Map<string, string>()
  // Only the first :root block (the defaults); media overrides come later.
  const block = css.slice(css.indexOf(':root {'), css.indexOf('}', css.indexOf(':root {')))
  for (const m of block.matchAll(/(--[\w-]+):\s*([^;]+);/g)) out.set(m[1] as string, (m[2] as string).trim())
  return out
}

const vars = cssVars(tokensCss)

const SPEC_C1_1: Record<string, string> = {
  '--ink-0': '#0a0a0a',
  '--ink-1': '#0f0f0f',
  '--ink-2': '#141414',
  '--ink-3': '#1a1a1a',
  '--line-1': '#1f1f1f',
  '--line-2': '#2a2a2a',
  '--text-1': '#ededed',
  '--text-2': '#b4b4b4', // raised from the spec default #a8a8a8 so secondary sentences read on black; recorded in DESIGN.md
  '--text-3': '#858585', // raised from the spec default #808080 for AA on --ink-3; recorded in DESIGN.md
  '--accent': '#e4f24c',
  '--accent-ink': '#0a0a0a',
  '--state-ok': '#4cc38a',
  '--state-conflict': '#f2555a',
  '--state-possible': '#f0a44b',
  '--state-running': '#5bc0eb',
  '--state-idle': '#8c8c8c',
  // Node colours changed from the spec's near-greys so sources read apart at a glance (UI-REVIEW.md, DESIGN.md).
  '--node-code': '#97a8c0',
  '--node-github': '#c8b08e',
  '--node-slack': '#c77ddb',
  '--node-linear': '#6f8df5',
  '--node-core': '#e58fa8', // not the accent: only the evidence path is yellow
}

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) walk(p, out)
    else if (/\.tsx?$/.test(name)) out.push(p)
  }
  return out
}

function referencedVars(value: unknown, out: string[] = []): string[] {
  if (typeof value === 'string') for (const m of value.matchAll(/var\((--[\w-]+)\)/g)) out.push(m[1] as string)
  else if (Array.isArray(value)) value.forEach((v) => referencedVars(v, out))
  else if (value && typeof value === 'object') Object.values(value).forEach((v) => referencedVars(v, out))
  return out
}

/*
 * Files excluded from the literal scan, each for a reason:
 * - components/brand/simple-paths.ts: generated brand data (official brand hex colours, not design tokens).
 * - app/**\/opengraph-image.tsx and components/landing/og.tsx: rendered by next/og into a PNG, where CSS variables do not exist.
 * - components/hero/**: WebGL shader code and three.js colours; read from tokens at runtime where possible.
 * - app/layout.tsx and app/manifest.ts: the browser theme colour in metadata must be a literal colour value.
 */
const EXCLUDED = [/simple-paths\.ts$/, /opengraph-image\.tsx$/, /components\/landing\/og\.tsx$/, /components\/hero\//, /app\/layout\.tsx$/, /app\/manifest\.ts$/]

/** Violations found by this test and reported to the lead; listed so the rest of the scan stays strict. */
const KNOWN_SPACING_BUGS: string[] = []

const sources = [...walk(join(root, 'components')), ...walk(join(root, 'app'))].filter((f) => !EXCLUDED.some((r) => r.test(f)))

describe('C-AC-1 tokens', () => {
  it('C-AC-1 every colour token from spec C1.1 exists with the exact value', () => {
    for (const [name, hex] of Object.entries(SPEC_C1_1)) expect(vars.get(name)?.toLowerCase(), name).toBe(hex)
  })

  it('C-AC-1 spacing tokens follow the 4-point scale from spec C1.3', () => {
    const scale = [2, 4, 8, 12, 16, 20, 24, 32, 40, 48, 64, 80, 96]
    const space = [...vars.entries()].filter(([k]) => k.startsWith('--space-')).map(([, v]) => parseInt(v, 10))
    expect(space.sort((a, b) => a - b)).toEqual(scale)
  })

  it('C-AC-1 radius and motion tokens match spec C1.3 and C1.4', () => {
    expect(vars.get('--radius-sm')).toBe('4px')
    expect(vars.get('--radius-md')).toBe('6px')
    expect(vars.get('--radius-lg')).toBe('10px')
    expect(vars.get('--dur-1')).toBe('120ms')
    expect(vars.get('--dur-4')).toBe('520ms')
    expect(vars.get('--ease-standard')).toBe('cubic-bezier(0.2, 0, 0, 1)')
    expect(vars.get('--ease-emphasized')).toBe('cubic-bezier(0.3, 0, 0, 1)')
    expect(vars.get('--ease-exit')).toBe('cubic-bezier(0.4, 0, 1, 1)')
  })

  it('C-AC-1 the type scale has the eleven sizes of spec C1.2', () => {
    const sizes = [12, 13, 14, 16, 18, 22, 28, 36, 48, 64, 80]
    const fs = [...vars.entries()].filter(([k]) => k.startsWith('--fs-')).map(([, v]) => parseInt(v, 10))
    expect(fs.sort((a, b) => a - b)).toEqual(sizes)
  })

  it('C-AC-1 every Tailwind theme value references a CSS variable defined in tokens.css', () => {
    const refs = referencedVars([colors, fontSize, borderRadius, transitionDuration, transitionTimingFunction, config.theme])
    expect(refs.length).toBeGreaterThan(40)
    const missing = refs.filter((r) => !vars.has(r) && !r.startsWith('--font-newsreader') && !r.startsWith('--font-public-sans') && !r.startsWith('--font-jetbrains'))
    expect(missing).toEqual([])
  })

  it('C-AC-1 JavaScript motion tokens equal the CSS motion tokens', () => {
    for (const [k, ms] of Object.entries(DUR)) expect(vars.get(`--dur-${k}`)).toBe(`${ms}ms`)
    const toCss = (e: number[]) => `cubic-bezier(${e.join(', ')})`
    expect(toCss(EASE.standard)).toBe(vars.get('--ease-standard'))
    expect(toCss(EASE.emphasized)).toBe(vars.get('--ease-emphasized'))
    expect(toCss(EASE.exit)).toBe(vars.get('--ease-exit'))
  })

  it('C-AC-1 the scan covers the component and app sources', () => {
    expect(sources.length).toBeGreaterThan(40)
  })

  it('C-AC-1 no hex colour literals in components or app code', () => {
    const offenders: string[] = []
    for (const file of sources) {
      const text = readFileSync(file, 'utf8')
      for (const m of text.matchAll(/['"`(\s:]#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b/g)) {
        offenders.push(`${relative(root, file)}: ${m[0].trim()}`)
      }
    }
    expect(offenders).toEqual([])
  })

  it('C-AC-1 no pixel values in Tailwind arbitrary values', () => {
    const offenders: string[] = []
    for (const file of sources) {
      const text = readFileSync(file, 'utf8')
      for (const m of text.matchAll(/[\w:-]+-\[[^\]]*\d+px[^\]]*\]/g)) offenders.push(`${relative(root, file)}: ${m[0]}`)
    }
    expect(offenders).toEqual([])
  })

  const spacingOffenders = () => {
    const allowed = new Set(['0', 'px', '0.5', '1', '1.5', '2', '3', '4', '5', '6', '8', '10', '12', '16', '20', '24', 'auto', 'page', 'gutter', 'rail', 'status', 'guide'])
    const offenders: string[] = []
    const re = /(?:^|[\s"'`])-?(?:[a-z]+:)*(p|px|py|pt|pb|pl|pr|m|mx|my|mt|mb|ml|mr|gap|gap-x|gap-y|space-x|space-y)-([\w.]+)(?=[\s"'`]|$)/g
    for (const file of sources) {
      const text = readFileSync(file, 'utf8')
      for (const cls of text.matchAll(/className=(?:"([^"]*)"|\{[^}]*\})/g)) {
        const chunk = cls[0]
        for (const m of chunk.matchAll(re)) {
          if (!allowed.has(m[2] as string)) offenders.push(`${relative(root, file)}: ${m[0].trim()}`)
        }
      }
    }
    return offenders
  }

  it('C-AC-1 spacing utilities use only the 4-point scale', () => {
    expect(spacingOffenders().filter((o) => !KNOWN_SPACING_BUGS.includes(o))).toEqual([])
  })

})
