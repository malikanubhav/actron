'use client'
import { createContext, useContext, type ReactNode } from 'react'
import { ArrowSquareOut, CaretDown } from '@phosphor-icons/react/dist/ssr'
import type { ConnectorCheck, ConnectorDefinition } from '@/lib/api/types'
import { CopyButton } from '../core/Formatting'
import { Glyph } from '../glyphs/Glyph'
import { Button } from '../ui/Button'
import { cx } from '../ui/cx'
import { useGuideStore } from './guide-store'
import { OPTIONAL_GUIDE_STEPS } from './form-logic'

export interface GuideContextValue {
  def: ConnectorDefinition
  checks: ConnectorCheck[] | undefined
  isHttps: boolean
  checking: boolean
  recheck: () => void
  origin: string
}

export const GuideContext = createContext<GuideContextValue | null>(null)

function useGuide(): GuideContextValue {
  const ctx = useContext(GuideContext)
  if (!ctx) throw new Error('Guide components render inside a setup guide.')
  return ctx
}

/** Error codes named by failing checks, so the matching troubleshooting entry stands out. */
export function failingCodes(checks: readonly ConnectorCheck[] | undefined): Set<string> {
  const out = new Set<string>()
  for (const c of checks ?? []) {
    if (c.ok !== false) continue
    for (const m of c.message.matchAll(/\b([a-z]+(?:_[a-z]+)+|[A-Z]+_[A-Z]+|\d{3})\b/g)) out.add(m[1] as string)
  }
  return out
}

export function Step({
  n,
  id,
  title,
  children,
  hideOnHttps = false,
}: {
  n: number
  id: string
  title: string
  children?: ReactNode
  hideOnHttps?: boolean
}) {
  const { def, checks, isHttps, checking, recheck } = useGuide()
  const expanded = useGuideStore((s) => s.expanded[def.provider])
  const setExpanded = useGuideStore((s) => s.setExpanded)
  if (hideOnHttps && isHttps) return null
  const step = def.guide.find((s) => s.id === id)
  const check = step?.checkId ? checks?.find((c) => c.id === step.checkId) : undefined
  const status = check?.ok === true ? 'done' : check?.ok === false ? 'failed' : 'waiting'
  const optional = Boolean(step?.checkId && OPTIONAL_GUIDE_STEPS.has(step.checkId))
  const firstOpen = def.guide.find((s) => {
    const c = s.checkId ? checks?.find((x) => x.id === s.checkId) : undefined
    return c?.ok !== true && !(isHttps && s.checkId === 'socket_mode')
  })?.id
  const open = expanded === undefined ? firstOpen === id : expanded === id
  const panelId = `guide-${def.provider}-${id}`
  return (
    <section data-testid="guide-step" data-step={id} data-status={status} className="border-b border-line-1 last:border-b-0">
      <h3>
        <button
          type="button"
          aria-expanded={open}
          aria-controls={panelId}
          onClick={() => setExpanded(def.provider, open ? null : id)}
          className="flex w-full items-center gap-3 py-4 text-left"
        >
          <span
            className={cx(
              'inline-flex size-7 shrink-0 items-center justify-center rounded-full border font-mono text-caption tabular',
              status === 'done' && 'border-state-ok/60 text-state-ok',
              status === 'failed' && 'border-state-conflict/60 text-state-conflict',
              status === 'waiting' && 'border-line-2 text-fg-2',
            )}
          >
            {status === 'done' ? <Glyph name="TestPass" size={14} title="Done" /> : String(n).padStart(2, '0')}
          </span>
          <span className="min-w-0 flex-1 text-small font-medium text-fg-1">{title}</span>
          <span
            className={cx(
              'text-caption font-medium',
              status === 'done' ? 'text-state-ok' : status === 'failed' ? 'text-state-conflict' : 'text-fg-3',
            )}
          >
            {status === 'done' ? 'Done' : status === 'failed' ? 'Check failed' : optional ? 'Optional' : 'Not yet'}
          </span>
          <CaretDown size={14} aria-hidden className={cx('text-fg-3 transition-transform duration-2', open && 'rotate-180')} />
        </button>
      </h3>
      <div id={panelId} hidden={!open} className="flex flex-col gap-3 pb-5 pl-10 text-small text-fg-2">
        {children}
        {check ? (
          <div
            data-testid="guide-check"
            role={check.ok === false ? 'alert' : 'status'}
            className={cx(
              'flex flex-col gap-2 rounded-sm border px-3 py-2',
              check.ok === true && 'border-state-ok/40',
              check.ok === false && 'border-state-conflict/40',
              check.ok === null && 'border-line-1',
            )}
          >
            <p className={cx('text-small', check.ok === false ? 'text-state-conflict' : 'text-fg-2')}>
              <span className="eyebrow mr-2">Check</span>
              {check.message}
            </p>
            {check.ok === false && check.troubleshooting ? (
              <p className="text-small text-fg-1" data-testid="guide-troubleshooting">
                {check.troubleshooting}
              </p>
            ) : null}
            <div>
              <Button size="sm" onClick={recheck} loading={checking} loadingText="Checking">
                Check again
              </Button>
            </div>
          </div>
        ) : null}
      </div>
    </section>
  )
}

/** The exact clicks, in order: "Create New App → From an app manifest". */
export function Clicks({ children }: { children: ReactNode }) {
  return <p className="rounded-sm bg-ink-2 px-3 py-2 font-mono text-caption text-fg-1">{children}</p>
}

export function CopyValue({ value, label }: { value: string; label?: string }) {
  return (
    <span className="flex min-w-0 items-center gap-2 rounded-sm border border-line-1 px-3 py-1.5">
      <code className="min-w-0 flex-1 truncate font-mono text-caption text-fg-1">{value}</code>
      <CopyButton value={value} label={label ?? 'Copy'} />
    </span>
  )
}

export function DeepLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer noopener"
      className="inline-flex items-center gap-1 text-fg-1 underline decoration-line-2 underline-offset-4 hover:decoration-fg-2"
    >
      {children}
      <ArrowSquareOut size={12} aria-hidden />
      <span className="sr-only"> (opens in a new tab)</span>
    </a>
  )
}

/** The manifest from the connector definition (the backend picks the dev or production variant). */
export function Manifest() {
  const { def } = useGuide()
  const manifest = def.fields.find((f) => f.ui_component === 'manifestPanel')?.content ?? ''
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <span className="eyebrow">Manifest · {manifest.includes('socket_mode_enabled: true') ? 'Socket Mode' : 'HTTPS'}</span>
        <CopyButton value={manifest} label="Copy manifest" />
      </div>
      <pre tabIndex={0} className="max-h-40 overflow-auto overscroll-contain rounded-sm bg-ink-2 p-3 font-mono text-caption text-fg-2">{manifest}</pre>
    </div>
  )
}

/** The prefilled-manifest link (Slack accepts `manifest_yaml` on the new-app page [VERIFY]). */
export function ManifestLink() {
  const { def } = useGuide()
  const manifest = def.fields.find((f) => f.ui_component === 'manifestPanel')?.content ?? ''
  return (
    <DeepLink href={`https://api.slack.com/apps?new_app=1&manifest_yaml=${encodeURIComponent(manifest)}`}>
      Open Slack app creation with the manifest filled in
    </DeepLink>
  )
}

export function WebhookValues() {
  const { origin } = useGuide()
  return (
    <div className="flex flex-col gap-2">
      <CopyValue value={`${origin}/webhooks/github`} label="Copy URL" />
      <CopyValue value="application/json" />
      <p className="text-caption text-fg-3">
        The secret is on the Repository card once the repository is checked. Tick: pushes, pull requests, pull request reviews,
        pull request review comments, issues, issue comments.
      </p>
    </div>
  )
}

function Table({ head, rows, testId }: { head: [string, string]; rows: [string, string][]; testId: string }) {
  return (
    <table className="w-full border-collapse text-caption" data-testid={testId}>
      <thead>
        <tr>
          <th scope="col" className="eyebrow border-b border-line-1 py-1.5 pr-3 text-left">
            {head[0]}
          </th>
          <th scope="col" className="eyebrow border-b border-line-1 py-1.5 text-left">
            {head[1]}
          </th>
        </tr>
      </thead>
      <tbody>
        {rows.map(([a, b]) => (
          <tr key={a} className="border-b border-line-1 last:border-b-0">
            <td className="py-1.5 pr-3 align-top font-mono text-fg-1">{a}</td>
            <td className="py-1.5 align-top text-fg-2">{b}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

export const SLACK_SCOPE_REASONS: [string, string][] = [
  ['app_mentions:read', 'Hear @Actron.'],
  ['channels:history', 'Read messages in public channels the bot is in.'],
  ['groups:history', 'Read messages in private channels the bot is in.'],
  ['channels:read', 'List public channels for the picker.'],
  ['groups:read', 'List private channels for the picker.'],
  ['chat:write', "Post and edit Actron's messages."],
  ['commands', 'The /actron command.'],
  ['im:write', 'Direct messages when a person must act.'],
  ['reactions:read', 'Read reactions.'],
  ['team:read', 'Workspace name.'],
  ['users:read', 'Names, to match people across tools.'],
  ['users:read.email', 'Emails, to match people across tools.'],
]

export function ScopeTable() {
  return <Table head={['Scope', 'Why Actron needs it']} rows={SLACK_SCOPE_REASONS} testId="scope-table" />
}

export const GITHUB_PERMISSIONS: [string, string][] = [
  ['Contents: read and write', "Read code; push Actron's branches to the push target."],
  ['Pull requests: read and write', 'Read reviews; open pull requests.'],
  ['Issues: read', 'Read issues and comments for history.'],
  ['Metadata: read', 'Required by GitHub for every token.'],
  ['Actions: read', 'Read workflow runs for test results.'],
  ['Checks: read', 'Read check results on pull requests.'],
]

export function PermissionTable() {
  return <Table head={['Permission', 'Why Actron needs it']} rows={GITHUB_PERMISSIONS} testId="permission-table" />
}

export function Troubleshooting({ children }: { children: ReactNode }) {
  return (
    <section className="mt-6 flex flex-col gap-2" aria-labelledby="troubleshooting-title">
      <h3 id="troubleshooting-title" className="eyebrow">
        Troubleshooting
      </h3>
      <dl className="flex flex-col gap-1">{children}</dl>
    </section>
  )
}

export function Troubleshoot({ code, children }: { code: string; children: ReactNode }) {
  const { checks } = useGuide()
  const active = failingCodes(checks).has(code)
  return (
    <div
      data-testid="troubleshoot"
      data-code={code}
      data-active={active ? 'true' : 'false'}
      className={cx('grid grid-cols-3 gap-3 rounded-sm px-2 py-1.5 text-caption', active && 'bg-state-conflict/10')}
    >
      <dt className={cx('font-mono', active ? 'text-state-conflict' : 'text-fg-2')}>{code}</dt>
      <dd className="col-span-2 text-fg-2">{children}</dd>
    </div>
  )
}

export function P({ children }: { children?: ReactNode }) {
  return <p className="text-small text-fg-2">{children}</p>
}

export function InlineCode({ children }: { children?: ReactNode }) {
  return <code className="rounded-sm bg-ink-2 px-1 font-mono text-caption text-fg-1">{children}</code>
}

/** Components the guide MDX files may use (also registered in mdx-components.tsx). */
export const guideComponents = {
  Step,
  Clicks,
  CopyValue,
  DeepLink,
  Manifest,
  ManifestLink,
  WebhookValues,
  ScopeTable,
  PermissionTable,
  Troubleshooting,
  Troubleshoot,
  p: P,
  code: InlineCode,
}
