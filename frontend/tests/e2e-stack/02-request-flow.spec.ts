import { expect, test, type Page } from '@playwright/test'
import { Api, signIn, slackAction, slackCalls, slackCommand, stack, workspaceState } from './helpers'

/**
 * One feature request from Slack to merged memory, through the real UI and the Slack handlers (PROMPT 9.6):
 * Slack command → live in the UI → investigation and evidence → answer in the UI (Slack status updated) → ticket
 * edit voids the old approval → Slack and UI approve at once → build streams, fails, repairs → PR tab → request
 * changes → new build → approve PR → write-back in the graph explorer. Needs 01-connect.
 */
test.describe.configure({ mode: 'serial' })

const TEXT = 'Add a subtract function next to `add` in calc/ops.py'
let api: Api
let rid = ''

test.beforeAll(async () => {
  api = await Api.signIn()
})

test.afterAll(async () => {
  await api.dispose()
})

/** The id of the request that was not in `before` (a Slack command answers before the request exists). */
async function newRequestId(before: string[]): Promise<string> {
  let id = ''
  await expect
    .poll(async () => {
      const list = (await api.get<{ requests: { id: string }[] }>('/api/requests?limit=100')).requests
      id = list.find((r) => !before.includes(r.id))?.id ?? ''
      return id
    })
    .toMatch(/^req_/)
  return id
}

async function approveFromHeader(page: Page, noun: RegExp) {
  await page.getByTestId('header-approve').click()
  const dialog = page.getByRole('dialog', { name: noun })
  await expect(dialog).toBeVisible()
  await dialog.getByRole('button', { name: noun }).click()
}

test('B-AC-51 B-AC-1 a Slack command creates a request that appears live on Home', async ({ page }) => {
  await signIn(page, '/app')
  const before = (await api.get<{ requests: { id: string }[] }>('/api/requests?limit=100')).requests.map((r) => r.id)
  const acks = (await slackCalls('chat.postMessage')).length
  expect(await slackCommand(TEXT)).toBe(200)
  rid = await newRequestId(before)
  // The row arrives through the workspace stream; the page is not reloaded.
  await expect(page.locator(`[data-testid="request-row"] a[href^="/app/requests/${rid}"]`)).toBeVisible()
  const req = await api.request(rid)
  expect(req.slack?.channel).toBe((await stack()).slackChannel)
  expect((await slackCalls('chat.postMessage')).length).toBeGreaterThan(acks)
})

test('C-AC-23 the investigation shows its graph tool calls on the timeline and the evidence on the canvas', async ({ page }) => {
  await signIn(page, `/app/requests/${rid}`)
  await expect(workspaceState(page)).toHaveAttribute('data-state', /Needs your input|Investigating/)
  await expect(page.getByTestId('tool-call-card').first()).toBeVisible()
  expect(await page.getByTestId('tool-call-card').count()).toBeGreaterThan(2)
  await expect(page.getByTestId('timeline-item').filter({ hasText: /find_symbol|search|callers/ }).first()).toBeVisible()
  await expect(page.locator('[data-testid="graph-canvas"] canvas').first()).toBeVisible()
  await page.getByRole('button', { name: 'List view' }).click()
  await expect(page.getByTestId('graph-list').getByRole('button').first()).toBeVisible()
})

test('C-AC-13 show path on an evidence card traces its path on the canvas', async ({ page }) => {
  await signIn(page, `/app/requests/${rid}?tab=evidence`)
  await expect(page.getByTestId('evidence-card').first()).toBeVisible()
  const showPath = page.getByRole('button', { name: 'Show path' }).first()
  await showPath.click()
  await expect(page.getByRole('button', { name: 'Tracing path' }).first()).toBeVisible()
})

test('B-AC-52 B-AC-31 an answer in the UI is recorded and the Slack status message is updated, not re-posted', async ({ page }) => {
  await api.waitFor(rid, ['Needs your input'])
  const updates = (await slackCalls('chat.update')).length
  const channel = (await stack()).slackChannel
  // Top-level messages in the request's channel (DMs to the person who must act go elsewhere, B-AC-56).
  const topLevel = async () =>
    (await slackCalls('chat.postMessage')).filter((c) => c.params.channel === channel && c.params.thread_ts === undefined).length
  const posts = await topLevel()
  await signIn(page, `/app/requests/${rid}?tab=questions`)
  const card = page.locator('[data-testid="question-card"][data-answered="false"]').first()
  await card.getByRole('radio').first().check()
  await card.getByRole('button', { name: 'Send answer' }).click()
  await expect(page.locator('[data-testid="question-card"]').first()).toHaveAttribute('data-answered', 'true')
  await expect(page.getByTestId('answer').first()).toContainText(/Dev user · (Actron|UI|web)/i)
  await expect(workspaceState(page)).toHaveAttribute('data-state', 'Awaiting approval', { timeout: 60_000 })
  await expect.poll(async () => (await slackCalls('chat.update')).length).toBeGreaterThan(updates)
  const last = (await slackCalls('chat.update')).at(-1)
  expect(last?.params.channel).toBe(channel)
  // The status message is edited in place; no new top-level message for the state change.
  expect(await topLevel()).toBe(posts)
  // The ticket was written to Linear.
  const req = await api.request(rid)
  expect(req.revisions.at(-1)?.linear?.identifier).toMatch(/^ENG-\d+/)
})

test('B-AC-9 B-AC-37 editing the ticket voids the earlier approval target; the old hash from Slack is refused', async ({ page }) => {
  const v1 = (await api.request(rid)).currentRevision!
  await signIn(page, `/app/requests/${rid}?tab=ticket`)
  await page.getByRole('button', { name: 'Edit ticket' }).click()
  await page.getByLabel('Objective').fill('Add a subtract(a, b) function next to add in calc/ops.py, with a test.')
  await page.getByRole('button', { name: 'Save as new revision' }).click()
  await expect(page.getByTestId('header-approve')).toHaveText(`Approve ticket v${v1.n + 1}`)
  expect(await slackAction(`approve_ticket:${rid}:${v1.hash}`, (await stack()).requester)).toBe(200)
  await expect
    .poll(async () => (await api.request(rid)).approvals.some((a) => a.status === 'refused' && a.reason === 'stale_revision'))
    .toBe(true)
  const req = await api.request(rid)
  expect(req.state).toBe('Awaiting approval')
  expect(req.currentRevision?.n).toBe(v1.n + 1)
})

test('B-AC-8 B-AC-38 approving from Slack and the UI at the same moment counts once and starts one build', async ({ page }) => {
  const rev = (await api.request(rid)).currentRevision!
  await signIn(page, `/app/requests/${rid}?tab=ticket`)
  await page.getByTestId('header-approve').click()
  const dialog = page.getByRole('dialog', { name: new RegExp(`Approve ticket v${rev.n}`) })
  await expect(dialog).toBeVisible()
  const requester = (await stack()).requester
  await Promise.all([
    dialog.getByRole('button', { name: new RegExp(`Approve ticket v${rev.n}`) }).click(),
    slackAction(`approve_ticket:${rid}:${rev.hash}`, requester),
  ])
  await expect(workspaceState(page)).toHaveAttribute('data-state', /Building|PR ready for review/, { timeout: 60_000 })
  const req = await api.waitFor(rid, ['PR ready for review'], 120_000)
  expect(req.approvals.filter((a) => a.kind === 'ticket' && a.status === 'accepted')).toHaveLength(1)
  expect(req.builds).toHaveLength(1)
})

test('B-AC-39 B-AC-40 the build streamed its steps; the first attempt failed a real test and the repair passed', async ({ page }) => {
  await signIn(page, `/app/requests/${rid}?tab=build`)
  const theatre = page.getByTestId('build-theatre')
  await expect(theatre).toBeVisible()
  await expect(theatre.getByRole('region', { name: 'Build steps' })).toContainText(/Context pack written|Diff check passed/)
  await expect(theatre.getByRole('region', { name: 'Repair attempts' })).toBeVisible()
  await expect(page.locator('[data-testid="timeline-item"][data-type="build.repair"]').first()).toBeAttached()
  await expect(page.locator('[data-testid="timeline-item"][data-type="tests.result"]').first()).toBeAttached()
  const req = await api.request(rid)
  const build = req.builds[0]!
  expect(build.status).toBe('passed')
  expect(build.attempts).toBe(2)
  // The first attempt's real pytest failure (fake Pi wrote `return a + b` for subtract) is in the build log.
  const log = await (await api.ctx.get(`/api/requests/${rid}/builds/${build.id}/log`)).text()
  expect(log).toMatch(/test_subtract/)
})

test('C-AC-26 B-AC-76 the PR tab shows the diff, the tests on the head and the constraints', async ({ page }) => {
  await signIn(page, `/app/requests/${rid}?tab=pr`)
  const pr = page.getByTestId('pr-panel')
  await expect(pr).toBeVisible()
  await expect(pr.getByTestId('diff-viewer')).toContainText('calc/ops.py')
  await expect(pr.getByTestId('diff-viewer')).toContainText('def subtract')
  await expect(pr.getByTestId('test-list')).toContainText('test_subtract')
  await expect(pr.getByTestId('constraints-checklist')).toContainText('add keeps its signature')
  const pulls = (await (await fetch('http://127.0.0.1:18100/github/pulls')).json()) as { pulls: { number: number; files: string[] }[] }
  const number = (await api.request(rid)).pr!.number
  expect(pulls.pulls.find((p) => p.number === number)?.files).toEqual(['calc/ops.py', 'tests/test_ops.py'])
})

test('B-AC-71 requesting changes on the PR starts a new build on the same branch', async ({ page }) => {
  const before = await api.request(rid)
  await signIn(page, `/app/requests/${rid}?tab=pr`)
  await page.locator('#pr-feedback').fill('Please add a second test case for subtract with negative numbers.')
  await page.getByTestId('pr-panel').getByRole('button', { name: 'Request changes' }).click()
  await expect(workspaceState(page)).toHaveAttribute('data-state', /Changes requested|Building/, { timeout: 60_000 })
  const after = await api.waitFor(rid, ['PR ready for review'], 120_000)
  expect(after.builds).toHaveLength(2)
  expect(after.pr?.number).toBe(before.pr?.number)
})

test('B-AC-49 approving the PR writes the change back; the graph explorer finds it', async ({ page }) => {
  const pr = (await api.request(rid)).pr!
  await signIn(page, `/app/requests/${rid}?tab=pr`)
  await approveFromHeader(page, new RegExp(`Approve PR #${pr.number}`))
  await expect(workspaceState(page)).toHaveAttribute('data-state', 'Done', { timeout: 60_000 })
  await expect(page.locator('[data-testid="timeline-item"][data-type="writeback.done"]').first()).toBeAttached({ timeout: 60_000 })
  await page.goto('/app/graph')
  await page.getByTestId('graph-search').fill('subtract')
  const results = page.getByTestId('graph-results')
  await expect(results).toContainText(/Pull request|PR|subtract/i)
  await results.getByRole('button').first().click()
  await expect(page.getByTestId('node-inspector')).toBeVisible()
})

test('B-AC-31 B-AC-36 an answer given in Slack updates the open request page live', async ({ page }) => {
  const before = (await api.get<{ requests: { id: string }[] }>('/api/requests?limit=100')).requests.map((r) => r.id)
  expect(await slackCommand('Add a multiply function next to `add` in calc/ops.py')).toBe(200)
  const id = await newRequestId(before)
  const req = await api.waitFor(id, ['Needs your input'])
  await signIn(page, `/app/requests/${id}?tab=questions`)
  await expect(page.locator('[data-testid="question-card"][data-answered="false"]').first()).toBeVisible()
  const q = req.questions.find((x) => !x.answer)!
  expect(await slackAction(`answer:${id}:${q.questionId}:#0`, (await stack()).requester)).toBe(200)
  await expect(page.getByTestId('answer').first()).toContainText(/Slack/)
  await expect(workspaceState(page)).toHaveAttribute('data-state', 'Awaiting approval', { timeout: 60_000 })
})
