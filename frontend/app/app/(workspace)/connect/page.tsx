import type { Metadata } from 'next'
import { Suspense } from 'react'
import { dehydrate, HydrationBoundary, QueryClient } from '@tanstack/react-query'
import { ConnectScreen } from '@/components/connect/ConnectScreen'
import { serverApiOrNull } from '@/lib/api/server'
import { DEV_FIXTURES } from '@/lib/env'
import { qk } from '@/lib/query-keys'
import { normalizeConnectors } from '@/lib/connectors'

export const metadata: Metadata = {
  title: 'Connect',
  description: 'Connect your repository, Slack and Linear, and watch Actron read them into one graph.',
}

/** Initial data on the server so cards and counts paint once, without layout shift (C8). */
export default async function ConnectPage() {
  const client = new QueryClient()
  if (!DEV_FIXTURES) {
    const [connectors, connections, ingestion, stats, requests] = await Promise.all([
      serverApiOrNull('/api/connectors', { timeoutMs: 2500 }),
      serverApiOrNull('/api/connections', { timeoutMs: 2500 }),
      serverApiOrNull('/api/ingestion/status', { timeoutMs: 2500 }),
      serverApiOrNull('/api/graph/stats', { timeoutMs: 2500 }),
      serverApiOrNull('/api/requests?limit=1', { timeoutMs: 2500 }),
    ])
    if (connectors) client.setQueryData(qk.connectors(), normalizeConnectors(connectors as { providers?: unknown }))
    if (connections) client.setQueryData(qk.connections(), connections)
    if (ingestion) client.setQueryData(qk.ingestion(), ingestion)
    if (stats) client.setQueryData(qk.graphStats(), stats)
    if (requests) client.setQueryData(qk.requests({ group: undefined, limit: 1 }), requests)
  }
  return (
    <HydrationBoundary state={dehydrate(client)}>
      <Suspense fallback={null}>
        <ConnectScreen />
      </Suspense>
    </HydrationBoundary>
  )
}
