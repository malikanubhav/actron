/**
 * Helpers for the full-stack e2e suite (PROMPT 9.6). The stack is `scripts/e2e_stack.sh`: the real frontend,
 * backend and worker against fake Slack, GitHub and Linear servers (backend/tests/e2e_stack/). The control API
 * (:18100) reads what the fakes recorded and injects provider failures. Test data only.
 */
import { createHmac, randomUUID } from 'node:crypto'
import { expect, request, type APIRequestContext, type Page } from '@playwright/test'

export const FRONTEND = process.env.E2E_STACK_URL ?? 'http://127.0.0.1:3300'
export const BACKEND = process.env.E2E_STACK_BACKEND ?? 'http://127.0.0.1:18080'
export const CONTROL = process.env.E2E_STACK_CONTROL ?? 'http://127.0.0.1:18100'
/** The name the sign-in screen's Dev login uses; the API helper signs in as the same person. */
export const DEV_USER = 'Dev user'

export interface StackInfo {
  workspace: string
  slackTeam: string
  slackChannel: string
  requester: string
  approver: string
  signingSecret: string
  githubToken: string
  linearKey: string
  slackBotToken: string
  repo: string
  fork: string
}

let info: StackInfo | null = null
export async function stack(): Promise<StackInfo> {
  if (!info) info = (await (await fetch(`${CONTROL}/health`)).json()) as StackInfo
  return info
}

export async function control<T = Record<string, unknown>>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${CONTROL}${path}`, body === undefined ? undefined : {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`control ${path}: ${res.status}`)
  return (await res.json()) as T
}

export async function slackCalls(method: string): Promise<{ method: string; params: Record<string, unknown> }[]> {
  return (await control<{ calls: { method: string; params: Record<string, unknown> }[] }>(`/slack/calls?method=${method}`)).calls
}

/* ------------------------------------------------------------------ API client for setup and assertions */

export type Json = Record<string, unknown> & { [k: string]: unknown }

export class Api {
  private constructor(
    readonly ctx: APIRequestContext,
    private csrf: string,
  ) {}

  static async signIn(name = DEV_USER): Promise<Api> {
    const ctx = await request.newContext({ baseURL: BACKEND })
    const r = await ctx.post('/api/auth/dev-login', { data: { name } })
    expect(r.status(), await r.text()).toBe(200)
    const cookies = (await ctx.storageState()).cookies
    const csrf = cookies.find((c) => c.name === 'actron_csrf')?.value ?? ''
    return new Api(ctx, csrf)
  }

  private headers() {
    return { 'X-CSRF-Token': this.csrf, 'Idempotency-Key': randomUUID() }
  }

  async get<T = Json>(path: string): Promise<T> {
    const r = await this.ctx.get(path)
    expect(r.ok(), `${path}: ${r.status()} ${await r.text()}`).toBeTruthy()
    return (await r.json()) as T
  }

  async post(path: string, data: unknown = {}) {
    return this.ctx.post(path, { data, headers: this.headers() })
  }

  async delete(path: string) {
    return this.ctx.delete(path, { headers: this.headers() })
  }

  async request(id: string): Promise<RequestDetail> {
    return (await this.get<{ request: RequestDetail }>(`/api/requests/${id}`)).request
  }

  async connections(): Promise<{ id: string; provider: string; status: string; sync: { state: string; reason: string | null } }[]> {
    return (await this.get<{ connections: never[] }>('/api/connections')).connections
  }

  async createRequest(text: string, kindHint?: 'feature' | 'bug' | 'question'): Promise<string> {
    const r = await this.post('/api/requests', { text, ...(kindHint ? { kindHint } : {}) })
    expect(r.status(), await r.text()).toBe(201)
    return ((await r.json()) as { request: { id: string } }).request.id
  }

  /** Waits until the request reaches one of `states` (the worker runs the real workflow). */
  async waitFor(id: string, states: string[], timeout = 90_000): Promise<RequestDetail> {
    let last: RequestDetail | null = null
    await expect
      .poll(
        async () => {
          last = await this.request(id)
          return states.includes(last.state)
        },
        { timeout, intervals: [500, 1000] },
      )
      .toBe(true)
    return last as unknown as RequestDetail
  }

  /** Answers every open question with its first option (or a short text). */
  async answerAll(id: string): Promise<void> {
    const req = await this.request(id)
    for (const q of req.questions.filter((x) => !x.answer)) {
      const value = q.options[0]?.value ?? 'Keep the current behaviour.'
      const r = await this.post(`/api/requests/${id}/answers`, { questionId: q.questionId, value })
      expect(r.ok(), await r.text()).toBeTruthy()
    }
  }

  async approveTicket(id: string): Promise<void> {
    const req = await this.request(id)
    const r = await this.post(`/api/requests/${id}/approvals`, { kind: 'ticket', revisionHash: req.currentRevision?.hash })
    expect(r.ok(), await r.text()).toBeTruthy()
  }

  /** Runs a request to "Awaiting approval": answers the questions the investigation asks. */
  async toApproval(text: string): Promise<string> {
    const id = await this.createRequest(text, 'feature')
    const req = await this.waitFor(id, ['Needs your input', 'Awaiting approval', 'Ticket ready'])
    if (req.state === 'Needs your input') await this.answerAll(id)
    await this.waitFor(id, ['Awaiting approval'])
    return id
  }

  async dispose() {
    await this.ctx.dispose()
  }
}

export interface RequestDetail {
  id: string
  title: string
  state: string
  label: string | null
  questions: { questionId: string; text: string; options: { value: string; label: string }[]; answer: unknown }[]
  currentRevision: { n: number; hash: string } | null
  revisions: { n: number; hash: string; linear: { identifier: string } | null }[]
  approvals: { kind: string; status: string; surface: string; reason: string | null }[]
  builds: { id: string; status: string; attempts: number; testsPassed: number; testsFailed: number; report: Json | null }[]
  pr: { number: number; headSha: string; state: string } | null
  allowedActions: string[]
  outcome: string | null
  slack: { channel: string; threadTs: string } | null
  answer: { text: string } | null
}

/* ------------------------------------------------------------------ Slack (signed requests, as Slack sends them) */

function sign(secret: string, body: string, ts = Math.floor(Date.now() / 1000)) {
  const sig = 'v0=' + createHmac('sha256', secret).update(`v0:${ts}:${body}`).digest('hex')
  return { 'X-Slack-Request-Timestamp': String(ts), 'X-Slack-Signature': sig }
}

/** `/actron <text>` from a Slack user, signed with the e2e signing secret. Returns the HTTP status. */
export async function slackCommand(text: string, user?: string): Promise<number> {
  const s = await stack()
  const body = new URLSearchParams({
    token: 'unused', team_id: s.slackTeam, team_domain: 'northwind', channel_id: s.slackChannel, channel_name: 'eng',
    user_id: user ?? s.requester, user_name: 'dana', command: '/actron', text, api_app_id: 'A0001',
    trigger_id: `trig-${randomUUID()}`, response_url: `${CONTROL}/slack/respond`,
  }).toString()
  const res = await fetch(`${BACKEND}/slack/commands`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded', ...sign(s.signingSecret, body) },
    body,
  })
  return res.status
}

/** A button click in Slack (block_actions), e.g. `answer:<rid>:<qid>:<value>` or `approve_ticket:<rid>:<hash>`. */
export async function slackAction(actionId: string, user?: string): Promise<number> {
  const s = await stack()
  const payload = {
    type: 'block_actions', team: { id: s.slackTeam, domain: 'northwind' }, api_app_id: 'A0001',
    user: { id: user ?? s.approver, team_id: s.slackTeam }, trigger_id: `trig-${randomUUID()}`,
    channel: { id: s.slackChannel, name: 'eng' }, container: { type: 'message', channel_id: s.slackChannel },
    response_url: `${CONTROL}/slack/respond`, actions: [{ action_id: actionId, type: 'button', value: 'x' }],
  }
  const body = new URLSearchParams({ payload: JSON.stringify(payload) }).toString()
  const res = await fetch(`${BACKEND}/slack/interactions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded', ...sign(s.signingSecret, body) },
    body,
  })
  return res.status
}

/* ------------------------------------------------------------------ UI */

/** Signs in through the sign-in screen's Dev login and waits for the shell. */
export async function signIn(page: Page, next = '/app') {
  await page.goto(`/app/signin?next=${encodeURIComponent(next)}`)
  await page.getByTestId('dev-login').click()
  const path = next.split('?')[0]!
  await page.waitForURL((url) => url.pathname === path)
  await expect(page.getByTestId('footer-status')).toBeVisible()
}

export async function openRequest(page: Page, id: string, tab?: string) {
  await page.goto(`/app/requests/${id}${tab ? `?tab=${tab}` : ''}`)
  await expect(page.getByTestId('request-workspace')).toBeVisible()
}

export function workspaceState(page: Page) {
  return page.getByTestId('request-workspace')
}
