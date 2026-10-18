'use client'
import { Minus, Plus } from '@phosphor-icons/react/dist/ssr'
import type { ConnectorOption, FormField } from '@/lib/api/types'
import { CopyButton } from '../core/Formatting'
import { cx } from '../ui/cx'
import type { FieldValue } from './form-logic'

const inputClass = (invalid: boolean) =>
  cx(
    'h-9 w-full rounded-sm border bg-ink-1 px-3 text-small text-fg-1 placeholder:text-fg-3 focus-visible:border-accent',
    invalid ? 'border-state-conflict/70' : 'border-line-2',
  )

/** "Where do I find this?" disclosure with the field's exact steps. */
export function InfoDisclosure({ info }: { info: string }) {
  return (
    <details className="group text-caption">
      <summary className="cursor-pointer list-none text-fg-2 underline decoration-line-2 underline-offset-4 hover:text-fg-1">
        Where do I find this?
      </summary>
      <p className="mt-2 rounded-sm bg-ink-2 px-3 py-2 text-fg-2">{info}</p>
    </details>
  )
}

/** True for addresses GitHub cannot deliver webhooks to: plain HTTP, localhost and private networks. */
export function isLocalOrigin(origin: string): boolean {
  try {
    const { protocol, hostname } = new URL(origin)
    return protocol !== 'https:' || hostname === 'localhost' || /^(127\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)/.test(hostname) || hostname.endsWith('.local')
  } catch {
    return false
  }
}

export function WebhookPanel({ field, origin, secret }: { field: FormField; origin: string; secret: string }) {
  const url = `${origin}/webhooks/github`
  const events = ['Pushes', 'Pull requests', 'Pull request reviews', 'Pull request review comments', 'Issues', 'Issue comments']
  return (
    <section data-testid="webhook-panel" aria-label={field.label} className="flex flex-col gap-3 rounded-md border border-line-1 p-4">
      <div className="flex flex-col gap-1">
        <h4 className="text-small font-medium text-fg-1">{field.label}</h4>
        {field.description ? <p className="text-caption text-fg-2">{field.description}</p> : null}
        {isLocalOrigin(origin) ? (
          <p className="text-caption text-fg-2" data-testid="webhook-local-note">
            GitHub cannot reach this address, so Actron checks for changes every five minutes instead. Add the webhook once Actron has a
            public HTTPS address.
          </p>
        ) : null}
      </div>
      <dl className="grid grid-cols-3 gap-x-3 gap-y-2 text-caption">
        <dt className="eyebrow pt-1">Payload URL</dt>
        <dd className="col-span-2 flex min-w-0 items-center gap-2">
          <code className="min-w-0 truncate font-mono text-fg-1" data-testid="webhook-url">
            {url}
          </code>
          <CopyButton value={url} label="Copy URL" />
        </dd>
        <dt className="eyebrow pt-1">Content type</dt>
        <dd className="col-span-2 flex items-center gap-2">
          <code className="font-mono text-fg-1">application/json</code>
          <CopyButton value="application/json" />
        </dd>
        <dt className="eyebrow pt-1">Secret</dt>
        <dd className="col-span-2 flex min-w-0 items-center gap-2">
          <code className="min-w-0 truncate font-mono text-fg-1" data-testid="webhook-secret">
            {secret}
          </code>
          <CopyButton value={secret} label="Copy secret" />
        </dd>
        <dt className="eyebrow pt-1">Events</dt>
        <dd className="col-span-2">
          <ul className="flex flex-col gap-0.5 text-fg-1" data-testid="webhook-events">
            {events.map((e) => (
              <li key={e}>{e}</li>
            ))}
          </ul>
        </dd>
      </dl>
      <p className="text-caption text-fg-3">Actron generated this secret and stores it encrypted with the connection.</p>
    </section>
  )
}

export function ManifestPanel({ field }: { field: FormField }) {
  const manifest = field.content ?? ''
  return (
    <section data-testid="manifest-panel" aria-label={field.label} className="flex flex-col gap-2 rounded-md border border-line-1 p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex flex-col gap-1">
          <h4 className="text-small font-medium text-fg-1">{field.label}</h4>
          {field.description ? <p className="text-caption text-fg-2">{field.description}</p> : null}
        </div>
        <CopyButton value={manifest} label="Copy manifest" />
      </div>
      <pre tabIndex={0} className="max-h-40 overflow-auto overscroll-contain rounded-sm bg-ink-2 p-3 font-mono text-caption text-fg-2">{manifest}</pre>
      <a
        href="https://api.slack.com/apps?new_app=1"
        target="_blank"
        rel="noreferrer noopener"
        className="text-caption text-fg-2 underline underline-offset-4 hover:text-fg-1"
      >
        Open Slack app creation<span className="sr-only"> (opens in a new tab)</span>
      </a>
    </section>
  )
}

export interface FieldControlProps {
  field: FormField
  value: FieldValue | undefined
  onChange: (value: FieldValue) => void
  onBlur?: () => void
  error?: string | null
  options?: { value: string; label: string; note?: string; default?: boolean; protected?: boolean }[]
  optionsLoading?: boolean
  idPrefix: string
}

function optionLabel(o: ConnectorOption): string {
  const marks = [o.default ? 'default' : null, o.protected ? 'protected' : null].filter(Boolean).join(', ')
  return marks ? `${o.label} (${marks})` : o.label
}

/** One input rendered from a connector field definition (spec C, C12). */
export function FieldControl({ field, value, onChange, onBlur, error, options = [], optionsLoading = false, idPrefix }: FieldControlProps) {
  const id = `${idPrefix}-${field.field_id}`
  const descId = field.description ? `${id}-desc` : undefined
  const errId = error ? `${id}-err` : undefined
  const describedBy = [descId, errId].filter(Boolean).join(' ') || undefined
  const invalid = Boolean(error)

  let control: React.ReactNode
  switch (field.ui_component) {
    case 'password':
    case 'text':
      control = (
        <input
          id={id}
          name={field.field_id}
          type={field.is_secret || field.ui_component === 'password' ? 'password' : 'text'}
          autoComplete={field.is_secret ? 'off' : undefined}
          spellCheck={false}
          placeholder={field.placeholder}
          value={typeof value === 'string' ? value : ''}
          onChange={(e) => onChange(e.target.value)}
          onBlur={onBlur}
          required={field.required}
          aria-invalid={invalid || undefined}
          aria-describedby={describedBy}
          className={cx(inputClass(invalid), (field.is_secret || field.placeholder?.includes('/')) && 'font-mono')}
        />
      )
      break
    case 'select': {
      const sorted = [...options].sort((a, b) => Number(Boolean(b.default)) - Number(Boolean(a.default)))
      control = (
        <select
          id={id}
          name={field.field_id}
          value={typeof value === 'string' ? value : ''}
          onChange={(e) => onChange(e.target.value)}
          onBlur={onBlur}
          required={field.required}
          aria-invalid={invalid || undefined}
          aria-describedby={describedBy}
          aria-busy={optionsLoading || undefined}
          className={inputClass(invalid)}
        >
          <option value="">{optionsLoading ? 'Loading options…' : `Choose ${field.label.toLowerCase()}`}</option>
          {sorted.map((o) => (
            <option key={o.value} value={o.value}>
              {optionLabel(o)}
              {o.note && !o.default ? ` · ${o.note}` : ''}
            </option>
          ))}
        </select>
      )
      break
    }
    case 'multiselect': {
      const selected = Array.isArray(value) ? value : []
      control = (
        <fieldset id={id} aria-describedby={describedBy} aria-invalid={invalid || undefined} className="flex flex-col gap-1">
          <legend className="sr-only">{field.label}</legend>
          {optionsLoading ? <p className="text-caption text-fg-3">Loading options…</p> : null}
          {!optionsLoading && options.length === 0 ? (
            <p className="text-caption text-fg-3">No channels yet. Invite Actron to a channel, then check again.</p>
          ) : null}
          {options.map((o) => {
            const checked = selected.includes(o.value)
            return (
              <label
                key={o.value}
                className={cx(
                  'flex cursor-pointer items-center gap-3 rounded-sm border px-3 py-2 text-small transition-colors duration-1',
                  checked ? 'border-accent/60 bg-accent-wash text-fg-1' : 'border-line-1 text-fg-2 hover:bg-ink-2',
                )}
              >
                <input
                  type="checkbox"
                  name={field.field_id}
                  value={o.value}
                  checked={checked}
                  onChange={() => onChange(checked ? selected.filter((v) => v !== o.value) : [...selected, o.value])}
                  onBlur={onBlur}
                  className="accent-accent"
                />
                <span className="min-w-0 flex-1 font-mono">{o.label}</span>
                {o.note ? <span className="text-caption text-fg-3">{o.note}</span> : null}
              </label>
            )
          })}
        </fieldset>
      )
      break
    }
    case 'stepper': {
      const n = typeof value === 'number' ? value : Number(value ?? field.default ?? 0)
      const min = field.min ?? 1
      const max = field.max ?? 3650
      control = (
        <div className="flex items-center gap-2">
          <button
            type="button"
            aria-label={`Fewer days for ${field.label.toLowerCase()}`}
            onClick={() => onChange(Math.max(min, n - 30))}
            className="press inline-flex size-9 items-center justify-center rounded-sm border border-line-2 text-fg-2 hover:bg-ink-3 hover:text-fg-1"
          >
            <Minus size={14} aria-hidden />
          </button>
          <input
            id={id}
            name={field.field_id}
            type="number"
            inputMode="numeric"
            min={min}
            max={max}
            value={Number.isFinite(n) ? n : ''}
            onChange={(e) => onChange(e.target.value === '' ? null : Number(e.target.value))}
            onBlur={onBlur}
            aria-invalid={invalid || undefined}
            aria-describedby={describedBy}
            className={cx(inputClass(invalid), 'w-24 text-center font-mono tabular')}
          />
          <button
            type="button"
            aria-label={`More days for ${field.label.toLowerCase()}`}
            onClick={() => onChange(Math.min(max, n + 30))}
            className="press inline-flex size-9 items-center justify-center rounded-sm border border-line-2 text-fg-2 hover:bg-ink-3 hover:text-fg-1"
          >
            <Plus size={14} aria-hidden />
          </button>
          <span className="text-caption text-fg-3">days</span>
        </div>
      )
      break
    }
    case 'file':
      control = (
        <input
          id={id}
          name={field.field_id}
          type="file"
          accept={field.accept}
          onChange={(e) => onChange(e.target.files?.[0] ?? null)}
          onBlur={onBlur}
          required={field.required}
          aria-invalid={invalid || undefined}
          aria-describedby={describedBy}
          className="block w-full text-caption text-fg-2 file:mr-3 file:h-8 file:rounded-sm file:border file:border-line-2 file:bg-ink-2 file:px-3 file:text-caption file:text-fg-1"
        />
      )
      break
    default:
      return null
  }

  const labelled = field.ui_component !== 'multiselect'
  return (
    <div className="flex flex-col gap-1.5" data-field={field.field_id}>
      {labelled ? (
        <label htmlFor={id} className="text-caption font-medium text-fg-1">
          {field.label}
          {field.required ? null : <span className="ml-2 font-normal text-fg-3">optional</span>}
        </label>
      ) : (
        <p className="text-caption font-medium text-fg-1" id={`${id}-label`}>
          {field.label}
        </p>
      )}
      {field.description ? (
        <p id={descId} className="text-caption text-fg-3">
          {field.description}
        </p>
      ) : null}
      {control}
      {error ? (
        <p id={errId} className="text-caption text-state-conflict">
          {error}
        </p>
      ) : null}
      {field.info ? <InfoDisclosure info={field.info} /> : null}
    </div>
  )
}
