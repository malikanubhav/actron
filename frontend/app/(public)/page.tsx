import type { Metadata } from 'next'
import { Landing } from '@/components/landing/Landing'
import { HERO_HEADLINE, HERO_PURPOSE } from '@/components/landing/copy'
import { loadLandingData } from '@/components/landing/data'

export const metadata: Metadata = {
  title: { absolute: 'Actron · Check what your team decided before AI writes code' },
  description: HERO_PURPOSE,
  alternates: { canonical: '/' },
  openGraph: {
    type: 'website',
    title: HERO_HEADLINE,
    description: HERO_PURPOSE,
    siteName: 'Actron',
  },
  twitter: { card: 'summary_large_image', title: HERO_HEADLINE, description: HERO_PURPOSE },
}

export default async function LandingPage() {
  const data = await loadLandingData()
  return <Landing replay={data.replay} stats={data.stats} screenshots={data.screenshots} screenshotSource={data.screenshotSource} />
}
