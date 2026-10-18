/**
 * FIXTURE: recorded-style test data for development and tests only; never used in production builds.
 *
 * MSW handlers for connector definitions, validation, options, setup-guide checks and connection creation
 * (spec C, C12 and C13). fork A's handlers.ts spreads these before its own.
 */
import { http, HttpResponse, type HttpHandler } from 'msw'
import type { ConnectionView, Provider } from '@/lib/api/types'
import {
  CONNECTOR_DEFINITIONS,
  CONNECTOR_OPTIONS,
  checksFixture,
  validateFixture,
  type CheckOutcome,
} from '../data/connectors'

function scenario(): string {
  if (typeof window === 'undefined') return 'default'
  try {
    const fromUrl = new URLSearchParams(window.location.search).get('fixture')
    return fromUrl ?? window.sessionStorage.getItem('actron.fixture') ?? 'default'
  } catch {
    return 'default'
  }
}

const outcomes = new Map<string, CheckOutcome>()

function outcomeFor(provider: string): CheckOutcome {
  const known = outcomes.get(provider)
  if (known) return known
  return scenario() === 'empty' ? 'pending' : 'connected'
}

/** Test hook: reset what the checks report. */
export function resetConnectorFixtures(): void {
  outcomes.clear()
}

function outcomeFromValues(provider: string, values: Record<string, unknown>, ok: boolean): CheckOutcome {
  const all = Object.values(values)
    .filter((v): v is string => typeof v === 'string')
    .join(' ')
  if (!ok) return 'auth_failed'
  if (provider === 'github' && /readonly/i.test(all)) return 'readonly'
  if (provider === 'slack' && /noscope/i.test(all)) return 'missing_scope'
  if (provider === 'slack' && /nochannel/i.test(all)) return 'not_in_channel'
  return 'connected'
}

const PREFIX = '*/api'

export const connectorHandlers: HttpHandler[] = [
  http.get(`${PREFIX}/connectors`, () => HttpResponse.json({ providers: CONNECTOR_DEFINITIONS })),

  http.post(`${PREFIX}/connectors/:provider/validate`, async ({ params, request }) => {
    const provider = String(params.provider)
    let body: { values?: Record<string, unknown> } = {}
    try {
      body = (await request.json()) as { values?: Record<string, unknown> }
    } catch {
      body = {}
    }
    const values = body.values ?? {}
    const result = validateFixture(provider, values)
    outcomes.set(provider, outcomeFromValues(provider, values, result.ok))
    return HttpResponse.json(result)
  }),

  http.get(`${PREFIX}/connectors/:provider/options`, ({ params, request }) => {
    const provider = String(params.provider)
    const field = new URL(request.url).searchParams.get('field') ?? ''
    const options = CONNECTOR_OPTIONS[provider]?.[field] ?? []
    return HttpResponse.json({ options })
  }),

  http.get(`${PREFIX}/connectors/:provider/checks`, ({ params }) => {
    const provider = String(params.provider)
    return HttpResponse.json({ checks: checksFixture(provider, outcomeFor(provider)) })
  }),

  http.post(`${PREFIX}/connections`, async ({ request }) => {
    let provider: Provider = 'github'
    let config: Record<string, unknown> = {}
    let secretLast4: string | null = null
    const type = request.headers.get('content-type') ?? ''
    if (type.includes('multipart/form-data')) {
      const form = await request.formData()
      provider = (String(form.get('provider') ?? 'slack_export') as Provider) ?? 'slack_export'
      const archive = form.get('archive')
      config = { archive: archive instanceof File ? archive.name : 'export.zip' }
    } else {
      const body = (await request.json()) as {
        provider?: Provider
        config?: Record<string, unknown>
        secret?: Record<string, string>
      }
      provider = body.provider ?? 'github'
      config = body.config ?? {}
      const firstSecret = Object.values(body.secret ?? {}).find((v) => typeof v === 'string' && v.length >= 4)
      secretLast4 = firstSecret ? firstSecret.slice(-4) : null
    }
    const now = new Date().toISOString()
    const connection: ConnectionView = {
      id: `conn_fixture_${provider}`,
      provider,
      status: 'connected',
      config,
      secretLast4,
      createdAt: now,
      updatedAt: now,
      sync: { state: 'BACKFILLING', lastSyncedAt: null, reason: null, perMinute: 0, counts: {} },
    }
    return HttpResponse.json({ connection, runId: `run_fixture_${provider}` }, { status: 201 })
  }),
]
