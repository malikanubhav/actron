import { expect, test } from '@playwright/test'
import { open } from './helpers'

for (const scale of [1, 2] as const) {
  test.describe(`glyphs at ${scale}x`, () => {
    test.use({ deviceScaleFactor: scale })
    test(`C-AC-4 every glyph renders static and animated at ${scale}x`, async ({ page }) => {
      await page.emulateMedia({ reducedMotion: 'reduce' })
      await open(page, '/app/dev/glyphs')
      const grid = page.getByTestId('glyph-grid')
      const cells = grid.locator('[data-glyph-cell]')
      expect(await cells.count()).toBeGreaterThanOrEqual(31)
      for (const cell of await cells.all()) {
        await expect(cell.locator('svg[data-animated="false"]')).toHaveCount(1)
        await expect(cell.locator('svg[data-animated="true"]')).toHaveCount(1)
      }
      await expect(grid).toHaveScreenshot(`glyphs-${scale}x.png`, { maxDiffPixelRatio: 0.01 })
    })
  })
}

test('C-AC-5 every brand mark loads', async ({ page }) => {
  await open(page, '/app/dev/glyphs')
  const images = page.getByTestId('brand-grid').locator('img')
  for (const img of await images.all()) {
    await expect.poll(async () => img.evaluate((el) => (el as HTMLImageElement).naturalWidth)).toBeGreaterThan(0)
  }
  const res = await page.request.get('/brands/LICENSES.md')
  expect(res.status()).toBe(200)
})
