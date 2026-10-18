import { describe, expect, it } from 'vitest'
import { DEFAULT_GUIDES, normalizeConnectors } from '@/lib/connectors'
import { typeName } from '@/lib/type-names'

describe('normalizeConnectors (C-AC-49 against the real backend shape)', () => {
  it('keeps a guide array from the contract as it is', () => {
    const guide = [{ id: 'a', title: 'A', checkId: 'x' }]
    const out = normalizeConnectors({ providers: [{ provider: 'github', title: 'GitHub', label: 'x', fields: [], guide }] })
    expect(out.providers[0]?.guide).toEqual(guide)
  })

  it('replaces a guide name with the spec C13 steps for that provider', () => {
    const out = normalizeConnectors({ providers: [{ provider: 'slack', title: 'Slack', label: 'x', fields: [], guide: 'slack' }] })
    expect(out.providers[0]?.guide).toEqual(DEFAULT_GUIDES.slack)
    expect(out.providers[0]?.guide).toHaveLength(6)
  })

  it('gives providers without a guide an empty list and missing fields an empty array', () => {
    const out = normalizeConnectors({ providers: [{ provider: 'slack_export', title: 'Export', label: 'x', guide: null }] })
    expect(out.providers[0]?.guide).toEqual([])
    expect(out.providers[0]?.fields).toEqual([])
  })

  it('survives a missing providers list', () => {
    expect(normalizeConnectors({}).providers).toEqual([])
  })

  it('has the C13 step counts: Slack 6, GitHub 4, Linear 3', () => {
    expect(DEFAULT_GUIDES.slack).toHaveLength(6)
    expect(DEFAULT_GUIDES.github).toHaveLength(4)
    expect(DEFAULT_GUIDES.linear).toHaveLength(3)
  })
})

describe('typeName', () => {
  it.each([
    ['CodeFunction', 2, 'Functions'],
    ['CodeFunction', 1, 'Function'],
    ['GithubPullRequest', 5, 'Pull requests'],
    ['GithubPullRequest', 1, 'Pull request'],
    ['GithubRepository', 1, 'Repository'],
    ['GithubRepository', 3, 'Repositories'],
    ['SlackMessage', 9, 'Messages'],
    ['GitCommit', 2, 'Commits'],
    ['GithubIssue', 2, 'Issues'],
    ['LinearComment', 2, 'Comments'],
    ['Decision', 2, 'Decisions'],
    ['Person', 1, 'Person'],
    ['GitBranch', 2, 'Branches'],
    ['GithubPullRequestFile', 2, 'PR files'],
  ])('%s × %d → %s', (type, count, expected) => {
    expect(typeName(type, count)).toBe(expected)
  })
})
