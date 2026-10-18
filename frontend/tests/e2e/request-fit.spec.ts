import { expect, test } from '@playwright/test'
import { FIXTURE_IDS, open } from './helpers'

/**
 * The request page's three panels take whatever height the header leaves (at least 480 px) and the status bar always
 * sits below them. A header that grows (a long answer, a banner, a quote) once pushed the page 30 to 350 px past the
 * screen while the columns kept a fixed height, and a fixed frame let them spill past the sticky status bar.
 */
test.use({ viewport: { width: 1440, height: 900 } })

const STATES: [string, string][] = [
  ['investigating', FIXTURE_IDS.live],
  ['awaiting approval (stale)', `${FIXTURE_IDS.stale}?tab=ticket`],
  ['building', `${FIXTURE_IDS.building}?tab=build`],
  ['failed', `${FIXTURE_IDS.failed}?tab=build`],
  ['PR ready', `${FIXTURE_IDS.prReady}?tab=pr`],
  ['done', FIXTURE_IDS.done],
  ['cancelled', FIXTURE_IDS.cancelled],
]

test.describe('a screen too short for the header', () => {
  test.use({ viewport: { width: 1440, height: 600 } })

  for (const [name, path] of STATES) {
    test(`the status bar stays below the columns: ${name}`, async ({ page }) => {
      await open(page, `/app/requests/${path}`)
      await expect(page.getByTestId('request-workspace')).toBeVisible()
      await page.waitForTimeout(400)
      // Scroll to the end: the page may scroll here, but the columns must end above the status bar, never under it.
      await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight))
      const { columnsBottom, footerTop, footerBottom, innerHeight } = await page.evaluate(() => {
        const columns = document.querySelector('.request-columns')?.getBoundingClientRect()
        const footer = document.querySelector('[data-testid="footer-status"]')?.getBoundingClientRect()
        return {
          columnsBottom: columns ? columns.bottom : 0,
          footerTop: footer ? footer.top : 0,
          footerBottom: footer ? footer.bottom : 0,
          innerHeight: window.innerHeight,
        }
      })
      expect(columnsBottom, 'content continues below the status bar').toBeLessThanOrEqual(footerTop + 1)
      expect(footerBottom, 'the status bar is not at the bottom of the screen').toBeGreaterThanOrEqual(innerHeight - 1)
    })
  }
})

for (const [name, path] of STATES) {
  test(`panels are tall and the status bar stays below them at 1440x900: ${name}`, async ({ page }) => {
    await open(page, `/app/requests/${path}`)
    await expect(page.getByTestId('request-workspace')).toBeVisible()
    await page.waitForTimeout(600)
    // The page may scroll a little when the header is tall; the end of the page must still end on the status bar.
    await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight))
    const { columnsHeight, columnsBottom, footerTop } = await page.evaluate(() => {
      const columns = document.querySelector('.request-columns')?.getBoundingClientRect()
      const footer = document.querySelector('[data-testid="footer-status"]')?.getBoundingClientRect()
      return { columnsHeight: columns ? columns.height : 0, columnsBottom: columns ? columns.bottom : 0, footerTop: footer ? footer.top : 0 }
    })
    expect(columnsHeight, 'the panels are too short to read').toBeGreaterThanOrEqual(475)
    expect(columnsBottom, 'the columns run under the status bar').toBeLessThanOrEqual(footerTop + 1)
  })
}
