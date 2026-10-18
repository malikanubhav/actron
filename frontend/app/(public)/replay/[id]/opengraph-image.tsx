import { ImageResponse } from 'next/og'
import { OG_SIZE, OgCard, loadDisplayFont, replayTitle } from '@/components/landing/og'
import { serverApiOrNull } from '@/lib/api/server'
import type { RequestDetail } from '@/lib/api/types'

export const alt = 'Replay of an Actron request'
export const size = OG_SIZE
export const contentType = 'image/png'

export default async function ReplayOpengraphImage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  const [font, replay] = await Promise.all([
    loadDisplayFont(),
    serverApiOrNull<{ request: RequestDetail }>(`/api/public/replays/${encodeURIComponent(id)}`, { timeoutMs: 2500, withCookies: false }),
  ])
  return new ImageResponse(<OgCard eyebrow="" title={replayTitle(replay?.request.title)} font={font} />, {
    ...OG_SIZE,
    fonts: font ? [{ name: 'Newsreader', data: font, weight: 400, style: 'normal' }] : undefined,
  })
}
