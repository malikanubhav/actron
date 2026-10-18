/**
 * Captures screenshots from the running app (spec C, C-AC-21, C-AC-38):
 * - every screen and main state at 1440 and 1920 into tests/screenshots/ (review loop and README),
 * - the five landing journey images into public/landing/journey-0N.png (1440×900).
 * Runs against the fixture build: `npm run build:fixtures`, then `npx tsx scripts/capture-screens.ts`
 * (it starts `next start` on port 3100 unless CAPTURE_BASE_URL is set).
 */
import { chromium, type Page } from '@playwright/test'
import { spawn, type ChildProcess } from 'node:child_process'
import { mkdirSync, rmSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { FIXTURE_IDS } from '../tests/fixtures/data/ids'

const root = join(import.meta.dirname, '..')
const base = process.env.CAPTURE_BASE_URL ?? 'http://127.0.0.1:3100'
const outDir = join(root, 'tests', 'screenshots')
const landingDir = join(root, 'public', 'landing')
const only = process.env.CAPTURE_ONLY ? new Set(process.env.CAPTURE_ONLY.split(',')) : null

interface Shot {
  name: string
  path: string
  scenario?: 'empty' | 'backend-down'
  prepare?: (page: Page) => Promise<void>
  fullPage?: boolean
}

const R = (id: string, tab?: string) => `/app/requests/${id}${tab ? `?tab=${tab}` : ''}`

const SHOTS: Shot[] = [
  {
    name: 'landing',
    path: '/',
    fullPage: true,
    prepare: async (page) => {
      // Scroll through once so the journey reveal runs, then return to the top.
      await page.evaluate(async () => {
        for (let y = 0; y < document.body.scrollHeight; y += 600) {
          window.scrollTo(0, y)
          await new Promise((r) => setTimeout(r, 120))
        }
        window.scrollTo(0, 0)
      })
      await page.waitForTimeout(1500)
    },
  },
  { name: 'signin', path: '/app/signin' },
  { name: 'home', path: '/app' },
  { name: 'home-empty', path: '/app', scenario: 'empty' },
  { name: 'home-backend-down', path: '/app', scenario: 'backend-down' },
  { name: 'connect', path: '/app/connect' },
  { name: 'connect-empty', path: '/app/connect', scenario: 'empty' },
  {
    name: 'connect-guide',
    path: '/app/connect',
    prepare: async (page) => {
      await page.getByRole('button', { name: /Set up step by step/ }).first().click()
      await page.waitForTimeout(600)
    },
  },
  { name: 'request-done-evidence', path: R(FIXTURE_IDS.done, 'evidence') },
  {
    name: 'request-done-path',
    path: R(FIXTURE_IDS.done, 'evidence'),
    prepare: async (page) => {
      await page.getByRole('button', { name: 'Show path' }).first().click()
      await page.waitForTimeout(3500)
    },
  },
  { name: 'request-live-investigating', path: R(FIXTURE_IDS.live), prepare: async (page) => void (await page.waitForTimeout(4000)) },
  { name: 'request-stale-ticket', path: R(FIXTURE_IDS.stale, 'ticket') },
  { name: 'request-building', path: R(FIXTURE_IDS.building, 'build') },
  { name: 'request-failed', path: R(FIXTURE_IDS.failed, 'build') },
  { name: 'request-pr-ready', path: R(FIXTURE_IDS.prReady, 'pr'), prepare: async (page) => void (await page.waitForTimeout(1500)) },
  { name: 'request-cancelled', path: R(FIXTURE_IDS.cancelled) },
  { name: 'request-answered', path: R(FIXTURE_IDS.answered) },
  { name: 'request-nothing-found', path: R(FIXTURE_IDS.nothing, 'evidence') },
  {
    name: 'replay',
    path: `${R(FIXTURE_IDS.done)}/replay`,
    prepare: async (page) => {
      for (let i = 0; i < 24; i++) await page.getByRole('button', { name: 'Step forward' }).click()
      await page.waitForTimeout(500)
    },
  },
  { name: 'public-replay', path: `/replay/${FIXTURE_IDS.done}` },
  { name: 'inbox', path: '/app/inbox' },
  {
    name: 'graph',
    path: '/app/graph',
    prepare: async (page) => {
      await page.getByTestId('graph-search').fill('evaluate')
      await page.getByTestId('graph-results').getByRole('button').first().click()
      await page.waitForTimeout(2000)
    },
  },
  { name: 'system', path: '/app/system', prepare: async (page) => void (await page.waitForTimeout(3000)) },
  { name: 'settings', path: '/app/settings' },
  {
    name: 'palette',
    path: '/app',
    prepare: async (page) => {
      await page.keyboard.press('Control+k')
      await page.getByRole('combobox').fill('ev')
      await page.waitForTimeout(500)
    },
  },
  { name: 'not-found', path: '/app/no-such-screen' },
  { name: 'glyphs', path: '/app/dev/glyphs', fullPage: true },
]

/**
 * Landing journey images: a crop of the two whole columns that tell each step, at 2x so the text stays
 * readable when the image is shown at 60% of the page width.
 */
type Pair = ['Timeline' | 'Graph' | 'Details', 'Timeline' | 'Graph' | 'Details']
const JOURNEY: { file: string; path: string; columns: Pair; prepare?: (page: Page) => Promise<void> }[] = [
  { file: 'journey-01.png', path: R(FIXTURE_IDS.live), columns: ['Timeline', 'Graph'], prepare: async (page) => void (await page.waitForTimeout(6000)) },
  {
    file: 'journey-02.png',
    path: R(FIXTURE_IDS.done, 'evidence'),
    columns: ['Graph', 'Details'],
    prepare: async (page) => {
      await page.getByRole('button', { name: 'Show path' }).first().click()
      await page.waitForTimeout(3500)
      // Clicking scrolls the evidence list; the shot starts at its first line.
      await page
        .locator('section[aria-label="Details"]')
        .first()
        .evaluate((root) => {
          for (const el of [root, ...root.querySelectorAll('*')]) if (el.scrollTop > 0) el.scrollTop = 0
        })
      await page.waitForTimeout(200)
    },
  },
  { file: 'journey-03.png', path: R(FIXTURE_IDS.stale, 'ticket'), columns: ['Graph', 'Details'] },
  { file: 'journey-04.png', path: R(FIXTURE_IDS.building, 'build'), columns: ['Graph', 'Details'] },
  { file: 'journey-05.png', path: R(FIXTURE_IDS.prReady, 'pr'), columns: ['Graph', 'Details'], prepare: async (page) => void (await page.waitForTimeout(1500)) },
]

async function columnsClip(page: Page, columns: Pair) {
  // Long headers push the columns past the viewport; scroll so their bottom edge sits above the status bar.
  await page.evaluate((name) => {
    const el = document.querySelector(`section[aria-label="${name}"]`)
    if (!el) return
    const overflow = el.getBoundingClientRect().bottom - (window.innerHeight - 40)
    if (overflow > 0) window.scrollBy(0, overflow)
  }, columns[0])
  await page.waitForTimeout(150)
  const boxes = await Promise.all(columns.map((c) => page.locator(`section[aria-label="${c}"]`).first().boundingBox()))
  const [a, b] = boxes
  if (!a || !b) throw new Error('columns not found')
  const x = Math.min(a.x, b.x)
  const width = Math.max(a.x + a.width, b.x + b.width) - x
  const y = Math.min(a.y, b.y)
  // Never below the viewport's status bar (32 px) or the columns.
  const viewport = page.viewportSize()
  const bottom = Math.min(Math.max(a.y + a.height, b.y + b.height), (viewport?.height ?? 880) - 34)
  // The whole panels, ending at their bottom edge: a fixed 16:10 cut through legends and text mid-line.
  return { x, y, width, height: Math.round(bottom - y) }
}

async function waitReady(page: Page, path: string) {
  await page.getByTestId('dev-fixtures-badge').first().waitFor({ state: 'visible', timeout: 20_000 })
  if (path.startsWith('/app') && !path.startsWith('/app/signin')) await page.getByTestId('footer-status').waitFor({ timeout: 20_000 })
  await page.waitForLoadState('networkidle').catch(() => undefined)
  await page.waitForTimeout(800)
}

async function startServer(): Promise<ChildProcess | null> {
  if (process.env.CAPTURE_BASE_URL) return null
  // The image optimiser caches by URL; re-captured journey images must not be served from the old cache.
  rmSync(join(root, '.next-fixtures', 'cache', 'images'), { recursive: true, force: true })
  const child = spawn('sh', ['-c', 'node scripts/prepare-msw.mjs && npx next start --port 3100'], {
    cwd: root,
    env: { ...process.env, NEXT_DIST_DIR: '.next-fixtures', NEXT_PUBLIC_ACTRON_DEV_FIXTURES: '1' },
    stdio: 'ignore',
    detached: true,
  })
  for (let i = 0; i < 60; i++) {
    try {
      const res = await fetch(base)
      if (res.ok) return child
    } catch {
      // not up yet
    }
    await new Promise((r) => setTimeout(r, 1000))
  }
  throw new Error('server did not start')
}

async function main() {
  mkdirSync(outDir, { recursive: true })
  mkdirSync(landingDir, { recursive: true })
  const server = await startServer()
  const browser = await chromium.launch()
  try {
    for (const width of [1440, 1920] as const) {
      const context = await browser.newContext({ viewport: { width, height: width === 1440 ? 900 : 1080 }, colorScheme: 'dark' })
      await context.addInitScript(() => {
        ;(window as unknown as { __actronFixtureSpeed: number }).__actronFixtureSpeed = 0.3
        ;(window as unknown as { __actronFixtureSlackApproval: boolean }).__actronFixtureSlackApproval = false
      })
      for (const shot of SHOTS) {
        if (only && !only.has(shot.name)) continue
        const page = await context.newPage()
        const url = `${base}${shot.path}${shot.scenario ? `${shot.path.includes('?') ? '&' : '?'}fixture=${shot.scenario}` : ''}`
        await page.goto(url)
        await waitReady(page, shot.path)
        if (shot.prepare) await shot.prepare(page)
        await page.screenshot({ path: join(outDir, `${shot.name}-${width}.png`), fullPage: shot.fullPage ?? false })
        console.log(`captured ${shot.name}-${width}`)
        await page.close()
      }
      await context.close()
    }
    if (!only || only.has('journey')) {
      const context = await browser.newContext({ viewport: { width: 1440, height: 880 }, deviceScaleFactor: 2, colorScheme: 'dark' })
      await context.addInitScript(() => {
        ;(window as unknown as { __actronFixtureSpeed: number }).__actronFixtureSpeed = 0.3
        ;(window as unknown as { __actronFixtureSlackApproval: boolean }).__actronFixtureSlackApproval = false
        // The DEV FIXTURES badge stays in the full-page captures; these crops show fixture data until they are
        // re-captured against a real workspace (CAPTURE_BASE_URL=<real app>).
      })
      writeFileSync(
        join(landingDir, 'journey.json'),
        `${JSON.stringify({ source: process.env.CAPTURE_BASE_URL ? 'live' : 'fixtures', capturedAt: new Date().toISOString() }, null, 2)}\n`,
      )
      for (const j of JOURNEY) {
        const page = await context.newPage()
        await page.goto(`${base}${j.path}`)
        await waitReady(page, j.path)
        if (j.prepare) await j.prepare(page)
        await page.screenshot({ path: join(landingDir, j.file), clip: await columnsClip(page, j.columns) })
        console.log(`captured ${j.file}`)
        await page.close()
      }
      await context.close()
    }
  } finally {
    await browser.close()
    // The server runs in its own process group (sh → next start); stop the whole group.
    if (server?.pid) process.kill(-server.pid, 'SIGTERM')
  }
}

main().catch((error: unknown) => {
  console.error(error)
  process.exit(1)
})
