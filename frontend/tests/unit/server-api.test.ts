import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('server-only', () => ({}))
const getAll = vi.fn()
vi.mock('next/headers', () => ({ cookies: async () => ({ getAll }) }))

import { ApiError } from '@/lib/api'
import { serverApi, serverApiOrNull } from '@/lib/api/server'

const fetchMock = vi.fn()
beforeEach(() => {
  fetchMock.mockReset()
  getAll.mockReset()
  getAll.mockReturnValue([])
  vi.stubGlobal('fetch', fetchMock)
  vi.stubEnv('API_INTERNAL_URL', 'http://backend.test:8080/')
})
afterEach(() => {
  vi.unstubAllGlobals()
  vi.unstubAllEnvs()
})

const ok = (body: unknown) => new Response(JSON.stringify(body), { status: 200 })

describe('B-AC-59 server-side API access', () => {
  it('calls the internal URL without a trailing slash and parses JSON', async () => {
    fetchMock.mockResolvedValue(ok({ hello: 'world' }))
    await expect(serverApi('/api/health')).resolves.toEqual({ hello: 'world' })
    expect(fetchMock.mock.calls[0]?.[0]).toBe('http://backend.test:8080/api/health')
  })

  it('forwards the incoming cookies, url-encoded, and skips them on public routes', async () => {
    getAll.mockReturnValue([
      { name: 'sid', value: 'a b' },
      { name: 'actron_csrf', value: 'x' },
    ])
    fetchMock.mockImplementation(async () => ok({}))
    await serverApi('/api/me')
    expect((fetchMock.mock.calls[0]?.[1] as RequestInit).headers).toMatchObject({ Cookie: 'sid=a%20b; actron_csrf=x' })
    await serverApi('/api/public/replays/r1', { withCookies: false })
    expect((fetchMock.mock.calls[1]?.[1] as RequestInit).headers).not.toHaveProperty('Cookie')
  })

  it('does not send a Cookie header when there are no cookies', async () => {
    fetchMock.mockImplementation(async () => ok({}))
    await serverApi('/api/me')
    expect((fetchMock.mock.calls[0]?.[1] as RequestInit).headers).not.toHaveProperty('Cookie')
  })

  it('uses no-store by default and revalidate when asked', async () => {
    fetchMock.mockImplementation(async () => ok({}))
    await serverApi('/api/a')
    expect(fetchMock.mock.calls[0]?.[1]).toMatchObject({ cache: 'no-store' })
    await serverApi('/api/b', { revalidate: 60 })
    expect(fetchMock.mock.calls[1]?.[1]).toMatchObject({ next: { revalidate: 60 } })
  })

  it('turns an error body into an ApiError with its code, message and status', async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify({ error: { code: 'not_found', message: 'No such request.' } }), { status: 404 }))
    const error = await serverApi('/api/requests/x').catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ code: 'not_found', message: 'No such request.', status: 404 })
  })

  it('falls back to a plain message when the error body is not JSON', async () => {
    fetchMock.mockResolvedValue(new Response('<html>bad gateway</html>', { status: 502 }))
    await expect(serverApi('/api/x')).rejects.toMatchObject({ code: 'http_error', message: 'The server answered 502.', status: 502 })
  })

  it('aborts a call that takes longer than the timeout', async () => {
    fetchMock.mockImplementation((_url: string, init: RequestInit) => new Promise((_resolve, reject) => init.signal?.addEventListener('abort', () => reject(new Error('aborted')))))
    await expect(serverApi('/api/slow', { timeoutMs: 20 })).rejects.toThrow('aborted')
  })

  it('serverApiOrNull returns null on any failure and the data on success', async () => {
    fetchMock.mockRejectedValueOnce(new Error('connection refused'))
    await expect(serverApiOrNull('/api/x')).resolves.toBeNull()
    fetchMock.mockResolvedValueOnce(ok({ a: 1 }))
    await expect(serverApiOrNull('/api/x')).resolves.toEqual({ a: 1 })
  })
})
