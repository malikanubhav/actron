// FIXTURE: recorded-style test data for development and tests only; never used in production builds.
// Starts MSW in the browser. Loaded only when NEXT_PUBLIC_ACTRON_DEV_FIXTURES=1 (components/shell/Providers.tsx).
import { setupWorker } from 'msw/browser'
import { handlers } from './handlers'
import { detectScenario, getEngine, resetEngine, SCENARIOS, type Scenario } from './engine'

let started: Promise<void> | null = null

export async function startWorker(): Promise<void> {
  if (!started) {
    getEngine()
    const worker = setupWorker(...handlers)
    started = worker
      .start({ onUnhandledRequest: 'bypass', quiet: true, serviceWorker: { url: '/mockServiceWorker.js' } })
      .then(() => undefined)
  }
  return started
}

/** Switches the fixture scenario and reloads the page (also reachable with `?fixture=<name>`). */
export function setScenario(scenario: Scenario): void {
  if (!SCENARIOS.includes(scenario)) return
  try {
    window.sessionStorage.setItem('actron.fixture', scenario)
  } catch {
    // Storage blocked: the URL parameter still works.
  }
  resetEngine()
  const url = new URL(window.location.href)
  url.searchParams.set('fixture', scenario)
  window.location.assign(url.toString())
}

export { detectScenario, SCENARIOS }
