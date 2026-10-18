'use client'
import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import { useRef, useState } from 'react'
import { SignOut } from '@phosphor-icons/react/dist/ssr'
import { Glyph } from '../glyphs/Glyph'
import type { GlyphName } from '../glyphs/names'
import { ActronMark } from '../brand/ActronLogo'
import { useMe, useNotifications, useRequests } from '@/lib/hooks/queries'
import { waitingOnYouCount } from '../home/ask'
import { endpoints } from '@/lib/api/endpoints'
import { initials } from '@/lib/format'
import { cx } from '../ui/cx'

export const NAV: { href: string; label: string; glyph: GlyphName; shortcut?: string; match: (p: string) => boolean }[] = [
  { href: '/app', label: 'Requests', glyph: 'Home', shortcut: 'G H', match: (p) => p === '/app' || p.startsWith('/app/requests') },
  { href: '/app/inbox', label: 'Inbox', glyph: 'Inbox', shortcut: 'G I', match: (p) => p.startsWith('/app/inbox') },
  { href: '/app/graph', label: 'Graph', glyph: 'Graph', shortcut: 'G G', match: (p) => p.startsWith('/app/graph') },
  { href: '/app/system', label: 'System', glyph: 'System', shortcut: 'G S', match: (p) => p.startsWith('/app/system') },
  { href: '/app/connect', label: 'Connect', glyph: 'Connect', shortcut: 'G C', match: (p) => p.startsWith('/app/connect') },
  { href: '/app/settings', label: 'Settings', glyph: 'Settings', match: (p) => p.startsWith('/app/settings') },
]

function RailLink({ item, active, badge }: { item: (typeof NAV)[number]; active: boolean; badge?: number }) {
  return (
    <Link
      href={item.href}
      aria-current={active ? 'page' : undefined}
      className={cx(
        'group relative flex w-15 flex-col items-center justify-center gap-1 rounded-md py-1.5 transition-colors duration-1',
        active ? 'bg-ink-3 text-fg-1' : 'text-fg-3 hover:bg-ink-2 hover:text-fg-1',
      )}
    >
      {active ? <span aria-hidden className="absolute -left-0.5 top-1/2 h-5 w-0.5 -translate-y-1/2 rounded-full bg-fg-1" /> : null}
      <Glyph name={item.glyph} size={20} />
      {/* The visible label is the accessible name, so speech input users can say what they see. */}
      <span className="text-eyebrow leading-none tracking-normal">{item.label}</span>
      {badge ? <span className="sr-only">, {badge} {badge === 1 ? 'request waits' : 'requests wait'} on you</span> : null}
      {badge ? (
        <span aria-hidden className="absolute right-1 top-0.5 inline-flex min-w-4 items-center justify-center rounded-sm bg-accent px-0.5 font-mono text-eyebrow leading-4 text-accent-ink tabular">
          {badge > 9 ? '9+' : badge}
        </span>
      ) : null}
      {item.shortcut ? (
        <span
          aria-hidden
          className="pointer-events-none absolute left-full z-50 ml-2 hidden items-center gap-2 whitespace-nowrap rounded-sm border border-line-2 bg-ink-2 px-2 py-1 text-caption text-fg-1 shadow-overlay group-hover:flex group-focus-visible:flex"
        >
          {item.label}
          <kbd className="font-mono text-eyebrow text-fg-3">{item.shortcut}</kbd>
        </span>
      ) : null}
    </Link>
  )
}

/** Slim 64-px rail: workspace at the top, the six screens, the user menu at the bottom (PROMPT 8.7). */
export function Rail() {
  const pathname = usePathname() ?? '/app'
  const router = useRouter()
  const me = useMe()
  const notifications = useNotifications()
  const [menu, setMenu] = useState(false)
  const menuButton = useRef<HTMLButtonElement>(null)
  // The badge counts requests waiting on you, the same number Home and Inbox show in their headlines.
  const needs = useRequests('needs_you')
  const waiting =
    notifications.isSuccess && needs.isSuccess ? waitingOnYouCount(notifications.data.notifications, needs.data.requests) : 0
  const workspace = me.data?.workspace.name ?? 'Workspace'

  return (
    <nav aria-label="Main" className="sticky top-0 flex h-dvh w-rail shrink-0 flex-col items-center gap-2 border-r border-line-1 bg-ink-0 py-4">
      <Link
        href="/app"
        className="group relative mb-3 flex h-10 w-10 items-center justify-center rounded-md text-fg-1 hover:bg-ink-2"
        aria-label={`Actron, workspace ${workspace}`}
      >
        <ActronMark size={24} />
        <span className="pointer-events-none absolute left-full z-50 ml-3 hidden whitespace-nowrap rounded-sm border border-line-2 bg-ink-2 px-2 py-1 text-caption text-fg-1 shadow-overlay group-hover:block group-focus-visible:block">
          {workspace}
        </span>
      </Link>
      <ul className="flex flex-col items-center gap-1">
        {NAV.map((item) => (
          <li key={item.href}>
            <RailLink item={item} active={item.match(pathname)} badge={item.href === '/app/inbox' ? waiting : undefined} />
          </li>
        ))}
      </ul>
      <span className="flex-1" />
      {/* Escape is handled here, not on the menu: right after opening, focus is still on the trigger. */}
      <div
        className="relative"
        onKeyDown={(e) => {
          if (e.key === 'Escape' && menu) {
            setMenu(false)
            menuButton.current?.focus()
          }
        }}
      >
        <button
          ref={menuButton}
          type="button"
          onClick={() => setMenu((m) => !m)}
          aria-expanded={menu}
          aria-haspopup="menu"
          className="press flex size-9 items-center justify-center rounded-full border border-line-2 bg-ink-2 font-mono text-eyebrow text-fg-1 hover:border-fg-3"
        >
          <span aria-hidden>{initials(me.data?.user.name ?? 'You')}</span>
          <span className="sr-only">Account: {me.data?.user.name ?? 'you'}</span>
        </button>
        {menu ? (
          <div
            role="menu"
            aria-label="Account"
            className="absolute bottom-0 left-full z-50 ml-3 flex w-56 flex-col rounded-md border border-line-2 bg-ink-2 p-1 shadow-overlay"
          >
            <div className="px-3 py-2">
              <p className="text-small text-fg-1">{me.data?.user.name ?? 'Signed in'}</p>
              <p className="text-caption text-fg-3">
                {workspace} · {me.data?.workspace.role ?? 'member'}
              </p>
            </div>
            <Link role="menuitem" href="/app/settings" className="rounded-sm px-3 py-2 text-small text-fg-2 hover:bg-ink-3 hover:text-fg-1" onClick={() => setMenu(false)}>
              Settings
            </Link>
            <button
              role="menuitem"
              type="button"
              className="flex items-center gap-2 rounded-sm px-3 py-2 text-left text-small text-fg-2 hover:bg-ink-3 hover:text-fg-1"
              onClick={() => {
                void endpoints
                  .logout()
                  .catch(() => undefined)
                  .finally(() => {
                    router.replace('/app/signin')
                    router.refresh()
                  })
              }}
            >
              <SignOut size={14} aria-hidden />
              Sign out
            </button>
          </div>
        ) : null}
      </div>
    </nav>
  )
}
