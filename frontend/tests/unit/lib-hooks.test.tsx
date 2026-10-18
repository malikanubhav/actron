import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, renderHook, waitFor } from '@testing-library/react'
import { getCsrfToken, setCsrfToken, setFetch } from '@/lib/api'
import { qk } from '@/lib/query-keys'
import { useToasts } from '@/lib/toasts'
import { useUi } from '@/lib/store'
import type { EventEnvelope, RequestDetail } from '@/lib/api/types'
import * as q from '@/lib/hooks/queries'
import * as m from '@/lib/hooks/mutations'
import { ingestWorkspaceEvents, invalidationsFor, toastFor, useWorkspaceStream, WORKSPACE_EVENT_LIMIT } from '@/lib/hooks/useWorkspaceStream'
import { useRequestStream } from '@/lib/hooks/useRequestStream'
import { FakeSource, fakeFactory } from './helpers/fake-source'
import { makeClient, makeEvent, makeRequestDetail, PERSON, wrapper } from './helpers/render'

type Call = { url: string; method: string; body: unknown; key: string | undefined }
let calls: Call[]
let routes: Record<string, () => Response | Promise<Response>>

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

beforeEach(() => {
  calls = []
  routes = {}
  useToasts.getState().clear()
  setFetch(vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    const method = init?.method ?? 'GET'
    const headers = (init?.headers ?? {}) as Record<string, string>
    calls.push({ url: String(url), method, body: typeof init?.body === 'string' ? JSON.parse(init.body) : undefined, key: headers['Idempotency-Key'] })
    const route = routes[`${method} ${String(url).split('?')[0]}`]
    return route ? route() : json({})
  }) as unknown as typeof fetch)
})
afterEach(() => {
  setFetch(null)
  setCsrfToken(null)
})

const toasts = () => useToasts.getState().toasts

describe('query hooks', () => {
  it('useMe stores the CSRF token it receives for later writes', async () => {
    routes['GET /api/me'] = () => json({ user: PERSON, csrfToken: 'tok-1', workspace: { id: 'w', name: 'W' } })
    const { result } = renderHook(() => q.useMe(), { wrapper: wrapper(makeClient()) })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(getCsrfToken()).toBe('tok-1')
  })

  it('useRequests passes the group and limit and returns the counts', async () => {
    routes['GET /api/requests'] = () => json({ requests: [], counts: { needsYou: 2, running: 1, done: 0 } })
    const { result } = renderHook(() => q.useRequests('needs_you', 5), { wrapper: wrapper(makeClient()) })
    await waitFor(() => expect(result.current.data?.counts.needsYou).toBe(2))
    expect(calls[0]?.url).toBe('/api/requests?group=needs_you&limit=5')
  })

  it('useRequest does not fetch without an id', async () => {
    const { result } = renderHook(() => q.useRequest(''), { wrapper: wrapper(makeClient()) })
    expect(result.current.fetchStatus).toBe('idle')
    expect(calls).toHaveLength(0)
  })

  it('useRequest fetches one request', async () => {
    const detail = makeRequestDetail()
    routes[`GET /api/requests/${detail.id}`] = () => json({ request: detail })
    const { result } = renderHook(() => q.useRequest(detail.id), { wrapper: wrapper(makeClient()) })
    await waitFor(() => expect(result.current.data?.request.title).toBe(detail.title))
  })

  it('useEvents and useWorkspaceEvents read the cache the streams write, starting empty', () => {
    const client = makeClient()
    client.setQueryData(qk.events('r1'), [makeEvent('tool.called', {}, 1)])
    const a = renderHook(() => q.useEvents('r1'), { wrapper: wrapper(client) })
    const b = renderHook(() => q.useWorkspaceEvents(), { wrapper: wrapper(client) })
    expect(a.result.current.data).toHaveLength(1)
    expect(b.result.current.data).toEqual([])
  })

  it('useSubgraph keeps the previous mode data while the new mode loads', async () => {
    routes['GET /api/graph/subgraph'] = () => json({ nodes: [{ id: 'a' }], links: [] })
    const client = makeClient()
    const { result, rerender } = renderHook(({ mode }: { mode: 'aggregated' | 'expanded' }) => q.useSubgraph('r1', mode), {
      wrapper: wrapper(client),
      initialProps: { mode: 'aggregated' as const } as { mode: 'aggregated' | 'expanded' },
    })
    await waitFor(() => expect(result.current.data).toBeDefined())
    rerender({ mode: 'expanded' })
    expect(result.current.data).toBeDefined()
    await waitFor(() => expect(calls.some((c) => c.url.includes('mode=expanded'))).toBe(true))
  })

  it('simple readers hit their routes', async () => {
    const client = makeClient()
    const hooks = [q.useIngestion, q.useConnections, q.useConnectors, q.useNotifications, q.useSettings, q.useGraphStats, q.useHealth]
    for (const h of hooks) renderHook(() => h(), { wrapper: wrapper(client) })
    await waitFor(() => expect(calls.length).toBeGreaterThanOrEqual(7))
    const urls = calls.map((c) => c.url)
    for (const u of ['/api/ingestion/status', '/api/connections', '/api/connectors', '/api/notifications', '/api/settings', '/api/graph/stats', '/api/health']) {
      expect(urls).toContain(u)
    }
  })
})

describe('mutation hooks', () => {
  const ok = { result: { status: 'accepted', reason: null, eventId: 1, state: 'Building' } }

  it('useReviseTicket saves, toasts, and refreshes the revisions', async () => {
    routes['POST /api/requests/r1/ticket/revisions'] = () => json({ result: ok.result, revision: {} })
    const client = makeClient()
    const spy = vi.spyOn(client, 'invalidateQueries')
    const { result } = renderHook(() => m.useReviseTicket('r1'), { wrapper: wrapper(client) })
    await act(async () => {
      await result.current.run({ content: { objective: 'x' } as never })
    })
    expect(calls[0]?.body).toEqual({ content: { objective: 'x' } })
    expect(toasts()[0]?.title).toMatch(/New ticket revision saved/)
    expect(spy).toHaveBeenCalledWith({ queryKey: qk.revisions('r1') })
  })

  it('C-AC-18 useReviseTicket reports a 409 as a refusal with the reason', async () => {
    routes['POST /api/requests/r1/ticket/revisions'] = () => json({ error: { code: 'invalid_transition', message: 'no' } }, 409)
    const { result } = renderHook(() => m.useReviseTicket('r1'), { wrapper: wrapper(makeClient()) })
    await act(async () => {
      await result.current.run({ content: {} as never }).catch(() => undefined)
    })
    expect(toasts()[0]).toMatchObject({ kind: 'error', title: 'The ticket edit was refused.' })
  })

  it('useFeedback sends text and head sha', async () => {
    routes['POST /api/requests/r1/feedback'] = () => json(ok)
    const { result } = renderHook(() => m.useFeedback('r1'), { wrapper: wrapper(makeClient()) })
    await act(async () => {
      await result.current.run({ text: 'rename', headSha: 'abc' })
    })
    expect(calls[0]?.body).toEqual({ text: 'rename', headSha: 'abc' })
    expect(toasts()[0]?.title).toMatch(/Feedback sent/)
  })

  it.each([
    ['cancel', 'POST /api/requests/r1/cancel', 'Request cancelled.'],
    ['retry', 'POST /api/requests/r1/retry', 'Retrying the step that failed.'],
    ['close-pr', 'POST /api/requests/r1/close-pr', 'Pull request closed.'],
  ] as const)('useLifecycle %s calls its route and says what happened', async (action, route, title) => {
    routes[route] = () => json(ok)
    const { result } = renderHook(() => m.useLifecycle('r1', action), { wrapper: wrapper(makeClient()) })
    await act(async () => {
      await result.current.run({ reason: 'dup' })
    })
    expect(calls[0]?.method + ' ' + calls[0]?.url).toBe(route)
    expect(toasts()[0]?.title).toBe(title)
  })

  it('useLifecycle failure names the action', async () => {
    routes['POST /api/requests/r1/retry'] = () => json({ error: { code: 'boom', message: 'down' } }, 500)
    const { result } = renderHook(() => m.useLifecycle('r1', 'retry'), { wrapper: wrapper(makeClient()) })
    await act(async () => {
      await result.current.run({}).catch(() => undefined)
    })
    expect(toasts()[0]).toMatchObject({ title: 'Retrying did not go through.', body: 'down' })
  })

  it('useCreateRequest seeds the request cache so the page opens without a second fetch', async () => {
    const detail = makeRequestDetail({ id: 'req_NEW' })
    routes['POST /api/requests'] = () => json({ request: detail })
    const client = makeClient()
    const { result } = renderHook(() => m.useCreateRequest(), { wrapper: wrapper(client) })
    await act(async () => {
      await result.current.run({ text: 'Add dark mode', kindHint: 'feature' })
    })
    expect(client.getQueryData<{ request: RequestDetail }>(qk.request('req_NEW'))?.request.id).toBe('req_NEW')
    expect(calls[0]?.body).toEqual({ text: 'Add dark mode', kindHint: 'feature' })
  })

  it('useCreateRequest tells the user when it fails', async () => {
    routes['POST /api/requests'] = () => json({ error: { code: 'x', message: 'busy' } }, 500)
    const { result } = renderHook(() => m.useCreateRequest(), { wrapper: wrapper(makeClient()) })
    await act(async () => {
      await result.current.run({ text: 'x' }).catch(() => undefined)
    })
    expect(toasts()[0]?.title).toBe('The request did not go through.')
  })

  it('workspace mutations call their routes and toast', async () => {
    routes['POST /api/connections/c1/sync'] = () => json({ triggered: true })
    routes['DELETE /api/connections/c1'] = () => new Response(null, { status: 204 })
    routes['POST /api/connections/c1/reset-cursor'] = () => json({ connection: {} })
    routes['PATCH /api/connections/c1'] = () => json({ connection: {}, reingest: true })
    const client = makeClient()
    const sync = renderHook(() => m.useSyncNow(), { wrapper: wrapper(client) })
    const dis = renderHook(() => m.useDisconnect(), { wrapper: wrapper(client) })
    const reset = renderHook(() => m.useResetCursor(), { wrapper: wrapper(client) })
    const patch = renderHook(() => m.usePatchConnection(), { wrapper: wrapper(client) })
    await act(async () => {
      await sync.result.current.run({ connectionId: 'c1' })
      await dis.result.current.run({ connectionId: 'c1' })
      await reset.result.current.run({ connectionId: 'c1' })
      await patch.result.current.run({ connectionId: 'c1', config: { branch: 'dev' } })
    })
    expect(toasts().map((t) => t.title)).toEqual([
      'Sync started. Counts update as items arrive.',
      'Source disconnected. Its memory stays in the graph.',
      'Cursor reset. The next sync reads this source from the start.',
      'Saved. Code memory is being rebuilt for the new branch.',
    ])
    expect(calls.find((c) => c.method === 'PATCH')?.body).toEqual({ config: { branch: 'dev' } })
  })

  it('usePatchConnection says plain Saved when nothing is re-ingested', async () => {
    routes['PATCH /api/connections/c1'] = () => json({ connection: {} })
    const { result } = renderHook(() => m.usePatchConnection(), { wrapper: wrapper(makeClient()) })
    await act(async () => {
      await result.current.run({ connectionId: 'c1', config: {} })
    })
    expect(toasts()[0]?.title).toBe('Saved.')
  })

  it.each([
    ['useSyncNow', 'Sync', 'POST /api/connections/c1/sync'],
    ['useDisconnect', 'Disconnect', 'DELETE /api/connections/c1'],
    ['useResetCursor', 'Reset', 'POST /api/connections/c1/reset-cursor'],
  ] as const)('%s failure is reported with its action name', async (hook, name, route) => {
    routes[route] = () => json({ error: { code: 'x', message: 'nope' } }, 500)
    const { result } = renderHook(() => m[hook](), { wrapper: wrapper(makeClient()) })
    await act(async () => {
      await result.current.run({ connectionId: 'c1' }).catch(() => undefined)
    })
    expect(toasts()[0]?.title).toBe(`${name} did not go through.`)
  })

  it('usePutSettings and useRaiseBudget write the returned settings into the cache', async () => {
    const settings = { monthlyBudgetUsd: 100 }
    routes['PUT /api/settings'] = () => json({ settings })
    routes['POST /api/settings/budget'] = () => json({ settings: { monthlyBudgetUsd: 200 } })
    const client = makeClient()
    const put = renderHook(() => m.usePutSettings(), { wrapper: wrapper(client) })
    const raise = renderHook(() => m.useRaiseBudget(), { wrapper: wrapper(client) })
    await act(async () => {
      await put.result.current.run({ partial: settings as never })
    })
    expect(client.getQueryData(qk.settings())).toEqual({ settings })
    await act(async () => {
      await raise.result.current.run({ capUsd: 200 })
    })
    expect(client.getQueryData(qk.settings())).toEqual({ settings: { monthlyBudgetUsd: 200 } })
    expect(calls[1]?.body).toEqual({ capUsd: 200 })
    expect(toasts().map((t) => t.title)).toEqual(['Settings saved.', 'Budget raised. Waiting builds resume.'])
  })

  it('C-AC-18 a failed settings save leaves the cached settings alone and says why', async () => {
    routes['PUT /api/settings'] = () => json({ error: { code: 'invalid_transition', message: 'x' } }, 409)
    const client = makeClient()
    client.setQueryData(qk.settings(), { settings: { monthlyBudgetUsd: 1 } })
    const { result } = renderHook(() => m.usePutSettings(), { wrapper: wrapper(client) })
    await act(async () => {
      await result.current.run({ partial: {} }).catch(() => undefined)
    })
    expect(client.getQueryData(qk.settings())).toEqual({ settings: { monthlyBudgetUsd: 1 } })
    expect(toasts()[0]?.title).toBe('Saving settings was refused.')
  })

  it('useRaiseBudget failure is reported', async () => {
    routes['POST /api/settings/budget'] = () => json({ error: { code: 'x', message: 'no' } }, 500)
    const { result } = renderHook(() => m.useRaiseBudget(), { wrapper: wrapper(makeClient()) })
    await act(async () => {
      await result.current.run({ capUsd: 1 }).catch(() => undefined)
    })
    expect(toasts()[0]?.title).toBe('Raising the budget did not go through.')
  })

  it('C-AC-18 useMarkRead marks one notification read at once and lowers the unread count', async () => {
    let release: () => void = () => undefined
    routes['POST /api/notifications/n1/read'] = () => new Promise<Response>((r) => (release = () => r(json({}))))
    routes['GET /api/notifications'] = () => json({ notifications: [], unread: 0 })
    const client = makeClient()
    client.setQueryData(qk.notifications(), {
      notifications: [
        { id: 'n1', readAt: null },
        { id: 'n2', readAt: null },
      ],
      unread: 2,
    })
    const { result } = renderHook(() => m.useMarkRead(), { wrapper: wrapper(client) })
    let done: Promise<unknown> = Promise.resolve()
    act(() => {
      done = result.current.run({ id: 'n1' })
    })
    await waitFor(() => expect(client.getQueryData<{ unread: number }>(qk.notifications())?.unread).toBe(1))
    const mid = client.getQueryData<{ notifications: { id: string; readAt: string | null }[] }>(qk.notifications())
    expect(mid?.notifications[0]?.readAt).not.toBeNull()
    expect(mid?.notifications[1]?.readAt).toBeNull()
    await waitFor(() => expect(calls.some((c) => c.url === '/api/notifications/n1/read')).toBe(true))
    await act(async () => {
      release()
      await done
    })
  })

  it('C-AC-18 useMarkRead restores the list when the server refuses', async () => {
    routes['POST /api/notifications/n1/read'] = () => json({ error: { code: 'x', message: 'no' } }, 500)
    routes['GET /api/notifications'] = () => json({ error: { code: 'x', message: 'no' } }, 500)
    const client = makeClient()
    const before = { notifications: [{ id: 'n1', readAt: null }], unread: 1 }
    client.setQueryData(qk.notifications(), before)
    const { result } = renderHook(() => m.useMarkRead(), { wrapper: wrapper(client) })
    await act(async () => {
      await result.current.run({ id: 'n1' }).catch(() => undefined)
    })
    expect(client.getQueryData(qk.notifications())).toEqual(before)
    expect(toasts()[0]?.title).toBe('Marking as read did not go through.')
  })

  it('useApprove reports a refused or pending result without a success toast', async () => {
    const client = makeClient()
    client.setQueryData(qk.request('r1'), { request: makeRequestDetail({ id: 'r1' }) })
    const { result } = renderHook(() => m.useApprove('r1', PERSON), { wrapper: wrapper(client) })
    routes['POST /api/requests/r1/approvals'] = () => json({ result: { status: 'refused', reason: 'stale_revision' } })
    await act(async () => {
      await result.current.run({ kind: 'ticket', target: 'h' })
    })
    expect(toasts()[0]?.title).toBe('The approval was refused.')
    expect(toasts()[0]?.body).toMatch(/ticket changed/)
    routes['POST /api/requests/r1/approvals'] = () => json({ result: { status: 'pending' } })
    await act(async () => {
      await result.current.run({ kind: 'pr', target: 's' })
    })
    expect(toasts()[1]?.title).toMatch(/Waiting for the workflow/)
    routes['POST /api/requests/r1/approvals'] = () => json(ok)
    await act(async () => {
      await result.current.run({ kind: 'pr', target: 's2' })
    })
    expect(toasts()[2]?.title).toMatch(/Writing back to memory/)
    await act(async () => {
      await result.current.run({ kind: 'ticket', target: 's3' })
    })
    expect(toasts()[3]?.title).toBe('Ticket approved. Build started.')
  })
})

describe('workspace stream', () => {
  const ev = (type: string, payload: Record<string, unknown> = {}, id = 1, requestId: string | null = 'r2', at?: string): EventEnvelope => ({
    ...makeEvent(type, payload, id, at),
    id,
    requestId: requestId as string,
  })

  it('ingestWorkspaceEvents adds new events once and caps the list', () => {
    const client = makeClient()
    expect(ingestWorkspaceEvents(client, [ev('tool.called', {}, 1)])).toHaveLength(1)
    expect(ingestWorkspaceEvents(client, [ev('tool.called', {}, 1)])).toEqual([])
    const many = Array.from({ length: WORKSPACE_EVENT_LIMIT + 20 }, (_, i) => ev('tool.called', {}, i + 10))
    ingestWorkspaceEvents(client, many)
    expect(client.getQueryData<EventEnvelope[]>(qk.workspaceEvents())).toHaveLength(WORKSPACE_EVENT_LIMIT)
  })

  it('invalidationsFor maps events to the caches they change', () => {
    expect(invalidationsFor(ev('ingestion.finished', {}, 1, null))).toEqual([qk.ingestion(), qk.connections(), qk.graphStats()])
    expect(invalidationsFor(ev('ingestion.progress', {}, 1, null))).toEqual([qk.ingestion(), qk.connections()])
    expect(invalidationsFor(ev('question.asked', {}, 1, 'r1'))).toEqual([qk.requestsAll(), qk.notifications()])
    expect(invalidationsFor(ev('tool.called', {}, 1, null))).toEqual([])
  })

  it.each([
    ['Needs your input', 'A request needs your answer.', 'needs_you', 'tab=questions'],
    ['Awaiting approval', 'A ticket is ready for your approval.', 'needs_you', 'tab=ticket'],
    ['PR ready for review', 'A pull request is ready for review.', 'needs_you', 'tab=pr'],
    ['Needs attention', 'A request stopped and needs attention.', 'error', 'tab=build'],
  ])('toastFor raises a toast when a request moves to %s', (to, title, kind, tab) => {
    toastFor(ev('request.state_changed', { to }, 1, 'r2'), 'r1')
    expect(toasts()[0]).toMatchObject({ title, kind })
    expect(toasts()[0]?.action?.href).toBe(`/app/requests/r2?${tab}`)
  })

  it('toastFor stays quiet for the request being viewed, events without a request and other states', () => {
    toastFor(ev('request.state_changed', { to: 'Needs your input' }, 1, 'r1'), 'r1')
    toastFor(ev('request.state_changed', { to: 'Needs your input' }, 2, null), null)
    toastFor(ev('request.state_changed', { to: 'Building' }, 3, 'r2'), 'r1')
    expect(toasts()).toHaveLength(0)
  })

  it('toastFor tells the user about an approval given in Slack', () => {
    toastFor(ev('approval.recorded', { surface: 'slack', kind: 'pr', by: { name: 'Sam' } }, 1, 'r2'), null)
    expect(toasts()[0]?.delivery).toBe('Approved in Slack by Sam. Write-back started.')
    toastFor(ev('approval.recorded', { surface: 'slack', kind: 'ticket' }, 2, 'r2'), null)
    expect(toasts()[1]?.delivery).toBe('Approved in Slack by someone. Build started.')
    toastFor(ev('approval.recorded', { surface: 'ui', kind: 'ticket' }, 3, 'r2'), null)
    expect(toasts()).toHaveLength(2)
  })

  it('useWorkspaceStream stores live events, refreshes caches, and toasts only for recent events', async () => {
    FakeSource.reset()
    const client = makeClient()
    const spy = vi.spyOn(client, 'invalidateQueries')
    renderHook(() => useWorkspaceStream({ factory: fakeFactory }), { wrapper: wrapper(client) })
    const src = FakeSource.latest()
    expect(src.url).toBe('/api/stream')
    src.open()
    expect(useUi.getState().workspaceStream).toBe('live')
    const fresh = new Date().toISOString()
    act(() => {
      src.send(ev('request.state_changed', { to: 'Needs your input' }, 5, 'r2', fresh))
      src.send(ev('request.state_changed', { to: 'Needs your input' }, 6, 'r3', '2020-01-01T00:00:00.000Z'))
    })
    expect(client.getQueryData<EventEnvelope[]>(qk.workspaceEvents())).toHaveLength(2)
    expect(spy).toHaveBeenCalledWith({ queryKey: qk.notifications() })
    expect(toasts()).toHaveLength(1)
  })

  it('useWorkspaceStream does not connect when disabled and closes on unmount', () => {
    FakeSource.reset()
    const off = renderHook(() => useWorkspaceStream({ enabled: false, factory: fakeFactory }), { wrapper: wrapper(makeClient()) })
    expect(FakeSource.instances).toHaveLength(0)
    off.unmount()
    const on = renderHook(() => useWorkspaceStream({ factory: fakeFactory }), { wrapper: wrapper(makeClient()) })
    on.unmount()
    expect(FakeSource.latest().closed).toBe(true)
  })
})

describe('request stream hook (C-AC-17)', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('C-AC-17 reports status, applies new events to the request and refetches after a state change', async () => {
    FakeSource.reset()
    const client = makeClient()
    const detail = makeRequestDetail({ id: 'r1', updatedAt: '2026-10-17T09:00:00.000Z' })
    client.setQueryData(qk.request('r1'), { request: detail })
    const spy = vi.spyOn(client, 'invalidateQueries')
    const { result } = renderHook(() => useRequestStream('r1', { factory: fakeFactory, refetchDelayMs: 50 }), { wrapper: wrapper(client) })
    expect(result.current.status).toBe('connecting')
    const src = FakeSource.latest()
    expect(src.url).toBe('/api/requests/r1/events')
    act(() => src.open())
    expect(result.current.status).toBe('live')
    act(() => {
      src.send({ ...makeEvent('request.state_changed', { to: 'Needs your input', from: 'Investigating' }, 1), requestId: 'r1' })
      src.send({ ...makeEvent('request.state_changed', { to: 'Needs your input', from: 'Investigating' }, 1), requestId: 'r1' })
    })
    expect(client.getQueryData<EventEnvelope[]>(qk.events('r1'))).toHaveLength(1)
    expect(client.getQueryData<{ request: RequestDetail }>(qk.request('r1'))?.request.state).toBe('Needs your input')
    expect(spy).not.toHaveBeenCalled()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60)
    })
    expect(spy).toHaveBeenCalledWith({ queryKey: qk.request('r1'), exact: true })
  })

  it('C-AC-17 does not connect without an id or when disabled, and stops on unmount', () => {
    FakeSource.reset()
    renderHook(() => useRequestStream('', { factory: fakeFactory }), { wrapper: wrapper(makeClient()) })
    renderHook(() => useRequestStream('r1', { factory: fakeFactory, enabled: false }), { wrapper: wrapper(makeClient()) })
    expect(FakeSource.instances).toHaveLength(0)
    const { unmount } = renderHook(() => useRequestStream('r1', { factory: fakeFactory }), { wrapper: wrapper(makeClient()) })
    unmount()
    expect(FakeSource.latest().closed).toBe(true)
  })
})
