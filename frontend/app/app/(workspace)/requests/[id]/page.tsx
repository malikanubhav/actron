import type { Metadata } from 'next'
import { Suspense } from 'react'
import { dehydrate, HydrationBoundary, QueryClient } from '@tanstack/react-query'
import { RequestScreen } from '@/components/request/RequestScreen'
import { serverApiOrNull } from '@/lib/api/server'
import { DEV_FIXTURES } from '@/lib/env'
import { qk } from '@/lib/query-keys'
import type { RequestDetail } from '@/lib/api/types'

type Props = { params: Promise<{ id: string }> }

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { id } = await params
  const data = await serverApiOrNull<{ request: RequestDetail }>(`/api/requests/${encodeURIComponent(id)}`, { timeoutMs: 2000 })
  return {
    title: data ? data.request.title : 'Request',
    description: data ? `${data.request.state}. ${data.request.headline}` : 'A request in Actron: evidence, questions, ticket, build and pull request.',
  }
}

export default async function RequestPage({ params }: Props) {
  const { id } = await params
  const client = new QueryClient()
  // Fixture mode: the browser's MSW scenario owns the data, so the server does not prefetch.
  const data = DEV_FIXTURES ? null : await serverApiOrNull<{ request: RequestDetail }>(`/api/requests/${encodeURIComponent(id)}`, { timeoutMs: 2500 })
  if (data) client.setQueryData(qk.request(id), data)
  return (
    <HydrationBoundary state={dehydrate(client)}>
      <Suspense>
        <RequestScreen id={id} />
      </Suspense>
    </HydrationBoundary>
  )
}
