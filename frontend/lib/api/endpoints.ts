/** Typed functions, one per route in spec B, B.C7. */
import { api } from '../api'
import { normalizeConnectors } from '../connectors'
import type {
  ActionResult,
  ConnectionView,
  ConnectorCheck,
  ConnectorOption,
  EventEnvelope,
  GraphStats,
  Health,
  IngestionStatus,
  Kind,
  Me,
  NodeDetail,
  NotificationItem,
  PrDiffFile,
  RequestDetail,
  RequestSummary,
  Revision,
  RevisionDiff,
  Run,
  SearchResult,
  Settings,
  Subgraph,
  TicketContent,
  ValidateResult,
  PersonRef,
  GraphNode,
  GraphLink,
} from './types'

export type RequestGroup = 'needs_you' | 'running' | 'done'

export const endpoints = {
  me: () => api<Me>('/api/me'),
  devLogin: (name: string, idempotencyKey?: string) =>
    api<{ user: PersonRef; workspace: { id: string; name: string } }>('/api/auth/dev-login', {
      method: 'POST',
      body: { name },
      idempotencyKey,
    }),
  logout: () => api<void>('/api/auth/logout', { method: 'POST' }),

  connectors: async () => normalizeConnectors(await api<{ providers?: unknown }>('/api/connectors')),
  validateConnector: (provider: string, values: Record<string, unknown>, idempotencyKey?: string) =>
    api<ValidateResult>(`/api/connectors/${provider}/validate`, { method: 'POST', body: { values }, idempotencyKey }),
  connectorOptions: (provider: string, field: string, values: Record<string, string>) =>
    api<{ options: ConnectorOption[] }>(`/api/connectors/${provider}/options`, { query: { field, ...values } }),
  connectorChecks: (provider: string) => api<{ checks: ConnectorCheck[] }>(`/api/connectors/${provider}/checks`),

  connections: () => api<{ connections: ConnectionView[] }>('/api/connections'),
  createConnection: (
    body: { provider: string; config: Record<string, unknown>; secret?: Record<string, string> } | FormData,
    idempotencyKey?: string,
  ) => api<{ connection: ConnectionView; runId: string }>('/api/connections', { method: 'POST', body, idempotencyKey }),
  patchConnection: (id: string, config: Record<string, unknown>, idempotencyKey?: string) =>
    api<{ connection: ConnectionView; reingest?: boolean }>(`/api/connections/${id}`, {
      method: 'PATCH',
      body: { config },
      idempotencyKey,
    }),
  deleteConnection: (id: string, idempotencyKey?: string) =>
    api<void>(`/api/connections/${id}`, { method: 'DELETE', idempotencyKey }),
  syncConnection: (id: string, idempotencyKey?: string) =>
    api<{ triggered: boolean }>(`/api/connections/${id}/sync`, { method: 'POST', idempotencyKey }),
  resetCursor: (id: string, idempotencyKey?: string) =>
    api<{ connection: ConnectionView }>(`/api/connections/${id}/reset-cursor`, { method: 'POST', idempotencyKey }),

  ingestionStatus: () => api<IngestionStatus>('/api/ingestion/status'),
  ingestionRuns: (source?: string, limit = 20) => api<{ runs: Run[] }>('/api/ingestion/runs', { query: { source, limit } }),

  createRequest: (text: string, kindHint: Kind | undefined, idempotencyKey?: string) =>
    api<{ request: RequestDetail }>('/api/requests', { method: 'POST', body: { text, kindHint }, idempotencyKey }),
  requests: (group?: RequestGroup, limit?: number) =>
    api<{ requests: RequestSummary[]; counts: { needsYou: number; running: number; done: number } }>('/api/requests', {
      query: { group, limit },
    }),
  request: (id: string) => api<{ request: RequestDetail }>(`/api/requests/${id}`),
  replay: (id: string) => api<{ request: RequestDetail; events: EventEnvelope[] }>(`/api/requests/${id}/replay`),
  publicReplay: (id: string) =>
    api<{ request: RequestDetail; events: EventEnvelope[] }>(`/api/public/replays/${id}`),
  answer: (id: string, questionId: string, value: string, idempotencyKey?: string) =>
    api<{ result: ActionResult }>(`/api/requests/${id}/answers`, {
      method: 'POST',
      body: { questionId, value },
      idempotencyKey,
    }),
  reviseTicket: (id: string, content: TicketContent, idempotencyKey?: string) =>
    api<{ result: ActionResult; revision: Revision }>(`/api/requests/${id}/ticket/revisions`, {
      method: 'POST',
      body: { content },
      idempotencyKey,
    }),
  revisions: (id: string) =>
    api<{ revisions: Revision[]; diffs: RevisionDiff[] }>(`/api/requests/${id}/ticket/revisions`),
  approve: (
    id: string,
    body: { kind: 'ticket'; revisionHash: string } | { kind: 'pr'; headSha: string },
    idempotencyKey?: string,
  ) => api<{ result: ActionResult }>(`/api/requests/${id}/approvals`, { method: 'POST', body, idempotencyKey }),
  feedback: (id: string, text: string, headSha: string, idempotencyKey?: string) =>
    api<{ result: ActionResult }>(`/api/requests/${id}/feedback`, {
      method: 'POST',
      body: { text, headSha },
      idempotencyKey,
    }),
  cancel: (id: string, reason: string | undefined, idempotencyKey?: string) =>
    api<{ result: ActionResult }>(`/api/requests/${id}/cancel`, { method: 'POST', body: { reason }, idempotencyKey }),
  retry: (id: string, idempotencyKey?: string) =>
    api<{ result: ActionResult }>(`/api/requests/${id}/retry`, { method: 'POST', idempotencyKey }),
  closePr: (id: string, reason: string | undefined, idempotencyKey?: string) =>
    api<{ result: ActionResult }>(`/api/requests/${id}/close-pr`, { method: 'POST', body: { reason }, idempotencyKey }),
  prDiff: (id: string) => api<{ files: PrDiffFile[]; headSha: string }>(`/api/requests/${id}/pr/diff`),
  buildLog: (id: string, buildId: string) =>
    api<string>(`/api/requests/${id}/builds/${buildId}/log`, { as: 'text' }),

  subgraph: (requestId: string, mode: 'aggregated' | 'expanded') =>
    api<Subgraph>('/api/graph/subgraph', { query: { requestId, mode } }),
  node: (id: string) => api<NodeDetail>(`/api/graph/nodes/${encodeURIComponent(id)}`),
  neighbours: (id: string, types?: string, limit = 50) =>
    api<Subgraph>(`/api/graph/nodes/${encodeURIComponent(id)}/neighbours`, { query: { types, limit } }),
  search: (q: string, types?: string, limit = 20) =>
    api<{ results: SearchResult[] }>('/api/graph/search', { query: { q, types, limit } }),
  path: (from: string, to: string, maxHops = 6) =>
    api<{ found: boolean; nodes: GraphNode[]; links: GraphLink[] }>('/api/graph/path', { query: { from, to, maxHops } }),
  sample: (limit = 3000) => api<Subgraph>('/api/graph/sample', { query: { limit } }),
  stats: () => api<GraphStats>('/api/graph/stats'),
  quick: (tool: 'callers' | 'owners' | 'decisions_for' | 'shortest_path' | 'tests_for', ids: string[], depth?: number) =>
    api<unknown>(`/api/graph/quick/${tool}`, { query: { ids: ids.join(','), depth } }),

  notifications: (unread?: boolean) =>
    api<{ notifications: NotificationItem[]; unread: number }>('/api/notifications', {
      query: { unread: unread ? 1 : undefined },
    }),
  readNotification: (id: string, idempotencyKey?: string) =>
    api<void>(`/api/notifications/${id}/read`, { method: 'POST', idempotencyKey }),

  settings: () => api<{ settings: Settings }>('/api/settings'),
  putSettings: (partial: Partial<Settings>, idempotencyKey?: string) =>
    api<{ settings: Settings }>('/api/settings', { method: 'PUT', body: partial, idempotencyKey }),
  raiseBudget: (capUsd: number, idempotencyKey?: string) =>
    api<{ settings: Settings }>('/api/settings/budget', { method: 'POST', body: { capUsd }, idempotencyKey }),

  health: () => api<Health>('/api/health'),
}

export type Endpoints = typeof endpoints
