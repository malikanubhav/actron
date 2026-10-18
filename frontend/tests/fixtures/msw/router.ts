// FIXTURE: recorded-style test data for development and tests only; never used in production builds.
// Server-side access to the same fixture data (lib/api/server.ts uses this when dev fixtures are on). No window and
// no timers here: the default scenario, as recorded.
import { FixtureEngine, type FixtureResponse } from './engine'

let serverEngine: FixtureEngine | null = null

function engine(): FixtureEngine {
  if (!serverEngine) serverEngine = new FixtureEngine({ scenario: 'default', timers: 'none' })
  return serverEngine
}

export function fixtureResponse(method: string, path: string, body?: unknown): { status: number; json: unknown } {
  const res: FixtureResponse = engine().route(method, path, body)
  return { status: res.status, json: res.json }
}
