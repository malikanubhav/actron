'use client'
import { useRouter } from 'next/navigation'
import { useEffect, useId, useRef, useState } from 'react'
import type { Kind } from '@/lib/api/types'
import { detectKind, KIND_LABEL } from '@/lib/kind'
import { useCreateRequest } from '@/lib/hooks/mutations'
import { useUi } from '@/lib/store'
import { KINDS } from '@/lib/api/types'
import { formatNumber } from '@/lib/format'
import { sentenceCase } from '@/lib/states'
import { Button } from '../ui/Button'
import { cx } from '../ui/cx'

export const MIN_LENGTH = 3
export const MAX_LENGTH = 4000

/** Multi-line request box; kind auto-detected as a chip the user can change; Cmd/Ctrl+Enter submits (PROMPT 8.8 C). */
export function RequestComposer({ disabledReason }: { disabledReason?: string | null }) {
  const id = useId()
  const router = useRouter()
  const ref = useRef<HTMLTextAreaElement>(null)
  const [text, setText] = useState('')
  const [chosen, setChosen] = useState<Kind | null>(null)
  const create = useCreateRequest()
  const composeSignal = useUi((s) => s.composeSignal)
  const kind = chosen ?? detectKind(text)
  const showKind = Boolean(chosen) || text.trim().length > 0
  const trimmed = text.trim()
  const tooLong = trimmed.length > MAX_LENGTH
  const valid = trimmed.length >= MIN_LENGTH && !tooLong && !disabledReason
  const firstSignal = useRef(composeSignal)

  useEffect(() => {
    if (composeSignal !== firstSignal.current) ref.current?.focus()
  }, [composeSignal])

  const submit = async () => {
    if (!valid || create.isPending) return
    try {
      const { request } = await create.run({ text: trimmed, kindHint: kind })
      setText('')
      setChosen(null)
      router.push(`/app/requests/${request.id}`)
    } catch {
      // The mutation shows the reason in a toast; the text stays so nothing is lost.
    }
  }

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        void submit()
      }}
      className="flex flex-col gap-3 rounded-lg border border-line-2 bg-ink-1 p-4 focus-within:border-fg-3"
      data-testid="request-composer"
    >
      <label htmlFor={id} className="eyebrow">
        New request
      </label>
      <textarea
        ref={ref}
        id={id}
        rows={3}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
            e.preventDefault()
            void submit()
          }
        }}
        placeholder="Describe the change or ask a question, for example: Show evaluation results inline for the top-level form."
        aria-describedby={`${id}-help`}
        aria-invalid={tooLong || undefined}
        className="w-full resize-y bg-transparent text-lead text-fg-1 outline-none placeholder:text-fg-3"
      />
      <div className="flex flex-wrap items-center gap-3">
        <span id={`${id}-kind`} className="text-caption font-medium text-fg-3">
          Kind
        </span>
        <div className="inline-flex items-center rounded-md border border-line-2 p-0.5">
          {/* Auto lets Actron pick: the picked kind is checked with a dashed outline; a kind you choose is filled. */}
          <button
            type="button"
            aria-pressed={!chosen}
            onClick={() => setChosen(null)}
            className={cx(
              'h-6 rounded-sm px-3 text-caption font-medium transition-colors duration-1',
              !chosen ? 'bg-ink-3 text-fg-1' : 'text-fg-3 hover:text-fg-1',
            )}
          >
            Auto
          </button>
          <span aria-hidden className="mx-0.5 h-4 w-px bg-line-2" />
          <div role="radiogroup" aria-labelledby={`${id}-kind`} className="inline-flex items-center">
            {KINDS.map((k) => {
              const checked = showKind && kind === k
              return (
                <button
                  key={k}
                  type="button"
                  role="radio"
                  aria-checked={checked}
                  onClick={() => setChosen(k)}
                  className={cx(
                    'h-6 rounded-sm border px-3 text-caption font-medium transition-colors duration-1',
                    checked && chosen ? 'border-transparent bg-ink-3 text-fg-1' : checked ? 'border-dashed border-fg-3 text-fg-1' : 'border-transparent text-fg-3 hover:text-fg-1',
                  )}
                >
                  {sentenceCase(KIND_LABEL[k])}
                </button>
              )
            })}
          </div>
        </div>
        <p id={`${id}-help`} className="flex-1 text-caption text-fg-3">
          {disabledReason
            ? disabledReason
            : tooLong
              ? `Keep it under ${formatNumber(MAX_LENGTH)} characters.`
              : chosen
                ? 'Kind set by you.'
                : text.trim()
                  ? 'Kind detected from your words. Change it if it is wrong.'
                  : 'Auto: Actron picks the kind from your words. Choose one to override it.'}
        </p>
        <Button
          type="submit"
          variant="primary"
          disabled={!valid}
          loading={create.isPending}
          loadingText="Starting"
          shortcut="⌘↵"
          title={valid ? undefined : (disabledReason ?? (tooLong ? `Keep it under ${formatNumber(MAX_LENGTH)} characters.` : 'Type a request first.'))}        >
          Ask Actron
        </Button>
      </div>
    </form>
  )
}
