import { expect, test, type Page } from '@playwright/test'
import { Api, control, signIn, workspaceState } from './helpers'

/**
 * Graph explorer, inbox, command palette, keyboard-only flow, SSE reconnect, backend down and the production
 * build's lack of a fixtures badge, on the real stack (PROMPT 9.6). Needs 01-connect.
 */
test.describe.configure({ mode: 'serial' })

let api: Api

test.beforeAll(async () => {
  api = await Api.signIn()
})

test.afterAll(async () => {
  await control('/clear', {})
  await api.dispose()
})

async function newWaitingRequest(text: string): Promise<string> {
  const id = await api.createRequest(text, 'feature')
  await api.waitFor(id, ['Needs your input'])
  return id
}

test('graph explorer: search, open a node with where it came from, follow a link, run a quick query', async ({ page }) => {
  await signIn(page, '/app/graph')
  await page.getByTestId('graph-search').fill('total')
  const results = page.getByTestId('graph-results')
  await expect(results.getByRole('button').first()).toBeVisible()
  // Results are grouped by type with the file path under the name, so pick `total` inside the Functions group.
  await results.getByRole('region', { name: /^Functions?$/ }).getByRole('button', { name: /^total\b/ }).first().click()
  const inspector = page.getByTestId('node-inspector')
  await expect(inspector).toBeVisible()
  await expect(inspector).toContainText('Where it came from')
  await expect(page).toHaveURL(/node=code%3Afn%3Aacme%2Fcalc%3Acalc%2Fops\.py%3A%3Atotal|node=code:fn:acme\/calc:calc\/ops\.py::total/)
  await page.getByRole('button', { name: 'Callers' }).click()
  await expect(page.getByTestId('quick-result')).toBeVisible()
  // Expand: follow one of the function's links; the explorer opens the neighbour.
  const first = new URL(page.url()).searchParams.get('node')
  const link = inspector.locator('li > button[title]').first()
  await expect(link).toBeVisible()
  await link.click()
  await expect.poll(() => new URL(page.url()).searchParams.get('node')).not.toBe(first)
  await expect(page.getByRole('img', { name: /Graph explorer\. \d+ nodes/ })).toBeVisible()
})

test('B-AC-62 inbox items open the request at the tab that needs you', async ({ page }) => {
  const id = await newWaitingRequest('Add a power function next to `add` in calc/ops.py')
  await signIn(page, '/app/inbox')
  const item = page.locator(`[data-row][href*="${id}"]`).first()
  await expect(item).toBeVisible()
  expect(await item.getAttribute('href')).toMatch(/tab=questions/)
  await item.click()
  await page.waitForURL(`**/app/requests/${id}?tab=questions`)
  await expect(page.getByRole('tab', { name: /Questions/ })).toHaveAttribute('aria-selected', 'true')
})

test('command palette finds a request by its words and opens it', async ({ page }) => {
  const id = await newWaitingRequest('Add a clamp function next to `add` in calc/ops.py')
  await signIn(page, '/app')
  await page.keyboard.press('Control+k')
  const input = page.getByRole('combobox', { name: /Search requests/ })
  await expect(input).toBeFocused()
  await input.fill('clamp')
  await expect(page.getByRole('option', { name: /clamp/ }).first()).toBeVisible()
  await page.keyboard.press('Enter')
  await page.waitForURL(`**/app/requests/${id}**`)
})

test('C-AC-31 keyboard only: sign in, open a request, answer, approve, open the PR tab', async ({ page }) => {
  const id = await newWaitingRequest('Add a halve function next to `add` in calc/ops.py')
  await page.goto('/app/signin')
  await expect(page.getByTestId('slack-signin')).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(page.getByTestId('dev-login')).toBeFocused()
  await page.keyboard.press('Enter')
  await page.waitForURL((url) => url.pathname === '/app')
  await expect(page.getByTestId('footer-status')).toBeVisible()
  await page.keyboard.press('Control+k')
  const palette = page.getByRole('combobox', { name: /Search requests/ })
  await expect(palette).toBeFocused()
  await palette.fill('halve')
  await expect(page.getByRole('option', { name: /halve/ }).first()).toBeVisible()
  await page.keyboard.press('Enter')
  await page.waitForURL(`**/app/requests/${id}**`)
  await expect(workspaceState(page)).toHaveAttribute('data-state', 'Needs your input')
  await page.getByRole('tab', { name: /Questions/ }).focus()
  await page.keyboard.press('Enter')
  const card = page.locator('[data-testid="question-card"][data-answered="false"]').first()
  await card.getByRole('radio').first().focus()
  await page.keyboard.press('Space')
  await card.getByRole('button', { name: 'Send answer' }).focus()
  await page.keyboard.press('Enter')
  await expect(workspaceState(page)).toHaveAttribute('data-state', 'Awaiting approval', { timeout: 60_000 })
  await page.locator('body').focus()
  await page.keyboard.press('a')
  const dialog = page.getByRole('dialog', { name: /Approve ticket v1/ })
  await expect(dialog).toBeVisible()
  await expect(dialog.getByRole('button', { name: /Approve ticket v1/ })).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(workspaceState(page)).toHaveAttribute('data-state', 'PR ready for review', { timeout: 120_000 })
  await page.getByRole('tab', { name: 'PR' }).focus()
  await page.keyboard.press('Enter')
  await expect(page.getByTestId('pr-panel')).toBeVisible()
})

test.describe('reduced motion', () => {
  test.use({ reducedMotion: 'reduce' })

  async function movingAnimations(page: Page) {
    return page.evaluate(() =>
      document
        .getAnimations()
        .filter((a) => a.playState === 'running')
        .map((a) => {
          const frames = (a.effect as KeyframeEffect | null)?.getKeyframes() ?? []
          return [...new Set(frames.flatMap((f) => Object.keys(f)))]
        })
        .filter((props) => props.some((p) => ['transform', 'translate', 'rotate', 'scale', 'offsetDistance', 'left', 'top'].includes(p))),
    )
  }

  test('C-AC-7 Home and a live request page do not move anything under reduced motion', async ({ page }) => {
    const id = await api.createRequest('Add a double function next to `add` in calc/ops.py', 'feature')
    await signIn(page, '/app')
    await page.waitForTimeout(1000)
    expect(await movingAnimations(page)).toEqual([])
    await page.goto(`/app/requests/${id}`)
    await expect(workspaceState(page)).toBeVisible()
    await page.waitForTimeout(1500)
    expect(await movingAnimations(page)).toEqual([])
  })
})

test('B-AC-4 C-AC-17 the request stream reconnects after the backend restarts and loses no events', async ({ page }) => {
  const id = await api.toApproval('Add a triple function next to `add` in calc/ops.py')
  await signIn(page, `/app/requests/${id}?tab=build`)
  await expect(workspaceState(page)).toHaveAttribute('data-state', 'Awaiting approval')
  // Hold the pull request call so the build's last events happen while the API is down.
  await control('/github/delay', { match: 'POST /repos/acme/calc-fork/pulls$', seconds: 8 })
  await api.approveTicket(id)
  await control('/backend/down', {})
  await expect(page.getByTestId('reconnecting-banner').or(page.getByTestId('offline-banner')).first()).toBeVisible({ timeout: 30_000 })
  await control('/backend/up', {})
  await expect(workspaceState(page)).toHaveAttribute('data-state', 'PR ready for review', { timeout: 120_000 })
  await expect(page.getByTestId('reconnecting-banner')).toBeHidden({ timeout: 30_000 })
  // Every event once, none lost: one build start, one PR opened, both test runs.
  const count = (type: string) => page.locator(`[data-testid="timeline-item"][data-type="${type}"]`).count()
  expect(await count('build.started')).toBe(1)
  expect(await count('pr.opened')).toBe(1)
  expect(await count('tests.result')).toBe(2)
  expect(await count('request.created')).toBe(1)
})

test('backend down: screens show the designed error state and recover with Retry', async ({ page }) => {
  await signIn(page, '/app')
  await control('/backend/down', {})
  try {
    await page.goto('/app/inbox')
    await expect(page.getByTestId('error-state').or(page.getByTestId('server-error')).first()).toBeVisible()
    await expect(page.getByRole('button', { name: /Retry|Reload/ }).first()).toBeVisible()
  } finally {
    await control('/backend/up', {})
  }
  await page.getByRole('button', { name: /Retry|Reload/ }).first().click()
  await expect(page.getByTestId('error-state')).toHaveCount(0, { timeout: 30_000 })
  await expect(page.getByTestId('footer-status')).toBeVisible()
})

for (const path of ['/', '/app/signin', '/app', '/app/inbox', '/app/graph', '/app/connect', '/app/settings']) {
  test(`C-AC-20 no DEV FIXTURES badge on ${path} without the flag`, async ({ page }) => {
    if (path.startsWith('/app') && path !== '/app/signin') await signIn(page, path)
    else await page.goto(path)
    await expect(page.locator('body')).toBeVisible()
    await page.waitForLoadState('networkidle')
    await expect(page.getByTestId('dev-fixtures-badge')).toHaveCount(0)
  })
}
