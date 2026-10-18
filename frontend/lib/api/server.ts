import 'server-only'
/**
 * Server-side API access for server components (spec C, C4): calls API_INTERNAL_URL directly and forwards the
 * incoming request's cookies. With NEXT_PUBLIC_ACTRON_DEV_FIXTURES=1 the same paths are answered from
 * tests/fixtures (the browser uses MSW for the same data), so fixture mode never needs a backend.
 */
import { cookies } from 'next/headers'
import { DEV_FIXTURES, apiInternalUrl } from '../env'
import { ApiError } from '../api'

export interface ServerFetchOptions {
  /** Abort after this many milliseconds (landing page fetches must never block first paint for long). */
  timeoutMs?: number
  /** Forward the session cookie (app routes) or not (public routes). */
  withCookies?: boolean
  revalidate?: number | false
}

export async function serverApi<T>(path: string, options: ServerFetchOptions = {}): Promise<T> {
  const { timeoutMs = 4000, withCookies = true, revalidate = false } = options
  if (DEV_FIXTURES) {
    const { fixtureResponse } = await import('@/tests/fixtures/msw/router')
    const res = fixtureResponse('GET', path)
    if (res.status >= 400) {
      const body = res.json as { error?: { code?: string; message?: string } } | undefined
      throw new ApiError(body?.error?.code ?? 'http_error', body?.error?.message ?? 'Fixture error', res.status)
    }
    return res.json as T
  }
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (withCookies) {
    const jar = await cookies()
    const cookieHeader = jar
      .getAll()
      .map((c) => `${c.name}=${encodeURIComponent(c.value)}`)
      .join('; ')
    if (cookieHeader) headers.Cookie = cookieHeader
  }
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  try {
    const response = await fetch(`${apiInternalUrl()}${path}`, {
      headers,
      signal: controller.signal,
      ...(revalidate === false ? { cache: 'no-store' as const } : { next: { revalidate } }),
    })
    if (!response.ok) {
      let code = 'http_error'
      let message = `The server answered ${response.status}.`
      try {
        const body = (await response.json()) as { error?: { code?: string; message?: string } }
        code = body.error?.code ?? code
        message = body.error?.message ?? message
      } catch {
        // Non-JSON error body.
      }
      throw new ApiError(code, message, response.status)
    }
    return (await response.json()) as T
  } finally {
    clearTimeout(timer)
  }
}

/** Same as serverApi but returns null on any failure (backend down, timeout, 404). */
export async function serverApiOrNull<T>(path: string, options: ServerFetchOptions = {}): Promise<T | null> {
  try {
    return await serverApi<T>(path, options)
  } catch {
    return null
  }
}
