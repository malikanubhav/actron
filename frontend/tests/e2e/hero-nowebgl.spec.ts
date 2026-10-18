import { expect, test } from '@playwright/test'

// A separate file because launch options force a new browser worker.
test.use({ launchOptions: { args: ['--disable-webgl', '--disable-3d-apis'] } })

test('C-AC-28 shows the static image when WebGL is unavailable', async ({ page }) => {
  await page.addInitScript(() => Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 }))
  await page.goto('/')
  await expect(page.getByTestId('hero-visual')).toHaveAttribute('data-hero-mode', 'fallback')
  await expect(page.getByTestId('hero-fallback')).toBeVisible()
})
