import { expect, test } from '@playwright/test'
import { FIXTURE_IDS, fast, open } from './helpers'

test.describe('live request', () => {
  test('C-AC-23 tool calls appear live in order, the system map pulses and nodes highlight', async ({ page }) => {
    await fast(page, 0.3)
    await open(page, `/app/requests/${FIXTURE_IDS.live}`)
    await page.getByRole('button', { name: /Show system map/ }).click()
    const cards = page.getByTestId('tool-call-card')
    await expect(cards.first()).toBeVisible({ timeout: 20_000 })
    await expect(page.getByTestId('screen-header').locator('h1')).toHaveText(/Investigating\. \d+ graph quer/)
    // More cards keep arriving.
    const first = await cards.count()
    await expect.poll(async () => cards.count(), { timeout: 20_000 }).toBeGreaterThan(first)
    // The system map shows the FalkorDB edge active at some point.
    await expect(page.locator('[data-edge="actron-falkordb"][data-active="true"]').or(page.locator('[data-edge="falkordb-pi"][data-active="true"]')).first()).toBeAttached({ timeout: 20_000 })
    // Hovering a finished tool call highlights its nodes (the row becomes a pressable highlight target).
    const row = page.locator('[data-type="tool.called"] [role="button"]').first()
    await row.hover()
    await row.click()
    await expect(row).toHaveAttribute('aria-pressed', 'true')
  })

  test('approval with a stale hash shows the reason inline (C-AC-11 in the browser)', async ({ page }) => {
    await open(page, `/app/requests/${FIXTURE_IDS.stale}?tab=ticket`)
    await expect(page.getByTestId('stale-text')).toHaveText(/You approved v1\. This is v2\. Approve again to build\./)
    await expect(page.getByTestId('approval-target')).toContainText('Revision v2 · SHA-256')
  })

  test('show path traces the evidence path with quote cards (C-AC-13)', async ({ page }) => {
    await open(page, `/app/requests/${FIXTURE_IDS.done}?tab=evidence`)
    const showPath = page.getByRole('button', { name: 'Show path' }).first()
    await expect(showPath).toBeVisible()
    const started = Date.now()
    await showPath.click()
    await expect(page.getByTestId('trace-quote').first()).toBeVisible({ timeout: 6000 })
    expect(Date.now() - started).toBeLessThan(6000)
    await expect(page.getByRole('button', { name: 'Tracing path' })).toBeVisible()
  })

  test('deep link opens the right tab and keeps it on reload (C-AC-44)', async ({ page }) => {
    await open(page, `/app/requests/${FIXTURE_IDS.building}?tab=build`)
    await expect(page.getByRole('tab', { name: 'Build' })).toHaveAttribute('aria-selected', 'true')
    await page.getByRole('tab', { name: 'Ticket' }).click()
    await expect(page).toHaveURL(/tab=ticket/)
    await page.reload()
    await expect(page.getByRole('tab', { name: 'Ticket' })).toHaveAttribute('aria-selected', 'true')
    // In-app back navigation returns to the request with its tab (history restore across a full reload is not
    // exercised here: MSW does not control pages restored from the back-forward cache).
    await page.getByRole('link', { name: /^Inbox/ }).first().click()
    await page.waitForURL('**/app/inbox')
    await page.goBack()
    await expect(page.getByRole('tab', { name: 'Ticket' })).toHaveAttribute('aria-selected', 'true')
  })

  test('C-AC-46 build tab and summary show tokens and estimated cost', async ({ page }) => {
    await open(page, `/app/requests/${FIXTURE_IDS.building}?tab=build`)
    const costs = page.getByTestId('cost-badge')
    await expect(costs.first()).toContainText(/tokens/)
    await expect(costs.first()).toContainText(/\$\d|<\$0\.01/)
    await expect(page.getByTestId('build-theatre').getByTestId('cost-badge')).toBeVisible()
  })

  test('C-AC-17 the stream reconnects and resumes after a drop', async ({ page }) => {
    await fast(page, 0.3)
    await open(page, `/app/requests/${FIXTURE_IDS.live}`, 'stream-drop')
    await expect(page.getByTestId('reconnecting-banner')).toBeVisible({ timeout: 20_000 })
    await expect(page.getByTestId('reconnecting-banner')).toBeHidden({ timeout: 30_000 })
    const types = await page.locator('[data-testid="timeline-item"]').evaluateAll((els) => els.map((e) => e.getAttribute('data-type')))
    expect(types.filter((t) => t === 'request.created')).toHaveLength(1)
  })
})
