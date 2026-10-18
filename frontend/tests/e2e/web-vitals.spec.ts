import { expect, test } from '@playwright/test'
import { FIXTURE_IDS, fast, open } from './helpers'

/** C-AC-34 (and C-AC-3): LCP and CLS on the Request page during a live scripted investigation. */
test('C-AC-34 the live Request page keeps LCP under 2.5 s and CLS under 0.05', async ({ page }) => {
  await fast(page, 0.3)
  await page.addInitScript(() => {
    const w = window as unknown as { __cls: number; __lcp: number }
    w.__cls = 0
    w.__lcp = 0
    new PerformanceObserver((list) => {
      for (const e of list.getEntries() as (PerformanceEntry & { value: number; hadRecentInput: boolean })[]) if (!e.hadRecentInput) w.__cls += e.value
    }).observe({ type: 'layout-shift', buffered: true })
    new PerformanceObserver((list) => {
      const entries = list.getEntries()
      const last = entries[entries.length - 1]
      if (last) w.__lcp = last.startTime
    }).observe({ type: 'largest-contentful-paint', buffered: true })
  })
  await open(page, `/app/requests/${FIXTURE_IDS.live}`)
  await expect(page.getByTestId('tool-call-card').first()).toBeVisible({ timeout: 20_000 })
  await page.waitForTimeout(3000)
  const { cls, lcp } = await page.evaluate(() => {
    const w = window as unknown as { __cls: number; __lcp: number }
    return { cls: w.__cls, lcp: w.__lcp }
  })
  test.info().annotations.push({ type: 'vitals', description: `LCP ${Math.round(lcp)} ms, CLS ${cls.toFixed(3)}` })
  expect(lcp).toBeLessThan(2500)
  expect(cls).toBeLessThan(0.05)
})

test('C-AC-3 fonts load without shifting the landing headline', async ({ page }) => {
  await page.addInitScript(() => {
    const w = window as unknown as { __cls: number }
    w.__cls = 0
    new PerformanceObserver((list) => {
      for (const e of list.getEntries() as (PerformanceEntry & { value: number; hadRecentInput: boolean })[]) if (!e.hadRecentInput) w.__cls += e.value
    }).observe({ type: 'layout-shift', buffered: true })
  })
  await page.goto('/')
  await page.evaluate(() => document.fonts.ready)
  await page.waitForTimeout(500)
  const cls = await page.evaluate(() => (window as unknown as { __cls: number }).__cls)
  expect(cls).toBeLessThan(0.05)
})
