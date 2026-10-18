'use client'
import dynamic from 'next/dynamic'
import Image from 'next/image'
import { useCallback, useEffect, useState } from 'react'
import { heroMode, readEnvironment, type HeroMode } from './mode'
import { HERO_STAGE_TEXT, type HeroStage } from './timeline'
import { BrandMark } from '../brand/BrandMark'
import { cx } from '../ui/cx'

// The 3D scene (three.js, R3F, drei) is its own chunk, fetched only after first paint and only when it will run.
const HeroScene = dynamic(() => import('./HeroScene'), { ssr: false, loading: () => null })

type Phase = 'waiting' | HeroMode

function whenIdle(callback: () => void): () => void {
  if (typeof window.requestIdleCallback === 'function') {
    const id = window.requestIdleCallback(callback, { timeout: 1500 })
    return () => window.cancelIdleCallback(id)
  }
  const id = window.setTimeout(callback, 600)
  return () => window.clearTimeout(id)
}

/**
 * The landing hero visual (spec C, C6). Nothing renders until the browser is idle after first paint, so the
 * headline stays the largest contentful paint. Then: the live 3D memory graph, or the static image of the same
 * scene under reduced motion, save-data, four or fewer cores, or no WebGL.
 */
export function HeroVisual({ className }: { className?: string }) {
  const [phase, setPhase] = useState<Phase>('waiting')
  const [stage, setStage] = useState<HeroStage>('request')
  useEffect(() => whenIdle(() => setPhase(heroMode(readEnvironment()))), [])
  // Stable: the scene reloads its graph whenever this changes, and the stage state re-renders this component often.
  const toFallback = useCallback(() => setPhase('fallback'), [])
  return (
    // Below 768 px the static image arrives after idle and would become the largest paint if it were wider than
    // the headline (mobile LCP 6.5 s measured on 18 Oct 2026); there it stays smaller than the headline block.
    <div
      className={cx('relative aspect-square w-full max-md:mx-auto max-md:max-w-48', className)}
      data-testid="hero-visual"
      data-hero-mode={phase}
      aria-hidden="true"
    >
      {phase === 'fallback' ? (
        <Image
          src="/landing/hero-fallback.png"
          alt=""
          fill
          sizes="(min-width: 1024px) 40vw, 90vw"
          className="fade-in object-contain"
          data-testid="hero-fallback"
        />
      ) : null}
      {phase === '3d' ? <HeroScene onUnavailable={toFallback} onStage={setStage} /> : null}
      {phase === '3d' || phase === 'fallback' ? (
        // What the graph is doing right now. The static image shows the finished state; the live scene walks the stages.
        <div className="pointer-events-none absolute inset-x-0 bottom-0 flex justify-center max-md:hidden" data-testid="hero-status">
          <span className="inline-flex min-w-72 items-center justify-center gap-2 rounded-sm border border-line-2 bg-ink-1/90 px-3 py-1.5 text-caption text-fg-2">
            <BrandMark name="falkordb" size={14} decorative />
            <span key={phase === '3d' ? stage : 'static'} className="fade-in">
              {phase === '3d' ? HERO_STAGE_TEXT[stage] : HERO_STAGE_TEXT.found}
            </span>
          </span>
        </div>
      ) : null}
    </div>
  )
}
