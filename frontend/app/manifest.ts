import type { MetadataRoute } from 'next'

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: 'Actron',
    short_name: 'Actron',
    description: 'Checks what your team already decided before an AI writes code, and shows the graph path behind every step.',
    start_url: '/app',
    display: 'standalone',
    background_color: '#0a0a0a',
    theme_color: '#0a0a0a',
    icons: [
      { src: '/actron-brand/icon-192.png', sizes: '192x192', type: 'image/png' },
      { src: '/actron-brand/icon-512.png', sizes: '512x512', type: 'image/png' },
      { src: '/actron-brand/favicon.svg', sizes: 'any', type: 'image/svg+xml' },
    ],
  }
}
