'use client'
import { LIST_SHORTCUTS, SHORTCUTS } from '@/lib/shortcuts'
import { useUi } from '@/lib/store'
import { Dialog } from '../ui/Dialog'

function Keys({ keys }: { keys: string }) {
  const parts = keys.split(' ').map((k) => (k === 'mod+k' ? 'Ctrl/Cmd K' : k.toUpperCase()))
  return (
    <span className="flex items-center gap-1">
      {parts.map((p, i) => (
        <kbd key={i} className="inline-flex h-6 min-w-6 items-center justify-center rounded-sm border border-line-2 px-1.5 font-mono text-eyebrow text-fg-1">
          {p}
        </kbd>
      ))}
    </span>
  )
}

/** `?` shows every shortcut. */
export function ShortcutSheet() {
  const open = useUi((s) => s.shortcutsOpen)
  const setOpen = useUi((s) => s.setShortcutsOpen)
  return (
    <Dialog open={open} onClose={() => setOpen(false)} label="Keyboard" title="Shortcuts">
      <dl className="flex flex-col">
        {[...SHORTCUTS, ...LIST_SHORTCUTS.map((l) => ({ ...l, action: l.keys }))].map((s) => (
          <div key={s.keys} className="flex items-center justify-between gap-4 border-b border-line-1 py-2 last:border-b-0">
            <dt className="text-small text-fg-2">{s.label}</dt>
            <dd>
              <Keys keys={s.keys} />
            </dd>
          </div>
        ))}
      </dl>
    </Dialog>
  )
}
