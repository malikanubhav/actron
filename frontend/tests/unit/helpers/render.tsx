import type { ReactElement, ReactNode } from 'react'
import { render, type RenderOptions } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { EventEnvelope, RequestDetail } from '@/lib/api/types'

export function makeClient(): QueryClient {
  return new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity }, mutations: { retry: false } } })
}

export function wrapper(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

export function renderWithClient(ui: ReactElement, client = makeClient(), options?: RenderOptions) {
  return { client, ...render(ui, { wrapper: wrapper(client), ...options }) }
}

export const PERSON = { personId: 'actron:person:dana', userId: 'u1', name: 'Dana Ilić', avatarUrl: null }

export function makeRequestDetail(overrides: Partial<RequestDetail> = {}): RequestDetail {
  return {
    id: 'req_TEST000000000000000001',
    title: 'Show evaluation results inline',
    kind: 'feature',
    state: 'Investigating',
    label: null,
    requester: PERSON,
    source: 'slack',
    createdAt: '2026-10-17T09:00:00.000Z',
    updatedAt: '2026-10-17T09:00:00.000Z',
    lastEvent: null,
    pipelineStep: 1,
    needsYou: false,
    text: 'Show evaluation results inline for the top-level form.',
    headline: 'Investigating.',
    purpose: 'Actron is reading the graph.',
    slack: null,
    findings: null,
    evidence: [],
    questions: [],
    revisions: [],
    currentRevision: null,
    approvals: [],
    builds: [],
    pr: null,
    investigation: null,
    outcome: null,
    answer: null,
    allowedActions: [],
    ...overrides,
  }
}

export function makeEvent(type: string, payload: Record<string, unknown> = {}, seq = 1, at?: string): EventEnvelope {
  return {
    id: 1000 + seq,
    requestId: 'req_TEST000000000000000001',
    seq,
    type,
    at: at ?? new Date(Date.UTC(2026, 9, 17, 9, 0, seq)).toISOString(),
    actor: 'actron',
    surface: 'system',
    payload,
  }
}

export const TICKET = {
  objective: 'Show evaluation results inline next to the evaluated form.',
  context: 'Two earlier decisions limit where results may appear.',
  acceptanceCriteria: ['Given a form, when evaluated, then the result shows inline.'],
  constraintsToPreserve: [{ text: 'Results stay in the output window too.', evidenceIds: ['ev1'] }],
  affectedFunctions: ['code:fn:src/evaluate.ts#evaluateCode'],
  testPlan: [{ kind: 'existing' as const, target: 'code:fn:x', command: 'npm test -- evaluate' }],
  outOfScope: ['Changing the REPL window layout.'],
  targetBranch: 'dev',
}
