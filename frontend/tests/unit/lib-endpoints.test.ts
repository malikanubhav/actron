import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, setCsrfToken, setFetch } from '@/lib/api'
import { endpoints } from '@/lib/api/endpoints'

type Call = { url: string; method: string; body: unknown; headers: Record<string, string> }
let calls: Call[]
let reply: () => Response

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

beforeEach(() => {
  calls = []
  reply = () => json({})
  setCsrfToken('csrf-9')
  setFetch(vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    calls.push({
      url: String(url),
      method: init?.method ?? 'GET',
      body: typeof init?.body === 'string' ? JSON.parse(init.body) : init?.body,
      headers: (init?.headers ?? {}) as Record<string, string>,
    })
    return reply()
  }) as unknown as typeof fetch)
})
afterEach(() => {
  setFetch(null)
  setCsrfToken(null)
})

const last = () => calls[calls.length - 1] as Call

describe('B.C7 endpoint functions send the documented method, path, query and body', () => {
  const cases: [string, () => Promise<unknown>, string, string, unknown][] = [
    ['me', () => endpoints.me(), 'GET', '/api/me', undefined],
    ['devLogin', () => endpoints.devLogin('Dana', 'k1'), 'POST', '/api/auth/dev-login', { name: 'Dana' }],
    ['logout', () => endpoints.logout(), 'POST', '/api/auth/logout', undefined],
    ['validateConnector', () => endpoints.validateConnector('github', { repo: 'a/b' }, 'k'), 'POST', '/api/connectors/github/validate', { values: { repo: 'a/b' } }],
    ['connectorOptions', () => endpoints.connectorOptions('github', 'branch', { repo: 'a/b' }), 'GET', '/api/connectors/github/options?field=branch&repo=a%2Fb', undefined],
    ['connectorChecks', () => endpoints.connectorChecks('slack'), 'GET', '/api/connectors/slack/checks', undefined],
    ['connections', () => endpoints.connections(), 'GET', '/api/connections', undefined],
    ['createConnection', () => endpoints.createConnection({ provider: 'linear', config: { team: 't' } }, 'k'), 'POST', '/api/connections', { provider: 'linear', config: { team: 't' } }],
    ['patchConnection', () => endpoints.patchConnection('c1', { branch: 'dev' }, 'k'), 'PATCH', '/api/connections/c1', { config: { branch: 'dev' } }],
    ['deleteConnection', () => endpoints.deleteConnection('c1', 'k'), 'DELETE', '/api/connections/c1', undefined],
    ['syncConnection', () => endpoints.syncConnection('c1', 'k'), 'POST', '/api/connections/c1/sync', undefined],
    ['resetCursor', () => endpoints.resetCursor('c1', 'k'), 'POST', '/api/connections/c1/reset-cursor', undefined],
    ['ingestionStatus', () => endpoints.ingestionStatus(), 'GET', '/api/ingestion/status', undefined],
    ['ingestionRuns', () => endpoints.ingestionRuns('github'), 'GET', '/api/ingestion/runs?source=github&limit=20', undefined],
    ['ingestionRuns default', () => endpoints.ingestionRuns(), 'GET', '/api/ingestion/runs?limit=20', undefined],
    ['createRequest', () => endpoints.createRequest('Add dark mode', 'feature', 'k'), 'POST', '/api/requests', { text: 'Add dark mode', kindHint: 'feature' }],
    ['requests', () => endpoints.requests('needs_you', 5), 'GET', '/api/requests?group=needs_you&limit=5', undefined],
    ['requests all', () => endpoints.requests(), 'GET', '/api/requests', undefined],
    ['request', () => endpoints.request('r1'), 'GET', '/api/requests/r1', undefined],
    ['replay', () => endpoints.replay('r1'), 'GET', '/api/requests/r1/replay', undefined],
    ['publicReplay', () => endpoints.publicReplay('r1'), 'GET', '/api/public/replays/r1', undefined],
    ['answer', () => endpoints.answer('r1', 'q1', 'dev', 'k'), 'POST', '/api/requests/r1/answers', { questionId: 'q1', value: 'dev' }],
    ['revisions', () => endpoints.revisions('r1'), 'GET', '/api/requests/r1/ticket/revisions', undefined],
    ['approve ticket', () => endpoints.approve('r1', { kind: 'ticket', revisionHash: 'h' }, 'k'), 'POST', '/api/requests/r1/approvals', { kind: 'ticket', revisionHash: 'h' }],
    ['approve pr', () => endpoints.approve('r1', { kind: 'pr', headSha: 's' }, 'k'), 'POST', '/api/requests/r1/approvals', { kind: 'pr', headSha: 's' }],
    ['feedback', () => endpoints.feedback('r1', 'rename it', 'abc', 'k'), 'POST', '/api/requests/r1/feedback', { text: 'rename it', headSha: 'abc' }],
    ['cancel', () => endpoints.cancel('r1', 'duplicate', 'k'), 'POST', '/api/requests/r1/cancel', { reason: 'duplicate' }],
    ['retry', () => endpoints.retry('r1', 'k'), 'POST', '/api/requests/r1/retry', undefined],
    ['closePr', () => endpoints.closePr('r1', undefined, 'k'), 'POST', '/api/requests/r1/close-pr', {}],
    ['prDiff', () => endpoints.prDiff('r1'), 'GET', '/api/requests/r1/pr/diff', undefined],
    ['subgraph', () => endpoints.subgraph('r1', 'expanded'), 'GET', '/api/graph/subgraph?requestId=r1&mode=expanded', undefined],
    ['node encodes id', () => endpoints.node('code:fn:a/b#c'), 'GET', '/api/graph/nodes/code%3Afn%3Aa%2Fb%23c', undefined],
    ['neighbours', () => endpoints.neighbours('n1', 'Function'), 'GET', '/api/graph/nodes/n1/neighbours?types=Function&limit=50', undefined],
    ['search', () => endpoints.search('evaluate'), 'GET', '/api/graph/search?q=evaluate&limit=20', undefined],
    ['path', () => endpoints.path('a', 'b'), 'GET', '/api/graph/path?from=a&to=b&maxHops=6', undefined],
    ['sample', () => endpoints.sample(), 'GET', '/api/graph/sample?limit=3000', undefined],
    ['stats', () => endpoints.stats(), 'GET', '/api/graph/stats', undefined],
    ['quick joins ids', () => endpoints.quick('callers', ['a', 'b'], 2), 'GET', '/api/graph/quick/callers?ids=a%2Cb&depth=2', undefined],
    ['notifications unread', () => endpoints.notifications(true), 'GET', '/api/notifications?unread=1', undefined],
    ['notifications all', () => endpoints.notifications(), 'GET', '/api/notifications', undefined],
    ['readNotification', () => endpoints.readNotification('n1', 'k'), 'POST', '/api/notifications/n1/read', undefined],
    ['settings', () => endpoints.settings(), 'GET', '/api/settings', undefined],
    ['putSettings', () => endpoints.putSettings({ autoApprove: false } as never, 'k'), 'PUT', '/api/settings', { autoApprove: false }],
    ['raiseBudget', () => endpoints.raiseBudget(50, 'k'), 'POST', '/api/settings/budget', { capUsd: 50 }],
    ['health', () => endpoints.health(), 'GET', '/api/health', undefined],
  ]

  it.each(cases)('%s', async (_name, run, method, url, body) => {
    await run()
    expect(last().method).toBe(method)
    expect(last().url).toBe(url)
    expect(last().body).toEqual(body)
  })

  it('writes carry the CSRF token and the idempotency key given by the caller', async () => {
    await endpoints.answer('r1', 'q1', 'dev', 'key-42')
    expect(last().headers['X-CSRF-Token']).toBe('csrf-9')
    expect(last().headers['Idempotency-Key']).toBe('key-42')
  })

  it('createConnection passes a FormData body through untouched', async () => {
    const form = new FormData()
    form.set('provider', 'github')
    await endpoints.createConnection(form, 'k')
    expect(last().body).toBe(form)
    expect(last().headers['Content-Type']).toBeUndefined()
  })

  it('buildLog asks for text and returns the raw log', async () => {
    reply = () => new Response('step 1\nstep 2', { status: 200 })
    await expect(endpoints.buildLog('r1', 'b1')).resolves.toBe('step 1\nstep 2')
    expect(last().url).toBe('/api/requests/r1/builds/b1/log')
    expect(last().headers.Accept).toBe('text/plain')
  })

  it('connectors fills in the default guide steps when the backend sends none', async () => {
    reply = () => json({ providers: [{ provider: 'linear', label: 'Linear' }] })
    const res = await endpoints.connectors()
    expect(res.providers[0]?.guide.map((s) => s.id)).toEqual(['key', 'paste', 'team'])
  })

  it('a 409 body becomes an ApiError with isConflict and its code', async () => {
    reply = () => json({ error: { code: 'stale_revision', message: 'old' } }, 409)
    const error = await endpoints.approve('r1', { kind: 'ticket', revisionHash: 'h' }, 'k').catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ code: 'stale_revision', isConflict: true })
  })
})
