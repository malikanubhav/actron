import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import { describe, expect, it } from 'vitest'

const root = join(__dirname, '..', '..')
function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) walk(p, out)
    else if (/\.tsx?$/.test(name)) out.push(p)
  }
  return out
}

/*
 * Excluded: next/og image routes and the landing og helper render outside the app with their own formatting,
 * and the hero renders a canvas, not text.
 */
const EXCLUDED = [/opengraph-image\.tsx$/, /components\/landing\/og\.tsx$/, /components\/hero\//]
const files = [...walk(join(root, 'components')), ...walk(join(root, 'app'))].filter((f) => !EXCLUDED.some((r) => r.test(f)))

describe('C-AC-42 formatting goes through lib/format.ts', () => {
  it.each([
    ['.toLocaleString(', /\.toLocaleString\(/],
    ['toLocaleDateString', /toLocaleDateString/],
    ['toLocaleTimeString', /toLocaleTimeString/],
    ['new Intl.', /new Intl\./],
  ])('C-AC-42 no raw %s in components or routes', (_name, re) => {
    const hits = files.filter((f) => re.test(readFileSync(f, 'utf8'))).map((f) => relative(root, f))
    expect(hits).toEqual([])
  })
})
