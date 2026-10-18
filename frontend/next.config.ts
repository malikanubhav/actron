import type { NextConfig } from 'next'
import createMDX from '@next/mdx'

// The browser always calls same-origin /api, /slack and /webhooks. Next.js proxies them to the
// backend, so session and CSRF cookies stay first-party (spec C, C4).
const apiInternalUrl = (process.env.API_INTERNAL_URL ?? 'http://127.0.0.1:8080').replace(/\/$/, '')

const securityHeaders = [
  { key: 'X-Content-Type-Options', value: 'nosniff' },
  { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
  { key: 'X-Frame-Options', value: 'DENY' },
  { key: 'Permissions-Policy', value: 'camera=(), microphone=(), geolocation=()' },
]

const nextConfig: NextConfig = {
  output: 'standalone',
  // The fixture build used by Playwright lives in its own folder so it never replaces the production build.
  distDir: process.env.NEXT_DIST_DIR ?? '.next',
  reactStrictMode: true,
  poweredByHeader: false,
  // Gzip in Next's proxy buffers server-sent events until the stream ends; Caddy compresses in front instead.
  compress: false,
  pageExtensions: ['ts', 'tsx', 'mdx'],
  typedRoutes: false,
  experimental: {
    optimizePackageImports: ['@phosphor-icons/react'],
  },
  async rewrites() {
    return {
      beforeFiles: [],
      afterFiles: [
        { source: '/api/:path*', destination: `${apiInternalUrl}/api/:path*` },
        { source: '/slack/:path*', destination: `${apiInternalUrl}/slack/:path*` },
        { source: '/webhooks/:path*', destination: `${apiInternalUrl}/webhooks/:path*` },
      ],
      fallback: [],
    }
  },
  async headers() {
    return [
      { source: '/:path*', headers: securityHeaders },
      {
        source: '/brands/:path*',
        headers: [{ key: 'Cache-Control', value: 'public, max-age=31536000, immutable' }],
      },
      {
        source: '/actron-brand/:path*',
        headers: [{ key: 'Cache-Control', value: 'public, max-age=31536000, immutable' }],
      },
    ]
  },
}

const withMDX = createMDX({})

export default withMDX(nextConfig)
