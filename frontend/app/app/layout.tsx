import type { Metadata } from 'next'
import { Providers } from '@/components/shell/Providers'

export const metadata: Metadata = {
  robots: { index: false, follow: false },
}

/** Everything under /app shares the query client, motion settings and (in fixture mode) MSW. */
export default function AppSectionLayout({ children }: { children: React.ReactNode }) {
  return <Providers>{children}</Providers>
}
