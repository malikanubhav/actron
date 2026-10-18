import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, within, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { SourceCard, topCounts } from '@/components/connect/SourceCard'
import { useGuideStore } from '@/components/connect/guide-store'
import { connection, def, installEndpoints, renderWithClient } from './helpers'
import type { SyncState } from '@/lib/api/types'
import { sentenceCase } from '@/lib/states'
import { connectionFor } from '@/components/connect/form-logic'

const mocks = vi.hoisted(() => ({
  connectors: vi.fn(),
  validateConnector: vi.fn(),
  connectorOptions: vi.fn(),
  connectorChecks: vi.fn(),
  createConnection: vi.fn(),
  syncConnection: vi.fn(),
  deleteConnection: vi.fn(),
}))
vi.mock('@/lib/api/endpoints', () => ({ endpoints: mocks }))

beforeEach(() => {
  vi.clearAllMocks()
  installEndpoints(mocks)
  useGuideStore.getState().reset()
})

const STATES: SyncState[] = ['BACKFILLING', 'SYNCING', 'PARTIAL', 'FAILED', 'UP TO DATE']

describe('SourceCard (spec C, C2; PROMPT 8.8 B)', () => {
  it.each(STATES)('C-AC-8 shows the %s chip from the shared state map', (state) => {
    renderWithClient(<SourceCard def={def('slack')} connection={connection('slack', { state })} />)
    const card = screen.getByTestId('source-card-slack')
    expect(card).toHaveAttribute('data-state', state)
    expect(within(card).getByText(sentenceCase(state))).toBeInTheDocument()
  })

  it('C-AC-8 not connected shows the label, Not connected, the guide button and the form', () => {
    renderWithClient(<SourceCard def={def('github')} connection={undefined} />)
    expect(screen.getByText('Source 01 · code')).toBeInTheDocument()
    expect(screen.getByText('Not connected')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Set up step by step' })).toBeInTheDocument()
    expect(screen.getByTestId('connector-form-github')).toBeInTheDocument()
  })

  it('opens its setup guide', async () => {
    const user = userEvent.setup()
    renderWithClient(<SourceCard def={def('linear')} connection={undefined} />)
    await user.click(screen.getByRole('button', { name: 'Set up step by step' }))
    expect(useGuideStore.getState().open).toBe('linear')
  })

  it('shows counts by type, items per minute, the working branch chip and only the last four secret characters', () => {
    renderWithClient(
      <SourceCard
        def={def('github')}
        connection={connection('github', {
          counts: { CodeFunction: 4210, GithubPullRequest: 1296, GitCommit: 8811 },
          secretLast4: 'a91f',
          config: { workingBranch: 'dev' },
        })}
      />,
    )
    expect(screen.getByTestId('working-branch')).toHaveTextContent('Branch · dev')
    expect(screen.getByTestId('secret-last4')).toHaveTextContent('••••a91f')
    expect(screen.getByText('Functions: 4,210')).toBeInTheDocument()
    expect(screen.getByText('items a minute', { exact: false })).toBeInTheDocument()
    expect(screen.queryByTestId('connector-form-github')).not.toBeInTheDocument()
  })

  it('the repository card shows its code and GitHub API rows apart, each with its own state, and the branch only on code', () => {
    const code = { ...connection('code', { counts: { CodeFunction: 5533 }, config: { workingBranch: 'published' } }), id: 'conn_code' }
    const github = connection('github', { state: 'PARTIAL', reason: 'public rate limit', counts: { GithubPullRequest: 12 }, config: { workingBranch: 'published', repository: 'BetterThanTomorrow/calva' } })
    renderWithClient(<SourceCard def={def('github')} connection={connectionFor('github', [code, github])} rows={[code, github]} />)
    const codeRow = screen.getByTestId('connection-row-code')
    const apiRow = screen.getByTestId('connection-row-github')
    expect(within(codeRow).getByRole('heading', { name: 'Code (git)' })).toBeInTheDocument()
    expect(within(apiRow).getByRole('heading', { name: 'GitHub API' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent('Repository · BetterThanTomorrow/calva')
    expect(screen.queryByTestId('guide-progress')).toBeNull()
    expect(within(codeRow).getByText('Up to date')).toBeInTheDocument()
    expect(within(apiRow).getByText('Partial')).toBeInTheDocument()
    expect(within(codeRow).getByTestId('working-branch')).toHaveTextContent('published')
    expect(within(apiRow).queryByTestId('working-branch')).toBeNull()
    const partial = within(apiRow).getByTestId('partial-state')
    expect(partial).toHaveTextContent('GitHub API read only part of its history.')
    expect(partial).toHaveTextContent("GitHub's public rate limit stopped the read after 12 pull requests. Add a GitHub access token")
    expect(within(partial).getByRole('button', { name: 'Add a GitHub token' })).toBeInTheDocument()
    expect(screen.getAllByTestId('partial-state')).toHaveLength(1)
    // Split cards carry one chip per row and none in the header, so each state is named once.
    expect(screen.getAllByText('Partial')).toHaveLength(1)
    expect(screen.getAllByText('Up to date')).toHaveLength(1)
    expect(screen.getAllByRole('button', { name: 'Sync now' })).toHaveLength(1)
  })

  it('shows the plain-language reason for a partial sync', () => {
    renderWithClient(
      <SourceCard
        def={def('linear')}
        connection={connection('linear', { state: 'PARTIAL', reason: 'Linear rate limit reached at 1,800 issues; the rest arrives at 14:00 UTC.' })}
      />,
    )
    expect(screen.getByTestId('partial-state')).toHaveTextContent('Linear rate limit reached at 1,800 issues')
  })

  it('a failed source offers Retry sync, which calls sync now', async () => {
    const user = userEvent.setup()
    renderWithClient(<SourceCard def={def('linear')} connection={connection('linear', { state: 'FAILED', reason: 'The key was revoked.' })} />)
    await user.click(screen.getByRole('button', { name: 'Retry sync' }))
    await waitFor(() => expect(mocks.syncConnection).toHaveBeenCalledWith('conn_linear', expect.any(String)))
  })

  it('Sync now is disabled while a backfill runs', () => {
    renderWithClient(<SourceCard def={def('slack')} connection={connection('slack', { state: 'BACKFILLING' })} />)
    expect(screen.getByRole('button', { name: 'Sync now' })).toBeDisabled()
  })

  it('Disconnect asks first and names what stops', async () => {
    const user = userEvent.setup()
    renderWithClient(<SourceCard def={def('slack')} connection={connection('slack')} />)
    await user.click(screen.getByRole('button', { name: 'Disconnect' }))
    expect(screen.getByText(/Approvals in Slack stop working/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Disconnect Slack' }))
    await waitFor(() => expect(mocks.deleteConnection).toHaveBeenCalledWith('conn_slack', expect.any(String)))
  })

  it('the optional Slack export card is marked optional when not connected', () => {
    renderWithClient(<SourceCard def={def('slack_export')} connection={undefined} />)
    expect(screen.getByText('Optional · Slack export')).toBeInTheDocument()
    expect(screen.getByText('Optional')).toBeInTheDocument()
  })

  it('keeps the six largest counts', () => {
    expect(topCounts({ a: 1, b: 9, c: 0, d: 5, e: 2, f: 3, g: 4, h: 8 }).map(([k]) => k)).toEqual(['b', 'h', 'd', 'g', 'f', 'e'])
  })
})
