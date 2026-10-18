import { ImageResponse } from 'next/og'
import { OG_SIZE, OgCard, loadDisplayFont } from '@/components/landing/og'
import { HERO_HEADLINE } from '@/components/landing/copy'

export const alt = HERO_HEADLINE
export const size = OG_SIZE
export const contentType = 'image/png'

export default async function OpengraphImage() {
  const font = await loadDisplayFont()
  return new ImageResponse(<OgCard eyebrow="" title={HERO_HEADLINE} font={font} />, {
    ...OG_SIZE,
    fonts: font ? [{ name: 'Newsreader', data: font, weight: 400, style: 'normal' }] : undefined,
  })
}
