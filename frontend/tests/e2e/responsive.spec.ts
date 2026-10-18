import { expect, test } from '@playwright/test'

test.describe('375 px', () => {
  test.use({ viewport: { width: 375, height: 812 } })

  test('C-AC-45 the landing page has no horizontal scroll at 375 px', async ({ page }) => {
    await page.goto('/')
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
    expect(overflow).toBeLessThanOrEqual(0)
  })

  test('C-AC-45 app routes below 1,024 px show the small-screen notice', async ({ page }) => {
    await page.goto('/app')
    await expect(page.getByText('Actron works best on a larger screen. Approvals also work in Slack.')).toBeVisible()
  })
})

test.describe('1,000 px', () => {
  test.use({ viewport: { width: 1000, height: 800 } })
  test('C-AC-45 the notice also shows just below 1,024 px', async ({ page }) => {
    await page.goto('/app')
    await expect(page.getByText('Actron works best on a larger screen. Approvals also work in Slack.')).toBeVisible()
  })
})
