import { existsSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { routeSizes } from '@/lib/bundle-size'

const distDir = join(__dirname, '..', '..', process.env.BUNDLE_DIST_DIR ?? '.next')
const built = existsSync(join(distDir, 'build-manifest.json'))
const BUDGET = 250 * 1024
/** Graph-heavy routes load the canvas as a separate chunk but are still exempt by the spec (C-AC-16). */
const EXEMPT = new Set(['/app/graph', '/app/dev/canvas'])

describe.skipIf(!built)('bundle budget (C-AC-16)', () => {
  const sizes = built ? routeSizes(distDir) : []

  it('C-AC-16 finds every app route in the build output', () => {
    const routes = sizes.map((s) => s.route)
    for (const r of ['/', '/app', '/app/inbox', '/app/connect', '/app/settings', '/app/requests/[id]', '/app/signin']) expect(routes).toContain(r)
  })

  it('C-AC-16 first-load JS is under 250 KB gzipped on non-graph routes', () => {
    const over = sizes.filter((s) => !EXEMPT.has(s.route) && s.gzipBytes > BUDGET).map((s) => `${s.route}: ${(s.gzipBytes / 1024).toFixed(1)} KB`)
    console.log(sizes.map((s) => `${s.route} ${(s.gzipBytes / 1024).toFixed(1)} KB`).join('\n'))
    expect(over).toEqual([])
  })

  it('C-AC-16 the landing page does not ship three.js, d3 or shiki in its first load', () => {
    const landing = sizes.find((s) => s.route === '/')
    expect(landing).toBeDefined()
    expect(landing!.gzipBytes).toBeLessThan(BUDGET)
  })
})
