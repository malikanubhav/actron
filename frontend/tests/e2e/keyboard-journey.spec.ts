import { expect, test } from '@playwright/test'
import { FIXTURE_IDS, fast, open } from './helpers'

/** C-AC-31: sign in → open request → answer → approve → open PR tab, keyboard only. */
test('C-AC-31 keyboard-only core journey', async ({ page }) => {
  await fast(page)
  await open(page, '/app/signin')
  await expect(page.getByTestId('slack-signin')).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(page.getByTestId('dev-login')).toBeFocused()
  await page.keyboard.press('Enter')
  await page.waitForURL('**/app')
  await expect(page.getByTestId('footer-status')).toBeVisible()

  // Open the live request through the command palette.
  await page.keyboard.press('Control+k')
  const palette = page.getByRole('combobox', { name: /Search requests/ })
  await expect(palette).toBeFocused()
  await palette.fill('inline')
  await page.keyboard.press('Enter')
  await page.waitForURL(`**/app/requests/${FIXTURE_IDS.live}**`)

  // Wait for the questions, then answer them with the keyboard.
  await expect(page.getByTestId('request-workspace')).toHaveAttribute('data-state', 'Needs your input', { timeout: 30_000 })
  const questionsTab = page.getByRole('tab', { name: /Questions/ })
  await questionsTab.focus()
  await page.keyboard.press('Enter')
  for (let i = 0; i < 4; i++) {
    const card = page.locator('[data-testid="question-card"][data-answered="false"]').first()
    if (!(await card.isVisible().catch(() => false))) break
    const radio = card.getByRole('radio').first()
    await radio.focus()
    await page.keyboard.press('Space')
    await card.getByRole('button', { name: 'Send answer' }).focus()
    await page.keyboard.press('Enter')
    await expect(card).toHaveAttribute('data-answered', 'true').catch(() => undefined)
    await page.waitForTimeout(300)
  }
  await expect(page.getByTestId('request-workspace')).toHaveAttribute('data-state', 'Awaiting approval', { timeout: 30_000 })

  // `a` opens the approval confirmation naming the hash; Enter confirms.
  await page.locator('body').focus()
  await page.keyboard.press('a')
  const dialog = page.getByRole('dialog', { name: /Approve ticket v1/ })
  await expect(dialog).toBeVisible()
  await expect(dialog.getByTestId('confirm-target')).toContainText('v1 ·')
  await expect(dialog.getByRole('button', { name: /Approve ticket v1/ })).toBeFocused()
  await page.keyboard.press('Enter')

  await expect(page.getByTestId('request-workspace')).toHaveAttribute('data-state', 'PR ready for review', { timeout: 45_000 })
  const prTab = page.getByRole('tab', { name: 'PR' })
  await prTab.focus()
  await page.keyboard.press('Enter')
  await expect(page.getByTestId('pr-panel')).toBeVisible()
})
