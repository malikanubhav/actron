import type { Metadata } from 'next'
import { dehydrate, HydrationBoundary, QueryClient } from '@tanstack/react-query'
import { HomeScreen } from '@/components/home/HomeScreen'
import { serverApiOrNull } from '@/lib/api/server'
import { DEV_FIXTURES } from '@/lib/env'
import { qk } from '@/lib/query-keys'
import type { RequestSummary } from '@/lib/api/types'

export const metadata: Metadata = {
  title: 'Requests',
  description: 'Requests that need you, running and done. Ask Actron for a change.',
}

type List = { requests: RequestSummary[]; counts: { needsYou: number; running: number; done: number } }

/** Initial data on the server for first paint; the client keeps it live. */
export default async function HomePage() {
  const client = new QueryClient()
  // Fixture mode: the browser's MSW scenario owns the data, so the server does not prefetch.
  const [needs, running, done, connections] = DEV_FIXTURES
    ? [null, null, null, null]
    : await Promise.all([
        serverApiOrNull<List>('/api/requests?group=needs_you', { timeoutMs: 2500 }),
        serverApiOrNull<List>('/api/requests?group=running', { timeoutMs: 2500 }),
        serverApiOrNull<List>('/api/requests?group=done&limit=20', { timeoutMs: 2500 }),
        serverApiOrNull('/api/connections', { timeoutMs: 2500 }),
      ])
  // Connections decide the composer and the first-run checklist; prefetching them avoids a layout shift.
  if (connections) client.setQueryData(qk.connections(), connections)
  if (needs) client.setQueryData(qk.requests({ group: 'needs_you', limit: undefined }), needs)
  if (running) client.setQueryData(qk.requests({ group: 'running', limit: undefined }), running)
  if (done) client.setQueryData(qk.requests({ group: 'done', limit: 20 }), done)
  return (
    <HydrationBoundary state={dehydrate(client)}>
      <HomeScreen />
    </HydrationBoundary>
  )
}
