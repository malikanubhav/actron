import type { Metadata } from 'next'
import { notFound } from 'next/navigation'
import { Glyph } from '@/components/glyphs/Glyph'
import { GLYPH_NAMES, GLYPH_MOTION } from '@/components/glyphs/names'
import { BrandMark, BRAND_NAMES } from '@/components/brand/BrandMark'
import { PageFrame } from '@/components/shell/PageFrame'
import { ScreenHeader } from '@/components/core/ScreenHeader'
import { DEV_FIXTURES } from '@/lib/env'
import { sentenceCase } from '@/lib/states'

export const metadata: Metadata = { title: 'Glyphs', description: 'Every Actron glyph in its static and animated state, for visual tests.' }

/** Hidden page for visual tests (C-AC-4); exists only in dev and fixture builds. */
export default function GlyphsPage() {
  if (!DEV_FIXTURES && process.env.ACTRON_ENV === 'prod') notFound()
  return (
    <PageFrame>
      <ScreenHeader eyebrow="Dev · Glyphs" headline={`${GLYPH_NAMES.length} glyphs, static and animated.`} purpose="24-pixel grid, 1.5 stroke, round caps. Used by the visual snapshot tests." />
      <ul className="grid grid-cols-6 gap-px overflow-hidden rounded-lg border border-line-1 bg-line-1" data-testid="glyph-grid">
        {GLYPH_NAMES.map((name) => (
          <li key={name} className="flex flex-col items-center gap-3 bg-ink-0 px-3 py-5" data-glyph-cell={name}>
            <div className="flex items-center gap-4 text-fg-1">
              <Glyph name={name} size={24} title={`${name} static`} />
              <span className="text-accent">
                <Glyph name={name} size={24} animated title={`${name} animated`} />
              </span>
            </div>
            <span className="font-mono text-eyebrow text-fg-2">{name}</span>
            <span className="text-caption text-fg-3">{sentenceCase(GLYPH_MOTION[name])}</span>
          </li>
        ))}
      </ul>
      <section className="flex flex-col gap-3">
        <h2 className="eyebrow">Brand marks</h2>
        <ul className="flex flex-wrap gap-6" data-testid="brand-grid">
          {BRAND_NAMES.map((b) => (
            <li key={b} className="flex flex-col items-center gap-2 text-fg-1">
              <BrandMark name={b} size={28} />
              <span className="font-mono text-eyebrow text-fg-3">{b}</span>
            </li>
          ))}
        </ul>
      </section>
    </PageFrame>
  )
}
