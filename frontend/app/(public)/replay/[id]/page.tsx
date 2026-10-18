import type { Metadata } from 'next'
import Link from 'next/link'
import { Providers } from '@/components/shell/Providers'
import { ReplayScreen } from '@/components/replay/ReplayScreen'
import { ActronWordmark } from '@/components/brand/ActronLogo'
import { serverApiOrNull } from '@/lib/api/server'
import type { RequestDetail } from '@/lib/api/types'

type Props = { params: Promise<{ id: string }> }

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { id } = await params
  const data = await serverApiOrNull<{ request: RequestDetail }>(`/api/public/replays/${encodeURIComponent(id)}`, {
    withCookies: false,
    timeoutMs: 2000,
  })
  const title = data ? `Replay: ${data.request.title}` : 'Replay'
  return {
    title,
    description: 'Watch how Actron handled a request, step by step: graph queries, evidence, the ticket, the build and the pull request.',
    openGraph: { title, type: 'article' },
  }
}

/** Public replay (spec C, C5.3; C-AC-25). The API returns 404 unless the workspace allows public replays. */
export default async function PublicReplayPage({ params }: Props) {
  const { id } = await params
  return (
    <Providers>
      <div className="min-h-dvh bg-ink-0">
        <header className="flex items-center justify-between border-b border-line-1 px-4 py-3 sm:px-page">
          <Link href="/" aria-label="Actron home">
            <ActronWordmark size={22} />
          </Link>
          <Link href="/app" className="text-small text-fg-2 hover:text-fg-1">
            Open the app
          </Link>
        </header>
        <main id="main">
          <ReplayScreen id={id} isPublic />
        </main>
      </div>
    </Providers>
  )
}
