/**
 * Screenshots from the real stack (compose: frontend :3000, backend behind it), no fixtures.
 * Signs in with the dev login, then captures the main screens and real requests at 1440 and 1920
 * into tests/screenshots/real/. Usage: REAL_REQUEST_IDS=req_a,req_b npx tsx scripts/capture-real.ts
 */
import { chromium } from '@playwright/test'
import { mkdirSync } from 'node:fs'
import { join } from 'node:path'

const base = process.env.CAPTURE_BASE_URL ?? 'http://127.0.0.1:3000'
const outDir = join(import.meta.dirname, '..', 'tests', 'screenshots', 'real')
const requests = (process.env.REAL_REQUEST_IDS ?? '').split(',').filter(Boolean)

const shots: { name: string; path: string; wait?: number }[] = [
  { name: 'home', path: '/app' },
  { name: 'connect', path: '/app/connect', wait: 2500 },
  { name: 'graph', path: '/app/graph', wait: 2500 },
  { name: 'system', path: '/app/system' },
  { name: 'inbox', path: '/app/inbox' },
  { name: 'settings', path: '/app/settings' },
  { name: 'landing', path: '/', wait: 2500 },
  { name: 'notfound', path: '/app/does-not-exist' },
  ...requests.flatMap((id, i) => [
    { name: `request-${i + 1}-evidence`, path: `/app/requests/${id}?tab=evidence`, wait: 3000 },
    { name: `request-${i + 1}-ticket`, path: `/app/requests/${id}?tab=ticket`, wait: 1500 },
    { name: `request-${i + 1}-build`, path: `/app/requests/${id}?tab=build`, wait: 1500 },
  ]),
]

async function main(): Promise<void> {
  mkdirSync(outDir, { recursive: true })
  const browser = await chromium.launch()
  for (const width of [1440, 1920]) {
    const context = await browser.newContext({ viewport: { width, height: width === 1440 ? 900 : 1080 } })
    const page = await context.newPage()
    const login = await page.request.post(`${base}/api/auth/dev-login`, { data: { name: 'Vikram' } })
    if (!login.ok()) throw new Error(`dev login failed: ${login.status()}`)
    for (const shot of shots) {
      await page.goto(`${base}${shot.path}`, { waitUntil: 'networkidle' })
      await page.waitForTimeout(shot.wait ?? 1200)
      await page.screenshot({ path: join(outDir, `${shot.name}-${width}.png`) })
      if (shot.name === 'landing') await page.screenshot({ path: join(outDir, `landing-full-${width}.png`), fullPage: true })
      console.log(`captured ${shot.name}-${width}`)
    }
    await context.close()
  }
  await browser.close()
}

void main()
