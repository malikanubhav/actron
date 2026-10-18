'use client'
import { useEffect, useId, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError, newIdempotencyKey, reasonText } from '@/lib/api'
import { endpoints } from '@/lib/api/endpoints'
import type { ConnectorDefinition, ConnectorOption, FormField, ValidateResult } from '@/lib/api/types'
import { qk } from '@/lib/query-keys'
import { toast } from '@/lib/toasts'
import { Button } from '../ui/Button'
import { cx } from '../ui/cx'
import { Glyph } from '../glyphs/Glyph'
import { FieldControl, ManifestPanel, WebhookPanel } from './FieldControl'
import {
  buildPayload,
  canCheck,
  canSubmit,
  fieldError,
  initialValues,
  isInputField,
  needsValidation,
  oauthEnabled,
  optionQuery,
  rootFields,
  visibleFields,
  type FieldValue,
  type FormState,
  type SlackPath,
  type Values,
} from './form-logic'

export interface OAuthReturn {
  status: 'ok' | 'cancelled' | 'expired' | string
  team?: string | null
}

export function oauthMessage(ret: OAuthReturn): { ok: boolean; text: string } {
  if (ret.status === 'ok') return { ok: true, text: `Connected to ${ret.team || 'your workspace'} as @Actron.` }
  if (ret.status === 'cancelled') return { ok: false, text: "You cancelled the Slack approval. Try again when you're ready." }
  if (ret.status === 'expired') return { ok: false, text: 'Slack says the request expired. Start again.' }
  return { ok: false, text: 'Slack did not complete the approval. Start again.' }
}

function randomSecret(): string {
  const bytes = new Uint8Array(20)
  if (typeof crypto !== 'undefined' && crypto.getRandomValues) crypto.getRandomValues(bytes)
  return `whsec_${Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')}`
}

function OptionsLoader({
  def,
  field,
  values,
  onOptions,
}: {
  def: ConnectorDefinition
  field: FormField
  values: Values
  onOptions: (fieldId: string, options: ConnectorOption[], loading: boolean) => void
}) {
  const query = useMemo(() => optionQuery(def, values), [def, values])
  // Options depend on the parent's value only; refetching on every keystroke elsewhere is not needed.
  const parentValue = field.dependsOn ? (query[field.dependsOn] ?? '') : ''
  const result = useQuery({
    queryKey: qk.connectorOptions(def.provider, field.field_id, { parent: parentValue }),
    queryFn: () => endpoints.connectorOptions(def.provider, field.field_id, query),
    staleTime: 60_000,
  })
  const { data, isLoading } = result
  useEffect(() => {
    onOptions(field.field_id, data?.options ?? [], isLoading)
  }, [data, isLoading, field.field_id, onOptions])
  return null
}

export interface ConnectorFormProps {
  def: ConnectorDefinition
  oauthReturn?: OAuthReturn | null
  onConnected?: (secretLast4: string | null) => void
}

/** A source's form, rendered only from its definition (spec C, C12; C-AC-49..53). */
export function ConnectorForm({ def, oauthReturn = null, onConnected }: ConnectorFormProps) {
  const idPrefix = useId().replace(/:/g, '')
  const client = useQueryClient()
  const withOauth = oauthEnabled(def)
  const oauthOk = oauthReturn?.status === 'ok'
  const [rawValues, setValues] = useState<Values>(() => initialValues(def))
  const [touched, setTouched] = useState<Record<string, boolean>>({})
  const [state, setState] = useState<FormState>({ validated: false, oauthOk, path: withOauth && !oauthOk ? 'oauth' : oauthOk ? 'oauth' : 'token' })
  const [validation, setValidation] = useState<ValidateResult | null>(null)
  const [options, setOptions] = useState<Record<string, { list: ConnectorOption[]; loading: boolean }>>({})
  const [savedLast4, setSavedLast4] = useState<string | null | undefined>(undefined)
  const [webhookSecret] = useState<string>(randomSecret)
  const origin = typeof window !== 'undefined' ? window.location.origin : ''

  // Selects with no choice yet take the default option (the default branch, the default team) once options
  // arrive; a select fed by a multiselect takes the first chosen item.
  const values: Values = { ...rawValues }
  const parentOf = (f: FormField) => def.fields.find((x) => x.field_id === f.dependsOn)
  for (const f of def.fields) {
    if (f.ui_component !== 'select' || values[f.field_id]) continue
    const fromParent = parentOf(f)?.ui_component === 'multiselect'
    const list = f.optionsFrom ? (options[f.field_id]?.list ?? []) : []
    const preferred = f.optionsFrom ? list.find((o) => o.default) : undefined
    if (preferred) values[f.field_id] = preferred.value
    else if (fromParent) {
      const chosen = values[f.dependsOn as string]
      if (Array.isArray(chosen) && chosen[0]) values[f.field_id] = chosen[0]
    }
  }

  const shown = visibleFields(def, values, state)
  const roots = rootFields(def, state)
  const rootIds = new Set(roots.map((f) => f.field_id))

  const onOptions = useMemo(
    () => (fieldId: string, list: ConnectorOption[], loading: boolean) =>
      setOptions((prev) => {
        const current = prev[fieldId]
        if (current && current.loading === loading && current.list === list) return prev
        return { ...prev, [fieldId]: { list, loading } }
      }),
    [],
  )

  const optionsFor = (field: FormField): { list: ConnectorOption[]; loading: boolean } => {
    if (field.optionsFrom) return options[field.field_id] ?? { list: [], loading: true }
    // A select fed by a multiselect parent offers the parent's chosen items.
    const parent = def.fields.find((f) => f.field_id === field.dependsOn)
    if (parent?.ui_component === 'multiselect') {
      const chosen = Array.isArray(values[parent.field_id]) ? (values[parent.field_id] as string[]) : []
      const parentOptions = options[parent.field_id]?.list ?? []
      return { list: parentOptions.filter((o) => chosen.includes(o.value)), loading: false }
    }
    return { list: [], loading: false }
  }

  const setValue = (field: FormField, value: FieldValue) => {
    setValues((prev) => ({ ...prev, [field.field_id]: value }))
    if (rootIds.has(field.field_id) && state.validated) {
      setState((s) => ({ ...s, validated: false }))
      setValidation(null)
    }
  }

  const check = useMutation({
    mutationFn: (rootValues: Record<string, unknown>) => endpoints.validateConnector(def.provider, rootValues, newIdempotencyKey()),
    onSuccess: (result) => {
      setValidation(result)
      setState((s) => ({ ...s, validated: result.ok }))
    },
    onError: (error) =>
      setValidation({ ok: false, found: '', details: {}, errors: [{ field: '', message: reasonText(error) }] }),
  })

  const connect = useMutation({
    mutationFn: async () => {
      const key = newIdempotencyKey()
      if (def.fields.some((f) => f.type === 'file')) {
        const form = new FormData()
        form.set('provider', def.provider)
        for (const f of def.fields) {
          const v = values[f.field_id]
          if (v instanceof File) form.set(f.field_id, v)
        }
        return endpoints.createConnection(form, key)
      }
      const { config, secret } = buildPayload(def, values, state)
      if (def.fields.some((f) => f.ui_component === 'webhookPanel') && webhookSecret) {
        secret.webhook_secret = (validation?.details.webhookSecret as string | undefined) ?? webhookSecret
      }
      return endpoints.createConnection({ provider: def.provider, config, secret: Object.keys(secret).length ? secret : undefined }, key)
    },
    onSuccess: (data) => {
      // Secrets leave the page state at once; only the last four characters come back.
      setValues((prev) => {
        const next = { ...prev }
        for (const f of def.fields) if (f.is_secret) next[f.field_id] = ''
        return next
      })
      setSavedLast4(data.connection.secretLast4)
      toast.success(`${def.title} connected. The first backfill has started.`)
      void client.invalidateQueries({ queryKey: qk.connections() })
      void client.invalidateQueries({ queryKey: qk.ingestion() })
      onConnected?.(data.connection.secretLast4)
    },
    onError: (error) => {
      if (error instanceof ApiError && error.code === 'already_connected') toast.error(`${def.title} is already connected.`)
    },
  })

  const errorFor = (field: FormField): string | null => {
    const server = validation?.errors.find((e) => e.field === field.field_id)?.message
    if (server) return server
    return touched[field.field_id] ? fieldError(field, values[field.field_id]) : null
  }

  const generalErrors = validation?.errors.filter((e) => !e.field || !def.fields.some((f) => f.field_id === e.field)) ?? []
  const oauthNote = oauthReturn ? oauthMessage(oauthReturn) : null
  const mustCheck = needsValidation(def, state)
  const submitReady = canSubmit(def, values, state)
  const isFileForm = def.fields.some((f) => f.type === 'file')

  const choosePath = (path: SlackPath) => setState((s) => ({ ...s, path }))

  return (
    <form
      noValidate
      data-testid={`connector-form-${def.provider}`}
      className="flex flex-col gap-4"
      onSubmit={(e) => {
        e.preventDefault()
        const all: Record<string, boolean> = {}
        for (const f of shown) all[f.field_id] = true
        setTouched(all)
        if (submitReady) connect.mutate()
      }}
    >
      {shown
        .filter((f) => f.optionsFrom)
        .map((f) => (
          <OptionsLoader key={f.field_id} def={def} field={f} values={values} onOptions={onOptions} />
        ))}

      {withOauth ? (
        <div className="grid grid-cols-2 gap-3" role="group" aria-label="How to connect Slack">
          <div
            className={cx(
              'flex flex-col gap-2 rounded-md border p-3',
              state.path === 'oauth' ? 'border-line-2 bg-ink-1' : 'border-line-1',
            )}
          >
            <a
              href={def.oauth?.url ?? '#'}
              onClick={() => choosePath('oauth')}
              data-testid="add-to-slack"
              className="press inline-flex h-10 items-center justify-center gap-2 rounded-md border border-line-2 bg-fg-1 px-4 text-small font-medium text-ink-0 hover:bg-fg-2"
            >
              {/* Slack's official mark, unmodified. */}
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src="/brands/slack.svg" alt="" width={18} height={18} aria-hidden />
              Add to Slack
            </a>
            <p className="text-caption text-fg-3">Approve Actron in Slack, then choose channels here.</p>
          </div>
          <div
            className={cx(
              'flex flex-col gap-2 rounded-md border p-3',
              state.path === 'token' ? 'border-line-2 bg-ink-1' : 'border-line-1',
            )}
          >
            <Button
              variant={state.path === 'token' ? 'secondary' : 'ghost'}
              aria-pressed={state.path === 'token'}
              onClick={() => choosePath('token')}
              className="h-10"
            >
              Connect with tokens
            </Button>
            <p className="text-caption text-fg-3">Paste a bot token. Works on a laptop without a public address.</p>
          </div>
        </div>
      ) : null}

      {oauthNote ? (
        <p
          role={oauthNote.ok ? 'status' : 'alert'}
          data-testid="oauth-result"
          className={cx('rounded-sm border px-3 py-2 text-small', oauthNote.ok ? 'border-state-ok/40 text-fg-1' : 'border-state-conflict/40 text-state-conflict')}
        >
          {oauthNote.text}
        </p>
      ) : null}

      {shown.map((field) => {
        if (field.ui_component === 'manifestPanel') return <ManifestPanel key={field.field_id} field={field} />
        if (field.ui_component === 'webhookPanel')
          return (
            <WebhookPanel
              key={field.field_id}
              field={field}
              origin={origin}
              secret={(validation?.details.webhookSecret as string | undefined) ?? webhookSecret}
            />
          )
        if (!isInputField(field)) return null
        const opts = optionsFor(field)
        return (
          <FieldControl
            key={field.field_id}
            idPrefix={idPrefix}
            field={field}
            value={values[field.field_id]}
            onChange={(v) => setValue(field, v)}
            onBlur={() => setTouched((t) => ({ ...t, [field.field_id]: true }))}
            error={errorFor(field)}
            options={opts.list}
            optionsLoading={opts.loading}
          />
        )
      })}

      {validation?.ok ? (
        <p role="status" data-testid="validate-found" className="flex items-start gap-2 rounded-sm border border-state-ok/40 px-3 py-2 text-small text-fg-1">
          <span className="mt-0.5 text-state-ok">
            <Glyph name="TestPass" size={14} />
          </span>
          {validation.found}
        </p>
      ) : null}
      {generalErrors.length ? (
        <p role="alert" className="rounded-sm border border-state-conflict/40 px-3 py-2 text-small text-state-conflict">
          {generalErrors.map((e) => e.message).join(' ')}
        </p>
      ) : null}
      {connect.isError ? (
        <p role="alert" className="rounded-sm border border-state-conflict/40 px-3 py-2 text-small text-state-conflict">
          {reasonText(connect.error)}
        </p>
      ) : null}
      {savedLast4 !== undefined ? (
        <p role="status" data-testid="saved-secret" className="text-small text-fg-2">
          Connected.{' '}
          {savedLast4 ? `The secret ending in ${savedLast4} is saved and will not be shown again.` : 'Secrets are saved and will not be shown again.'}
        </p>
      ) : null}

      <div className="flex flex-wrap items-center gap-2">
        {mustCheck && !state.validated ? (
          <Button
            variant="primary"
            disabled={!canCheck(def, values, state)}
            loading={check.isPending}
            loadingText="Checking"
            onClick={() => {
              const rootValues: Record<string, unknown> = {}
              for (const f of roots) rootValues[f.field_id] = values[f.field_id]
              check.mutate(rootValues)
            }}
          >
            Check connection
          </Button>
        ) : (
          <Button type="submit" variant="primary" disabled={!submitReady} loading={connect.isPending} loadingText={isFileForm ? 'Importing' : 'Connecting'}>
            {isFileForm ? 'Import export' : 'Connect'}
          </Button>
        )}
        {mustCheck && !state.validated ? (
          <span className="text-caption text-fg-3">Actron makes one test call before saving anything.</span>
        ) : null}
      </div>
    </form>
  )
}
