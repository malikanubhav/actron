import { expect, test } from '@playwright/test'
import { FIXTURE_IDS, open } from './helpers'

test('C-AC-12 canvas holds 60 fps with 300 nodes and 600 links while panning and zooming', async ({ page }) => {
  await open(page, '/app/dev/canvas')
  const canvas = page.getByTestId('bench').locator('canvas')
  await expect(canvas).toBeVisible()
  await page.waitForTimeout(1500)
  await page.evaluate(() => {
    window.__actronFrames = []
    window.__actronMeasure = true
  })
  const box = await canvas.boundingBox()
  if (!box) throw new Error('no canvas')
  const cx = box.x + box.width / 2
  const cy = box.y + box.height / 2
  await page.mouse.move(cx, cy)
  await page.mouse.down()
  for (let i = 0; i < 40; i++) await page.mouse.move(cx + Math.sin(i / 4) * 200, cy + Math.cos(i / 5) * 120)
  await page.mouse.up()
  for (let i = 0; i < 20; i++) await page.mouse.wheel(0, i % 2 ? 120 : -120)
  await page.waitForTimeout(300)
  const frames = await page.evaluate(() => {
    window.__actronMeasure = false
    return (window.__actronFrames ?? []).slice(2)
  })
  expect(frames.length).toBeGreaterThan(20)
  const sorted = [...frames].sort((a, b) => a - b)
  const p95 = sorted[Math.floor(sorted.length * 0.95)] ?? 0
  test.info().annotations.push({ type: 'p95 frame ms', description: p95.toFixed(2) })
  expect(p95).toBeLessThanOrEqual(16.7)
})

test('C-AC-32 list view and keyboard navigation work on the request canvas', async ({ page }) => {
  await open(page, `/app/requests/${FIXTURE_IDS.done}`)
  const canvas = page.locator('[data-testid="graph-canvas"] canvas').first()
  await expect(canvas).toBeVisible()
  await canvas.focus()
  await page.keyboard.press('ArrowRight')
  await expect(page.locator('[data-testid="graph-canvas"] [aria-live="polite"]').first()).not.toBeEmpty()
  await page.keyboard.press('ArrowRight')
  await page.getByRole('button', { name: 'List view' }).click()
  const list = page.getByTestId('graph-list')
  await expect(list).toBeVisible()
  await list.getByRole('button').first().click()
  await expect(list.locator('[aria-current="true"]')).toHaveCount(1)
  await page.getByRole('button', { name: 'Canvas view' }).click()
})

test('explorer search, expand and inspector provenance', async ({ page }) => {
  await open(page, '/app/graph')
  await page.getByTestId('graph-search').fill('evaluate')
  const results = page.getByTestId('graph-results')
  await expect(results.getByRole('button').first()).toBeVisible()
  await results.getByRole('button').first().click()
  await expect(page.getByTestId('node-inspector')).toBeVisible()
  await expect(page.getByTestId('node-inspector')).toContainText('Where it came from')
  await page.getByRole('button', { name: 'Callers' }).click()
  await expect(page.getByTestId('quick-result')).toBeVisible()
})
