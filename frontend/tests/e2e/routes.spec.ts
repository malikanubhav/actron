import { expect, test } from '@playwright/test'
import { SCREENS, consoleErrors, open } from './helpers'

test.describe('routes (C-AC-15)', () => {
  for (const screen of SCREENS) {
    test(`C-AC-15 ${screen.path} renders eyebrow, headline and purpose without console errors`, async ({ page }) => {
      const errors = consoleErrors(page)
      await open(page, screen.path)
      const header = page.getByTestId('screen-header').first()
      await expect(header).toBeVisible()
      await expect(header.locator('.eyebrow').first()).toContainText(screen.eyebrow)
      await expect(header.locator('h1')).not.toBeEmpty()
      await expect(header.locator('p').first()).toBeVisible()
      await page.waitForTimeout(500)
      expect(errors.filter((e) => !/Download the React DevTools/.test(e))).toEqual([])
    })
  }

  test('C-AC-15 sign-in renders its header and focuses the Slack button', async ({ page }) => {
    await open(page, '/app/signin')
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Sign in to see what your team already decided.')
    await expect(page.getByTestId('slack-signin')).toBeFocused()
    await expect(page.getByTestId('dev-login')).toBeVisible()
  })

  test('C-AC-15 the landing page renders', async ({ page }) => {
    await open(page, '/')
    await expect(page.getByRole('heading', { level: 1 })).toContainText('Your AI doesn’t know what your team already decided')
  })
})
