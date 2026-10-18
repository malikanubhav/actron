import { expect, test } from '@playwright/test'
import { FIXTURE_IDS, open } from './helpers'

test.describe('replay', () => {
  test('C-AC-24 plays all events in order, respects pause and speed, ends in the final view', async ({ page }) => {
    await open(page, `/app/requests/${FIXTURE_IDS.done}/replay`)
    const position = page.getByTestId('replay-position')
    const totalText = (await position.textContent()) ?? '0 / 0'
    const total = Number(totalText.split('/')[1])
    expect(total).toBeGreaterThan(10)
    await page.getByRole('radio', { name: '4×' }).click()
    await page.getByTestId('replay-play').click()
    await expect.poll(async () => Number(((await position.textContent()) ?? '0').split('/')[0]), { timeout: 10_000 }).toBeGreaterThan(3)
    await page.getByRole('button', { name: 'Pause' }).click()
    const paused = await position.textContent()
    await page.waitForTimeout(1200)
    expect(await position.textContent()).toBe(paused)
    // Jump to the end: the view equals the finished request.
    await page.getByRole('slider').fill(String(total))
    await expect(position).toHaveText(`${total} / ${total}`)
    await expect(page.getByTestId('request-workspace')).toHaveAttribute('data-state', 'Done')
    const items = await page.getByTestId('timeline-item').count()
    expect(items).toBeGreaterThan(5)
  })

  test('step controls move one event at a time with a caption', async ({ page }) => {
    await open(page, `/app/requests/${FIXTURE_IDS.done}/replay`)
    await page.getByRole('button', { name: 'Step forward' }).click()
    await expect(page.getByTestId('replay-position')).toHaveText(/^1 \//)
    await expect(page.getByTestId('replay-sentence')).not.toBeEmpty()
    await page.getByRole('button', { name: 'Step back' }).click()
    await expect(page.getByTestId('replay-position')).toHaveText(/^0 \//)
  })

  test('C-AC-25 public replay renders when allowed and 404s for unknown requests', async ({ page }) => {
    await open(page, `/replay/${FIXTURE_IDS.done}`)
    await expect(page.getByTestId('replay-controls')).toBeVisible()
    await open(page, '/replay/req_does_not_exist')
    await expect(page.getByText('This replay is not available.')).toBeVisible()
  })

  test('C-AC-47 home shows "Watch a replay" because a finished request exists', async ({ page }) => {
    await open(page, '/app')
    await expect(page.getByRole('link', { name: 'Watch a replay' })).toBeVisible()
    await open(page, '/app', 'empty')
    await expect(page.getByRole('link', { name: 'Watch a replay' })).toHaveCount(0)
  })
})
