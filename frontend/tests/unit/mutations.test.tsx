import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, renderHook, waitFor } from '@testing-library/react'
import { ApiError } from '@/lib/api'
import { qk } from '@/lib/query-keys'
import { useToasts } from '@/lib/toasts'
import type { RequestDetail } from '@/lib/api/types'
import { makeClient, makeRequestDetail, PERSON, wrapper } from './helpers/render'

const answer = vi.fn()
const approve = vi.fn()
vi.mock('@/lib/api/endpoints', () => ({
  endpoints: {
    answer: (...a: unknown[]) => answer(...a),
    approve: (...a: unknown[]) => approve(...a),
  },
}))

const { applyAnswer, applyPendingApproval, isPendingApproval, optimistic, rollback, useAnswer, useApprove, reportError, PENDING_PREFIX } = await import('@/lib/hooks/mutations')

const detail = makeRequestDetail({
  state: 'Needs your input',
  questions: [{ questionId: 'q1', text: 'Which branch?', kind: 'choice', options: [{ value: 'dev', label: 'dev' }], evidenceIds: [], required: true, answer: null }],
})

beforeEach(() => {
  answer.mockReset()
  approve.mockReset()
  useToasts.getState().clear()
})
afterEach(() => vi.restoreAllMocks())

describe('optimistic helpers (C-AC-18)', () => {
  it('applyAnswer records the answer as from this person in the UI', () => {
    const d = applyAnswer(PERSON)(detail, { questionId: 'q1', value: 'dev' })
    expect(d.questions[0]?.answer).toMatchObject({ value: 'dev', surface: 'ui', by: PERSON })
    expect(detail.questions[0]?.answer).toBeNull()
  })

  it('applyPendingApproval adds a pending approval marked by its prefix', () => {
    const d = applyPendingApproval(PERSON)(detail, { kind: 'ticket', target: 'h2', idempotencyKey: 'k' })
    expect(d.approvals[0]?.id).toBe(`${PENDING_PREFIX}k`)
    expect(isPendingApproval(d.approvals[0] as RequestDetail['approvals'][number])).toBe(true)
  })

  it('C-AC-18 optimistic() applies and rollback() restores the cache', async () => {
    const client = makeClient()
    client.setQueryData(qk.request(detail.id), { request: detail })
    const ctx = await optimistic(client, { requestId: detail.id, apply: applyAnswer(PERSON) }, { questionId: 'q1', value: 'dev' })
    expect(client.getQueryData<{ request: RequestDetail }>(qk.request(detail.id))?.request.questions[0]?.answer?.value).toBe('dev')
    rollback(client, detail.id, ctx)
    expect(client.getQueryData<{ request: RequestDetail }>(qk.request(detail.id))?.request.questions[0]?.answer).toBeNull()
  })

  it('reportError separates refusals from failures', () => {
    reportError(new ApiError('stale_revision', 'x', 409), 'The approval')
    reportError(new Error('down'), 'Sync')
    const [a, b] = useToasts.getState().toasts
    expect(a).toMatchObject({ kind: 'error', title: 'The approval was refused.' })
    expect(a?.body).toMatch(/ticket changed/)
    expect(b).toMatchObject({ kind: 'error', title: 'Sync did not go through.', body: 'down' })
  })
})

describe('mutation hooks (C-AC-18, C-AC-19)', () => {
  it('C-AC-18 useAnswer shows the answer at once, then rolls back on 409 with the reason in a toast', async () => {
    const client = makeClient()
    client.setQueryData(qk.request(detail.id), { request: detail })
    let reject: (e: unknown) => void = () => undefined
    answer.mockImplementation(() => new Promise((_r, j) => (reject = j)))
    const { result } = renderHook(() => useAnswer(detail.id, PERSON), { wrapper: wrapper(client) })
    let p: Promise<unknown> = Promise.resolve()
    act(() => {
      p = result.current.run({ questionId: 'q1', value: 'dev' }).catch(() => undefined)
    })
    await waitFor(() => expect(client.getQueryData<{ request: RequestDetail }>(qk.request(detail.id))?.request.questions[0]?.answer?.value).toBe('dev'))
    await act(async () => {
      reject(new ApiError('invalid_transition', 'no', 409))
      await p
    })
    await waitFor(() => expect(useToasts.getState().toasts).toHaveLength(1))
    expect(client.getQueryData<{ request: RequestDetail }>(qk.request(detail.id))?.request.questions[0]?.answer).toBeNull()
    expect(useToasts.getState().toasts[0]?.body).toMatch(/not available in the current state/)
  })

  it('C-AC-18 a successful answer refetches the request so the server state replaces the optimistic one', async () => {
    const client = makeClient()
    client.setQueryData(qk.request(detail.id), { request: detail })
    const spy = vi.spyOn(client, 'invalidateQueries')
    answer.mockResolvedValue({ result: { status: 'accepted', reason: null, eventId: 1, state: 'Ticket ready' } })
    const { result } = renderHook(() => useAnswer(detail.id, PERSON), { wrapper: wrapper(client) })
    await act(async () => {
      await result.current.run({ questionId: 'q1', value: 'dev' })
    })
    expect(spy).toHaveBeenCalledWith({ queryKey: qk.request(detail.id), exact: true })
    expect(useToasts.getState().toasts).toHaveLength(0)
  })

  it('C-AC-19 each run gets a new idempotency key; retryLast reuses the last one', async () => {
    const client = makeClient()
    client.setQueryData(qk.request(detail.id), { request: detail })
    approve.mockRejectedValueOnce(new Error('network')).mockResolvedValue({ result: { status: 'accepted', reason: null, eventId: 2, state: 'Building' } })
    const { result } = renderHook(() => useApprove(detail.id, PERSON), { wrapper: wrapper(client) })
    await act(async () => {
      await result.current.run({ kind: 'ticket', target: 'h2' }).catch(() => undefined)
    })
    const firstKey = approve.mock.calls[0]?.[2]
    await act(async () => {
      await result.current.retryLast()
    })
    expect(approve.mock.calls[1]?.[2]).toBe(firstKey)
    expect(approve.mock.calls[1]?.[1]).toEqual({ kind: 'ticket', revisionHash: 'h2' })
    expect(result.current.lastKey()).toBe(firstKey)
    await act(async () => {
      await result.current.run({ kind: 'pr', target: 'f00' })
    })
    expect(approve.mock.calls[2]?.[2]).not.toBe(firstKey)
    expect(approve.mock.calls[2]?.[1]).toEqual({ kind: 'pr', headSha: 'f00' })
  })

  it('C-AC-18 an approval refused with 409 rolls back the pending approval', async () => {
    const client = makeClient()
    client.setQueryData(qk.request(detail.id), { request: detail })
    approve.mockRejectedValue(new ApiError('stale_revision', 'stale', 409))
    const { result } = renderHook(() => useApprove(detail.id, PERSON), { wrapper: wrapper(client) })
    await act(async () => {
      await result.current.run({ kind: 'ticket', target: 'h1' }).catch(() => undefined)
    })
    expect(client.getQueryData<{ request: RequestDetail }>(qk.request(detail.id))?.request.approvals).toEqual([])
    expect(useToasts.getState().toasts[0]?.title).toBe('The approval was refused.')
  })

  it('retryLast with nothing to retry rejects', async () => {
    const { result } = renderHook(() => useApprove(detail.id, PERSON), { wrapper: wrapper(makeClient()) })
    await expect(result.current.retryLast()).rejects.toThrow('Nothing to retry.')
  })
})
