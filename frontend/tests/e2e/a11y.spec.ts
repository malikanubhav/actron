import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import { FIXTURE_IDS, open } from './helpers'

/** C-AC-30: zero serious or critical axe violations on every route in its primary states. */
const ROUTES: { path: string; scenario?: 'empty' }[] = [
  { path: '/' },
  { path: '/app/signin' },
  { path: '/app' },
  { path: '/app', scenario: 'empty' },
  { path: '/app/inbox' },
  { path: '/app/graph' },
  { path: '/app/system' },
  { path: '/app/connect' },
  { path: '/app/connect', scenario: 'empty' },
  { path: '/app/settings' },
  { path: `/app/requests/${FIXTURE_IDS.done}` },
  { path: `/app/requests/${FIXTURE_IDS.stale}?tab=ticket` },
  { path: `/app/requests/${FIXTURE_IDS.building}?tab=build` },
  { path: `/app/requests/${FIXTURE_IDS.prReady}?tab=pr` },
  { path: `/app/requests/${FIXTURE_IDS.done}/replay` },
  { path: `/replay/${FIXTURE_IDS.done}` },
  { path: '/app/dev/glyphs' },
  { path: '/app/does-not-exist' },
]

for (const r of ROUTES) {
  test(`C-AC-30 axe: ${r.path}${r.scenario ? ` (${r.scenario})` : ''}`, async ({ page }) => {
    await open(page, r.path, r.scenario)
    await page.waitForLoadState('networkidle')
    const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze()
    const serious = results.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')
    expect(serious.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).slice(0, 3).join(' | ')}`)).toEqual([])
  })
}
