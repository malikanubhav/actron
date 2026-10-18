import { render } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactElement } from 'react'
import { vi } from 'vitest'
import { CONNECTOR_DEFINITIONS, CONNECTOR_OPTIONS, checksFixture, validateFixture, type CheckOutcome } from '@/tests/fixtures/data/connectors'
import type { ConnectionView, ConnectorDefinition } from '@/lib/api/types'

export function def(provider: string): ConnectorDefinition {
  const found = CONNECTOR_DEFINITIONS.find((d) => d.provider === provider)
  if (!found) throw new Error(provider)
  return found
}

export const outcome: { value: CheckOutcome } = { value: 'connected' }

/** Fixture-backed endpoint implementations, installed by each test file's vi.mock. */
export function installEndpoints(endpoints: Record<string, ReturnType<typeof vi.fn>>) {
  endpoints.connectors!.mockImplementation(async () => ({ providers: CONNECTOR_DEFINITIONS }))
  endpoints.validateConnector!.mockImplementation(async (provider: string, values: Record<string, unknown>) =>
    validateFixture(provider, values),
  )
  endpoints.connectorOptions!.mockImplementation(async (provider: string, field: string) => ({
    options: CONNECTOR_OPTIONS[provider]?.[field] ?? [],
  }))
  endpoints.connectorChecks!.mockImplementation(async (provider: string) => ({ checks: checksFixture(provider, outcome.value) }))
  endpoints.createConnection!.mockImplementation(async (body: unknown) => {
    const b = body as { provider?: string; secret?: Record<string, string> }
    const secret = Object.values(b.secret ?? {})[0]
    return {
      connection: connection(b.provider ?? 'slack_export', { secretLast4: secret ? secret.slice(-4) : null, state: 'BACKFILLING' }),
      runId: 'run_1',
    }
  })
  endpoints.syncConnection!.mockImplementation(async () => ({ triggered: true }))
  endpoints.deleteConnection!.mockImplementation(async () => undefined)
}

export function endpointMocks() {
  return {
    connectors: vi.fn(),
    validateConnector: vi.fn(),
    connectorOptions: vi.fn(),
    connectorChecks: vi.fn(),
    createConnection: vi.fn(),
    syncConnection: vi.fn(),
    deleteConnection: vi.fn(),
  }
}

export function connection(
  provider: string,
  over: { state?: ConnectionView['sync']['state']; secretLast4?: string | null; reason?: string | null; counts?: Record<string, number>; config?: Record<string, unknown> } = {},
): ConnectionView {
  return {
    id: `conn_${provider}`,
    provider: provider as ConnectionView['provider'],
    status: 'connected',
    config: over.config ?? {},
    secretLast4: over.secretLast4 ?? null,
    createdAt: '2026-10-16T09:00:00Z',
    updatedAt: '2026-10-17T11:58:00Z',
    sync: {
      state: over.state ?? 'UP TO DATE',
      lastSyncedAt: '2026-10-17T11:58:00Z',
      reason: over.reason ?? null,
      perMinute: 120,
      counts: over.counts ?? {},
    },
  }
}

export function renderWithClient(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return { client, ...render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>) }
}
