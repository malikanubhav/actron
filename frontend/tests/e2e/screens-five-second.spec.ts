import { expect, test } from '@playwright/test'
import { FIXTURE_IDS, open } from './helpers'

/**
 * C-AC-22: every screen and primary state passes the five-second checklist: eyebrow, situation headline,
 * purpose line, one obvious main action, visible state.
 */
const CASES: { name: string; path: string; scenario?: 'empty'; headline: RegExp; action: RegExp; state?: RegExp }[] = [
  { name: 'home', path: '/app', headline: /need you|running|building|Nothing needs you/, action: /Ask Actron/ },
  { name: 'home empty', path: '/app', scenario: 'empty', headline: /No requests yet/, action: /Connect a repository/ },
  { name: 'request awaiting approval (stale)', path: `/app/requests/${FIXTURE_IDS.stale}?tab=ticket`, headline: /ready for your approval/, action: /Approve ticket v2/, state: /Awaiting approval/i },
  { name: 'request building', path: `/app/requests/${FIXTURE_IDS.building}?tab=build`, headline: /Building/, action: /Cancel/, state: /Building/i },
  { name: 'request failed', path: `/app/requests/${FIXTURE_IDS.failed}?tab=build`, headline: /failed|stopped|needs/i, action: /Retry/, state: /Needs attention/i },
  { name: 'request PR ready', path: `/app/requests/${FIXTURE_IDS.prReady}?tab=pr`, headline: /ready for review/, action: /Approve PR/, state: /PR ready for review/i },
  { name: 'request done', path: `/app/requests/${FIXTURE_IDS.done}`, headline: /Done/, action: /Replay/, state: /Done/i },
  { name: 'request cancelled', path: `/app/requests/${FIXTURE_IDS.cancelled}`, headline: /Cancelled|closed/, action: /.*/, state: /Cancelled/i },
  { name: 'inbox', path: '/app/inbox', headline: /notices? on|No notices yet/, action: /Mark read|Answer|See why|Approve|Review|Open/ },
  { name: 'graph', path: '/app/graph', headline: /node types|empty|memory/, action: /.*/ },
  { name: 'system', path: '/app/system', headline: /What Actron is doing right now/, action: /.*/ },
  { name: 'settings', path: '/app/settings', headline: /model|jobs/i, action: /Save changes/ },
  { name: 'connect', path: '/app/connect', headline: /memory|Connect a repository/i, action: /Sync now|Connect|Check connection/ },
]

for (const c of CASES) {
  test(`C-AC-22 five-second check: ${c.name}`, async ({ page }) => {
    await open(page, c.path, c.scenario)
    const header = page.getByTestId('screen-header').first()
    await expect(header.locator('.eyebrow').first()).not.toBeEmpty()
    await expect(header.locator('h1')).toHaveText(c.headline)
    await expect(header.locator('p').first()).not.toBeEmpty()
    await expect(page.getByRole('button', { name: c.action }).or(page.getByRole('link', { name: c.action })).first()).toBeVisible()
    if (c.state) await expect(page.getByText(c.state).first()).toBeVisible()
  })
}
