// FIXTURE: recorded-style test data for development and tests only; never used in production builds.
/**
 * The fixture engine: an in-memory Actron API used by MSW in the browser (handlers.ts) and by server components
 * (router.ts) when NEXT_PUBLIC_ACTRON_DEV_FIXTURES=1.
 *
 * Scenarios (URL `?fixture=<name>`, remembered in sessionStorage `actron.fixture`):
 *   default      nine Calva requests in every state, connected sources, a live request that investigates when opened
 *   empty        first run: nothing connected, no requests, zero graph counts, no notifications
 *   backend-down every /api route except /api/me answers 503 `unavailable`
 *   stream-drop  each SSE stream errors after its first two events, then resumes from Last-Event-ID
 *
 * Speed: live gaps are 500–900 ms multiplied by `window.__actronFixtureSpeed` (default 1; e2e uses 0.05).
 * The Slack approval of the "nothing found" request at the tenth workspace tick can be turned off with
 * `window.__actronFixtureSlackApproval = false`.
 */
import type {
  ActionResult,
  ConnectionView,
  EventEnvelope,
  NotificationItem,
  Provider,
  RequestDetail,
  RevisionDiff,
  Settings,
  State,
  TicketContent,
} from '@/lib/api/types'
import { isFinal } from '@/lib/states'
import { FIXTURE_IDS } from '../data/ids'
import { recordedHistory } from '../data/history'
import { deriveDetail, recordFor, summaryOf, type RequestRecord } from '../data/derive'
import {
  answerReadySteps,
  answerStep,
  approvalStep,
  buildSteps,
  cancelSteps,
  createdSteps,
  envelope,
  investigationSteps,
  prApprovalSteps,
  questionSteps,
  state as stateStep,
  ticketHash,
  ticketSteps,
  type Step,
} from '../data/lifecycle'
import { answeredSpec, nothingSpec, reqNode } from '../data/requests'
import { ME, PEOPLE } from '../data/people'
import type { RequestSpec } from '../data/spec'
import {
  connectionsFixture,
  graphStatsFixture,
  healthFixture,
  ingestionFixture,
  notificationsFixture,
  runsFixture,
  sampleFixture,
  settingsFixture,
} from '../data/workspace'
import { neighbours, nodeDetail, search, shortestPath, subgraphFor } from '../data/graphs'
import { buildLogFor, prDiffFor } from '../data/pr'
import { CATALOG_LINKS } from '../data/graph-catalog'
import { clone } from '../data/util'

export type Scenario = 'default' | 'empty' | 'backend-down' | 'stream-drop'
export const SCENARIOS: Scenario[] = ['default', 'empty', 'backend-down', 'stream-drop']
export type TimerMode = 'real' | 'immediate' | 'none'

export interface FixtureResponse {
  status: number
  json: unknown
  /** True when `json` is a plain-text body (raw build logs). */
  text?: boolean
}

type Listener = (event: EventEnvelope) => void

declare global {
  interface Window {
    __actronFixtureSpeed?: number
    __actronFixtureSlackApproval?: boolean
  }
}

const STORAGE_KEY = 'actron.fixture'
export const WS_KEY = 'ws'

/** Request event types that also travel on the workspace stream (Home, inbox, footer, system view). */
const WS_FORWARD = new Set([
  'request.created',
  'request.state_changed',
  'approval.recorded',
  'question.asked',
  'ticket.synced',
  'build.failed',
  'pr.opened',
  'notification.sent',
  'tool.called',
  'tool.result',
  'judgment.made',
  'handoff.created',
  'build.step',
  'tests.result',
  'writeback.done',
])

export function detectScenario(): Scenario {
  if (typeof window === 'undefined') return 'default'
  try {
    const fromUrl = new URLSearchParams(window.location.search).get('fixture')
    if (fromUrl && (SCENARIOS as string[]).includes(fromUrl)) {
      window.sessionStorage.setItem(STORAGE_KEY, fromUrl)
      return fromUrl as Scenario
    }
    const stored = window.sessionStorage.getItem(STORAGE_KEY)
    if (stored && (SCENARIOS as string[]).includes(stored)) return stored as Scenario
  } catch {
    // Storage blocked: fall back to the default scenario.
  }
  return 'default'
}

function speed(): number {
  const value = typeof window !== 'undefined' ? window.__actronFixtureSpeed : undefined
  return typeof value === 'number' && value >= 0 ? value : 1
}

const ok = (json: unknown, status = 200): FixtureResponse => ({ status, json })
const err = (status: number, code: string, message: string): FixtureResponse => ({ status, json: { error: { code, message } } })

const result = (status: ActionResult['status'], detailState: State, reason: string | null = null, eventId: number | null = null) => ({
  result: { status, reason, eventId, state: detailState },
})

export interface EngineOptions {
  scenario?: Scenario
  timers?: TimerMode
}

export class FixtureEngine {
  readonly scenario: Scenario
  readonly timers: TimerMode
  private records = new Map<string, RequestRecord>()
  private workspaceEvents: EventEnvelope[] = []
  private listeners = new Map<string, Set<Listener>>()
  private queues = new Map<string, Step[]>()
  private running = new Set<string>()
  private nextId = 9000
  private created = 0
  private connections: ConnectionView[]
  private notifications: NotificationItem[]
  private settings: Settings
  private streamOpens = new Map<string, number>()
  private liveStarted = false
  private wsTicker: ReturnType<typeof setInterval> | null = null
  private tick = 0
  private lastAt = 0

  constructor(options: EngineOptions = {}) {
    this.scenario = options.scenario ?? 'default'
    this.timers = options.timers ?? 'real'
    const empty = this.scenario === 'empty'
    this.connections = empty ? [] : connectionsFixture()
    this.notifications = empty ? [] : notificationsFixture()
    this.settings = settingsFixture()
    if (!empty) {
      for (const [id, { spec, events }] of recordedHistory()) {
        this.records.set(id, recordFor(spec, events))
      }
      // The live request was asked a moment ago.
      const live = this.records.get(FIXTURE_IDS.live)
      if (live) {
        const base = Date.now() - 40_000
        live.events.forEach((e, i) => (e.at = new Date(base + i * 2000).toISOString()))
        live.spec = { ...live.spec, createdAt: live.events[0]?.at ?? live.spec.createdAt }
      }
      this.workspaceEvents = [
        this.wsEvent('ingestion.started', { source: 'slack', mode: 'backfill', runId: 'run_fixture_slack' }, -1800),
        this.wsEvent('ingestion.partial', { source: 'linear', runId: 'run_fixture_linear', reason: 'Linear rate limit reached at 1,800 issues; the rest arrives at 14:00 UTC.' }, -1500),
        this.wsEvent('ingestion.finished', { source: 'github', runId: 'run_fixture_github', status: 'done', counts: { GitCommit: 4, CodeFunction: 11 }, durationMs: 41_000 }, -120),
      ]
    }
  }

  /* ------------------------------------------------------------ events */

  private now(): string {
    const t = Math.max(Date.now(), this.lastAt + 1)
    this.lastAt = t
    return new Date(t).toISOString()
  }

  private wsEvent(type: string, payload: Record<string, unknown>, offsetSeconds = 0): EventEnvelope {
    const at = offsetSeconds ? new Date(Date.now() + offsetSeconds * 1000).toISOString() : this.now()
    return { id: this.nextId++, requestId: null, seq: null, type, at, actor: 'actron', surface: 'system', payload }
  }

  private publish(key: string, event: EventEnvelope): void {
    for (const listener of this.listeners.get(key) ?? []) listener(event)
  }

  private pushWorkspace(event: EventEnvelope): void {
    this.workspaceEvents.push(event)
    if (this.workspaceEvents.length > 300) this.workspaceEvents.splice(0, this.workspaceEvents.length - 300)
    this.publish(WS_KEY, event)
  }

  /** Appends one step to a request's log and publishes it. */
  emit(requestId: string, step: Step): EventEnvelope | null {
    const record = this.records.get(requestId)
    if (!record) return null
    const event = envelope(requestId, step, record.events.length + 1, this.nextId++, this.now())
    record.events.push(event)
    this.publish(requestId, event)
    if (WS_FORWARD.has(event.type)) this.pushWorkspace(event)
    return event
  }

  /** Plays steps in order: at once in tests, with 500–900 ms gaps (× speed) in the browser. */
  script(requestId: string, steps: Step[]): void {
    if (this.timers !== 'real') {
      for (const s of steps) this.emit(requestId, s)
      return
    }
    const queue = this.queues.get(requestId) ?? []
    queue.push(...steps)
    this.queues.set(requestId, queue)
    if (this.running.has(requestId)) return
    this.running.add(requestId)
    let i = 0
    const next = () => {
      const q = this.queues.get(requestId) ?? []
      const step = q.shift()
      if (!step) {
        this.running.delete(requestId)
        return
      }
      this.emit(requestId, step)
      i += 1
      setTimeout(next, (500 + ((i * 137) % 400)) * speed())
    }
    setTimeout(next, 500 * speed())
  }

  detail(id: string): RequestDetail | null {
    const record = this.records.get(id)
    return record ? deriveDetail(record) : null
  }

  events(id: string): EventEnvelope[] {
    return this.records.get(id)?.events ?? []
  }

  /* ------------------------------------------------------------ streams */

  /** Replays events after `lastEventId`, then calls `listener` for each new one. */
  subscribe(key: string, lastEventId: number | null, listener: Listener): { replay: EventEnvelope[]; unsubscribe: () => void } {
    const log = key === WS_KEY ? this.workspaceEvents : this.events(key)
    const after = lastEventId ?? -Infinity
    const replay = log.filter((e) => (key === WS_KEY ? e.id : (e.seq ?? e.id)) > after)
    const set = this.listeners.get(key) ?? new Set<Listener>()
    set.add(listener)
    this.listeners.set(key, set)
    return { replay, unsubscribe: () => set.delete(listener) }
  }

  hasStream(key: string): boolean {
    return key === WS_KEY || this.records.has(key)
  }

  /** Counts stream opens; in `stream-drop` the first open of each stream errors after two events. */
  openStream(key: string): { dropAfter: number | null } {
    const n = (this.streamOpens.get(key) ?? 0) + 1
    this.streamOpens.set(key, n)
    if (key === FIXTURE_IDS.live) this.startLive()
    if (key === WS_KEY) this.startWorkspaceTicker()
    return { dropAfter: this.scenario === 'stream-drop' && n === 1 ? 2 : null }
  }

  /** The live request investigates once someone watches it. */
  startLive(): void {
    if (this.liveStarted || this.timers === 'none') return
    const record = this.records.get(FIXTURE_IDS.live)
    if (!record || record.events.length !== 2) return
    this.liveStarted = true
    this.script(FIXTURE_IDS.live, [...investigationSteps(record.spec), ...questionSteps(record.spec)])
  }

  private startWorkspaceTicker(): void {
    if (this.wsTicker || this.timers !== 'real' || this.scenario === 'empty') return
    this.wsTicker = setInterval(() => this.workspaceTick(), Math.max(50, 2000 * speed()))
  }

  /** One workspace tick: Slack backfill progress, linking progress, and once a Slack approval. */
  workspaceTick(): void {
    this.tick += 1
    const slack = this.connections.find((c) => c.provider === 'slack')
    if (slack && slack.sync.state === 'BACKFILLING') {
      const counts = slack.sync.counts
      counts.SlackMessage = (counts.SlackMessage ?? 0) + 120
      counts.SlackUser = Math.min(240, (counts.SlackUser ?? 0) + 1)
      slack.updatedAt = this.now()
      this.pushWorkspace(this.wsEvent('ingestion.progress', { source: 'slack', runId: 'run_fixture_slack', counts: { ...counts }, perMinute: slack.sync.perMinute, phase: 'messages' }))
      if (this.tick % 4 === 0) {
        this.pushWorkspace(this.wsEvent('linking.progress', { runId: 'run_fixture_slack', step: 'references', done: 2900 + this.tick * 12, total: 3334 }))
      }
      if (this.tick >= 30) {
        slack.sync = { ...slack.sync, state: 'UP TO DATE', lastSyncedAt: this.now(), perMinute: 0 }
        this.pushWorkspace(this.wsEvent('ingestion.finished', { source: 'slack', runId: 'run_fixture_slack', status: 'done', counts: { ...counts }, durationMs: 1_860_000 }))
        this.pushWorkspace(
          this.wsEvent('linking.finished', {
            runId: 'run_fixture_slack',
            counts: { references_resolved: 3294, pending: 40, decisions: 38, identities: 46, links_kept: 9410, links_dropped: 612 },
          }),
        )
      }
    }
    const slackApproval = typeof window === 'undefined' || window.__actronFixtureSlackApproval !== false
    if (this.tick === 10 && slackApproval && this.scenario === 'default') {
      const nothing = this.detail(FIXTURE_IDS.nothing)
      if (nothing?.state === 'Awaiting approval' && nothing.currentRevision) {
        this.emit(FIXTURE_IDS.nothing, approvalStep('ticket', nothing.currentRevision.hash, 'sam', 'slack'))
        this.script(FIXTURE_IDS.nothing, buildSteps(this.records.get(FIXTURE_IDS.nothing)?.spec ?? nothingSpec))
      }
    }
  }

  stop(): void {
    if (this.wsTicker) clearInterval(this.wsTicker)
    this.wsTicker = null
  }

  /* ------------------------------------------------------------ actions */

  private personMe() {
    return 'dana' as const
  }

  private createRequest(text: string, kindHint: string | undefined): FixtureResponse {
    const trimmed = text.trim()
    if (trimmed.length < 3 || trimmed.length > 4000) return err(422, 'validation_error', 'Write the request in 3 to 4,000 characters.')
    const question = kindHint === 'question' || (!kindHint && /^(why|how|what|where|who|when)\b|\?$/i.test(trimmed))
    const kind = question ? 'question' : kindHint === 'bug' || /\b(fix|bug|broken|crash|error)\b/i.test(trimmed) ? 'bug' : 'feature'
    this.created += 1
    const id = `req_01JCALVA0NEW${String(this.created).padStart(11, '0')}`
    const base = question ? answeredSpec : nothingSpec
    const spec = JSON.parse(JSON.stringify(base).split(base.id).join(id)) as RequestSpec
    spec.title = trimmed.split('\n')[0]?.slice(0, 90) ?? trimmed
    spec.text = trimmed
    spec.kind = kind
    spec.source = 'ui'
    spec.requester = this.personMe()
    spec.createdAt = this.now()
    spec.slack = null
    if (spec.build) spec.build.buildId = `bld_new_${this.created}`
    if (spec.pr) spec.pr = { ...spec.pr, number: 20 + this.created }
    const record = recordFor(spec, [])
    this.records.set(id, record)
    for (const s of createdSteps(spec)) this.emit(id, s)
    const rest = question
      ? [...investigationSteps(spec), ...answerReadySteps(spec)]
      : [...investigationSteps(spec), ...ticketSteps(spec, 1, 'Investigating')]
    if (this.timers !== 'none') this.script(id, rest)
    return ok({ request: this.detail(id) }, 201)
  }

  private answer(id: string, body: { questionId?: string; value?: string }): FixtureResponse {
    const detail = this.detail(id)
    if (!detail) return err(404, 'not_found', 'This request is not in Actron.')
    if (detail.state !== 'Needs your input') return err(409, 'invalid_transition', 'This request is not waiting for answers.')
    const q = detail.questions.find((x) => x.questionId === body.questionId)
    if (!q) return err(422, 'validation_error', 'Unknown question.')
    if (!body.value) return err(422, 'validation_error', 'An answer is required.')
    if (q.answer) return ok(result('duplicate', detail.state))
    const event = this.emit(id, answerStep(q.questionId, body.value, this.personMe(), 'ui'))
    const after = this.detail(id) as RequestDetail
    if (after.questions.every((x) => !x.required || x.answer)) {
      const record = this.records.get(id) as RequestRecord
      const branch = after.questions.find((x) => x.questionId.endsWith('branch'))?.answer?.value
      const first = record.contents.get(1)
      if (first && branch) {
        const target = branch.startsWith('new:') ? branch.slice(4) : branch
        record.contents.set(1, { ...first, content: { ...first.content, targetBranch: target } })
      }
      this.script(id, ticketSteps(record.spec, 1, 'Needs your input', 'Actron', record.contents.get(1)?.content))
    }
    return ok(result('accepted', after.state, null, event?.id ?? null))
  }

  private approve(id: string, body: { kind?: string; revisionHash?: string; headSha?: string }): FixtureResponse {
    const detail = this.detail(id)
    const record = this.records.get(id)
    if (!detail || !record) return err(404, 'not_found', 'This request is not in Actron.')
    if (body.kind === 'ticket') {
      if (detail.state !== 'Awaiting approval') return err(409, 'invalid_transition', 'There is no ticket waiting for approval.')
      const current = detail.currentRevision
      if (!current || body.revisionHash !== current.hash) {
        this.emit(id, { type: 'approval.refused', payload: { kind: 'ticket', target: body.revisionHash ?? '', reason: 'stale_revision', by: { personId: PEOPLE.dana.personId, name: PEOPLE.dana.name }, surface: 'ui' }, actor: 'person', surface: 'ui' })
        return err(409, 'stale_revision', `The ticket changed. v${current?.n ?? '?'} is the current revision; review it and approve again.`)
      }
      const event = this.emit(id, approvalStep('ticket', current.hash, this.personMe(), 'ui'))
      if (record.spec.build) {
        this.script(id, buildSteps(record.spec))
      } else {
        this.script(id, [
          stateStep('Awaiting approval', 'Building', 'ticket_approved'),
          { type: 'handoff.created', payload: { investigationId: `inv_${id}`, buildId: `bld_${id.slice(-4)}_${current.n}`, evidenceCount: detail.evidence.length } },
          { type: 'build.queued', payload: { buildId: `bld_${id.slice(-4)}_${current.n}`, position: 1 } },
        ])
      }
      return ok(result('accepted', 'Building', null, event?.id ?? null))
    }
    if (body.kind === 'pr') {
      if (detail.state !== 'PR ready for review' || !detail.pr) return err(409, 'invalid_transition', 'There is no pull request waiting for review.')
      if (body.headSha !== detail.pr.headSha) {
        this.emit(id, { type: 'approval.refused', payload: { kind: 'pr', target: body.headSha ?? '', reason: 'stale_head', by: { personId: PEOPLE.dana.personId, name: PEOPLE.dana.name }, surface: 'ui' }, actor: 'person', surface: 'ui' })
        return err(409, 'stale_head', `The pull request has a newer head (${detail.pr.headSha.slice(0, 7)}). Review it and approve again.`)
      }
      const spec = { ...record.spec, pr: record.spec.pr ? { ...record.spec.pr, headSha: detail.pr.headSha } : undefined }
      const [first, ...rest] = prApprovalSteps(spec, this.personMe(), 'ui')
      const event = first ? this.emit(id, first) : null
      this.script(id, rest)
      return ok(result('accepted', 'Done', null, event?.id ?? null))
    }
    return err(422, 'validation_error', 'kind must be ticket or pr.')
  }

  private revise(id: string, body: { content?: TicketContent }): FixtureResponse {
    const detail = this.detail(id)
    const record = this.records.get(id)
    if (!detail || !record) return err(404, 'not_found', 'This request is not in Actron.')
    if (!['Ticket ready', 'Awaiting approval', 'Needs attention'].includes(detail.state)) {
      return err(409, 'invalid_transition', 'The ticket can be edited only before the build or after it stops.')
    }
    if (!body.content || typeof body.content.objective !== 'string') return err(422, 'validation_error', 'The ticket content is missing.')
    const n = (detail.currentRevision?.n ?? 0) + 1
    record.contents.set(n, { content: body.content, by: PEOPLE.dana.name })
    const steps = ticketSteps(record.spec, n, detail.state, PEOPLE.dana.name, body.content)
    let first: EventEnvelope | null = null
    for (const s of steps) first = first ?? this.emit(id, s)
    const after = this.detail(id) as RequestDetail
    return ok({ ...result('accepted', after.state, null, first?.id ?? null), revision: after.revisions[after.revisions.length - 1] })
  }

  private revisionsOf(id: string): FixtureResponse {
    const detail = this.detail(id)
    if (!detail) return err(404, 'not_found', 'This request is not in Actron.')
    const diffs: RevisionDiff[] = []
    for (let i = 1; i < detail.revisions.length; i++) {
      const a = detail.revisions[i - 1]
      const b = detail.revisions[i]
      if (!a || !b) continue
      const changes = (Object.keys(b.content) as (keyof TicketContent)[])
        .filter((field) => JSON.stringify(a.content[field]) !== JSON.stringify(b.content[field]))
        .map((field) => ({ field, before: a.content[field], after: b.content[field] }))
      diffs.push({ from: a.n, to: b.n, changes })
    }
    return ok({ revisions: detail.revisions, diffs })
  }

  private lifecycle(id: string, action: 'cancel' | 'retry' | 'close-pr' | 'feedback', body: Record<string, unknown>): FixtureResponse {
    const detail = this.detail(id)
    const record = this.records.get(id)
    if (!detail || !record) return err(404, 'not_found', 'This request is not in Actron.')
    const me = { personId: PEOPLE.dana.personId, name: PEOPLE.dana.name }
    if (action === 'cancel') {
      if (isFinal(detail.state)) return err(409, 'invalid_transition', 'This request has already finished.')
      const steps = cancelSteps(detail.state, this.personMe(), 'ui', typeof body.reason === 'string' && body.reason ? body.reason : 'cancelled in Actron')
      const first = this.emit(id, steps[0] as Step)
      for (const s of steps.slice(1)) this.emit(id, s)
      return ok(result('accepted', 'Cancelled', null, first?.id ?? null))
    }
    if (action === 'retry') {
      if (detail.state !== 'Needs attention') return err(409, 'invalid_transition', 'Only a stopped request can be retried.')
      const buildId = `bld_retry_${record.events.length}`
      const first = this.emit(id, stateStep('Needs attention', 'Building', 'retry'))
      this.script(id, [
        { type: 'build.queued', payload: { buildId, position: 1 } },
        { type: 'build.started', payload: { buildId, branch: record.spec.build?.branch ?? `actron/${id.slice(-6).toLowerCase()}`, baseSha: record.spec.build?.baseSha ?? 'a41c9e27b3d0f5e1c8a24f6b9d0e3c7a15b2f8d4' } },
        { type: 'build.step', payload: { buildId, step: 'read', text: 'Reading the ticket and the earlier attempts' } },
      ])
      return ok(result('accepted', 'Building', null, first?.id ?? null))
    }
    if (action === 'close-pr') {
      if (detail.state !== 'PR ready for review') return err(409, 'invalid_transition', 'There is no open pull request to close.')
      const first = this.emit(id, { type: 'request.cancelled', payload: { reason: typeof body.reason === 'string' ? body.reason : 'pull request closed', by: me }, actor: 'person', surface: 'ui' })
      this.emit(id, stateStep('PR ready for review', 'Cancelled', 'pr_closed'))
      this.emit(id, { type: 'request.done', payload: { outcome: 'closed' } })
      return ok(result('accepted', 'Cancelled', null, first?.id ?? null))
    }
    // feedback
    if (detail.state !== 'PR ready for review' || !detail.pr) return err(409, 'invalid_transition', 'There is no pull request to give feedback on.')
    if (typeof body.text !== 'string' || body.text.trim().length < 3) return err(422, 'validation_error', 'Write the feedback in a few words.')
    if (body.headSha !== detail.pr.headSha) return err(409, 'stale_head', 'The pull request has a newer head. Reload and try again.')
    const buildId = record.spec.build?.buildId ?? 'bld_feedback'
    const newHead = `${detail.pr.headSha.slice(0, 32)}fb${String(record.events.length).padStart(6, '0')}`
    const first = this.emit(id, { type: 'review.feedback', payload: { kind: 'code_change_within_scope', text: body.text, by: me, surface: 'ui' }, actor: 'person', surface: 'ui' })
    this.emit(id, stateStep('PR ready for review', 'Changes requested', 'feedback'))
    this.script(id, [
      { type: 'build.step', payload: { buildId, step: 'feedback', text: 'Applying the review feedback on the same branch' } },
      { type: 'tests.result', payload: { buildId, passed: 14, failed: 0, skipped: 0, failing: [] } },
      { type: 'build.passed', payload: { buildId, headSha: newHead } },
      { type: 'pr.updated', payload: { number: detail.pr.number, headSha: newHead } },
      stateStep('Changes requested', 'PR ready for review', 'rebuilt'),
    ])
    return ok(result('accepted', 'Changes requested', null, first?.id ?? null))
  }

  /* ------------------------------------------------------------ router */

  route(method: string, rawUrl: string, body?: unknown): FixtureResponse {
    const url = new URL(rawUrl, 'http://fixture.local')
    const path = url.pathname.replace(/\/$/, '')
    const q = url.searchParams
    const b = (body && typeof body === 'object' ? body : {}) as Record<string, unknown>
    const M = method.toUpperCase()

    if (path === '/api/me' && M === 'GET') return ok(ME)
    if (this.scenario === 'backend-down') return err(503, 'unavailable', 'Actron could not reach the API. Retry in a moment.')

    // Auth
    if (path === '/api/auth/dev-login' && M === 'POST') return ok({ user: PEOPLE.dana, workspace: { id: ME.workspace.id, name: ME.workspace.name } })
    if (path === '/api/auth/logout' && M === 'POST') return ok(undefined, 204)
    if (path === '/api/auth/slack/start') return err(404, 'not_configured', 'Slack sign-in is not configured in this environment.')
    if (path === '/api/health') return ok(healthFixture())

    // Connections and ingestion
    if (path === '/api/connections' && M === 'GET') return ok({ connections: this.connections })
    if (path === '/api/connections' && M === 'POST') return this.connect(b)
    let m = /^\/api\/connections\/([^/]+)(\/sync|\/reset-cursor)?$/.exec(path)
    if (m) {
      const c = this.connections.find((x) => x.id === m?.[1])
      if (!c) return err(404, 'not_found', 'This connection does not exist.')
      if (!m[2] && M === 'DELETE') {
        this.connections = this.connections.filter((x) => x !== c)
        return ok(undefined, 204)
      }
      if (!m[2] && M === 'PATCH') {
        const patch = (b.config ?? {}) as Record<string, unknown>
        const reingest = 'workingBranch' in patch && patch.workingBranch !== c.config.workingBranch
        c.config = { ...c.config, ...patch }
        c.updatedAt = this.now()
        if (reingest) c.sync = { ...c.sync, state: 'BACKFILLING', reason: null }
        return ok(reingest ? { connection: c, reingest: true } : { connection: c })
      }
      if (m[2] === '/sync' && M === 'POST') {
        c.sync = { ...c.sync, state: c.sync.state === 'BACKFILLING' ? 'BACKFILLING' : 'SYNCING' }
        this.pushWorkspace(this.wsEvent('ingestion.started', { source: c.provider, mode: 'incremental', runId: `run_${c.provider}_${this.nextId}` }))
        return ok({ triggered: true }, 202)
      }
      if (m[2] === '/reset-cursor' && M === 'POST') return ok({ connection: c })
    }
    if (path === '/api/ingestion/status') return ok(ingestionFixture(this.connections, this.scenario === 'empty'))
    if (path === '/api/ingestion/runs') {
      const source = q.get('source')
      const runs = this.scenario === 'empty' ? [] : runsFixture().filter((r) => !source || r.source === source)
      return ok({ runs: runs.slice(0, Number(q.get('limit') ?? 20)) })
    }

    // Requests
    if ((path === '/api/requests' || path === '/api/ask') && M === 'POST') {
      return this.createRequest(String(b.text ?? ''), path === '/api/ask' ? 'question' : typeof b.kindHint === 'string' ? b.kindHint : undefined)
    }
    if (path === '/api/requests' && M === 'GET') return ok(this.list(q.get('group'), Number(q.get('limit') ?? 50)))
    m = /^\/api\/requests\/([^/]+)(\/.*)?$/.exec(path)
    if (m) {
      const id = m[1] as string
      const sub = m[2] ?? ''
      if (!this.records.has(id)) return err(404, 'not_found', 'This request is not in Actron.')
      if (sub === '' && M === 'GET') return ok({ request: this.detail(id) })
      if (sub === '/replay' && M === 'GET') {
        const d = this.detail(id) as RequestDetail
        if (!isFinal(d.state)) return err(409, 'not_finished', 'This request is still running. Replays open when it is done.')
        return ok({ request: d, events: this.events(id) })
      }
      if (sub === '/answers' && M === 'POST') return this.answer(id, b as { questionId?: string; value?: string })
      if (sub === '/approvals' && M === 'POST') return this.approve(id, b as { kind?: string })
      if (sub === '/ticket/revisions' && M === 'POST') return this.revise(id, b as { content?: TicketContent })
      if (sub === '/ticket/revisions' && M === 'GET') return this.revisionsOf(id)
      if (sub === '/cancel' && M === 'POST') return this.lifecycle(id, 'cancel', b)
      if (sub === '/retry' && M === 'POST') return this.lifecycle(id, 'retry', b)
      if (sub === '/close-pr' && M === 'POST') return this.lifecycle(id, 'close-pr', b)
      if (sub === '/feedback' && M === 'POST') return this.lifecycle(id, 'feedback', b)
      if (sub === '/pr/diff' && M === 'GET') {
        const d = this.detail(id) as RequestDetail
        if (!d.pr) return err(404, 'not_found', 'This request has no pull request yet.')
        const diff = prDiffFor((this.records.get(id) as RequestRecord).spec)
        return ok({ files: diff.files, headSha: d.pr.headSha })
      }
      const logMatch = /^\/builds\/([^/]+)\/log$/.exec(sub)
      if (logMatch && M === 'GET') {
        const record = this.records.get(id) as RequestRecord
        if (!record.spec.build || record.spec.build.buildId !== logMatch[1]) return err(404, 'not_found', 'No log for this build.')
        return { status: 200, json: buildLogFor(record.spec), text: true }
      }
    }
    m = /^\/api\/public\/replays\/([^/]+)$/.exec(path)
    if (m) {
      const d = this.detail(m[1] as string)
      if (!this.settings.allowPublicReplays || !d || !isFinal(d.state)) return err(404, 'not_found', 'This replay is not public.')
      const redacted: RequestDetail = { ...d, slack: null, requester: { ...d.requester, avatarUrl: null, userId: null } }
      return ok({ request: redacted, events: this.events(d.id) })
    }

    // Graph
    if (path === '/api/graph/subgraph') {
      const id = q.get('requestId') ?? ''
      const record = this.records.get(id)
      if (!record) return err(404, 'not_found', 'This request is not in Actron.')
      return ok(subgraphFor(record.spec, record.events, q.get('mode') === 'expanded' ? 'expanded' : 'aggregated'))
    }
    if (path === '/api/graph/stats') return ok(graphStatsFixture(this.scenario === 'empty'))
    if (path === '/api/graph/sample') return ok(this.scenario === 'empty' ? { mode: 'expanded', nodes: [], links: [], truncated: false } : sampleFixture(Math.min(3000, Number(q.get('limit') ?? 3000))))
    if (path === '/api/graph/search') {
      if (this.scenario === 'empty') return ok({ results: [] })
      return ok({ results: search(q.get('q') ?? '', q.get('types') ?? undefined, Math.min(50, Number(q.get('limit') ?? 20))) })
    }
    if (path === '/api/graph/path') {
      return ok(shortestPath(q.get('from') ?? '', q.get('to') ?? '', Math.min(6, Number(q.get('maxHops') ?? 6))))
    }
    m = /^\/api\/graph\/nodes\/(.+?)(\/neighbours)?$/.exec(path)
    if (m) {
      const id = decodeURIComponent(m[1] as string)
      if (m[2]) {
        const sub = neighbours(id, q.get('types') ?? undefined, Math.min(100, Number(q.get('limit') ?? 50)))
        return sub ? ok(sub) : err(404, 'not_found', 'This node is not in memory.')
      }
      const d = nodeDetail(id)
      return d ? ok(d) : err(404, 'not_found', 'This node is not in memory.')
    }
    m = /^\/api\/graph\/quick\/([a-z_]+)$/.exec(path)
    if (m) return ok(this.quick(m[1] as string, (q.get('ids') ?? '').split(',').filter(Boolean)))

    // Notifications and settings
    if (path === '/api/notifications' && M === 'GET') {
      const unreadOnly = q.get('unread') === '1'
      const list = this.notifications.filter((n) => !unreadOnly || !n.readAt)
      return ok({ notifications: list, unread: this.notifications.filter((n) => !n.readAt).length })
    }
    m = /^\/api\/notifications\/([^/]+)\/read$/.exec(path)
    if (m && M === 'POST') {
      const n = this.notifications.find((x) => x.id === m?.[1])
      if (!n) return err(404, 'not_found', 'This notification does not exist.')
      n.readAt = n.readAt ?? this.now()
      return ok(undefined, 204)
    }
    if (path === '/api/settings' && M === 'GET') return ok({ settings: this.settings })
    if (path === '/api/settings' && M === 'PUT') {
      const t = (b.thresholds ?? {}) as Record<string, unknown>
      if (Object.values(t).some((v) => typeof v !== 'number' || v < 0 || v > 1)) return err(422, 'validation_error', 'Thresholds are numbers between 0 and 1.')
      this.settings = { ...this.settings, ...(b as Partial<Settings>), thresholds: { ...this.settings.thresholds, ...(t as Partial<Settings['thresholds']>) } }
      return ok({ settings: this.settings })
    }
    if (path === '/api/settings/budget' && M === 'POST') {
      const cap = Number(b.capUsd)
      if (!Number.isFinite(cap) || cap <= 0) return err(422, 'validation_error', 'The cap must be a positive number of dollars.')
      this.settings = { ...this.settings, budget: { ...this.settings.budget, capUsd: cap } }
      return ok({ settings: this.settings })
    }
    return err(404, 'not_found', `No fixture for ${M} ${path}.`)
  }

  private connect(b: Record<string, unknown>): FixtureResponse {
    const provider = String(b.provider ?? '') as Provider
    if (!['github', 'code', 'slack', 'linear', 'slack_export'].includes(provider)) return err(422, 'validation_error', 'Unknown provider.')
    if (this.connections.some((c) => c.provider === provider)) return err(409, 'already_connected', 'This source is already connected.')
    const secret = Object.values((b.secret ?? {}) as Record<string, string>).find((v) => typeof v === 'string' && v.length >= 4)
    const now = this.now()
    const connection: ConnectionView = {
      id: `conn_fixture_${provider}`,
      provider,
      status: 'connected',
      config: (b.config ?? {}) as Record<string, unknown>,
      secretLast4: secret ? secret.slice(-4) : null,
      createdAt: now,
      updatedAt: now,
      sync: { state: 'BACKFILLING', lastSyncedAt: null, reason: null, perMinute: 0, counts: {} },
    }
    this.connections.push(connection)
    this.pushWorkspace(this.wsEvent('ingestion.started', { source: provider, mode: 'backfill', runId: `run_fixture_${provider}` }))
    return ok({ connection, runId: `run_fixture_${provider}` }, 201)
  }

  private list(group: string | null, limit: number) {
    const all = [...this.records.keys()]
      .map((id) => this.detail(id) as RequestDetail)
      .sort((a, b) => (a.updatedAt < b.updatedAt ? 1 : -1))
    const needsYou = all.filter((d) => d.needsYou).sort((a, b) => (a.updatedAt < b.updatedAt ? -1 : 1))
    const running = all.filter((d) => !d.needsYou && !isFinal(d.state))
    const done = all.filter((d) => isFinal(d.state)).slice(0, 20)
    const chosen = group === 'needs_you' ? needsYou : group === 'running' ? running : group === 'done' ? done : [...needsYou, ...running, ...done]
    return { requests: chosen.slice(0, limit).map(summaryOf), counts: { needsYou: needsYou.length, running: running.length, done: done.length } }
  }

  private quick(tool: string, ids: string[]): unknown {
    const set = new Set(ids)
    switch (tool) {
      case 'callers':
        return CATALOG_LINKS.filter((l) => l.type === 'CALLS' && set.has(l.to)).map((l) => ({ id: l.from, label: l.from.split('#').pop(), depth: 1, callSiteLines: [], confidence: l.confidence }))
      case 'tests_for':
        return CATALOG_LINKS.filter((l) => l.type === 'TESTS' && set.has(l.to)).map((l) => ({ testId: l.from, label: l.from.split('#').pop(), method: l.method, confidence: l.confidence }))
      case 'owners':
        return CATALOG_LINKS.filter((l) => l.type === 'KNOWS_ABOUT' && set.has(l.to)).map((l) => ({
          personId: l.from,
          name: Object.values(PEOPLE).find((p) => p.personId === l.from)?.name ?? l.from,
          basis: ['blame'],
          score: l.confidence,
        }))
      case 'decisions_for':
        return CATALOG_LINKS.filter((l) => l.type === 'CONSTRAINS' && set.has(l.to)).map((l) => ({ decisionId: l.from, confidence: l.confidence }))
      case 'shortest_path':
        return shortestPath(ids[0] ?? '', ids[1] ?? '', 6)
      default:
        return []
    }
  }

  /** Test helper: the current hash for a request's ticket. */
  currentHash(id: string): string | null {
    return this.detail(id)?.currentRevision?.hash ?? null
  }

  static ticketHash = ticketHash
  static requestNodeId = reqNode
  static clone = clone
}

let browserEngine: FixtureEngine | null = null

/** The browser's engine, created once per page load for the detected scenario. */
export function getEngine(): FixtureEngine {
  if (!browserEngine) browserEngine = new FixtureEngine({ scenario: detectScenario(), timers: 'real' })
  return browserEngine
}

export function resetEngine(): void {
  browserEngine?.stop()
  browserEngine = null
}
