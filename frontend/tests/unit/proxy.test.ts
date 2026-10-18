import { afterEach, describe, expect, it, vi } from 'vitest'
import { NextRequest } from 'next/server'
import { config, proxy } from '@/proxy'

function req(path: string, cookie?: string) {
  return new NextRequest(new URL(path, 'http://localhost:3000'), cookie ? { headers: { cookie } } : undefined)
}

describe('proxy auth redirect (C-AC-15)', () => {
  afterEach(() => vi.unstubAllEnvs())

  it('C-AC-15 redirects an unauthenticated /app request to sign-in with the return path', () => {
    vi.stubEnv('NEXT_PUBLIC_ACTRON_DEV_FIXTURES', '0')
    const res = proxy(req('/app/requests/req_1?tab=ticket'))
    expect(res.status).toBe(307)
    const location = new URL(res.headers.get('location') ?? '')
    expect(location.pathname).toBe('/app/signin')
    expect(location.searchParams.get('next')).toBe('/app/requests/req_1?tab=ticket')
  })

  it('C-AC-15 /app itself redirects without a next parameter', () => {
    vi.stubEnv('NEXT_PUBLIC_ACTRON_DEV_FIXTURES', '0')
    const location = new URL(proxy(req('/app')).headers.get('location') ?? '')
    expect(location.pathname).toBe('/app/signin')
    expect(location.searchParams.has('next')).toBe(false)
  })

  it('C-AC-15 lets a request with the session cookie through', () => {
    vi.stubEnv('NEXT_PUBLIC_ACTRON_DEV_FIXTURES', '0')
    const res = proxy(req('/app/inbox', 'actron_session=abc'))
    expect(res.headers.get('location')).toBeNull()
  })

  it('C-AC-15 never redirects the sign-in page itself', () => {
    vi.stubEnv('NEXT_PUBLIC_ACTRON_DEV_FIXTURES', '0')
    expect(proxy(req('/app/signin')).headers.get('location')).toBeNull()
  })

  it('dev fixtures have no backend session, so the check is off', () => {
    vi.stubEnv('NEXT_PUBLIC_ACTRON_DEV_FIXTURES', '1')
    expect(proxy(req('/app/inbox')).headers.get('location')).toBeNull()
  })

  it('matches only /app routes', () => {
    expect(config.matcher).toEqual(['/app', '/app/:path*'])
  })
})
