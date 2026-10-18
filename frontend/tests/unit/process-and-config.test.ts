import { existsSync, readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

const root = join(__dirname, '..', '..')
const repo = join(root, '..')

describe('fonts (C-AC-3)', () => {
  const layout = readFileSync(join(root, 'app', 'layout.tsx'), 'utf8')
  it('C-AC-3 loads all three families through next/font with display swap and a Latin subset', () => {
    expect(layout).toMatch(/from 'next\/font\/google'/)
    for (const family of ['Newsreader', 'Public_Sans', 'JetBrains_Mono']) expect(layout).toContain(family)
    expect(layout.match(/display: 'swap'/g)?.length).toBe(3)
    expect(layout.match(/subsets: \['latin'\]/g)?.length).toBe(3)
  })
  it('C-AC-3 never names a banned primary face', () => {
    const css = readFileSync(join(root, 'styles', 'tokens.css'), 'utf8')
    for (const banned of ['Inter', 'Roboto', 'Arial', 'Space Grotesk', 'system-ui']) expect(css).not.toContain(`'${banned}'`)
  })
})

describe('Lighthouse CI (C-AC-33, C-AC-45)', () => {
  const desktop = JSON.parse(readFileSync(join(root, 'lighthouserc.json'), 'utf8'))
  const mobile = JSON.parse(readFileSync(join(root, 'lighthouserc.mobile.json'), 'utf8'))
  it('C-AC-33 runs on the four routes of spec C, C8', () => {
    const urls: string[] = desktop.ci.collect.url
    for (const path of ['/', '/app', '/app/requests/', '/app/connect']) expect(urls.some((u) => new URL(u).pathname.startsWith(path))).toBe(true)
  })
  it('C-AC-33 measures a real finished request, not the fixture one', () => {
    const request = (desktop.ci.collect.url as string[]).find((u) => u.includes('/app/requests/'))
    expect(request).toMatch(/\/app\/requests\/req_[0-9A-Z]{26}$/)
    expect(request).not.toContain('req_01JCALVA0DONE')
  })
  it('C-AC-33 asserts the PROMPT 8.8a targets', () => {
    const all = desktop.ci.assert.assertMatrix.flatMap((m: { assertions: Record<string, [string, { minScore?: number; maxNumericValue?: number }]> }) =>
      Object.entries(m.assertions),
    ) as [string, [string, { minScore?: number; maxNumericValue?: number }]][]
    const get = (key: string) => all.find(([k]) => k === key)?.[1][1]
    expect(get('categories:performance')?.minScore).toBe(0.9)
    expect(get('categories:accessibility')?.minScore).toBe(0.95)
    expect(get('categories:best-practices')?.minScore).toBe(0.95)
    expect(get('categories:seo')?.minScore).toBe(0.9)
    expect(get('largest-contentful-paint')?.maxNumericValue).toBe(2500)
    expect(get('cumulative-layout-shift')?.maxNumericValue).toBe(0.05)
  })
  it('C-AC-45 has a mobile landing run with Performance at least 0.85', () => {
    expect(mobile.ci.collect.settings.formFactor).toBe('mobile')
    expect(mobile.ci.assert.assertions['categories:performance'][1].minScore).toBe(0.85)
  })
})

describe('design process evidence (C-AC-37, C-AC-38, C-AC-48)', () => {
  const log = existsSync(join(repo, 'BUILD-LOG.md')) ? readFileSync(join(repo, 'BUILD-LOG.md'), 'utf8') : ''
  it('C-AC-37 logs at least two review rounds that cover Request and Connect', () => {
    expect(log).toMatch(/Review round 1/)
    expect(log).toMatch(/Review round 2/)
    expect(log).toMatch(/Review round 1[\s\S]*Request[\s\S]*Connect/)
  })
  it('C-AC-48 logs at least two AI-look audit rounds', () => {
    expect((log.match(/AI-look audit, round \d/g) ?? []).length).toBeGreaterThanOrEqual(2)
  })
  it('C-AC-38 has every screen at 1440 and 1920 and the README references them', () => {
    const dir = join(root, 'tests', 'screenshots')
    const files = existsSync(dir) ? readdirSync(dir) : []
    const screens = ['landing', 'signin', 'home', 'connect', 'request-done-evidence', 'replay', 'inbox', 'graph', 'system', 'settings', 'not-found']
    for (const s of screens) {
      expect(files, s).toContain(`${s}-1440.png`)
      expect(files, s).toContain(`${s}-1920.png`)
    }
    expect(readFileSync(join(root, 'README.md'), 'utf8')).toContain('tests/screenshots/')
  })
})
