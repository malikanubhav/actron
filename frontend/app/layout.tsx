import type { Metadata, Viewport } from 'next'
import { JetBrains_Mono, Newsreader, Public_Sans } from 'next/font/google'
import { SITE_URL } from '@/lib/env'
import { DevFixturesBadge } from '@/components/shell/DevFixturesBadge'
import './globals.css'
import '@/components/glyphs/glyphs.css'

// Display: Newsreader (variable, optical sizes) for headlines and evidence quotes.
const newsreader = Newsreader({
  subsets: ['latin'],
  display: 'swap',
  variable: '--font-newsreader',
  axes: ['opsz'],
  style: ['normal'],
  adjustFontFallback: true,
})

// UI: Public Sans (variable) for body text and controls.
const publicSans = Public_Sans({
  subsets: ['latin'],
  display: 'swap',
  variable: '--font-public-sans',
})

// Data: JetBrains Mono for labels, ids, code, timestamps and metrics.
const jetbrains = JetBrains_Mono({
  subsets: ['latin'],
  display: 'swap',
  variable: '--font-jetbrains',
  weight: ['400', '500', '600'],
})

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: 'Actron · Check what your team decided before AI writes code',
    template: '%s · Actron',
  },
  description:
    'Actron reads your code, pull requests, tickets and Slack into one FalkorDB graph, checks every request against it, and builds the change with the evidence attached.',
  applicationName: 'Actron',
  icons: {
    icon: [
      { url: '/actron-brand/favicon.svg', type: 'image/svg+xml' },
      { url: '/actron-brand/favicon-32.png', sizes: '32x32', type: 'image/png' },
    ],
    apple: '/actron-brand/apple-touch-icon.png',
  },
  manifest: '/manifest.webmanifest',
}

export const viewport: Viewport = {
  themeColor: '#0a0a0a',
  colorScheme: 'dark',
  width: 'device-width',
  initialScale: 1,
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en-GB" className={`${newsreader.variable} ${publicSans.variable} ${jetbrains.variable}`}>
      <body>
        {children}
        <DevFixturesBadge />
      </body>
    </html>
  )
}
