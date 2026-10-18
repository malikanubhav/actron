'use client'
import { useEffect, useRef, type ReactNode } from 'react'
import { usePathname, useRouter } from 'next/navigation'
import { Rail } from './Rail'
import { FooterStatusBar } from './FooterStatusBar'
import { CommandPalette } from './CommandPalette'
import { ShortcutSheet } from './ShortcutSheet'
import { ToastViewport } from './ToastViewport'
import { SmallScreenNotice } from './SmallScreenNotice'
import { useWorkspaceStream } from '@/lib/hooks/useWorkspaceStream'
import { ShortcutMatcher, hrefFor } from '@/lib/shortcuts'
import { useUi } from '@/lib/store'
import { useMe } from '@/lib/hooks/queries'

export function requestIdFromPath(pathname: string): string | null {
  const match = /^\/app\/requests\/([^/]+)/.exec(pathname)
  return match ? decodeURIComponent(match[1] as string) : null
}

/** Signed-in shell (PROMPT 8.7): rail, content, footer status bar, palette, shortcuts, toasts, workspace stream. */
export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname() ?? '/app'
  const router = useRouter()
  const currentRequestId = requestIdFromPath(pathname)
  const matcher = useRef(new ShortcutMatcher())
  const setPalette = useUi((s) => s.setPaletteOpen)
  const setShortcuts = useUi((s) => s.setShortcutsOpen)
  const requestApprove = useUi((s) => s.requestApprove)
  const requestCompose = useUi((s) => s.requestCompose)
  useMe()
  useWorkspaceStream({ currentRequestId })

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (document.querySelector('dialog[open]') && !((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k')) return
      const action = matcher.current.feed(e)
      if (!action) return
      e.preventDefault()
      const href = hrefFor(action)
      if (href) {
        router.push(href)
        return
      }
      switch (action) {
        case 'palette':
          setPalette(!useUi.getState().paletteOpen)
          break
        case 'shortcuts':
          setShortcuts(true)
          break
        case 'new-request':
          if (pathname !== '/app') router.push('/app')
          requestCompose()
          break
        case 'approve':
          if (currentRequestId) requestApprove()
          break
        default:
          break
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [router, pathname, currentRequestId, setPalette, setShortcuts, requestApprove, requestCompose])

  return (
    <div className="flex min-h-dvh bg-ink-0">
      <a
        href="#main"
        className="sr-only-focusable fixed left-3 top-3 z-[80] rounded-md bg-accent px-3 py-2 text-small font-medium text-accent-ink"
      >
        Skip to main content
      </a>
      <Rail />
      <div className="flex min-w-0 flex-1 flex-col">
        <main id="main" tabIndex={-1} className="min-w-0 flex-1 outline-none">
          {children}
        </main>
        <FooterStatusBar />
      </div>
      <CommandPalette canApprove={Boolean(currentRequestId)} />
      <ShortcutSheet />
      <ToastViewport />
      <SmallScreenNotice />
    </div>
  )
}
