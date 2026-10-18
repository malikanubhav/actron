// FIXTURE: recorded-style test data for development and tests only; never used in production builds.
// The shape each fixture request is written in. lifecycle.ts turns a spec into contract events (spec B, B.C2).
import type { EvidenceRole, Kind, Label, QuestionOption, Surface, TicketContent } from '@/lib/api/types'
import type { PersonKey } from './people'

export interface ToolSpec {
  tool: string
  args: Record<string, unknown>
  summary: string
  nodeIds: string[]
  durationMs: number
  ok?: boolean
  error?: string
}

export interface JudgmentSpec {
  /** Emitted after the tool with this index. */
  afterTool: number
  job: string
  count: number
  what: string
  provider?: 'jev' | 'llm' | 'stub'
}

export interface EvidenceSpec {
  evidenceId: string
  role: EvidenceRole
  nodeId: string
  nodeType: string
  title: string
  quote: string | null
  source: { type: string; id: string; url: string | null; author: string | null; at: string | null }
  confidence: number
  flag?: boolean
  path: string[]
}

export interface QuestionSpec {
  questionId: string
  text: string
  options: QuestionOption[]
  evidenceIds: string[]
  required: boolean
  /** Recorded answer for historical fixtures. */
  answer?: { value: string; by: PersonKey; surface: Exclude<Surface, 'system'> }
}

export interface BuildStepSpec {
  text: string
  file?: string
  diff?: string
}

export interface TestsSpec {
  passed: number
  failed: number
  failing: { name: string; output: string }[]
}

export interface BuildSpec {
  buildId: string
  branch: string
  baseSha: string
  headSha: string
  position: number
  steps: BuildStepSpec[]
  /** Pi's graph tool calls, emitted after the step with this index. */
  piTools: (ToolSpec & { afterStep: number })[]
  /** Test runs in order; all but the last are followed by a repair. */
  attempts: { tests: TestsSpec; repair?: { reason: string; steps: BuildStepSpec[] } }[]
  outcome: 'passed' | 'failed'
  failReason?: string
  tokens: { input: number; output: number }
  costUsd: number
  report: Record<string, unknown>
}

export interface RequestSpec {
  id: string
  title: string
  text: string
  kind: Kind
  source: 'slack' | 'ui'
  requester: PersonKey
  createdAt: string
  slack: { channel: string; threadTs: string; permalink: string | null } | null
  mode: 'agent' | 'pipeline'
  tools: ToolSpec[]
  judgments: JudgmentSpec[]
  evidence: EvidenceSpec[]
  label: Label
  summary: string
  counts: { decisions: number; relatedWork: number; callers: number; tests: number }
  questions: QuestionSpec[]
  /** Ticket revisions in order (v1, v2, ...). */
  tickets: { content: TicketContent; by: string }[]
  linear: { issueId: string; identifier: string; url: string } | null
  build?: BuildSpec
  pr?: { number: number; url: string; headSha: string; title: string }
  investigation: { tokens: { input: number; output: number }; costUsd: number }
  writeback?: { prs: number; commits: number; functions: number; procedures: number }
  answer?: { text: string; citationIds: string[] }
}
