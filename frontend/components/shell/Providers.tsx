'use client'
import { useEffect, useState, type ReactNode } from 'react'
import { QueryClient, QueryClientProvider, HydrationBoundary, type DehydratedState } from '@tanstack/react-query'
import { ApiError } from '@/lib/api'
import { DEV_FIXTURES } from '@/lib/env'

export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 15_000,
        refetchOnWindowFocus: true,
        retryDelay: (attempt) => Math.min(4000, 600 * 2 ** attempt),
        retry: (failureCount, error) => {
          if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false
          // A server error is retried once, quickly, so a down backend shows its error state within seconds.
          if (error instanceof ApiError) return failureCount < 1
          return failureCount < 2
        },
      },
      mutations: { retry: false },
    },
  })
}

/** Starts MSW before anything fetches when dev fixtures are on; production builds never include the worker. */
function FixtureGate({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(!DEV_FIXTURES)
  useEffect(() => {
    if (!DEV_FIXTURES) return
    let cancelled = false
    import('@/tests/fixtures/msw/browser')
      .then((m) => m.startWorker())
      .then(() => {
        if (!cancelled) setReady(true)
      })
      .catch((error: unknown) => {
        console.error('Dev fixtures could not start', error)
        if (!cancelled) setReady(true)
      })
    return () => {
      cancelled = true
    }
  }, [])
  if (!ready) return <div className="min-h-dvh bg-ink-0" aria-busy="true" />
  return <>{children}</>
}

export function Providers({ children, state }: { children: ReactNode; state?: DehydratedState }) {
  const [client] = useState(makeQueryClient)
  return (
    <QueryClientProvider client={client}>
      <FixtureGate>
        <HydrationBoundary state={state}>{children}</HydrationBoundary>
      </FixtureGate>
    </QueryClientProvider>
  )
}
