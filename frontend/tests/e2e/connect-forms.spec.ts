import { test, expect } from '@playwright/test'

// Runs against the fixture build (NEXT_PUBLIC_ACTRON_DEV_FIXTURES=1). `?fixture=empty` is the first-run workspace
// where nothing is connected, so every source shows its form.

test.describe('Connect forms (spec C, C12)', () => {
  test('C-AC-49 every source renders its form from the connector definitions', async ({ page }) => {
    await page.goto('/app/connect?fixture=empty')
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Connect a repository to start.')
    const repo = page.getByTestId('source-card-github')
    await expect(repo.getByLabel('Access token')).toHaveAttribute('type', 'password')
    await expect(repo.getByLabel('Repository')).toHaveAttribute('placeholder', 'owner/name')
    await expect(repo.getByLabel(/History to read/)).toHaveValue('90')
    await expect(page.getByTestId('source-card-linear').getByLabel('API key')).toHaveAttribute('placeholder', 'lin_api_…')
    await expect(page.getByTestId('source-card-slack_export').getByLabel('Slack export')).toBeVisible()
  })

  test('C-AC-50 the working branch appears after the repository validates, default first', async ({ page }) => {
    await page.goto('/app/connect?fixture=empty')
    const repo = page.getByTestId('source-card-github')
    await expect(repo.getByLabel('Working branch')).toHaveCount(0)
    await repo.getByLabel('Access token').fill('github_pat_e2e_good')
    await repo.getByLabel('Repository').fill('BetterThanTomorrow/calva')
    await repo.getByRole('button', { name: 'Check connection' }).click()
    await expect(repo.getByTestId('validate-found')).toContainText('Repository found: BetterThanTomorrow/calva')
    await expect(repo.getByLabel('Working branch')).toHaveValue('dev')
    await expect(repo.getByTestId('webhook-panel')).toContainText('/webhooks/github')
  })

  test('C-AC-50 a rejected token is explained in plain words', async ({ page }) => {
    await page.goto('/app/connect?fixture=empty')
    const repo = page.getByTestId('source-card-github')
    await repo.getByLabel('Access token').fill('github_pat_bad')
    await repo.getByLabel('Repository').fill('BetterThanTomorrow/calva')
    await repo.getByRole('button', { name: 'Check connection' }).click()
    await expect(repo.getByText(/the token is wrong or has expired/i)).toBeVisible()
  })

  test('C-AC-51 a saved secret is never shown again, only its last four characters', async ({ page }) => {
    await page.goto('/app/connect?fixture=empty')
    const linear = page.getByTestId('source-card-linear')
    await linear.getByLabel('API key').fill('lin_api_e2e_7c3d')
    await linear.getByRole('button', { name: 'Check connection' }).click()
    await expect(linear.getByLabel('Team')).toHaveValue('team_cal')
    await linear.getByRole('button', { name: 'Connect' }).click()
    await expect(page.getByTestId('saved-secret')).toContainText('7c3d')
    await expect(page.locator('body')).not.toContainText('lin_api_e2e_7c3d')
  })

  test('C-AC-52 the Slack manifest panel copies the manifest', async ({ page, context }) => {
    await context.grantPermissions(['clipboard-read', 'clipboard-write'])
    await page.goto('/app/connect?fixture=empty')
    const slack = page.getByTestId('source-card-slack')
    await slack.getByRole('button', { name: 'Connect with tokens' }).click()
    await slack.getByTestId('manifest-panel').getByRole('button', { name: 'Copy manifest' }).click()
    const copied = await page.evaluate(() => navigator.clipboard.readText())
    expect(copied).toContain('slash_commands')
  })

  test('C-AC-53 Slack offers both paths and the token path reaches the channel picker', async ({ page }) => {
    await page.goto('/app/connect?fixture=empty')
    const slack = page.getByTestId('source-card-slack')
    await expect(slack.getByTestId('add-to-slack')).toBeVisible()
    await slack.getByRole('button', { name: 'Connect with tokens' }).click()
    await slack.getByLabel('Bot token').fill('xoxb-e2e-good')
    await slack.getByRole('button', { name: 'Check connection' }).click()
    await expect(slack.getByText('Connected to Calva team (fixture) as @Actron.')).toBeVisible()
    await expect(slack.getByRole('checkbox', { name: /#calva-dev/ })).toBeVisible()
  })

  test('C-AC-53 an OAuth return shows the workspace, or a plain error', async ({ page }) => {
    await page.goto('/app/connect?fixture=empty&oauth=slack&status=ok&team=Calva%20team%20(fixture)')
    await expect(page.getByTestId('oauth-result')).toHaveText('Connected to Calva team (fixture) as @Actron.')
    await page.goto('/app/connect?fixture=empty&oauth=slack&status=cancelled')
    await expect(page.getByTestId('oauth-result')).toHaveText("You cancelled the Slack approval. Try again when you're ready.")
  })

  test('connected sources show counts, the branch chip and partial reasons', async ({ page }) => {
    await page.goto('/app/connect?fixture=default')
    const repo = page.getByTestId('source-card-github')
    await expect(repo.getByText('BRANCH · dev')).toBeVisible()
    await expect(page.getByTestId('source-card-linear').getByTestId('partial-state')).toBeVisible()
    await expect(page.getByTestId('count-strip')).toBeVisible()
    await expect(page.getByTestId('linking-progress')).toBeVisible()
  })
})
