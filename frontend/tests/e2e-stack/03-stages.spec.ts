import { expect, test, type Page } from '@playwright/test'
import { Api, control, signIn, workspaceState } from './helpers'

/**
 * Cancel at each stage, the nothing-found label, Q&A and the Linear timeout, all against the real worker
 * (PROMPT 9.6). Fake-provider delays hold a request in a stage long enough to act on it there.
 */
test.describe.configure({ mode: 'serial' })

let api: Api

test.beforeAll(async () => {
  api = await Api.signIn()
})

test.afterEach(async () => {
  await control('/clear', {})
})

test.afterAll(async () => {
  await api.dispose()
})

async function cancelInUi(page: Page, consequence: RegExp) {
  await page.getByRole('button', { name: 'Cancel', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Cancel this request?' })
  await expect(dialog).toContainText(consequence)
  await dialog.getByRole('button', { name: 'Cancel request' }).click()
  await expect(workspaceState(page)).toHaveAttribute('data-state', 'Cancelled', { timeout: 60_000 })
  await expect(page.getByTestId('cancelled-banner')).toBeVisible()
}

test('B-AC-7 cancel while investigating', async ({ page }) => {
  // The freshness gate asks GitHub for the branch head before investigating; holding that answer keeps the
  // request in Investigating.
  await control('/github/delay', { match: 'GET /repos/acme/calc/commits/heads/', seconds: 20 })
  const id = await api.createRequest('Add a divide function next to `add` in calc/ops.py', 'feature')
  await signIn(page, `/app/requests/${id}`)
  await expect(workspaceState(page)).toHaveAttribute('data-state', 'Investigating')
  await cancelInUi(page, /investigation/i)
  expect((await api.request(id)).outcome).toBe('cancelled')
})

test('B-AC-7 cancel while it needs your input', async ({ page }) => {
  const id = await api.createRequest('Add a modulo function next to `add` in calc/ops.py', 'feature')
  await api.waitFor(id, ['Needs your input'])
  await signIn(page, `/app/requests/${id}`)
  await cancelInUi(page, /.+/)
  await expect(page.getByRole('button', { name: 'Cancel', exact: true })).toHaveCount(0)
})

test('B-AC-7 cancel while awaiting approval', async ({ page }) => {
  const id = await api.toApproval('Add a negate function next to `add` in calc/ops.py')
  await signIn(page, `/app/requests/${id}`)
  await cancelInUi(page, /.+/)
  const req = await api.request(id)
  expect(req.builds).toHaveLength(0)
})

test('B-AC-11 cancel while building stops the build', async ({ page }) => {
  // Hold the pull request call so the build is still running when the cancel arrives.
  await control('/github/delay', { match: 'POST /repos/acme/calc-fork/pulls$', seconds: 25 })
  const id = await api.toApproval('Add an absolute value function next to `add` in calc/ops.py')
  await api.approveTicket(id)
  await api.waitFor(id, ['Building'])
  await signIn(page, `/app/requests/${id}?tab=build`)
  await cancelInUi(page, /build/i)
  await expect.poll(async () => (await api.request(id)).builds[0]?.status, { timeout: 60_000 }).toBe('stopped')
})

test('B-AC-7 closing the pull request ends a request that has a PR', async ({ page }) => {
  const id = await api.toApproval('Add a square function next to `add` in calc/ops.py')
  await api.approveTicket(id)
  const req = await api.waitFor(id, ['PR ready for review'], 120_000)
  await signIn(page, `/app/requests/${id}?tab=pr`)
  await page.getByTestId('pr-panel').getByRole('button', { name: 'Close PR' }).click()
  const dialog = page.getByRole('dialog', { name: `Close PR #${req.pr!.number}?` })
  await dialog.getByRole('button', { name: `Close PR #${req.pr!.number}` }).click()
  await expect(workspaceState(page)).toHaveAttribute('data-state', 'Cancelled', { timeout: 60_000 })
  const pulls = (await control<{ pulls: { number: number; state: string }[] }>('/github/pulls')).pulls
  expect(pulls.find((p) => p.number === req.pr!.number)?.state).toBe('closed')
})

test('B-AC-26 a request nothing in the history touches is labelled nothing found', async ({ page }) => {
  const id = await api.createRequest('Translate the onboarding emails into Portuguese for the Lisbon office', 'feature')
  await api.waitFor(id, ['Needs your input', 'Awaiting approval'])
  await signIn(page, `/app/requests/${id}?tab=evidence`)
  expect((await api.request(id)).label).toBe('nothing_found')
  await expect(page.getByTestId('label-banner')).toHaveAttribute('data-label', 'nothing_found')
  await expect(page.getByTestId('label-banner')).toBeVisible()
})

test('B-AC-13 Q&A: a question from the composer ends with an answer and its sources, no ticket', async ({ page }) => {
  await signIn(page, '/app')
  const box = page.getByRole('textbox', { name: 'NEW REQUEST' })
  await box.fill('How does total use add?')
  await expect(page.getByRole('radio', { name: 'QUESTION' })).toHaveAttribute('aria-checked', 'true')
  await page.keyboard.press('Control+Enter')
  await page.waitForURL('**/app/requests/**')
  await expect(workspaceState(page)).toHaveAttribute('data-state', 'Done', { timeout: 60_000 })
  await expect(page.getByRole('tab', { name: 'Answer and sources' })).toBeVisible()
  await expect(page.getByTestId('answer-block')).toBeVisible()
  const id = page.url().split('/requests/')[1]!.split('?')[0]!
  const req = await api.request(id)
  expect(req.revisions).toHaveLength(0)
  expect(req.answer?.text).toBeTruthy()
})

test('B-AC-35 a Linear timeout keeps the ticket in Actron and says why', async ({ page }) => {
  // Linear answers slower than the e2e backend's 3 s timeout on every try.
  await control('/linear/delay', { operation: 'IssueCreate', seconds: 5 })
  const id = await api.createRequest('Add a cube function next to `add` in calc/ops.py', 'feature')
  await api.waitFor(id, ['Needs your input'])
  await api.answerAll(id)
  const req = await api.waitFor(id, ['Awaiting approval'], 120_000)
  expect(req.revisions.at(-1)?.linear).toBeNull()
  await signIn(page, `/app/requests/${id}?tab=ticket`)
  await expect(page.getByTestId('timeline')).toContainText('Not in Linear: Linear did not accept the ticket')
  // The approval flow still works without Linear.
  await expect(page.getByTestId('header-approve')).toHaveText(/Approve ticket v1/)
})
