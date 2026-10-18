'use client'
import { useQuery, keepPreviousData } from '@tanstack/react-query'
import { setCsrfToken } from '../api'
import { endpoints, type RequestGroup } from '../api/endpoints'
import type { EventEnvelope, PersonRef } from '../api/types'
import { qk, type SubgraphMode } from '../query-keys'

export const NOBODY: PersonRef = { personId: null, userId: null, name: 'You', avatarUrl: null }

export function useMe() {
  return useQuery({
    queryKey: qk.me(),
    queryFn: async () => {
      const me = await endpoints.me()
      setCsrfToken(me.csrfToken)
      return me
    },
    staleTime: 5 * 60_000,
    retry: false,
  })
}

export function useRequests(group?: RequestGroup, limit?: number) {
  return useQuery({ queryKey: qk.requests({ group, limit }), queryFn: () => endpoints.requests(group, limit) })
}

export function useRequest(id: string) {
  return useQuery({ queryKey: qk.request(id), queryFn: () => endpoints.request(id), enabled: Boolean(id) })
}

/** Events arrive only through the stream; this reads the cache the stream writes. */
export function useEvents(id: string) {
  return useQuery<EventEnvelope[]>({
    queryKey: qk.events(id),
    queryFn: () => Promise.resolve([] as EventEnvelope[]),
    staleTime: Infinity,
    gcTime: 10 * 60_000,
    initialData: [],
  })
}

export function useSubgraph(id: string, mode: SubgraphMode) {
  return useQuery({
    queryKey: qk.subgraph(id, mode),
    queryFn: () => endpoints.subgraph(id, mode),
    placeholderData: keepPreviousData,
    enabled: Boolean(id),
  })
}

export function useIngestion() {
  return useQuery({ queryKey: qk.ingestion(), queryFn: endpoints.ingestionStatus, refetchInterval: 30_000 })
}

export function useConnections() {
  return useQuery({ queryKey: qk.connections(), queryFn: endpoints.connections })
}

export function useConnectors() {
  return useQuery({ queryKey: qk.connectors(), queryFn: endpoints.connectors, staleTime: 10 * 60_000 })
}

export function useNotifications() {
  return useQuery({ queryKey: qk.notifications(), queryFn: () => endpoints.notifications() })
}

export function useSettings() {
  return useQuery({ queryKey: qk.settings(), queryFn: endpoints.settings })
}

export function useGraphStats() {
  return useQuery({ queryKey: qk.graphStats(), queryFn: endpoints.stats, staleTime: 60_000 })
}

export function useWorkspaceEvents() {
  return useQuery<EventEnvelope[]>({
    queryKey: qk.workspaceEvents(),
    queryFn: () => Promise.resolve([] as EventEnvelope[]),
    staleTime: Infinity,
    initialData: [],
  })
}

export function useHealth() {
  return useQuery({ queryKey: qk.health(), queryFn: endpoints.health, refetchInterval: 60_000, retry: false })
}
