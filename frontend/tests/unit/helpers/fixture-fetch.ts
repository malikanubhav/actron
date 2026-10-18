import { vi } from 'vitest'
import { setCsrfToken, setFetch } from '@/lib/api'
import { FixtureEngine, type FixtureResponse, type Scenario } from '@/tests/fixtures/msw/engine'
import { CONNECTOR_DEFINITIONS } from '@/tests/fixtures/data/connectors'

export interface FixtureApi {
  engine: FixtureEngine
  /** Every request the page made, in order. */
  calls: { method: string; path: string; body: unknown; key: string | undefined }[]
  /** Answer one method and path (query ignored) with a custom response instead of the fixture engine. */
  override: (method: string, path: string, response: FixtureResponse | (() => FixtureResponse | Promise<FixtureResponse>)) => void
  restore: () => void
}

/**
 * Routes `fetch` through the fixture engine (the same data the dev fixtures and end-to-end tests use), so a screen
 * can be rendered with realistic server answers and real mutations. Timers are off: nothing happens by itself.
 */
export function installFixtureFetch(scenario: Scenario = 'default'): FixtureApi {
  const engine = new FixtureEngine({ scenario, timers: 'none' })
  const overrides = new Map<string, FixtureResponse | (() => FixtureResponse | Promise<FixtureResponse>)>()
  // The connector catalogue is served by the MSW handlers, not the engine; answer it here from the same data.
  overrides.set('GET /api/connectors', { status: 200, json: { providers: CONNECTOR_DEFINITIONS } })
  const calls: FixtureApi['calls'] = []
  setCsrfToken('csrf-test')
  setFetch(
    vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      const path = String(url)
      const headers = (init?.headers ?? {}) as Record<string, string>
      const body = typeof init?.body === 'string' ? (JSON.parse(init.body) as unknown) : undefined
      calls.push({ method, path, body, key: headers['Idempotency-Key'] })
      const override = overrides.get(`${method} ${path.split('?')[0]}`)
      const res = override ? (typeof override === 'function' ? await override() : override) : engine.route(method, path, body)
      if (res.text) return new Response(String(res.json), { status: res.status })
      if (res.status === 204) return new Response(null, { status: 204 })
      return new Response(JSON.stringify(res.json), { status: res.status, headers: { 'Content-Type': 'application/json' } })
    }) as unknown as typeof fetch,
  )
  return {
    engine,
    calls,
    override: (method, path, response) => void overrides.set(`${method} ${path}`, response),
    restore: () => {
      engine.stop()
      setFetch(null)
      setCsrfToken(null)
    },
  }
}
