/**
 * API types for spec B, B.C7 (frozen contract, 17 Oct 2026).
 *
 * `scripts/gen_types.sh` writes lib/api/openapi.json (the backend's OpenAPI document) and lib/api/openapi.d.ts.
 * Shapes that the generated schema states exactly are aliases of it (PersonRef, TestPlanItem, Pr, TokenUsage,
 * Evidence; tests/unit/api-types.test.ts checks the rest still agree). The others stay hand-written because the
 * backend schema is looser than the contract (timestamps typed nullable, ticket fields optional on input, the
 * connector, graph and settings routes return untyped objects). Every other module imports from this file only.
 */
import type { components } from './openapi'

type Schemas = components['schemas']

export const STATES = [
  'Investigating',
  'Needs your input',
  'Ticket ready',
  'Awaiting approval',
  'Building',
  'Needs attention',
  'PR ready for review',
  'Changes requested',
  'Done',
  'Cancelled',
] as const
export type State = (typeof STATES)[number]

export const LABELS = ['conflict', 'possible_conflict', 'nothing_found', 'clear'] as const
export type Label = (typeof LABELS)[number]

export const KINDS = ['feature', 'bug', 'question'] as const
export type Kind = (typeof KINDS)[number]

export type Surface = 'slack' | 'ui' | 'system'
export type Actor = 'actron' | 'person' | 'slack'

export type PersonRef = Schemas['PersonRef']

export interface EventEnvelope<P = Record<string, unknown>> {
  id: number
  requestId: string | null
  seq: number | null
  type: string
  at: string
  actor: Actor
  surface: Surface
  payload: P
}

export interface QuestionOption {
  value: string
  label: string
  note?: string
  preselected?: boolean
}

export interface Question {
  questionId: string
  text: string
  kind: 'choice' | 'text'
  options: QuestionOption[]
  evidenceIds: string[]
  required: boolean
  answer: { value: string; by: PersonRef; surface: Surface; at: string } | null
}

export type TestPlanItem = Schemas['TestPlanItem']

export interface TicketContent {
  objective: string
  context: string
  acceptanceCriteria: string[]
  constraintsToPreserve: { text: string; evidenceIds: string[] }[]
  affectedFunctions: string[]
  testPlan: TestPlanItem[]
  outOfScope: string[]
  targetBranch: string
}

export interface Revision {
  n: number
  hash: string
  content: TicketContent
  createdBy: string
  createdAt: string
  linear: { issueId: string; identifier: string; url: string } | null
  externalEdit: boolean
}

export interface Approval {
  id: string
  kind: 'ticket' | 'pr'
  target: string
  status: 'accepted' | 'refused'
  reason: string | null
  by: PersonRef
  surface: 'slack' | 'ui'
  at: string
}

export type BuildStatus = 'queued' | 'running' | 'passed' | 'failed' | 'stopped' | 'waiting_budget'

export type TokenUsage = Schemas['Tokens']

export interface Build {
  id: string
  status: BuildStatus
  queuePosition: number | null
  branch: string
  baseSha: string
  headSha: string | null
  testsPassed: number
  testsFailed: number
  attempts: number
  startedAt: string
  finishedAt: string | null
  stopReason: string | null
  tokens: TokenUsage
  costUsd: number
  report: Record<string, unknown> | null
}

export type Pr = Schemas['Pr']

export type PipelineStep = 1 | 2 | 3 | 4 | 5 | 6

export interface RequestSummary {
  id: string
  title: string
  kind: Kind
  state: State
  label: Label | null
  requester: PersonRef
  source: 'slack' | 'ui'
  createdAt: string
  updatedAt: string
  lastEvent: { type: string; sentence: string; at: string } | null
  pipelineStep: PipelineStep
  needsYou: boolean
}

export type Evidence = Schemas['Evidence']
export type EvidenceRole = Evidence['role']
export type Tier = Evidence['tier']

/** PROMPT appendix D, spec B, B.C3. */
export interface SharedQuery {
  requestId: string
  seeds: { id: string; type: string; score: number }[]
  decisions: {
    id: string
    statement: string
    status: 'approved' | 'proposed' | 'superseded'
    quote: string
    source: { id: string; type: string; url: string }
    conflict: { label: 'conflict' | 'possible_conflict' | 'none'; probability: number }
    path: string[]
  }[]
  relatedWork: { id: string; type: string; title: string; state: string; url: string; path: string[] }[]
  impact: {
    callers: { id: string; depth: number }[]
    tests: { id: string }[]
    criticality: { id: string; percentile: number }[]
  }
  owners: { personId: string; name: string; basis: string[]; score: number }[]
  procedures: { id: string; testCommand: string }[]
  label: Label
  graph: { nodes: { id: string; type: string; label: string }[]; edges: { from: string; to: string; type: string }[] }
}

export type AllowedAction =
  | 'answer'
  | 'edit_ticket'
  | 'approve_ticket'
  | 'pr_feedback'
  | 'approve_pr'
  | 'close_pr'
  | 'retry'
  | 'cancel'

export interface RequestDetail extends RequestSummary {
  text: string
  headline: string
  purpose: string
  slack: { channel: string; threadTs: string; permalink: string | null } | null
  findings: SharedQuery | null
  evidence: Evidence[]
  questions: Question[]
  revisions: Revision[]
  currentRevision: { n: number; hash: string } | null
  approvals: Approval[]
  builds: Build[]
  pr: Pr | null
  investigation: { mode: 'agent' | 'pipeline'; toolCalls: number; tokens: TokenUsage; costUsd: number; stub: boolean } | null
  outcome: 'approved' | 'answered' | 'cancelled' | 'closed' | null
  answer: { text: string; citations: Evidence[] } | null
  allowedActions: AllowedAction[]
}

export type NodeGroup = 'code' | 'github' | 'slack' | 'linear' | 'core'

export interface GraphNode {
  id: string
  type: string
  label: string
  group: NodeGroup
  count?: number
  props?: Record<string, unknown>
}

export interface GraphLink {
  from: string
  to: string
  type: string
  method: string | null
  confidence: number | null
  count?: number
}

export interface Subgraph {
  mode: 'aggregated' | 'expanded'
  nodes: GraphNode[]
  links: GraphLink[]
  truncated: boolean
}

export type SyncState = 'NOT CONNECTED' | 'BACKFILLING' | 'SYNCING' | 'PARTIAL' | 'FAILED' | 'UP TO DATE'
export type Provider = 'github' | 'code' | 'slack' | 'linear' | 'slack_export'

export interface ConnectionView {
  id: string
  provider: Provider
  status: 'connected' | 'error' | 'disconnected'
  config: Record<string, unknown>
  secretLast4: string | null
  createdAt: string
  updatedAt: string
  sync: {
    state: SyncState
    lastSyncedAt: string | null
    reason: string | null
    perMinute: number
    counts: Record<string, number>
  }
}

export interface Run {
  id: string
  source: string
  mode: 'backfill' | 'incremental'
  status: 'running' | 'done' | 'partial' | 'failed'
  startedAt: string
  finishedAt: string | null
  items: Record<string, number>
  errors: { action: string; error: string; url?: string; at: string }[]
}

export interface ActionResult {
  status: 'accepted' | 'refused' | 'pending' | 'duplicate'
  reason: string | null
  eventId: number | null
  state: State
}

export interface Me {
  user: PersonRef & { email: string | null; slackUserId: string | null }
  workspace: { id: string; name: string; role: string }
  csrfToken: string
  env: 'dev' | 'prod'
  devFixtures: boolean
}

/** Connector form definitions (spec C, C12; fabric's ui_form plus dependsOn and optionsFrom). */
export type UiComponent =
  | 'password'
  | 'text'
  | 'select'
  | 'multiselect'
  | 'stepper'
  | 'info'
  | 'file'
  | 'oauthButton'
  | 'webhookPanel'
  | 'manifestPanel'

export interface FormField {
  field_id: string
  type: 'string' | 'number' | 'select' | 'multiselect' | 'file' | 'info' | 'oauth'
  required: boolean
  label: string
  description?: string
  ui_component: UiComponent
  info?: string
  is_secret?: boolean
  dependsOn?: string
  optionsFrom?: string
  default?: string | number | null
  placeholder?: string
  accept?: string
  maxSizeMb?: number
  path?: 'oauth' | 'token' | 'shared'
  content?: string
  min?: number
  max?: number
}

export interface GuideStep {
  id: string
  title: string
  checkId?: string | null
}

export interface ConnectorDefinition {
  provider: Provider
  title: string
  label: string
  oauth?: { enabled: boolean; url: string }
  fields: FormField[]
  guide: GuideStep[]
}

export interface ValidateResult {
  ok: boolean
  found: string
  details: Record<string, unknown>
  errors: { field: string; message: string }[]
}

export interface ConnectorOption {
  value: string
  label: string
  note?: string
  default?: boolean
  protected?: boolean
}

export interface ConnectorCheck {
  id: string
  ok: boolean | null
  message: string
  troubleshooting?: string
}

export interface IngestionStatus {
  sources: {
    provider: Provider
    state: SyncState
    counts: Record<string, number>
    perMinute: number
    lastSyncedAt: string | null
    reason: string | null
    runId: string | null
  }[]
  linking: {
    referencesResolved: number
    pending: number
    decisions: number
    identities: number
    linksKept: number
    linksDropped: number
  }
  memoryPercent: number
  totals: { nodes: number; links: number }
}

export interface NotificationItem {
  id: string
  kind: 'needs_input' | 'awaiting_approval' | 'build_failed' | 'pr_ready'
  title: string
  body: string
  requestId: string
  tab: string
  readAt: string | null
  createdAt: string
}

export interface JobModel {
  job: string
  primitive: string
  provider: 'jev' | 'llm' | 'stub'
  status: 'live' | 'stub'
}

export interface Settings {
  approvers: string[]
  modelPrices: Record<string, { inputPerMTokUsd: number; outputPerMTokUsd: number }>
  allowPublicReplays: boolean
  thresholds: { conflict: number; possibleConflict: number; linkKeep: number }
  models: { decision: string; writing: string; agent: string; coding: string }
  jobs: JobModel[]
  botIdentity: { name: string; email: string }
  budget: { capUsd: number; spentTodayUsd: number }
  schedules: { code: string; github: string; linear: string; slack: string }
}

export interface GraphStats {
  nodeTypes: number
  nodes: number
  links: number
  byType: { type: string; group: NodeGroup; count: number }[]
  ontology: { types: number; relationships: number }
}

export interface SearchResult {
  id: string
  type: string
  label: string
  snippet: string
  score: number
}

export interface NodeDetail {
  node: GraphNode & { props: Record<string, unknown> }
  sources: { type: string; url: string }[]
  incoming: GraphLink[]
  outgoing: GraphLink[]
}

export interface PrDiffFile {
  path: string
  status: 'added' | 'modified' | 'removed' | 'renamed'
  additions: number
  deletions: number
  patch: string
}

export interface RevisionDiff {
  from: number
  to: number
  changes: { field: string; before: unknown; after: unknown }[]
}

/** Spec A, A1: `{falkordb, postgres, redis, temporal: "ok"|"error", integrations: {...}, version}`. */
export interface Health {
  falkordb: 'ok' | 'error'
  postgres: 'ok' | 'error'
  redis: 'ok' | 'error'
  temporal: 'ok' | 'error'
  integrations: Record<string, string>
  version: string
  [key: string]: unknown
}

export interface ApiErrorBody {
  error: { code: string; message: string; details?: Record<string, unknown> }
}
