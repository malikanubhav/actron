'use client'
import { useEffect, useMemo, useState } from 'react'
import { GitBranch } from '@phosphor-icons/react/dist/ssr'
import type { ConnectionView, Settings } from '@/lib/api/types'
import { useConnections, useSettings } from '@/lib/hooks/queries'
import { useDisconnect, usePatchConnection, usePutSettings, useRaiseBudget, useResetCursor } from '@/lib/hooks/mutations'
import { reasonText } from '@/lib/api'
import { formatUsd } from '@/lib/format'
import { connectionAbout, connectionName } from '../connect/form-logic'
import { ScreenHeader } from '../core/ScreenHeader'
import { PanelLabelTitle } from '../core/PanelLabelTitle'
import { StateChip } from '../core/StateChip'
import { UnsavedChangesGuard } from '../core/UnsavedChangesGuard'
import { PageFrame } from '../shell/PageFrame'
import { ErrorState } from '../states/States'
import { SkeletonText } from '../states/Skeleton'
import { Button } from '../ui/Button'
import { Dialog } from '../ui/Dialog'
import { BrandMark } from '../brand/BrandMark'
import { cx } from '../ui/cx'

// Mutation hooks show the server's reason in a toast and then reject; nothing more to do here.
function shownInToast(): void {}

export interface SettingsDraft {
  conflict: string
  possibleConflict: string
  linkKeep: string
  approvers: string
  botName: string
  botEmail: string
  allowPublicReplays: boolean
}

export function draftFromSettings(s: Settings): SettingsDraft {
  return {
    conflict: String(s.thresholds.conflict),
    possibleConflict: String(s.thresholds.possibleConflict),
    linkKeep: String(s.thresholds.linkKeep),
    approvers: s.approvers.join(', '),
    botName: s.botIdentity.name,
    botEmail: s.botIdentity.email,
    allowPublicReplays: s.allowPublicReplays,
  }
}

export type SettingsErrors = Partial<Record<keyof SettingsDraft, string>>

export function validateSettings(d: SettingsDraft): SettingsErrors {
  const errors: SettingsErrors = {}
  const prob = (v: string) => {
    const n = Number(v)
    return v.trim() !== '' && Number.isFinite(n) && n >= 0 && n <= 1
  }
  if (!prob(d.conflict)) errors.conflict = 'Use a number between 0 and 1, such as 0.8.'
  if (!prob(d.possibleConflict)) errors.possibleConflict = 'Use a number between 0 and 1, such as 0.6.'
  else if (prob(d.conflict) && Number(d.possibleConflict) > Number(d.conflict)) errors.possibleConflict = 'Keep this at or below the conflict threshold.'
  if (!prob(d.linkKeep)) errors.linkKeep = 'Use a number between 0 and 1, such as 0.6.'
  if (d.botEmail.trim() && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(d.botEmail.trim())) errors.botEmail = 'Use an email address such as actron-bot@example.com.'
  if (d.approvers.split(',').some((a) => a.trim() && !/^[UW][A-Z0-9]{6,}$/.test(a.trim()))) errors.approvers = 'Use Slack user ids such as U04ABCDEF, separated by commas.'
  return errors
}

export function settingsPatch(d: SettingsDraft): Partial<Settings> {
  return {
    thresholds: { conflict: Number(d.conflict), possibleConflict: Number(d.possibleConflict), linkKeep: Number(d.linkKeep) },
    approvers: d.approvers
      .split(',')
      .map((a) => a.trim())
      .filter(Boolean),
    botIdentity: { name: d.botName.trim(), email: d.botEmail.trim() },
    allowPublicReplays: d.allowPublicReplays,
  }
}

/** The headline: how many jobs run without a model, said plainly. */
export function modelsHeadline(jobs: readonly { status: string }[]): string {
  const fixed = jobs.filter((j) => j.status === 'stub').length
  if (fixed === 0) return 'Every model job uses a model.'
  if (fixed === jobs.length) return `No model keys are set, so all ${jobs.length} jobs use fixed, cautious answers.`
  return `${fixed} of ${jobs.length} jobs have no model key and use fixed, cautious answers.`
}

/** What a job runs on, in one cell. */
function modelText(provider: string): string {
  if (provider === 'jev') return 'Jev'
  if (provider === 'llm') return 'LLM'
  return 'No key · fixed answer'
}

/** Jev primitives in plain words (PRD 10.2): noul returns a probability from 0 to 1. */
const PRIMITIVE_TEXT: Record<string, string> = { noul: 'Yes or no, as a probability', choice: 'Pick one option', score: 'Score on a scale', text: 'Written text', json: 'Structured fields', tools: 'Calls graph tools' }

const THRESHOLD_HELP: Record<'conflict' | 'possibleConflict' | 'linkKeep', { label: string; help: string }> = {
  conflict: { label: 'Conflict threshold', help: 'At or above this probability a decision is shown as a conflict and Actron asks before it builds.' },
  possibleConflict: { label: 'Possible conflict threshold', help: 'Between this and the conflict threshold, the decision is shown as a possible conflict.' },
  linkKeep: { label: 'Keep inferred links from', help: 'Model-made links below this probability are dropped. Lower keeps more links and more noise.' },
}

function Field({
  id,
  label,
  help,
  error,
  children,
}: {
  id: string
  label: string
  help?: string
  error?: string
  children: React.ReactNode
}) {
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-small font-medium text-fg-1">
        {label}
      </label>
      {help ? (
        <p id={`${id}-help`} className="text-caption text-fg-3">
          {help}
        </p>
      ) : null}
      {children}
      {error ? (
        <p id={`${id}-err`} className="text-caption text-state-conflict">
          {error}
        </p>
      ) : null}
    </div>
  )
}

const inputClass = (error?: string) =>
  cx('h-9 w-full rounded-sm border bg-ink-1 px-3 text-small text-fg-1 focus-visible:border-accent', error ? 'border-state-conflict/70' : 'border-line-2')

function BranchChange({ connection }: { connection: ConnectionView }) {
  const current = String(connection.config.workingBranch ?? '')
  const [value, setValue] = useState(current)
  const [confirm, setConfirm] = useState(false)
  const patch = usePatchConnection()
  const unchanged = !value.trim() || value.trim() === current
  return (
    <div className="flex items-end gap-2">
      <Field id={`branch-${connection.id}`} label="Working branch" help="Actron keeps this branch's code in memory. Type another branch to switch.">
        <input id={`branch-${connection.id}`} value={value} onChange={(e) => setValue(e.target.value)} className={cx(inputClass(), 'font-mono')} />
      </Field>
      {/* aria-disabled keeps the label readable (text-fg-2) while there is nothing to change; the help text says why. */}
      <Button
        aria-disabled={unchanged}
        className={cx(unchanged && 'cursor-not-allowed text-fg-2 hover:border-line-2 hover:bg-transparent')}
        onClick={() => {
          if (!unchanged) setConfirm(true)
        }}
      >
        Change
      </Button>
      <Dialog
        open={confirm}
        onClose={() => setConfirm(false)}
        label="Working branch"
        title={`Switch from ${current} to ${value.trim()}?`}
        footer={
          <>
            <Button variant="ghost" onClick={() => setConfirm(false)}>
              Keep {current}
            </Button>
            <Button
              variant="primary"
              loading={patch.isPending}
              onClick={() => void patch.run({ connectionId: connection.id, config: { workingBranch: value.trim() } }).catch(shownInToast).finally(() => setConfirm(false))}
            >
              Switch and rebuild
            </Button>
          </>
        }
      >
        <p className="text-small text-fg-2">
          Code memory for <code className="font-mono text-fg-1">{current}</code> is replaced by <code className="font-mono text-fg-1">{value.trim()}</code>. Actron
          re-reads the code now; requests investigated during the rebuild wait for it.
        </p>
      </Dialog>
    </div>
  )
}

/** Settings (PROMPT 8.8 G). */
export function SettingsScreen() {
  const q = useSettings()
  const connections = useConnections()
  const put = usePutSettings()
  const raise = useRaiseBudget()
  const disconnect = useDisconnect()
  const reset = useResetCursor()
  const [edited, setDraft] = useState<SettingsDraft | null>(null)
  const [touched, setTouched] = useState(false)
  const [danger, setDanger] = useState<{ kind: 'disconnect' | 'reset'; connection: ConnectionView } | null>(null)
  const [cap, setCap] = useState('')
  const original = useMemo(() => (q.data ? draftFromSettings(q.data.settings) : null), [q.data])
  const loaded = q.isSuccess

  // Links such as /app/settings#bot-identity arrive before the section exists; scroll once the data is in.
  useEffect(() => {
    if (!loaded || typeof window === 'undefined') return
    const id = window.location.hash.slice(1)
    if (!id) return
    // After the router's own scroll handling on navigation, which would otherwise put the page back at the top.
    const timer = window.setTimeout(() => {
      const target = document.getElementById(id)
      if (!target) return
      target.scrollIntoView({ block: 'start' })
      target.querySelector<HTMLInputElement>('input')?.focus({ preventScroll: true })
    }, 120)
    return () => window.clearTimeout(timer)
  }, [loaded])

  const draft = edited ?? original

  // The error state comes first: a failed first load has no data, and would otherwise read as loading forever.
  if (q.isError) {
    return (
      <PageFrame>
        <ScreenHeader eyebrow="Settings" headline="Settings could not be loaded." purpose="Connections, sync schedules, models, thresholds and bot identity." />
        <ErrorState title="Settings could not be loaded." body={reasonText(q.error)} action={<Button onClick={() => void q.refetch()}>Retry</Button>} />
      </PageFrame>
    )
  }
  if (q.isPending || !draft || !original) {
    return (
      <PageFrame>
        <ScreenHeader eyebrow="Settings" headline="Loading settings." purpose="Connections, sync schedules, models, thresholds and bot identity." />
        <SkeletonText lines={8} />
      </PageFrame>
    )
  }
  const s = q.data.settings
  const errors = validateSettings(draft)
  const valid = Object.keys(errors).length === 0
  const dirty = JSON.stringify(draft) !== JSON.stringify(original)
  const stubJobs = s.jobs.filter((j) => j.status === 'stub').length
  const set = <K extends keyof SettingsDraft>(k: K, v: SettingsDraft[K]) => setDraft({ ...draft, [k]: v })
  const err = (k: keyof SettingsDraft) => (touched ? errors[k] : undefined)
  const allSame = stubJobs > 0 && stubJobs === s.jobs.length
  const conns = connections.data?.connections ?? []
  const hasCodeRow = conns.some((c) => c.provider === 'code')
  const botMissing = !original.botName.trim() || !original.botEmail.trim()

  return (
    <PageFrame>
      <UnsavedChangesGuard when={dirty} />
      <ScreenHeader
        eyebrow="Settings"
        headline={modelsHeadline(s.jobs)}
        purpose="Control connections, sync schedules, models per job, thresholds and the bot's identity."
        actions={
          <>
            {!dirty ? (
              <span className="text-caption text-fg-3" id="save-reason">
                Nothing to save yet
              </span>
            ) : null}
            <Button
              variant={dirty ? 'primary' : 'secondary'}
              disabled={!dirty || !valid}
              aria-describedby={!dirty ? 'save-reason' : undefined}
              loading={put.isPending}
              loadingText="Saving"
              onClick={() => {
                setTouched(true)
                if (valid) void put.run({ partial: settingsPatch(draft) }).then((r) => setDraft(draftFromSettings(r.settings))).catch(shownInToast)
              }}
            >
              Save changes
            </Button>
          </>
        }
      />

      <section aria-labelledby="s-conn" className="flex flex-col gap-4">
        <PanelLabelTitle label="Connections" title="Sources and sync schedules" id="s-conn" />
        <ul className="flex flex-col border-t border-line-1">
          {conns.map((c) => {
            const about = connectionAbout(c.provider)
            const schedule = s.schedules[c.provider === 'slack_export' ? 'slack' : c.provider]
            return (
              <li key={c.id} className="flex flex-wrap items-start gap-x-8 gap-y-4 border-b border-line-1 py-4" data-testid={`settings-connection-${c.provider}`}>
                <div className="flex min-w-64 flex-1 flex-col gap-1">
                  <div className="flex items-center gap-2">
                    {c.provider === 'code' ? (
                      <GitBranch size={16} aria-hidden className="text-fg-2" />
                    ) : (
                      <BrandMark name={c.provider === 'github' ? 'github' : c.provider === 'linear' ? 'linear' : 'slack'} size={16} decorative />
                    )}
                    <span className="text-small font-medium text-fg-1">{connectionName(c.provider)}</span>
                    <StateChip state={c.sync.state} />
                  </div>
                  {about ? <p className="text-caption text-fg-3">{about}</p> : null}
                  <p className="text-caption text-fg-3">
                    {schedule ? `Syncs ${schedule}.` : 'Syncs when you ask.'}
                    {c.secretLast4 ? (
                      <>
                        {' '}
                        Secret ending in <span className="font-mono text-fg-2">{c.secretLast4}</span>.
                      </>
                    ) : null}
                  </p>
                </div>
                {c.provider === 'code' || (c.provider === 'github' && !hasCodeRow) ? <BranchChange connection={c} /> : null}
              </li>
            )
          })}
          {connections.data?.connections.length === 0 ? <li className="py-4 text-small text-fg-2">No sources connected. Use the Connect screen.</li> : null}
        </ul>
      </section>

      <section aria-labelledby="s-models" className="flex flex-col gap-4">
        {/* With no model at all the question in the title has one answer, given in the line below it. */}
        <PanelLabelTitle label="Models" title={allSame ? 'Model jobs' : 'Which model does each job'} id="s-models" />
        {stubJobs ? (
          <p className="max-w-measure text-small text-fg-2" data-testid="model-keys-hint">
            {allSame ? 'Every job below has no model key and returns a fixed, cautious answer. ' : 'Jobs marked “No key” return a fixed, cautious answer. '}
            To use models, add <code className="font-mono text-fg-1">TYPESAFE_API_KEY</code> for judgments and a model key such as{' '}
            <code className="font-mono text-fg-1">ANTHROPIC_API_KEY</code> with <code className="font-mono text-fg-1">MODEL_WRITING</code> for text to{' '}
            <code className="font-mono text-fg-1">.env</code>, then restart the server.
          </p>
        ) : null}
        <table className="w-full text-left text-small">
          <thead>
            <tr className="border-b border-line-1 text-caption font-medium text-fg-3">
              <th className="py-2 font-medium">Job</th>
              <th className="py-2 font-medium">Kind</th>
              {/* When every job runs on the same fallback, the line above says it once and the column is left out. */}
              {allSame ? null : <th className="py-2 font-medium">Runs on</th>}
            </tr>
          </thead>
          <tbody>
            {s.jobs.map((j) => (
              <tr key={j.job} className="border-b border-line-1" data-status={j.status}>
                <td className="py-2 font-mono text-caption text-fg-1">{j.job}</td>
                <td className="py-2 text-caption text-fg-2" title={`Jev primitive: ${j.primitive}`}>{PRIMITIVE_TEXT[j.primitive] ?? j.primitive}</td>
                {allSame ? null : (
                  <td className="py-2">
                    <span className={cx('inline-flex items-center gap-2 text-caption', j.status === 'live' ? 'text-fg-1' : 'text-fg-3')}>
                      {j.provider === 'jev' ? <BrandMark name="typesafe" size={14} decorative /> : null}
                      {modelText(j.provider)}
                    </span>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
        <p className="text-caption text-fg-3">
          Judgments use Jev; text uses the LLM ({s.models.writing || 'not set'}); the investigator uses {s.models.agent || 'the pipeline'}; Pi codes with {s.models.coding || 'no model'}. Model names come from the server environment.
        </p>
      </section>

      <section aria-labelledby="s-thr" className="flex flex-col gap-4">
        <PanelLabelTitle label="Thresholds" title="When Actron calls something a conflict" id="s-thr" />
        <div className="grid grid-cols-3 gap-gutter">
          {(['conflict', 'possibleConflict', 'linkKeep'] as const).map((k) => (
            <Field key={k} id={`thr-${k}`} label={THRESHOLD_HELP[k].label} help={THRESHOLD_HELP[k].help} error={err(k)}>
              <input
                id={`thr-${k}`}
                inputMode="decimal"
                value={draft[k]}
                onChange={(e) => set(k, e.target.value)}
                onBlur={() => setTouched(true)}
                aria-invalid={err(k) ? true : undefined}
                aria-describedby={`thr-${k}-help${err(k) ? ` thr-${k}-err` : ''}`}
                className={cx(inputClass(err(k)), 'font-mono tabular')}
              />
            </Field>
          ))}
        </div>
      </section>

      <section aria-labelledby="s-people" className="flex flex-col gap-4">
        <PanelLabelTitle label="People" title="Approvers and replays" id="s-people" />
        <div className="grid grid-cols-3 gap-gutter">
          <Field id="approvers" label="Approvers" help="Slack user ids allowed to approve, besides the requester and the owner." error={err('approvers')}>
            <input id="approvers" value={draft.approvers} onChange={(e) => set('approvers', e.target.value)} onBlur={() => setTouched(true)} aria-invalid={err('approvers') ? true : undefined} className={cx(inputClass(err('approvers')), 'font-mono')} />
          </Field>
        </div>
        <label className="flex items-center gap-3 text-small text-fg-1">
          <input type="checkbox" checked={draft.allowPublicReplays} onChange={(e) => set('allowPublicReplays', e.target.checked)} className="size-4 accent-accent" />
          Allow public replays of finished requests (anyone with the link can watch; private message text beyond what the request showed is removed)
        </label>
      </section>

      <section id="bot-identity" aria-labelledby="s-bot" className="flex scroll-mt-8 flex-col gap-4" data-testid="bot-identity">
        <PanelLabelTitle label="Bot identity" title="Who Actron's commits come from" id="s-bot" />
        {botMissing ? (
          <p className="max-w-measure text-small text-fg-2" data-testid="bot-identity-missing">
            Builds stop until the bot has a name and an email, because Actron signs every commit with them. Builds read{' '}
            <code className="font-mono text-fg-1">ACTRON_BOT_NAME</code> and <code className="font-mono text-fg-1">ACTRON_BOT_EMAIL</code> from{' '}
            <code className="font-mono text-fg-1">.env</code>; set both there and restart the server.
          </p>
        ) : null}
        <div className="grid grid-cols-3 gap-gutter">
          <Field id="bot-name" label="Bot name for commits" help="Shown as the author of Actron's commits.">
            <input id="bot-name" value={draft.botName} onChange={(e) => set('botName', e.target.value)} className={inputClass()} />
          </Field>
          <Field id="bot-email" label="Bot email for commits" help="Use an address your repository accepts commits from." error={err('botEmail')}>
            <input id="bot-email" type="email" value={draft.botEmail} onChange={(e) => set('botEmail', e.target.value)} onBlur={() => setTouched(true)} aria-invalid={err('botEmail') ? true : undefined} className={inputClass(err('botEmail'))} />
          </Field>
        </div>
      </section>

      <section aria-labelledby="s-budget" className="flex flex-col gap-4">
        <PanelLabelTitle label="Budget" title="Daily model budget" id="s-budget" />
        <p className="text-small text-fg-2">
          Spent today: <span className="font-mono text-fg-1 tabular">{formatUsd(s.budget.spentTodayUsd)}</span> of{' '}
          <span className="font-mono text-fg-1 tabular">{formatUsd(s.budget.capUsd)}</span>. At the cap, investigations use the pipeline and builds wait.
        </p>
        <div className="flex items-end gap-2">
          <Field id="cap" label="New daily cap in US dollars">
            <input id="cap" inputMode="decimal" value={cap} onChange={(e) => setCap(e.target.value)} placeholder={String(s.budget.capUsd)} className={cx(inputClass(), 'w-40 font-mono')} />
          </Field>
          <Button disabled={!(Number(cap) > s.budget.capUsd)} loading={raise.isPending} onClick={() => void raise.run({ capUsd: Number(cap) }).then(() => setCap('')).catch(shownInToast)}>
            Raise the cap
          </Button>
        </div>
      </section>

      <section aria-labelledby="s-danger" className="flex flex-col gap-4 rounded-lg border border-state-conflict/40 p-5">
        <PanelLabelTitle label="Danger zone" title="Disconnect or re-read a source" id="s-danger" />
        <ul className="flex flex-col gap-2">
          {conns.map((c) => (
            <li key={c.id} className="flex items-center gap-3">
              <span className="min-w-40 text-small text-fg-1">{connectionName(c.provider)}</span>
              <Button size="sm" onClick={() => setDanger({ kind: 'reset', connection: c })}>
                Re-read from the start
              </Button>
              <Button size="sm" variant="danger" onClick={() => setDanger({ kind: 'disconnect', connection: c })}>
                Disconnect
              </Button>
            </li>
          ))}
        </ul>
      </section>

      <Dialog
        open={danger !== null}
        onClose={() => setDanger(null)}
        label="Danger zone"
        title={danger ? (danger.kind === 'disconnect' ? `Disconnect ${connectionName(danger.connection.provider)}?` : `Re-read ${connectionName(danger.connection.provider)} from the start?`) : ''}
        footer={
          <>
            <Button variant="ghost" onClick={() => setDanger(null)}>
              Cancel
            </Button>
            <Button
              variant="danger"
              loading={disconnect.isPending || reset.isPending}
              onClick={() => {
                if (!danger) return
                const p = danger.kind === 'disconnect' ? disconnect.run({ connectionId: danger.connection.id }) : reset.run({ connectionId: danger.connection.id })
                void p.catch(shownInToast).finally(() => setDanger(null))
              }}
            >
              {danger?.kind === 'disconnect' ? 'Disconnect' : 'Re-read from the start'}
            </Button>
          </>
        }
      >
        <p className="text-small text-fg-2">
          {danger?.kind === 'disconnect'
            ? 'Syncing stops and the stored token is deleted. What is already in memory stays in the graph.'
            : 'The next sync reads this source from the start of its history window. Existing nodes are updated, not duplicated.'}
        </p>
      </Dialog>
    </PageFrame>
  )
}
