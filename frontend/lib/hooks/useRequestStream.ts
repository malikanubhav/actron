'use client'
/**
 * useRequestStream(id): one EventSource per open request (spec C, C4).
 * Appends envelopes to ['events', id] (deduped and ordered by seq), applies derived updates to ['request', id],
 * refetches the request after state-changing events and invalidates ['subgraph', id, *] after evidence changes.
 */
import { useEffect, useRef, useState } from 'react'
import { useQueryClient, type QueryClient } from '@tanstack/react-query'
import type { EventEnvelope, RequestDetail } from '../api/types'
import { qk } from '../query-keys'
import { StreamConnection, type EventSourceFactory, type StreamStatus } from '../stream/connection'
import { highestKey, mergeEvents } from '../stream/merge'
import { applyEvent, REFETCH_AFTER, SUBGRAPH_AFTER } from '../request-view'

export function ingestRequestEvents(client: QueryClient, id: string, incoming: EventEnvelope[]): EventEnvelope[] {
  const before = client.getQueryData<EventEnvelope[]>(qk.events(id))
  const merged = mergeEvents(before, incoming)
  if (merged === before) return []
  const beforeKeys = new Set((before ?? []).map((e) => e.seq ?? e.id))
  const added = merged.filter((e) => !beforeKeys.has(e.seq ?? e.id))
  client.setQueryData(qk.events(id), merged)
  client.setQueryData<{ request: RequestDetail }>(qk.request(id), (current) => {
    if (!current) return current
    // The fetched detail already reflects everything up to its updatedAt; the stream replays history on connect.
    const newer = added.filter((e) => e.at > current.request.updatedAt)
    return newer.length ? { request: newer.reduce(applyEvent, current.request) } : current
  })
  return added
}

export interface UseRequestStreamOptions {
  enabled?: boolean
  factory?: EventSourceFactory
  refetchDelayMs?: number
}

export function useRequestStream(id: string, options: UseRequestStreamOptions = {}): { status: StreamStatus } {
  const { enabled = true, factory, refetchDelayMs = 250 } = options
  const client = useQueryClient()
  const [status, setStatus] = useState<StreamStatus>('connecting')
  const refetchTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (!enabled || !id) return
    const scheduleRefetch = () => {
      if (refetchTimer.current) clearTimeout(refetchTimer.current)
      refetchTimer.current = setTimeout(() => {
        void client.invalidateQueries({ queryKey: qk.request(id), exact: true })
        void client.invalidateQueries({ queryKey: qk.requestsAll() })
      }, refetchDelayMs)
    }
    const connection = new StreamConnection({
      url: `/api/requests/${encodeURIComponent(id)}/events`,
      factory,
      lastEventId: () => highestKey(client.getQueryData<EventEnvelope[]>(qk.events(id))),
      onStatus: setStatus,
      onEvent: (event) => {
        const added = ingestRequestEvents(client, id, [event])
        if (added.length === 0) return
        if (added.some((e) => REFETCH_AFTER.has(e.type))) scheduleRefetch()
        if (added.some((e) => SUBGRAPH_AFTER.has(e.type))) {
          void client.invalidateQueries({ queryKey: qk.subgraphAll(id) })
        }
      },
    })
    connection.start()
    return () => {
      connection.stop()
      if (refetchTimer.current) clearTimeout(refetchTimer.current)
    }
  }, [client, id, enabled, factory, refetchDelayMs])

  return { status }
}
