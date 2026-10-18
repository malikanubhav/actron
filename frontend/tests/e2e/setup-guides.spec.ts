import { test, expect } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'

// Fixture build. Token text drives the fake provider: "bad" fails auth, "readonly" cannot push, "noscope" lacks scopes.

test.describe('Setup guides (spec C, C13)', () => {
  test('C-AC-54 each source card opens its guide with every step', async ({ page }) => {
    await page.goto('/app/connect?fixture=empty')
    for (const [provider, steps] of [
      ['github', 4],
      ['slack', 6],
      ['linear', 3],
    ] as const) {
      await page.getByTestId(`source-card-${provider}`).getByRole('button', { name: 'Set up step by step' }).click()
      const guide = page.getByTestId(`guide-${provider}`)
      await expect(guide.getByTestId('guide-step')).toHaveCount(steps)
      await page.keyboard.press('Escape')
      await expect(guide).toBeHidden()
    }
  })

  test('C-AC-55 checks turn green after the token validates', async ({ page }) => {
    await page.goto('/app/connect?fixture=empty')
    const linear = page.getByTestId('source-card-linear')
    await linear.getByLabel('API key').fill('lin_api_e2e_good')
    await linear.getByRole('button', { name: 'Check connection' }).click()
    await linear.getByRole('button', { name: 'Set up step by step' }).click()
    const guide = page.getByTestId('guide-linear')
    // The guide runs its checks when it opens; finished steps start folded, so there may be nothing left to re-check.
    await expect(guide.locator('[data-status="done"]')).toHaveCount(3)
  })

  test('C-AC-55 a failing check shows the mapped troubleshooting text', async ({ page }) => {
    await page.goto('/app/connect?fixture=empty')
    const slack = page.getByTestId('source-card-slack')
    await slack.getByRole('button', { name: 'Connect with tokens' }).click()
    await slack.getByLabel('Bot token').fill('xoxb-bad-token')
    await slack.getByRole('button', { name: 'Check connection' }).click()
    await slack.getByRole('button', { name: 'Set up step by step' }).click()
    const guide = page.getByTestId('guide-slack')
    await guide.getByRole('button', { name: 'Check again' }).first().click()
    await expect(guide.getByTestId('guide-troubleshooting').first()).toContainText('Copy it again from OAuth & Permissions.')
  })

  test('C-AC-56 missing Slack scopes and a read-only GitHub token are detected', async ({ page }) => {
    await page.goto('/app/connect?fixture=empty')
    const slack = page.getByTestId('source-card-slack')
    await slack.getByRole('button', { name: 'Connect with tokens' }).click()
    await slack.getByLabel('Bot token').fill('xoxb-noscope-token')
    await slack.getByRole('button', { name: 'Check connection' }).click()
    await slack.getByRole('button', { name: 'Set up step by step' }).click()
    await page.getByTestId('guide-slack').getByRole('button', { name: 'Check again' }).first().click()
    await expect(page.getByTestId('guide-slack').getByTestId('guide-troubleshooting').first()).toContainText('users:read.email')
    await page.keyboard.press('Escape')

    const repo = page.getByTestId('source-card-github')
    await repo.getByLabel('Access token').fill('github_pat_readonly')
    await repo.getByLabel('Repository').fill('BetterThanTomorrow/calva')
    await repo.getByRole('button', { name: 'Check connection' }).click()
    await repo.getByRole('button', { name: 'Set up step by step' }).click()
    await page.getByTestId('guide-github').getByRole('button', { name: 'Check again' }).first().click()
    await expect(page.getByTestId('guide-github').locator('[data-step="repository"]')).toHaveAttribute('data-status', 'failed')
  })

  test('C-AC-57 guides keep progress when closed and reopened, and pass axe', async ({ page }) => {
    await page.goto('/app/connect?fixture=default')
    const card = page.getByTestId('source-card-slack')
    await card.getByRole('button', { name: 'Set up step by step' }).click()
    const guide = page.getByTestId('guide-slack')
    const invite = guide.locator('[data-step="invite"] button[aria-expanded]')
    await invite.click()
    await expect(invite).toHaveAttribute('aria-expanded', 'true')
    const results = await new AxeBuilder({ page }).include('dialog[open]').analyze()
    expect(results.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')).toEqual([])
    await page.keyboard.press('Escape')
    await card.getByRole('button', { name: 'Set up step by step' }).click()
    await expect(guide.locator('[data-step="invite"] button[aria-expanded]')).toHaveAttribute('aria-expanded', 'true')
  })
})
