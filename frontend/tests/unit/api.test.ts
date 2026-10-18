import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError, buildUrl, NetworkError, newIdempotencyKey, parseError, reasonText, setCsrfToken, setFetch, getCsrfToken } from '@/lib/api'

type Call = { url: string; init: RequestInit }

function fakeFetch(responses: (Response | Error)[]) {
  const calls: Call[] = []
  const impl = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ url: String(url), init: init ?? {} })
    const next = responses.shift()
    if (!next) throw new Error('no response queued')
    if (next instanceof Error) throw next
    return next
  })
  setFetch(impl as unknown as typeof fetch)
  return calls
}

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
const header = (c: Call, name: string) => (c.init.headers as Record<string, string>)[name]

afterEach(() => {
  setFetch(null)
  setCsrfToken(null)
  vi.useRealTimers()
})

describe('C-AC-19 api client', () => {
  it('GET sends no CSRF or idempotency header and parses JSON', async () => {
    setCsrfToken('csrf-1')
    const calls = fakeFetch([json({ ok: 1 })])
    await expect(api('/api/me')).resolves.toEqual({ ok: 1 })
    expect(header(calls[0] as Call, 'X-CSRF-Token')).toBeUndefined()
    expect(header(calls[0] as Call, 'Idempotency-Key')).toBeUndefined()
    expect(calls[0]?.init.credentials).toBe('same-origin')
  })

  it('writes carry the CSRF token and an idempotency key, and JSON bodies', async () => {
    setCsrfToken('csrf-1')
    expect(getCsrfToken()).toBe('csrf-1')
    const calls = fakeFetch([json({ result: {} })])
    await api('/api/requests/r/answers', { method: 'POST', body: { questionId: 'q', value: 'dev' }, idempotencyKey: 'key-1' })
    const c = calls[0] as Call
    expect(header(c, 'X-CSRF-Token')).toBe('csrf-1')
    expect(header(c, 'Idempotency-Key')).toBe('key-1')
    expect(header(c, 'Content-Type')).toBe('application/json')
    expect(c.init.body).toBe('{"questionId":"q","value":"dev"}')
  })

  it('B-AC-59 without a token from /api/me, writes send the double-submit cookie value (server-prefetched /api/me)', async () => {
    document.cookie = 'actron_csrf=cookie-csrf%2B1; path=/'
    try {
      expect(getCsrfToken()).toBe('cookie-csrf+1')
      const calls = fakeFetch([json({})])
      await api('/api/connectors/github/validate', { method: 'POST', body: { values: {} } })
      expect(header(calls[0] as Call, 'X-CSRF-Token')).toBe('cookie-csrf+1')
      setCsrfToken('from-me')
      expect(getCsrfToken()).toBe('from-me')
    } finally {
      document.cookie = 'actron_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/'
    }
  })

  it('a write without a key still gets a fresh UUID', async () => {
    const calls = fakeFetch([json({})])
    await api('/api/x', { method: 'DELETE' })
    expect(header(calls[0] as Call, 'Idempotency-Key')).toMatch(/^[0-9a-f-]{36}$/)
  })

  it('C-AC-19 a network error is retried with the same idempotency key', async () => {
    const calls = fakeFetch([new TypeError('Failed to fetch'), new TypeError('Failed to fetch'), json({ result: { status: 'accepted' } })])
    const result = await api<{ result: { status: string } }>('/api/requests/r/approvals', { method: 'POST', body: {}, idempotencyKey: 'same' })
    expect(result.result.status).toBe('accepted')
    expect(calls).toHaveLength(3)
    expect(calls.map((c) => header(c, 'Idempotency-Key'))).toEqual(['same', 'same', 'same'])
  })

  it('gives up after the retries with a plain NetworkError', async () => {
    fakeFetch([new TypeError('x'), new TypeError('x')])
    await expect(api('/api/me', { networkRetries: 1 })).rejects.toBeInstanceOf(NetworkError)
  })

  it('HTTP errors are not retried and become typed ApiErrors', async () => {
    const calls = fakeFetch([json({ error: { code: 'stale_revision', message: 'Changed', details: { n: 2 } } }, 409)])
    const err = await api('/api/x', { method: 'POST' }).catch((e: unknown) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err).toMatchObject({ code: 'stale_revision', message: 'Changed', status: 409, details: { n: 2 }, isConflict: true })
    expect(calls).toHaveLength(1)
  })

  it('non-JSON error bodies get a fallback code', async () => {
    expect(await parseError(new Response('oops', { status: 404 }))).toMatchObject({ code: 'not_found', status: 404 })
    expect(await parseError(new Response('', { status: 401 }))).toMatchObject({ code: 'unauthenticated' })
    expect(await parseError(new Response('', { status: 502 }))).toMatchObject({ code: 'http_error', message: 'The server answered 502.' })
  })

  it('204, empty bodies, text mode and FormData', async () => {
    fakeFetch([new Response(null, { status: 204 }), new Response('', { status: 200 }), new Response('raw log', { status: 200 })])
    await expect(api('/api/x', { method: 'POST' })).resolves.toBeUndefined()
    await expect(api('/api/y')).resolves.toBeUndefined()
    await expect(api('/api/log', { as: 'text' })).resolves.toBe('raw log')
    const calls = fakeFetch([json({})])
    const fd = new FormData()
    fd.set('provider', 'slack_export')
    await api('/api/connections', { method: 'POST', body: fd })
    expect(calls[0]?.init.body).toBe(fd)
    expect(header(calls[0] as Call, 'Content-Type')).toBeUndefined()
  })

  it('buildUrl skips empty values and adds a leading slash', () => {
    expect(buildUrl('api/x')).toBe('/api/x')
    expect(buildUrl('/api/x', { a: 1, b: undefined, c: null, d: '', e: true })).toBe('/api/x?a=1&e=true')
    expect(buildUrl('/api/x', {})).toBe('/api/x')
  })

  it('newIdempotencyKey returns distinct UUIDs', () => {
    const a = newIdempotencyKey()
    expect(a).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/)
    expect(newIdempotencyKey()).not.toBe(a)
  })

  it.each([
    ['stale_revision', /ticket changed/],
    ['stale_head', /new commits/],
    ['external_edit', /Linear/],
    ['invalid_transition', /not available/],
    ['not_an_approver', /approvers list/],
    ['already_connected', /already connected/],
    ['not_finished', /still running/],
  ])('reasonText(%s) is plain words', (code, re) => {
    expect(reasonText(new ApiError(code, 'x', 409))).toMatch(re)
  })

  it('reasonText falls back to the message, network text and a generic sentence', () => {
    expect(reasonText(new ApiError('other', 'Server says no', 400))).toBe('Server says no')
    expect(reasonText(new NetworkError())).toMatch(/did not answer/)
    expect(reasonText(new Error('boom'))).toBe('boom')
    expect(reasonText(42)).toBe('Something went wrong.')
  })
})
