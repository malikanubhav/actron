// FIXTURE: recorded-style test data for development and tests only; never used in production builds.
// Workspace-level fixtures: connections, ingestion, notifications, settings, health, graph stats and the hero sample.
import type {
  ConnectionView,
  GraphLink,
  GraphNode,
  GraphStats,
  Health,
  IngestionStatus,
  NodeGroup,
  NotificationItem,
  Run,
  Settings,
  Subgraph,
} from '@/lib/api/types'
import snapshot from '@/lib/ontology-snapshot.json'
import { FIXTURE_IDS } from './ids'
import { hashString, prng } from './util'

const NOW_ISO = '2026-10-17T09:00:00Z'
const minutesAgo = (m: number) => new Date(Date.parse(NOW_ISO) - m * 60_000).toISOString()

/* ---------------------------------------------------------------- connections and ingestion */
export function connectionsFixture(): ConnectionView[] {
  return [
    {
      id: 'conn_fixture_github',
      provider: 'github',
      status: 'connected',
      config: {
        repository: 'BetterThanTomorrow/calva',
        workingBranch: 'dev',
        fork: 'calva-fixture/calva',
        upstream: 'BetterThanTomorrow/calva',
        historyDays: 90,
        webhook: false,
      },
      secretLast4: '9f2c',
      createdAt: '2026-10-15T08:00:00Z',
      updatedAt: minutesAgo(2),
      sync: {
        state: 'UP TO DATE',
        lastSyncedAt: minutesAgo(2),
        reason: null,
        perMinute: 0,
        counts: { CodeFile: 412, CodeFunction: 6840, CodeClass: 188, GitCommit: 2000, GithubPullRequest: 1296, GithubReview: 3410, GithubIssue: 905 },
      },
    },
    {
      id: 'conn_fixture_slack',
      provider: 'slack',
      status: 'connected',
      config: { workspace: 'Calva team (fixture)', channels: ['calva-dev', 'calva-help', 'releases'], requestsChannel: 'calva-dev', historyDays: 90 },
      secretLast4: 'k3Qd',
      createdAt: '2026-10-17T08:30:00Z',
      updatedAt: minutesAgo(0),
      sync: { state: 'BACKFILLING', lastSyncedAt: null, reason: null, perMinute: 840, counts: { SlackMessage: 6120, SlackUser: 214, SlackChannel: 3 } },
    },
    {
      id: 'conn_fixture_linear',
      provider: 'linear',
      status: 'connected',
      config: { team: 'CAL', teamName: 'Calva', ticketLabel: 'actron', historyDays: 90 },
      secretLast4: 'x81a',
      createdAt: '2026-10-16T12:00:00Z',
      updatedAt: minutesAgo(25),
      sync: {
        state: 'PARTIAL',
        lastSyncedAt: minutesAgo(25),
        reason: 'Linear rate limit reached at 1,800 issues; the rest arrives at 14:00 UTC.',
        perMinute: 0,
        counts: { LinearIssue: 1800, LinearComment: 4230, LinearUser: 12 },
      },
    },
  ]
}

export function ingestionFixture(connections: ConnectionView[], empty: boolean): IngestionStatus {
  const byProvider = new Map(connections.map((c) => [c.provider, c]))
  const providers = ['github', 'slack', 'linear', 'slack_export'] as const
  const sources = providers.map((provider) => {
    const c = byProvider.get(provider)
    return {
      provider,
      state: c?.sync.state ?? ('NOT CONNECTED' as const),
      counts: c?.sync.counts ?? {},
      perMinute: c?.sync.perMinute ?? 0,
      lastSyncedAt: c?.sync.lastSyncedAt ?? null,
      reason: c?.sync.reason ?? null,
      runId: c ? `run_fixture_${provider}` : null,
    }
  })
  const slack = byProvider.get('slack')
  const slackDone = slack?.sync.state === 'UP TO DATE'
  return {
    sources,
    linking: empty
      ? { referencesResolved: 0, pending: 0, decisions: 0, identities: 0, linksKept: 0, linksDropped: 0 }
      : { referencesResolved: 3120, pending: slackDone ? 40 : 214, decisions: 38, identities: 46, linksKept: 9410, linksDropped: 612 },
    memoryPercent: empty ? 0 : slackDone ? 88 : Math.min(87, 62 + Math.floor(((slack?.sync.counts.SlackMessage ?? 6120) - 6120) / 900)),
    // The same totals as GET /api/graph/stats, so Connect, Graph and the landing agree.
    totals: { nodes: graphStatsFixture(empty).nodes, links: graphStatsFixture(empty).links },
  }
}

export function runsFixture(): Run[] {
  return [
    {
      id: 'run_fixture_github',
      source: 'github',
      mode: 'incremental',
      status: 'done',
      startedAt: minutesAgo(3),
      finishedAt: minutesAgo(2),
      items: { GitCommit: 4, GithubPullRequest: 1, CodeFunction: 11 },
      errors: [],
    },
    {
      id: 'run_fixture_slack',
      source: 'slack',
      mode: 'backfill',
      status: 'running',
      startedAt: minutesAgo(30),
      finishedAt: null,
      items: { SlackMessage: 6120, SlackUser: 214 },
      errors: [],
    },
    {
      id: 'run_fixture_linear',
      source: 'linear',
      mode: 'backfill',
      status: 'partial',
      startedAt: minutesAgo(80),
      finishedAt: minutesAgo(25),
      items: { LinearIssue: 1800, LinearComment: 4230 },
      errors: [{ action: 'issues page 19', error: 'RATELIMITED: 1,800 requests per hour', url: 'https://api.linear.app/graphql', at: minutesAgo(25) }],
    },
    {
      id: 'run_fixture_github_backfill',
      source: 'github',
      mode: 'backfill',
      status: 'done',
      startedAt: '2026-10-15T08:00:00Z',
      finishedAt: '2026-10-15T08:41:00Z',
      items: { CodeFile: 412, CodeFunction: 6829, GitCommit: 1996, GithubPullRequest: 1295 },
      errors: [],
    },
  ]
}

/* ---------------------------------------------------------------- notifications */
export function notificationsFixture(): NotificationItem[] {
  return [
    {
      id: 'ntf_fixture_1',
      kind: 'pr_ready',
      title: 'PR #16 is ready for review.',
      body: 'Copy the evaluation result at the cursor. 16 of 16 tests passed.',
      requestId: FIXTURE_IDS.prReady,
      tab: 'pr',
      readAt: null,
      createdAt: '2026-10-16T16:58:00Z',
    },
    {
      id: 'ntf_fixture_2',
      kind: 'awaiting_approval',
      title: 'Ticket v2 is ready for your approval.',
      body: 'Make the nREPL connect timeout configurable. You approved v1; v2 adds a validation criterion.',
      requestId: FIXTURE_IDS.stale,
      tab: 'ticket',
      readAt: null,
      createdAt: '2026-10-17T07:35:00Z',
    },
    {
      id: 'ntf_fixture_3',
      kind: 'build_failed',
      title: 'The build failed twice.',
      body: 'Support custom nREPL middleware ordering in jack-in. cider-nrepl no longer loads first.',
      requestId: FIXTURE_IDS.failed,
      tab: 'build',
      readAt: null,
      createdAt: '2026-10-16T14:41:00Z',
    },
    {
      id: 'ntf_fixture_4',
      kind: 'awaiting_approval',
      title: 'Ticket v1 is ready for your approval.',
      body: 'Add a status bar tooltip that names the connected REPL type. Nothing in your history touches this.',
      requestId: FIXTURE_IDS.nothing,
      tab: 'ticket',
      readAt: '2026-10-17T07:50:00Z',
      createdAt: '2026-10-17T07:34:00Z',
    },
  ]
}

/* ---------------------------------------------------------------- settings and health */
export function settingsFixture(): Settings {
  return {
    approvers: ['U0FIXDANA', 'U0FIXSAM'],
    modelPrices: {
      'jev-1.13.0': { inputPerMTokUsd: 0.042, outputPerMTokUsd: 0 },
      'anthropic/claude-sonnet-5-5': { inputPerMTokUsd: 3, outputPerMTokUsd: 15 },
      'openrouter/qwen/qwen3-coder': { inputPerMTokUsd: 0.4, outputPerMTokUsd: 1.6 },
    },
    allowPublicReplays: true,
    thresholds: { conflict: 0.8, possibleConflict: 0.5, linkKeep: 0.6 },
    models: {
      decision: 'openrouter/qwen/qwen3-coder',
      writing: 'anthropic/claude-sonnet-5-5',
      agent: 'anthropic/claude-sonnet-5-5',
      coding: 'anthropic/claude-sonnet-5-5',
    },
    jobs: [
      { job: 'classify_message', primitive: 'choice', provider: 'jev', status: 'live' },
      { job: 'is_approval', primitive: 'noul', provider: 'jev', status: 'live' },
      { job: 'judge_link', primitive: 'noul', provider: 'jev', status: 'live' },
      { job: 'check_link', primitive: 'noul', provider: 'jev', status: 'live' },
      { job: 'rank_candidates', primitive: 'score', provider: 'jev', status: 'live' },
      { job: 'judge_conflict', primitive: 'choice', provider: 'jev', status: 'live' },
      { job: 'classify_request', primitive: 'choice', provider: 'jev', status: 'live' },
      { job: 'needs_question', primitive: 'noul', provider: 'jev', status: 'live' },
      { job: 'is_scope_change', primitive: 'noul', provider: 'jev', status: 'live' },
      { job: 'feedback_kind', primitive: 'choice', provider: 'jev', status: 'live' },
      { job: 'extract_decision', primitive: 'text', provider: 'llm', status: 'live' },
      { job: 'investigator_step', primitive: 'tools', provider: 'llm', status: 'live' },
      { job: 'write_questions', primitive: 'text', provider: 'llm', status: 'live' },
      { job: 'write_ticket', primitive: 'text', provider: 'llm', status: 'live' },
      { job: 'write_answer', primitive: 'text', provider: 'stub', status: 'stub' },
      { job: 'summarize_findings', primitive: 'text', provider: 'llm', status: 'live' },
    ],
    botIdentity: { name: 'Actron Bot', email: 'actron-bot@example.test' },
    budget: { capUsd: 20, spentTodayUsd: 3.42 },
    schedules: { code: 'on merge (webhook) and every 15 min', github: 'every 15 min', linear: 'every 30 min', slack: 'live (Socket Mode)' },
  }
}

export function healthFixture(): Health {
  return {
    falkordb: 'ok',
    postgres: 'ok',
    redis: 'ok',
    temporal: 'ok',
    integrations: { slack: 'ok', github: 'ok', linear: 'partial', jev: 'ok', llm: 'ok' },
    version: 'dev-fixture',
  }
}

/* ---------------------------------------------------------------- graph stats and sample */
const MAIN_COUNTS: Record<string, number> = {
  CodeRepository: 1,
  CodeComponent: 24,
  CodeDependency: 61,
  CodeFile: 412,
  CodeClass: 188,
  CodeFunction: 6840,
  CodeChunk: 9120,
  CodeDocument: 97,
  CodeOwnerRule: 6,
  GitCommit: 2000,
  GitAuthor: 141,
  GitBranch: 38,
  GitTag: 210,
  GitFileChange: 7340,
  GithubRepository: 2,
  GithubUser: 162,
  GithubPullRequest: 1296,
  GithubPullRequestFile: 5110,
  GithubReview: 3410,
  GithubReviewComment: 2870,
  GithubIssue: 905,
  GithubIssueComment: 3320,
  GithubLabel: 34,
  SlackChannel: 3,
  SlackMessage: 6120,
  SlackUser: 214,
  SlackReaction: 1890,
  LinearUser: 12,
  LinearTeam: 1,
  LinearIssue: 1800,
  LinearComment: 4230,
  LinearState: 7,
  LinearLabel: 19,
  LinearProject: 4,
  Workspace: 1,
  Person: 46,
  Identity: 131,
  Reference: 3334,
  Feature: 22,
  Decision: 38,
  Procedure: 14,
  Request: 9,
  Investigation: 9,
  BuildRun: 6,
}

export function graphStatsFixture(empty: boolean): GraphStats {
  const types = snapshot.types as { type: string; group: string }[]
  const byType = types.map((t) => ({
    type: t.type,
    group: t.group as NodeGroup,
    count: empty ? 0 : (MAIN_COUNTS[t.type] ?? 0),
  }))
  const nodes = byType.reduce((n, t) => n + t.count, 0)
  return {
    nodeTypes: types.length,
    nodes,
    links: empty ? 0 : Math.round(nodes * 4.58),
    byType: byType.sort((a, b) => b.count - a.count),
    ontology: { types: types.length, relationships: (snapshot as { relationshipCount: number }).relationshipCount },
  }
}

let sampleCache: Subgraph | null = null

/** A deterministic sample shaped like the real graph (for the 3D hero in fixture mode). */
export function sampleFixture(limit: number): Subgraph {
  if (!sampleCache) {
    const rand = prng(1764)
    const types = Object.entries(MAIN_COUNTS).filter(([, c]) => c > 20)
    const total = types.reduce((t, [, c]) => t + Math.sqrt(c), 0)
    const groupOf = new Map((snapshot.types as { type: string; group: string }[]).map((t) => [t.type, t.group as NodeGroup]))
    const nodes: GraphNode[] = []
    for (const [type, count] of types) {
      const n = Math.max(4, Math.round((Math.sqrt(count) / total) * 1500))
      for (let i = 0; i < n; i++) nodes.push({ id: `sample:${type}:${i}`, type, label: `${type} ${i + 1}`, group: groupOf.get(type) ?? 'core' })
    }
    const links: GraphLink[] = []
    for (let i = 0; i < nodes.length; i++) {
      const a = nodes[i] as GraphNode
      const fanout = 1 + Math.floor(rand() * 3)
      for (let k = 0; k < fanout && links.length < 3000; k++) {
        const near = Math.floor(rand() * 40) - 20
        const j = rand() < 0.75 ? Math.min(nodes.length - 1, Math.max(0, i + near)) : Math.floor(rand() * nodes.length)
        const b = nodes[j] as GraphNode
        if (a.id === b.id) continue
        links.push({ from: a.id, to: b.id, type: 'LINKED', method: rand() < 0.2 ? 'jev' : 'parsed', confidence: rand() < 0.2 ? 0.6 + rand() * 0.4 : 1 })
      }
    }
    sampleCache = { mode: 'expanded', nodes, links, truncated: false }
  }
  const nodes = sampleCache.nodes.slice(0, Math.max(0, limit))
  const keep = new Set(nodes.map((n) => n.id))
  return { mode: 'expanded', nodes, links: sampleCache.links.filter((l) => keep.has(l.from) && keep.has(l.to)), truncated: limit < sampleCache.nodes.length }
}

export function stableCount(key: string, min: number, max: number): number {
  return min + (hashString(key) % (max - min + 1))
}
