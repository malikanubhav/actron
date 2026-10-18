import { expect, test } from '@playwright/test'

declare global {
  interface Window {
    __actronHeroFrames?: number
  }
}

test.describe('3D hero', () => {
  test('C-AC-27 the headline paints before the hero visual loads', async ({ page }) => {
    await page.goto('/')
    const html = await (await page.request.get('/')).text()
    expect(html).toContain('know what your team already decided')
    // The visual is empty in server HTML; it fills in after the browser is idle.
    expect(html).toMatch(/data-hero-mode="waiting"/)
  })

  test.describe('reduced motion', () => {
    test.use({ reducedMotion: 'reduce' })
    test('C-AC-28 shows the static image under reduced motion', async ({ page }) => {
      await page.goto('/')
      await expect(page.getByTestId('hero-visual')).toHaveAttribute('data-hero-mode', 'fallback')
      await expect(page.getByTestId('hero-fallback')).toBeVisible()
      await expect(page.locator('[data-testid="hero-scene"] canvas')).toHaveCount(0)
    })
  })

  test('C-AC-29 pauses rendering when scrolled out of view', async ({ page }) => {
    await page.addInitScript(() => {
      Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 })
      ;(window as Window & { __actronHeroForce3d?: boolean }).__actronHeroForce3d = true
    })
    await page.goto('/')
    const mode = await page.getByTestId('hero-visual').getAttribute('data-hero-mode', { timeout: 5000 })
    test.skip(mode !== '3d' && mode !== 'waiting', 'WebGL is not available in this browser')
    await expect(page.getByTestId('hero-visual')).toHaveAttribute('data-hero-mode', '3d', { timeout: 5000 })
    await expect.poll(() => page.evaluate(() => window.__actronHeroFrames ?? 0), { timeout: 10000 }).toBeGreaterThan(5)
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight))
    await expect(page.getByTestId('hero-scene')).toHaveAttribute('data-active', 'false')
    const before = await page.evaluate(() => window.__actronHeroFrames ?? 0)
    await page.waitForTimeout(800)
    const after = await page.evaluate(() => window.__actronHeroFrames ?? 0)
    expect(after - before).toBeLessThanOrEqual(1)
    await page.evaluate(() => window.scrollTo(0, 0))
    await expect.poll(() => page.evaluate(() => window.__actronHeroFrames ?? 0)).toBeGreaterThan(after + 2)
  })
})
