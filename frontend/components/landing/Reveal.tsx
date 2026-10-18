'use client'
import { useEffect, useRef, type ReactNode } from 'react'

/**
 * One orchestrated reveal for the journey (spec C, C1.4 "landing scroll reveals"). Items are always visible: an
 * item below the fold plays a short entrance only when it scrolls into view. Nothing is hidden while waiting for
 * the observer, so print, full-page captures and pages without JavaScript show everything. Reduced motion skips it.
 */
export function Reveal({ children, className, stagger = 120 }: { children: ReactNode; className?: string; stagger?: number }) {
  const ref = useRef<HTMLOListElement>(null)
  useEffect(() => {
    const list = ref.current
    if (!list || typeof IntersectionObserver === 'undefined') return
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return
    const items = Array.from(list.querySelectorAll<HTMLElement>(':scope > li'))
    const below = items.filter((el) => el.getBoundingClientRect().top > window.innerHeight)
    if (below.length === 0 || typeof below[0]!.animate !== 'function') return
    let order = 0
    const observer = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue
        const el = entry.target as HTMLElement
        observer.unobserve(el)
        el.animate(
          [
            { opacity: 0, transform: 'translateY(24px)' },
            { opacity: 1, transform: 'none' },
          ],
          { duration: 480, delay: order++ * stagger, easing: 'cubic-bezier(0.2, 0, 0, 1)', fill: 'backwards' },
        )
        setTimeout(() => (order = Math.max(0, order - 1)), stagger)
      }
    })
    below.forEach((el) => observer.observe(el))
    return () => observer.disconnect()
  }, [stagger])
  return (
    <ol ref={ref} className={className}>
      {children}
    </ol>
  )
}
