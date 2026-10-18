import { NextResponse, type NextRequest } from 'next/server'

/**
 * Unauthenticated /app/* → /app/signin (spec C, C3). Only checks that the session cookie exists; the workspace
 * layout validates it with GET /api/me on the server. Dev fixtures have no backend session, so the check is off.
 */
export function proxy(request: NextRequest) {
  if (process.env.NEXT_PUBLIC_ACTRON_DEV_FIXTURES === '1') return NextResponse.next()
  const { pathname, search } = request.nextUrl
  if (pathname === '/app/signin' || pathname.startsWith('/app/signin/')) return NextResponse.next()
  if (request.cookies.has('actron_session')) return NextResponse.next()
  const url = request.nextUrl.clone()
  url.pathname = '/app/signin'
  url.search = ''
  if (pathname !== '/app') url.searchParams.set('next', `${pathname}${search}`)
  return NextResponse.redirect(url)
}

export const config = {
  matcher: ['/app', '/app/:path*'],
}
