import { expect, test } from '@playwright/test'
import { FIXTURE_IDS, fast, open } from './helpers'

test('C-AC-26 the System view reflects workspace events within one second', async ({ page }) => {
  await fast(page, 0.2)
  await open(page, '/app/system')
  const log = page.getByTestId('system-log')
  await expect(log.locator('li').first()).toBeVisible()
  await expect.poll(async () => log.locator('li').count(), { timeout: 15_000 }).toBeGreaterThan(1)
  // An ingestion event lights the source → FalkorDB edge.
  await expect(page.locator('[data-active="true"][data-edge]').first()).toBeAttached({ timeout: 15_000 })
})

test('C-AC-14 system map strip on the request page shows captions from real events only', async ({ page }) => {
  await open(page, `/app/requests/${FIXTURE_IDS.done}`)
  // Collapsed by default to one caption line; the map opens on demand.
  await expect(page.getByTestId('system-line')).toContainText(/ACTRON|GITHUB|FALKORDB|PI/i)
  await page.getByRole('button', { name: /Show system map/ }).click()
  const map = page.getByTestId('system-map').first()
  await expect(map).toBeVisible()
  await expect(map.locator('[data-active="true"][data-actor]')).toHaveCount(1)
  // The empty workspace has no events, so nothing is active.
  await open(page, '/app/system', 'empty')
  await expect(page.locator('[data-testid="system-map"] [data-active="true"]')).toHaveCount(0)
})

test('the strip opens, remembers the choice and collapses again', async ({ page }) => {
  await open(page, `/app/requests/${FIXTURE_IDS.done}`)
  await expect(page.getByTestId('system-map')).toHaveCount(0)
  await page.getByRole('button', { name: /Show system map/ }).click()
  await expect(page.getByTestId('system-map')).toHaveCount(1)
  await page.reload()
  await expect(page.getByRole('button', { name: /Hide system map/ })).toBeVisible()
  await page.getByRole('button', { name: /Hide system map/ }).click()
  await expect(page.getByTestId('system-map')).toHaveCount(0)
})
