/** TanStack Query keys (spec C, C4). Every server read goes through one of these. */
import type { RequestGroup } from './api/endpoints'

export type SubgraphMode = 'aggregated' | 'expanded'

export const qk = {
  me: () => ['me'] as const,
  requestsAll: () => ['requests'] as const,
  requests: (filters: { group?: RequestGroup; limit?: number } = {}) => ['requests', filters] as const,
  request: (id: string) => ['request', id] as const,
  events: (id: string) => ['events', id] as const,
  subgraphAll: (id: string) => ['subgraph', id] as const,
  subgraph: (id: string, mode: SubgraphMode) => ['subgraph', id, mode] as const,
  ingestion: () => ['ingestion'] as const,
  ingestionRuns: (source?: string) => ['ingestion', 'runs', source ?? 'all'] as const,
  notifications: () => ['notifications'] as const,
  connections: () => ['connections'] as const,
  connectors: () => ['connectors'] as const,
  connectorChecks: (provider: string) => ['connectors', provider, 'checks'] as const,
  connectorOptions: (provider: string, field: string, values: Record<string, string>) =>
    ['connectors', provider, 'options', field, values] as const,
  settings: () => ['settings'] as const,
  graphSearch: (q: string, types?: string) => ['graph-search', q, types ?? ''] as const,
  node: (id: string) => ['node', id] as const,
  neighbours: (id: string, types?: string) => ['node', id, 'neighbours', types ?? ''] as const,
  graphStats: () => ['graph-stats'] as const,
  revisions: (id: string) => ['request', id, 'revisions'] as const,
  prDiff: (id: string) => ['request', id, 'pr-diff'] as const,
  buildLog: (id: string, buildId: string) => ['request', id, 'build-log', buildId] as const,
  replay: (id: string) => ['replay', id] as const,
  health: () => ['health'] as const,
  workspaceEvents: () => ['workspace-events'] as const,
}
