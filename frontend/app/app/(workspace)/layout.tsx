import { redirect } from 'next/navigation'
import { dehydrate, QueryClient, HydrationBoundary } from '@tanstack/react-query'
import { AppShell } from '@/components/shell/AppShell'
import { serverApi, serverApiOrNull } from '@/lib/api/server'
import { DEV_FIXTURES } from '@/lib/env'
import { ApiError } from '@/lib/api'
import type { Me } from '@/lib/api/types'
import { qk } from '@/lib/query-keys'

/**
 * Signed-in shell for /app/*: rail, footer status bar, palette, toasts and the workspace stream (PROMPT 8.7).
 * The session is checked on the server with the forwarded cookie; no session → sign-in.
 */
export default async function WorkspaceLayout({ children }: { children: React.ReactNode }) {
  let me: Me | null = null
  try {
    me = await serverApi<Me>('/api/me', { timeoutMs: 3000 })
  } catch (error) {
    if (error instanceof ApiError && (error.status === 401 || error.status === 403)) redirect('/app/signin')
    // Backend unreachable: render the shell; screens show their own error states and retry.
    me = null
  }
  const client = new QueryClient()
  if (me) client.setQueryData(qk.me(), me)
  // The rail and footer read these on every screen. Hydrating them here, above the shell, keeps server and client
  // renders identical and lets page-level prefetches hydrate in render.
  if (me && !DEV_FIXTURES) {
    const [notifications, ingestion, settings] = await Promise.all([
      serverApiOrNull('/api/notifications', { timeoutMs: 2000 }),
      serverApiOrNull('/api/ingestion/status', { timeoutMs: 2000 }),
      serverApiOrNull('/api/settings', { timeoutMs: 2000 }),
    ])
    if (notifications) client.setQueryData(qk.notifications(), notifications)
    if (ingestion) client.setQueryData(qk.ingestion(), ingestion)
    if (settings) client.setQueryData(qk.settings(), settings)
  }
  return (
    <HydrationBoundary state={dehydrate(client)}>
      <AppShell>{children}</AppShell>
    </HydrationBoundary>
  )
}
