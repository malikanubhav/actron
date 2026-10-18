'use client'
/**
 * useWorkspaceStream(): the shell's single workspace stream (GET /api/stream). Keeps the latest workspace events
 * (for the System view and footer), refreshes requests, ingestion and notifications, and raises "needs you" toasts.
 */
import { useEffect } from 'react'
import { useQueryClient, type QueryClient } from '@tanstack/react-query'
import type { EventEnvelope } from '../api/types'
import { qk } from '../query-keys'
import { StreamConnection, type EventSourceFactory } from '../stream/connection'
import { highestKey, mergeEvents } from '../stream/merge'
import { useUi } from '../store'
import { toast } from '../toasts'
import { eventSentence, surfaceName } from '../events'

export const WORKSPACE_EVENT_LIMIT = 200

const NOTIFY_TYPES = new Set(['question.asked', 'ticket.synced', 'build.failed', 'pr.opened', 'notification.sent'])

export function ingestWorkspaceEvents(client: QueryClient, incoming: EventEnvelope[]): EventEnvelope[] {
  const before = client.getQueryData<EventEnvelope[]>(qk.workspaceEvents())
  const merged = mergeEvents(before, incoming)
  if (merged === before) return []
  const beforeKeys = new Set((before ?? []).map((e) => e.id))
  const added = merged.filter((e) => !beforeKeys.has(e.id))
  client.setQueryData(qk.workspaceEvents(), merged.slice(-WORKSPACE_EVENT_LIMIT))
  return added
}

/** Which caches a workspace event touches. */
export function invalidationsFor(event: EventEnvelope): (readonly unknown[])[] {
  const keys: (readonly unknown[])[] = []
  if (event.type.startsWith('ingestion.') || event.type.startsWith('linking.')) {
    keys.push(qk.ingestion(), qk.connections())
    if (event.type === 'ingestion.finished' || event.type === 'linking.finished') keys.push(qk.graphStats())
  }
  if (event.requestId) {
    keys.push(qk.requestsAll())
  }
  if (NOTIFY_TYPES.has(event.type) || event.type === 'request.state_changed') keys.push(qk.notifications())
  return keys
}

/** A toast for the events a person cares about while on another screen. */
export function toastFor(event: EventEnvelope, currentRequestId: string | null): void {
  if (!event.requestId || event.requestId === currentRequestId) return
  const p = event.payload as Record<string, unknown>
  const href = `/app/requests/${event.requestId}`
  if (event.type === 'request.state_changed') {
    const to = typeof p.to === 'string' ? p.to : ''
    if (to === 'Needs your input') toast.needsYou('A request needs your answer.', { action: { label: 'Open', href: `${href}?tab=questions` } })
    else if (to === 'Awaiting approval') toast.needsYou('A ticket is ready for your approval.', { action: { label: 'Open', href: `${href}?tab=ticket` } })
    else if (to === 'PR ready for review') toast.needsYou('A pull request is ready for review.', { action: { label: 'Open', href: `${href}?tab=pr` } })
    else if (to === 'Needs attention') toast.error('A request stopped and needs attention.', { action: { label: 'Open', href: `${href}?tab=build` } })
  } else if (event.type === 'approval.recorded' && p.surface === 'slack') {
    const by = typeof p.by === 'object' && p.by && 'name' in p.by ? String((p.by as { name: unknown }).name) : 'someone'
    toast.info(eventSentence(event), {
      delivery: `Approved in ${surfaceName(p.surface)} by ${by}. ${p.kind === 'pr' ? 'Write-back started.' : 'Build started.'}`,
      action: { label: 'Open', href },
    })
  }
}

export function useWorkspaceStream(options: { enabled?: boolean; factory?: EventSourceFactory; currentRequestId?: string | null } = {}) {
  const { enabled = true, factory, currentRequestId = null } = options
  const client = useQueryClient()
  const setStatus = useUi((s) => s.setWorkspaceStream)

  useEffect(() => {
    if (!enabled) return
    // The stream replays history on connect; only events from around now raise toasts.
    const since = Date.now() - 10_000
    const connection = new StreamConnection({
      url: '/api/stream',
      factory,
      lastEventId: () => highestKey(client.getQueryData<EventEnvelope[]>(qk.workspaceEvents())),
      onStatus: setStatus,
      onEvent: (event) => {
        const added = ingestWorkspaceEvents(client, [event])
        for (const e of added) {
          for (const key of invalidationsFor(e)) void client.invalidateQueries({ queryKey: key })
          if (Date.parse(e.at) >= since) toastFor(e, currentRequestId)
        }
      },
    })
    connection.start()
    return () => connection.stop()
  }, [client, enabled, factory, currentRequestId, setStatus])
}
