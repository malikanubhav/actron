import { expect, type Page } from '@playwright/test'
import { FIXTURE_IDS } from '../fixtures/data/ids'

export { FIXTURE_IDS }

/** Speeds up the scripted SSE fixtures so live flows finish in seconds. */
export async function fast(page: Page, speed = 0.05) {
  await page.addInitScript((s) => {
    ;(window as unknown as { __actronFixtureSpeed: number }).__actronFixtureSpeed = s
  }, speed)
}

/** Opens a path with a fixture scenario (default, empty, backend-down, stream-drop). */
export async function open(page: Page, path: string, scenario?: 'default' | 'empty' | 'backend-down' | 'stream-drop') {
  const url = scenario ? `${path}${path.includes('?') ? '&' : '?'}fixture=${scenario}` : path
  await page.goto(url)
  await expect(page.getByTestId('dev-fixtures-badge').first()).toBeVisible()
  // App screens: wait until the shell has hydrated (the footer renders after the fixture worker starts).
  if (path.startsWith('/app') && !path.startsWith('/app/signin')) await expect(page.getByTestId('footer-status')).toBeVisible()
}

/** Collects console errors so tests can assert none happened. */
export function consoleErrors(page: Page): string[] {
  const errors: string[] = []
  page.on('console', (msg) => {
    if (msg.type() === 'error') errors.push(msg.text())
  })
  page.on('pageerror', (err) => errors.push(err.message))
  return errors
}

/** Screens and their expected header copy for route and five-second checks. */
export const SCREENS = [
  { path: '/app', eyebrow: 'Requests' },
  { path: '/app/inbox', eyebrow: 'Inbox' },
  { path: '/app/graph', eyebrow: 'Graph' },
  { path: '/app/system', eyebrow: 'System' },
  { path: '/app/connect', eyebrow: 'Connect' },
  { path: '/app/settings', eyebrow: 'Settings' },
  { path: `/app/requests/${FIXTURE_IDS.done}`, eyebrow: 'Request' },
  { path: `/app/requests/${FIXTURE_IDS.done}/replay`, eyebrow: 'Replay' },
] as const
