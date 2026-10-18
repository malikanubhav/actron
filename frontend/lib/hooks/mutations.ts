'use client'
/**
 * Request and workspace mutations (spec C, C4).
 * - One idempotency key per user action; `retryLast()` repeats the same action with the same key (C-AC-19).
 * - Optimistic updates where the outcome is predictable, rolled back on error with the server's reason (C-AC-18).
 */
import { useCallback, useRef } from 'react'
import { useMutation, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { ApiError, newIdempotencyKey, reasonText } from '../api'
import { endpoints } from '../api/endpoints'
import type { ActionResult, Approval, Kind, PersonRef, RequestDetail, Settings, TicketContent } from '../api/types'
import { qk } from '../query-keys'
import { toast } from '../toasts'

type Keyed<V> = V & { idempotencyKey: string }

export interface OptimisticConfig<V> {
  requestId: string
  apply: (detail: RequestDetail, vars: V) => RequestDetail
}

export interface RollbackContext {
  previous: { request: RequestDetail } | undefined
}

/** Applies an optimistic change to ['request', id] and returns what is needed to roll it back. */
export async function optimistic<V>(client: QueryClient, config: OptimisticConfig<V>, vars: V): Promise<RollbackContext> {
  const key = qk.request(config.requestId)
  await client.cancelQueries({ queryKey: key, exact: true })
  const previous = client.getQueryData<{ request: RequestDetail }>(key)
  if (previous) client.setQueryData(key, { request: config.apply(previous.request, vars) })
  return { previous }
}

export function rollback(client: QueryClient, requestId: string, context: RollbackContext | undefined): void {
  if (context?.previous) client.setQueryData(qk.request(requestId), context.previous)
}

/** Shows the server's reason. 409s are expected refusals (stale revision, invalid transition, ...). */
export function reportError(error: unknown, action: string): void {
  const reason = reasonText(error)
  if (error instanceof ApiError && error.isConflict) toast.error(`${action} was refused.`, { body: reason })
  else toast.error(`${action} did not go through.`, { body: reason })
}

/** Wraps a mutation so each call gets a new idempotency key and `retryLast` reuses it. */
function useKeyed<V, R>(mutate: (vars: Keyed<V>) => Promise<R>) {
  const last = useRef<Keyed<V> | null>(null)
  const run = useCallback(
    (vars: V) => {
      const keyed = { ...vars, idempotencyKey: newIdempotencyKey() } as Keyed<V>
      last.current = keyed
      return mutate(keyed)
    },
    [mutate],
  )
  const retryLast = useCallback(() => (last.current ? mutate(last.current) : Promise.reject(new Error('Nothing to retry.'))), [mutate])
  return { run, retryLast, lastKey: () => last.current?.idempotencyKey ?? null }
}

function useSettle(requestId: string) {
  const client = useQueryClient()
  return useCallback(() => {
    void client.invalidateQueries({ queryKey: qk.request(requestId), exact: true })
    void client.invalidateQueries({ queryKey: qk.requestsAll() })
    void client.invalidateQueries({ queryKey: qk.notifications() })
  }, [client, requestId])
}

/* ------------------------------------------------------------------ answers */

export function applyAnswer(me: PersonRef) {
  return (detail: RequestDetail, vars: { questionId: string; value: string }): RequestDetail => ({
    ...detail,
    questions: detail.questions.map((q) =>
      q.questionId === vars.questionId ? { ...q, answer: { value: vars.value, by: me, surface: 'ui', at: new Date().toISOString() } } : q,
    ),
  })
}

export function useAnswer(requestId: string, me: PersonRef) {
  const client = useQueryClient()
  const settle = useSettle(requestId)
  const mutation = useMutation<{ result: ActionResult }, unknown, Keyed<{ questionId: string; value: string }>, RollbackContext>({
    mutationFn: (v) => endpoints.answer(requestId, v.questionId, v.value, v.idempotencyKey),
    onMutate: (v) => optimistic(client, { requestId, apply: applyAnswer(me) }, v),
    onError: (error, _v, context) => {
      rollback(client, requestId, context)
      reportError(error, 'Your answer')
    },
    onSettled: settle,
  })
  return { ...mutation, ...useKeyed(mutation.mutateAsync) }
}

/* ------------------------------------------------------------------ approvals */

export const PENDING_PREFIX = 'pending:'

export function applyPendingApproval(me: PersonRef) {
  return (detail: RequestDetail, vars: { kind: 'ticket' | 'pr'; target: string; idempotencyKey: string }): RequestDetail => {
    const pending: Approval = {
      id: `${PENDING_PREFIX}${vars.idempotencyKey}`,
      kind: vars.kind,
      target: vars.target,
      status: 'accepted',
      reason: null,
      by: me,
      surface: 'ui',
      at: new Date().toISOString(),
    }
    return { ...detail, approvals: [...detail.approvals, pending] }
  }
}

export function isPendingApproval(approval: Approval): boolean {
  return approval.id.startsWith(PENDING_PREFIX)
}

export function useApprove(requestId: string, me: PersonRef) {
  const client = useQueryClient()
  const settle = useSettle(requestId)
  const mutation = useMutation<{ result: ActionResult }, unknown, Keyed<{ kind: 'ticket' | 'pr'; target: string }>, RollbackContext>({
    mutationFn: (v) =>
      endpoints.approve(
        requestId,
        v.kind === 'ticket' ? { kind: 'ticket', revisionHash: v.target } : { kind: 'pr', headSha: v.target },
        v.idempotencyKey,
      ),
    onMutate: (v) => optimistic(client, { requestId, apply: applyPendingApproval(me) }, v),
    onSuccess: (data, v) => {
      if (data.result.status === 'refused') {
        toast.error('The approval was refused.', { body: reasonText(new ApiError(data.result.reason ?? 'refused', data.result.reason ?? '', 409)) })
      } else if (data.result.status === 'pending') {
        toast.info('Approval sent. Waiting for the workflow to confirm.')
      } else {
        toast.success(v.kind === 'ticket' ? 'Ticket approved. Build started.' : 'Pull request approved. Writing back to memory.')
      }
    },
    onError: (error, _v, context) => {
      rollback(client, requestId, context)
      reportError(error, 'The approval')
    },
    onSettled: settle,
  })
  return { ...mutation, ...useKeyed(mutation.mutateAsync) }
}

/* ------------------------------------------------------------------ tickets, feedback, lifecycle */

export function useReviseTicket(requestId: string) {
  const settle = useSettle(requestId)
  const client = useQueryClient()
  const mutation = useMutation<unknown, unknown, Keyed<{ content: TicketContent }>>({
    mutationFn: (v) => endpoints.reviseTicket(requestId, v.content, v.idempotencyKey),
    onSuccess: () => {
      toast.success('New ticket revision saved. Earlier approvals no longer count.')
      void client.invalidateQueries({ queryKey: qk.revisions(requestId) })
    },
    onError: (error) => reportError(error, 'The ticket edit'),
    onSettled: settle,
  })
  return { ...mutation, ...useKeyed(mutation.mutateAsync) }
}

export function useFeedback(requestId: string) {
  const settle = useSettle(requestId)
  const mutation = useMutation<unknown, unknown, Keyed<{ text: string; headSha: string }>>({
    mutationFn: (v) => endpoints.feedback(requestId, v.text, v.headSha, v.idempotencyKey),
    onSuccess: () => toast.success('Feedback sent. Actron will rebuild on the same branch.'),
    onError: (error) => reportError(error, 'Your feedback'),
    onSettled: settle,
  })
  return { ...mutation, ...useKeyed(mutation.mutateAsync) }
}

type Lifecycle = 'cancel' | 'retry' | 'close-pr'

export function useLifecycle(requestId: string, action: Lifecycle) {
  const settle = useSettle(requestId)
  const label = action === 'cancel' ? 'Cancelling' : action === 'retry' ? 'Retrying' : 'Closing the pull request'
  const mutation = useMutation<unknown, unknown, Keyed<{ reason?: string }>>({
    mutationFn: (v) =>
      action === 'cancel'
        ? endpoints.cancel(requestId, v.reason, v.idempotencyKey)
        : action === 'retry'
          ? endpoints.retry(requestId, v.idempotencyKey)
          : endpoints.closePr(requestId, v.reason, v.idempotencyKey),
    onSuccess: () =>
      toast.success(action === 'cancel' ? 'Request cancelled.' : action === 'retry' ? 'Retrying the step that failed.' : 'Pull request closed.'),
    onError: (error) => reportError(error, label),
    onSettled: settle,
  })
  return { ...mutation, ...useKeyed(mutation.mutateAsync) }
}

export function useCreateRequest() {
  const client = useQueryClient()
  const mutation = useMutation<{ request: RequestDetail }, unknown, Keyed<{ text: string; kindHint?: Kind }>>({
    mutationFn: (v) => endpoints.createRequest(v.text, v.kindHint, v.idempotencyKey),
    onSuccess: (data) => {
      client.setQueryData(qk.request(data.request.id), data)
      void client.invalidateQueries({ queryKey: qk.requestsAll() })
    },
    onError: (error) => reportError(error, 'The request'),
  })
  return { ...mutation, ...useKeyed(mutation.mutateAsync) }
}

/* ------------------------------------------------------------------ workspace */

export function useSyncNow() {
  const client = useQueryClient()
  const mutation = useMutation<unknown, unknown, Keyed<{ connectionId: string }>>({
    mutationFn: (v) => endpoints.syncConnection(v.connectionId, v.idempotencyKey),
    onSuccess: () => toast.info('Sync started. Counts update as items arrive.'),
    onError: (error) => reportError(error, 'Sync'),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: qk.ingestion() })
      void client.invalidateQueries({ queryKey: qk.connections() })
    },
  })
  return { ...mutation, ...useKeyed(mutation.mutateAsync) }
}

export function useDisconnect() {
  const client = useQueryClient()
  const mutation = useMutation<unknown, unknown, Keyed<{ connectionId: string }>>({
    mutationFn: (v) => endpoints.deleteConnection(v.connectionId, v.idempotencyKey),
    onSuccess: () => toast.success('Source disconnected. Its memory stays in the graph.'),
    onError: (error) => reportError(error, 'Disconnect'),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: qk.connections() })
      void client.invalidateQueries({ queryKey: qk.ingestion() })
    },
  })
  return { ...mutation, ...useKeyed(mutation.mutateAsync) }
}

export function useResetCursor() {
  const client = useQueryClient()
  const mutation = useMutation<unknown, unknown, Keyed<{ connectionId: string }>>({
    mutationFn: (v) => endpoints.resetCursor(v.connectionId, v.idempotencyKey),
    onSuccess: () => toast.success('Cursor reset. The next sync reads this source from the start.'),
    onError: (error) => reportError(error, 'Reset'),
    onSettled: () => void client.invalidateQueries({ queryKey: qk.connections() }),
  })
  return { ...mutation, ...useKeyed(mutation.mutateAsync) }
}

export function usePatchConnection() {
  const client = useQueryClient()
  const mutation = useMutation<{ reingest?: boolean }, unknown, Keyed<{ connectionId: string; config: Record<string, unknown> }>>({
    mutationFn: (v) => endpoints.patchConnection(v.connectionId, v.config, v.idempotencyKey),
    onSuccess: (data) => toast.success(data.reingest ? 'Saved. Code memory is being rebuilt for the new branch.' : 'Saved.'),
    onError: (error) => reportError(error, 'The change'),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: qk.connections() })
      void client.invalidateQueries({ queryKey: qk.ingestion() })
    },
  })
  return { ...mutation, ...useKeyed(mutation.mutateAsync) }
}

export function usePutSettings() {
  const client = useQueryClient()
  const mutation = useMutation<{ settings: Settings }, unknown, Keyed<{ partial: Partial<Settings> }>>({
    mutationFn: (v) => endpoints.putSettings(v.partial, v.idempotencyKey),
    onSuccess: (data) => {
      client.setQueryData(qk.settings(), data)
      toast.success('Settings saved.')
    },
    onError: (error) => reportError(error, 'Saving settings'),
  })
  return { ...mutation, ...useKeyed(mutation.mutateAsync) }
}

export function useRaiseBudget() {
  const client = useQueryClient()
  const mutation = useMutation<{ settings: Settings }, unknown, Keyed<{ capUsd: number }>>({
    mutationFn: (v) => endpoints.raiseBudget(v.capUsd, v.idempotencyKey),
    onSuccess: (data) => {
      client.setQueryData(qk.settings(), data)
      toast.success('Budget raised. Waiting builds resume.')
    },
    onError: (error) => reportError(error, 'Raising the budget'),
  })
  return { ...mutation, ...useKeyed(mutation.mutateAsync) }
}

export function useMarkRead() {
  const client = useQueryClient()
  const mutation = useMutation<unknown, unknown, Keyed<{ id: string }>, { previous: unknown }>({
    mutationFn: (v) => endpoints.readNotification(v.id, v.idempotencyKey),
    onMutate: async (v) => {
      await client.cancelQueries({ queryKey: qk.notifications() })
      const previous = client.getQueryData(qk.notifications())
      client.setQueryData<{ notifications: { id: string; readAt: string | null }[]; unread: number }>(qk.notifications(), (current) =>
        current
          ? {
              ...current,
              notifications: current.notifications.map((n) => (n.id === v.id ? { ...n, readAt: new Date().toISOString() } : n)),
              unread: Math.max(0, current.unread - (current.notifications.some((n) => n.id === v.id && !n.readAt) ? 1 : 0)),
            }
          : current,
      )
      return { previous }
    },
    onError: (error, _v, context) => {
      client.setQueryData(qk.notifications(), context?.previous)
      reportError(error, 'Marking as read')
    },
    onSettled: () => void client.invalidateQueries({ queryKey: qk.notifications() }),
  })
  return { ...mutation, ...useKeyed(mutation.mutateAsync) }
}
