'use client'
import { useRouter } from 'next/navigation'
import { useDeferredValue, useEffect, useId, useMemo, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { MagnifyingGlass } from '@phosphor-icons/react/dist/ssr'
import { useUi } from '@/lib/store'
import type { RequestSummary } from '@/lib/api/types'
import { useSyncNow } from '@/lib/hooks/mutations'
import { endpoints } from '@/lib/api/endpoints'
import { qk } from '@/lib/query-keys'
import {
  ACTION_COMMANDS,
  APPROVE_COMMAND,
  SCREEN_COMMANDS,
  nodeCommand,
  pushRecent,
  rankCommands,
  readRecent,
  requestCommand,
  type Command,
} from '@/lib/palette'
import { Glyph } from '../glyphs/Glyph'
import type { GlyphName } from '../glyphs/names'
import { cx } from '../ui/cx'

const KIND_GLYPH: Record<Command['kind'], GlyphName> = { screen: 'Home', request: 'Request', node: 'Graph', action: 'ToolCall' }
const KIND_LABEL: Record<Command['kind'], string> = { screen: 'Screen', request: 'Request', node: 'Node', action: 'Action' }

/** Cmd/Ctrl+K: jump to any request, node or screen; run actions. Keyboard only, no animation (high frequency). */
export function CommandPalette({ canApprove = false }: { canApprove?: boolean }) {
  const open = useUi((s) => s.paletteOpen)
  const setOpen = useUi((s) => s.setPaletteOpen)
  const requestApprove = useUi((s) => s.requestApprove)
  const requestCompose = useUi((s) => s.requestCompose)
  const setShortcuts = useUi((s) => s.setShortcutsOpen)
  const router = useRouter()
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const [recent, setRecent] = useState<string[]>([])
  const deferred = useDeferredValue(query)
  const inputRef = useRef<HTMLInputElement>(null)
  const dialogRef = useRef<HTMLDialogElement>(null)
  const listId = useId()
  // The palette lives in the shell on every page. It reads requests only when it opens, so it never creates cache
  // entries ahead of a page's server-prefetched data (which would defer that page's hydration).
  const client = useQueryClient()
  const [requestList, setRequestList] = useState<RequestSummary[]>([])
  const sync = useSyncNow()
  const nodes = useQuery({
    queryKey: qk.graphSearch(deferred),
    queryFn: () => endpoints.search(deferred, undefined, 8),
    enabled: open && deferred.trim().length >= 2,
    staleTime: 30_000,
  })

  useEffect(() => {
    const d = dialogRef.current
    if (!d) return
    if (open && !d.open) {
      setQuery('')
      setActive(0)
      setRecent(readRecent())
      void client
        .fetchQuery({ queryKey: qk.requests({ group: undefined, limit: 50 }), queryFn: () => endpoints.requests(undefined, 50), staleTime: 15_000 })
        .then((r) => setRequestList(r.requests))
        .catch(() => setRequestList([]))
      d.showModal()
      requestAnimationFrame(() => inputRef.current?.focus())
    } else if (!open && d.open) d.close()
  }, [open, client])

  const commands = useMemo(() => {
    const all: Command[] = [
      ...ACTION_COMMANDS,
      ...(canApprove ? [APPROVE_COMMAND] : []),
      ...SCREEN_COMMANDS,
      ...requestList.map(requestCommand),
      ...(nodes.data?.results ?? []).map(nodeCommand),
    ]
    return rankCommands(deferred, all, recent).slice(0, 12)
  }, [deferred, requestList, nodes.data, recent, canApprove])

  const run = (cmd: Command) => {
    setRecent(pushRecent(cmd.id))
    setOpen(false)
    if (cmd.href) {
      router.push(cmd.href)
      return
    }
    switch (cmd.action) {
      case 'new-request':
        router.push('/app')
        requestCompose()
        break
      case 'sync-now':
        void client
          .fetchQuery({ queryKey: qk.connections(), queryFn: endpoints.connections, staleTime: 15_000 })
          .then((r) => {
            for (const c of r.connections) if (c.status === 'connected') void sync.run({ connectionId: c.id })
          })
          .catch(() => undefined)
        break
      case 'approve-current':
        requestApprove()
        break
      case 'shortcuts':
        setShortcuts(true)
        break
      default:
        break
    }
  }

  return (
    <dialog
      ref={dialogRef}
      aria-label="Command palette"
      onCancel={(e) => {
        e.preventDefault()
        setOpen(false)
      }}
      onClick={(e) => {
        if (e.target === dialogRef.current) setOpen(false)
      }}
      className="mx-auto mt-[12vh] w-full max-w-2xl overscroll-contain rounded-lg border border-line-2 bg-ink-2 p-0 text-fg-1 shadow-overlay backdrop:bg-ink-0/70"
    >
      {open ? (
        <div className="flex flex-col">
          <div className="flex items-center gap-3 border-b border-line-1 px-4">
            <MagnifyingGlass size={16} aria-hidden className="text-fg-3" />
            <input
              ref={inputRef}
              role="combobox"
              aria-expanded="true"
              aria-controls={listId}
              aria-activedescendant={commands[active] ? `${listId}-${active}` : undefined}
              aria-autocomplete="list"
              aria-label="Search requests, nodes, screens and actions"
              placeholder="Search requests, nodes, screens and actions"
              value={query}
              onChange={(e) => {
                setQuery(e.target.value)
                setActive(0)
              }}
              onKeyDown={(e) => {
                if (e.key === 'ArrowDown') {
                  e.preventDefault()
                  setActive((a) => Math.min(commands.length - 1, a + 1))
                } else if (e.key === 'ArrowUp') {
                  e.preventDefault()
                  setActive((a) => Math.max(0, a - 1))
                } else if (e.key === 'Enter') {
                  e.preventDefault()
                  const cmd = commands[active]
                  if (cmd) run(cmd)
                }
              }}
              className="h-12 flex-1 bg-transparent text-body text-fg-1 outline-none placeholder:text-fg-3"
            />
            <kbd className="font-mono text-eyebrow text-fg-3">ESC</kbd>
          </div>
          <ul id={listId} role="listbox" aria-label="Results" className="max-h-96 overflow-y-auto overscroll-contain p-2">
            {commands.length === 0 ? (
              <li className="px-3 py-6 text-small text-fg-3" role="presentation">
                Nothing matches “{query}”. Try a request title, a function name or a screen.
              </li>
            ) : (
              commands.map((cmd, i) => (
                <li
                  key={cmd.id}
                  id={`${listId}-${i}`}
                  role="option"
                  aria-selected={i === active}
                  onMouseEnter={() => setActive(i)}
                  onClick={() => run(cmd)}
                  className={cx('flex cursor-pointer items-center gap-3 rounded-md px-3 py-2', i === active ? 'bg-ink-3' : '')}
                >
                  <span className={i === active ? 'text-fg-1' : 'text-fg-3'}>
                    <Glyph name={KIND_GLYPH[cmd.kind]} size={16} />
                  </span>
                  <span className="flex min-w-0 flex-1 flex-col">
                    <span className="truncate text-small text-fg-1">{cmd.title}</span>
                    {cmd.subtitle ? <span className="truncate text-caption text-fg-3">{cmd.subtitle}</span> : null}
                  </span>
                  {cmd.shortcut ? (
                    <kbd className="font-mono text-eyebrow text-fg-3">{cmd.shortcut}</kbd>
                  ) : (
                    <span className="text-caption text-fg-3">{KIND_LABEL[cmd.kind]}</span>
                  )}
                </li>
              ))
            )}
          </ul>
          <p className="border-t border-line-1 px-4 py-2 text-caption text-fg-3">
            ↑ ↓ to move · Enter to open · Esc to close
          </p>
        </div>
      ) : null}
    </dialog>
  )
}
