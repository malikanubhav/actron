import { describe, it, expect } from 'vitest'
import {
  buildPayload,
  canSubmit,
  connectHeadline,
  connectionFor,
  connectionName,
  connectionRows,
  fieldError,
  memoryExplainer,
  reasonSentence,
  initialValues,
  optionQuery,
  placeholderPrefix,
  visibleFields,
  workingBranch,
} from '@/components/connect/form-logic'
import { countsByGroup, memoryGraph } from '@/components/connect/memory-graph'
import { connection, def } from './helpers'

const base = { validated: false, oauthOk: false, path: 'token' as const }

describe('connector form logic (spec C, C12)', () => {
  it('C-AC-50 dependent fields stay hidden before validation and appear after', () => {
    const github = def('github')
    const values = initialValues(github)
    expect(visibleFields(github, values, base).map((f) => f.field_id)).toEqual(['access_token', 'repository', 'history_days'])
    expect(visibleFields(github, values, { ...base, validated: true }).map((f) => f.field_id)).toContain('working_branch')
  })

  it('C-AC-50 a field whose parent is dependent waits for the parent value', () => {
    const linear = def('linear')
    const values = initialValues(linear)
    const ids = () => visibleFields(linear, values, { ...base, validated: true }).map((f) => f.field_id)
    expect(ids()).not.toContain('ticket_label')
    values.team = 'team_cal'
    expect(ids()).toContain('ticket_label')
  })

  it('reads prefixes from placeholders and checks owner/name', () => {
    const slack = def('slack')
    const bot = slack.fields.find((f) => f.field_id === 'bot_token')!
    expect(placeholderPrefix(bot)).toBe('xoxb-')
    expect(fieldError(bot, 'xapp-1')).toBe('This should start with xoxb-')
    expect(fieldError(bot, '')).toBe('Enter the bot token.')
    const repo = def('github').fields.find((f) => f.field_id === 'repository')!
    expect(fieldError(repo, 'calva')).toBe('Use the form owner/name.')
    expect(fieldError(repo, 'BetterThanTomorrow/calva')).toBeNull()
  })

  it('C-AC-51 secrets are sent apart from config and never in option queries', () => {
    const github = def('github')
    const values = { ...initialValues(github), access_token: 'github_pat_x1234', repository: 'a/b', working_branch: 'dev' }
    const { config, secret } = buildPayload(github, values, { ...base, validated: true })
    expect(secret).toEqual({ access_token: 'github_pat_x1234' })
    expect(config).toMatchObject({ repository: 'a/b', working_branch: 'dev', history_days: 90 })
    expect(optionQuery(github, values)).not.toHaveProperty('access_token')
  })

  it('submit needs validation first', () => {
    const github = def('github')
    const values = { ...initialValues(github), access_token: 'github_pat_x', repository: 'a/b', working_branch: 'dev' }
    expect(canSubmit(github, values, base)).toBe(false)
    expect(canSubmit(github, values, { ...base, validated: true })).toBe(true)
  })

  it('reads the working branch from either config spelling', () => {
    expect(workingBranch(connection('github', { config: { workingBranch: 'dev' } }))).toBe('dev')
    expect(workingBranch(connection('github', { config: { working_branch: 'main' } }))).toBe('main')
    expect(workingBranch(undefined)).toBeNull()
  })
})

describe('repository card shows code and GitHub as one source (spec A, A11)', () => {
  it('takes the worse state and its reason, both counts and the github id, in either order', () => {
    const code = connection('code', { counts: { CodeFunction: 5 } })
    const github = connection('github', { state: 'PARTIAL', reason: 'pull request #1 not found', counts: { GithubPullRequest: 1 } })
    for (const list of [[code, github], [github, code]]) {
      const shown = connectionFor('github', list)
      expect(shown?.id).toBe('conn_github')
      expect(shown?.sync.state).toBe('PARTIAL')
      expect(shown?.sync.reason).toBe('pull request #1 not found')
      expect(shown?.sync.counts).toEqual({ CodeFunction: 5, GithubPullRequest: 1 })
      expect(shown?.sync.perMinute).toBe(240)
    }
    expect(connectionFor('github', [code, connection('github', { state: 'BACKFILLING' })])?.sync.state).toBe('BACKFILLING')
    expect(connectionFor('github', [code])?.id).toBe('conn_code')
    expect(connectionFor('slack', [code, connection('slack')])?.provider).toBe('slack')
  })

  it('keeps the rows behind the card apart, code first, each with its own name', () => {
    const code = connection('code')
    const github = connection('github')
    expect(connectionRows('github', [github, code, connection('slack')]).map((c) => c.provider)).toEqual(['code', 'github'])
    expect(connectionRows('slack', [github, connection('slack')]).map((c) => c.provider)).toEqual(['slack'])
    expect(connectionName('code')).toBe('Code (git)')
    expect(connectionName('github')).toBe('GitHub API')
  })
})

describe('partial reasons in plain sentences', () => {
  it('turns the GitHub rate limit into a sentence with a next step', () => {
    expect(reasonSentence('github', 'public rate limit', { GithubPullRequest: 12 })).toEqual({
      text: "GitHub's public rate limit stopped the read after 12 pull requests. Add a GitHub access token to read the full history.",
      action: 'add-token',
    })
  })
  it('keeps a sentence written for people, and wraps any other reason with a next step', () => {
    expect(reasonSentence('linear', 'Linear rate limit reached; the rest arrives at 14:00 UTC.').text).toBe('Linear rate limit reached; the rest arrives at 14:00 UTC.')
    expect(reasonSentence('github', 'pull request #1 not found').text).toBe('The provider reported: pull request #1 not found. Sync again later.')
    expect(reasonSentence('slack', null).text).toBe('The provider did not say why. Sync again later.')
  })
})

describe('memory explainer in the Connect purpose line', () => {
  it('says what the percentage measures only while the headline shows one', () => {
    expect(memoryExplainer({ memoryPercent: 50 })).toBe('The percentage is the share of each source’s history read so far.')
    expect(memoryExplainer({ memoryPercent: 100 })).toBeNull()
    expect(memoryExplainer({ memoryPercent: 0 })).toBeNull()
  })
})

describe('Connect headline (PROMPT 8.8 B)', () => {
  const now = Date.parse('2026-10-17T12:00:00Z')
  it('asks for a repository first', () => {
    expect(connectHeadline([], null, now)).toBe('Connect a repository to start.')
    expect(connectHeadline([connection('slack')], null, now)).toBe('Connect a repository to start.')
  })
  it('reports progress while backfilling', () => {
    expect(connectHeadline([connection('github'), connection('slack', { state: 'BACKFILLING' })], { memoryPercent: 62 }, now)).toBe(
      'Your memory is 62% built.',
    )
  })
  it('names a failed source', () => {
    expect(connectHeadline([connection('github'), connection('linear', { state: 'FAILED' })], { memoryPercent: 40 }, now)).toBe(
      'Linear stopped syncing. Your memory is 40% built.',
    )
  })
  it('names a partly read source', () => {
    expect(connectHeadline([connection('github'), connection('linear', { state: 'PARTIAL' })], { memoryPercent: 88 }, now)).toBe(
      'Your memory is 88% built. Linear is partly read.',
    )
  })
  it('does not claim a percentage next to a partly read source when the history window is complete', () => {
    expect(connectHeadline([connection('code'), connection('github', { state: 'PARTIAL' })], { memoryPercent: 100 }, now)).toBe(
      'Memory is built, but the GitHub API skipped some items.',
    )
  })
  it('says up to date with the last sync', () => {
    expect(connectHeadline([connection('github')], { memoryPercent: 100 }, now)).toBe('Memory is up to date. Last sync 2 min ago.')
  })
})

describe('memory graph (Connect canvas)', () => {
  it('builds one node per type with data and links them by ontology relationships', () => {
    const g = memoryGraph({
      byType: [
        { type: 'CodeFunction', group: 'code', count: 10 },
        { type: 'CodeFile', group: 'code', count: 3 },
        { type: 'SlackMessage', group: 'slack', count: 0 },
      ],
    })
    expect(g.nodes.map((n) => n.id)).toEqual(['type:CodeFunction', 'type:CodeFile'])
    expect(g.links.length).toBeGreaterThan(0)
    expect(g.links.every((l) => l.from !== l.to)).toBe(true)
  })
  it('invents nothing when there is no data', () => {
    expect(memoryGraph(undefined).nodes).toHaveLength(0)
    expect(countsByGroup(undefined)).toEqual({ code: 0, github: 0, slack: 0, linear: 0, core: 0 })
  })
})
