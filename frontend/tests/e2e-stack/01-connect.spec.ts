import { expect, test, type Page } from '@playwright/test'
import { Api, control, signIn, stack } from './helpers'

/**
 * Connect every source through the real Connect screen against the fake providers, watch the backfill finish,
 * see a partial run with its reason and recover with Sync now (PROMPT 9.6). Later spec files rely on these
 * connections, so this file runs first and disconnects anything left from an earlier run on a reused stack.
 */
test.describe.configure({ mode: 'serial' })

let api: Api

test.beforeAll(async () => {
  api = await Api.signIn()
  for (const c of await api.connections()) {
    if (c.status !== 'disconnected') await api.delete(`/api/connections/${c.id}`)
  }
  await control('/clear', {})
})

test.afterAll(async () => {
  await api.dispose()
})

function card(page: Page, provider: string) {
  return page.getByTestId(`source-card-${provider}`)
}

test('B-AC-58 dev login signs in and opens the app', async ({ page }) => {
  await page.goto('/app')
  await page.waitForURL('**/app/signin**')
  await page.getByTestId('dev-login').click()
  await page.waitForURL((url) => url.pathname === '/app')
  await expect(page.getByTestId('footer-status')).toBeVisible()
  await expect(page.getByRole('navigation', { name: 'Main' })).toBeVisible()
})

test('C-AC-49 C-AC-50 A-AC-44 connect GitHub through the form; a missing pull request leaves the run partial with its reason', async ({ page }) => {
  const s = await stack()
  // The first backfill cannot read pull request #1's files (404 from the fake): the run ends partial.
  await control('/github/inject', { match: '/repos/acme/calc/pulls/1/files$', status: 404, times: 1 })
  await signIn(page, '/app/connect')
  const repo = card(page, 'github')
  await expect(repo.getByText('NOT CONNECTED')).toBeVisible()
  await expect(repo.getByLabel('Working branch')).toHaveCount(0)
  await repo.getByLabel('Access token').fill(s.githubToken)
  await repo.getByLabel('Repository').fill(s.repo)
  await repo.getByLabel(/^Push to/).fill(s.fork)
  await repo.getByRole('button', { name: 'Check connection' }).click()
  await expect(repo.getByTestId('validate-found')).toContainText('Repository found: acme/calc, default branch main')
  await expect(repo.getByLabel('Working branch')).toHaveValue('main')
  await repo.getByRole('button', { name: 'Connect', exact: true }).click()
  await expect(repo.getByText('BRANCH · main')).toBeVisible()
  await expect(repo.getByTestId('secret-last4')).toContainText('0000')
  await expect(page.locator('body')).not.toContainText(s.githubToken)
  const partial = repo.getByTestId('partial-state')
  await expect(partial).toBeVisible({ timeout: 90_000 })
  await expect(partial).toContainText('pull request #1 not found')
  await expect(repo.getByText('PARTIAL')).toBeVisible()
})

test('A-AC-67 Sync now runs again and the repository becomes up to date', async ({ page }) => {
  await signIn(page, '/app/connect')
  const repo = card(page, 'github')
  await expect(repo.getByTestId('partial-state')).toBeVisible()
  await repo.getByRole('button', { name: 'Sync now' }).click()
  await expect(repo).toHaveAttribute('data-state', 'UP TO DATE', { timeout: 90_000 })
  await expect(repo.getByTestId('partial-state')).toHaveCount(0)
  const counts = repo.getByRole('definition')
  await expect(counts.first()).toBeVisible()
})

test('C-AC-53 connect Slack with a bot token and pick the channel', async ({ page }) => {
  const s = await stack()
  await signIn(page, '/app/connect')
  const slack = card(page, 'slack')
  await slack.getByLabel('Bot token').fill(s.slackBotToken)
  await slack.getByRole('button', { name: 'Check connection' }).click()
  await expect(slack.getByText('Connected to Northwind Labs as @actron.')).toBeVisible()
  await slack.getByRole('checkbox', { name: /#eng/ }).check()
  await slack.getByRole('button', { name: 'Connect', exact: true }).click()
  await expect(slack.getByText('UP TO DATE')).toBeVisible({ timeout: 90_000 })
  await expect(page.locator('body')).not.toContainText(s.slackBotToken)
})

test('C-AC-50 C-AC-51 connect Linear with an API key and choose the team; the key is shown only as its last four', async ({ page }) => {
  const s = await stack()
  await signIn(page, '/app/connect')
  const linear = card(page, 'linear')
  await linear.getByLabel('API key').fill(s.linearKey)
  await linear.getByRole('button', { name: 'Check connection' }).click()
  await expect(linear.getByTestId('validate-found')).toContainText('Connected as Vera Viewer in Acme.')
  await linear.getByLabel('Team').selectOption({ label: 'Engineering (ENG)' })
  await linear.getByRole('button', { name: 'Connect', exact: true }).click()
  await expect(linear.getByTestId('secret-last4')).toContainText('_key')
  await expect(page.locator('body')).not.toContainText(s.linearKey)
  await expect(linear.getByText('UP TO DATE')).toBeVisible({ timeout: 90_000 })
})

test('A-AC-69 ingestion reaches done for every source and memory counts show', async ({ page }) => {
  await signIn(page, '/app/connect')
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(/Memory is up to date/, { timeout: 90_000 })
  for (const provider of ['github', 'slack', 'linear']) {
    // The repository card shows one chip per connection row (code and GitHub API), so check the card's state.
    await expect(card(page, provider)).toHaveAttribute('data-state', 'UP TO DATE')
    await expect(card(page, provider).getByText('UP TO DATE').first()).toBeVisible()
  }
  await expect(page.getByTestId('count-strip')).toBeVisible()
  const status = await api.get<{ sources: { provider: string; state: string }[]; totals: { nodes: number } }>('/api/ingestion/status')
  expect(status.sources.map((x) => x.state).every((x) => x === 'UP TO DATE')).toBe(true)
  expect(status.totals.nodes).toBeGreaterThan(20)
})

test('C-AC-55 setup guides: checks turn green from the live providers and failures show troubleshooting', async ({ page }) => {
  await signIn(page, '/app/connect')
  await card(page, 'github').getByRole('button', { name: 'Set up step by step' }).click()
  const gh = page.getByTestId('guide-github')
  await expect(gh.locator('[data-step="token"]')).toHaveAttribute('data-status', 'done')
  await expect(gh.locator('[data-step="repository"]')).toHaveAttribute('data-status', 'done')
  await expect(gh.locator('[data-step="branch"]')).toHaveAttribute('data-status', 'done')
  await page.keyboard.press('Escape')
  await card(page, 'linear').getByRole('button', { name: 'Set up step by step' }).click()
  await expect(page.getByTestId('guide-linear').locator('[data-status="done"]')).toHaveCount(3)
  await page.keyboard.press('Escape')
  await card(page, 'slack').getByRole('button', { name: 'Set up step by step' }).click()
  const sl = page.getByTestId('guide-slack')
  for (const step of ['create', 'install', 'scopes', 'invite']) {
    await expect(sl.locator(`[data-step="${step}"]`)).toHaveAttribute('data-status', 'done')
  }
  // No app-level token was given and Actron has no public HTTPS address: the Socket Mode step explains why.
  await expect(sl.locator('[data-step="socket"]')).toHaveAttribute('data-status', 'failed')
  await expect(sl.locator('[data-step="socket"]').getByTestId('guide-troubleshooting')).toContainText('connections:write')
})
