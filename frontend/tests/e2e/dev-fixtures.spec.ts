import { expect, test } from '@playwright/test'

/**
 * C-AC-20: the DEV FIXTURES badge is visible on every screen of the fixture build. The "flag off" half is covered by
 * the unit test (DevFixturesBadge renders nothing without NEXT_PUBLIC_ACTRON_DEV_FIXTURES=1) and by running this
 * suite with E2E_BASE_URL against a production build, where `expectBadge` flips.
 */
const expectBadge = !process.env.E2E_BASE_URL

for (const path of ['/', '/app/signin', '/app', '/app/inbox', '/app/graph', '/app/system', '/app/connect', '/app/settings']) {
  test(`C-AC-20 DEV FIXTURES badge ${expectBadge ? 'is visible' : 'is absent'} on ${path}`, async ({ page }) => {
    await page.goto(path)
    const badge = page.getByTestId('dev-fixtures-badge').first()
    if (expectBadge) {
      await expect(badge).toBeVisible()
      await expect(badge).toHaveText('DEV FIXTURES')
    } else {
      await expect(page.getByTestId('dev-fixtures-badge')).toHaveCount(0)
    }
  })
}
