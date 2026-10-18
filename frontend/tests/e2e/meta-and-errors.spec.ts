import { expect, test } from '@playwright/test'
import { FIXTURE_IDS, open } from './helpers'

const ROUTES = ['/', '/app/signin', '/app', '/app/inbox', '/app/graph', '/app/system', '/app/connect', '/app/settings', `/app/requests/${FIXTURE_IDS.done}`]

test('C-AC-40 every route has a unique title and a meta description', async ({ page }) => {
  const titles = new Map<string, string>()
  for (const path of ROUTES) {
    await page.goto(path)
    await page.waitForLoadState('networkidle')
    const title = await page.title()
    const description = await page.locator('meta[name="description"]').getAttribute('content')
    expect(title, path).toMatch(/Actron/)
    expect(description, path).toBeTruthy()
    expect([...titles.values()], `${path} duplicates a title`).not.toContain(title)
    titles.set(path, title)
  }
})

test('C-AC-40 the 404 inside the app keeps the shell and speaks in the product voice', async ({ page }) => {
  await open(page, '/app/not-a-real-screen')
  await expect(page.getByTestId('not-found')).toContainText('This page isn’t in Actron’s memory.')
  await expect(page.getByRole('navigation', { name: 'Main' })).toBeVisible()
  await expect(page.getByTestId('footer-status')).toBeVisible()
})

test('C-AC-40 the public 404 renders', async ({ page }) => {
  const res = await page.goto('/no-such-page')
  expect(res?.status()).toBe(404)
  await expect(page.getByTestId('not-found')).toBeVisible()
})

test('backend down shows designed error states, not blank screens', async ({ page }) => {
  await open(page, '/app', 'backend-down')
  await expect(page.getByTestId('error-state').first()).toBeVisible()
  await expect(page.getByRole('button', { name: 'Retry' }).first()).toBeVisible()
})

test('C-AC-45 app routes below 1,024 px show the small-screen notice', async ({ page }) => {
  await page.setViewportSize({ width: 900, height: 800 })
  await open(page, '/app')
  await expect(page.getByTestId('small-screen-notice')).toBeVisible()
  await expect(page.getByTestId('small-screen-notice')).toContainText('Actron works best on a larger screen. Approvals also work in Slack.')
})
