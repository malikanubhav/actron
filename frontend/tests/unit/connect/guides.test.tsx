import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, within, act, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { SetupGuide } from '@/components/connect/SetupGuide'
import { useGuideStore } from '@/components/connect/guide-store'
import { failingCodes, SLACK_SCOPE_REASONS } from '@/components/connect/GuideComponents'
import { guideProgress, visibleGuideSteps } from '@/components/connect/form-logic'
import { checksFixture, MISSING_SCOPES } from '@/tests/fixtures/data/connectors'
import { def, installEndpoints, outcome, renderWithClient } from './helpers'

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
  outcome.value = 'connected'
  act(() => useGuideStore.getState().reset())
})

function openGuide(provider: string) {
  act(() => useGuideStore.getState().setOpen(provider))
  return renderWithClient(<SetupGuide def={def(provider)} />)
}

describe('Setup guides (spec C, C13)', () => {
  it('C-AC-54 the Slack guide has all six steps with copy buttons, deep links and checks', async () => {
    openGuide('slack')
    const guide = await screen.findByTestId('guide-slack')
    expect(within(guide).getAllByTestId('guide-step')).toHaveLength(6)
    expect(within(guide).getByText("Create the app from Actron's manifest")).toBeInTheDocument()
    expect(within(guide).getByText('Try it')).toBeInTheDocument()
  })

  it('C-AC-54 Slack steps carry the manifest copy, the scope table and the copyable commands', async () => {
    const user = userEvent.setup()
    openGuide('slack')
    await screen.findAllByTestId('guide-check')
    const open = async (step: string) => {
      const el = document.querySelector(`[data-step="${step}"] button[aria-expanded]`) as HTMLButtonElement
      if (el.getAttribute('aria-expanded') === 'false') await user.click(el)
    }
    await open('scopes')
    const table = screen.getByTestId('scope-table')
    expect(within(table).getAllByRole('row')).toHaveLength(SLACK_SCOPE_REASONS.length + 1)
    await open('invite')
    expect(screen.getByText('/invite @Actron')).toBeInTheDocument()
    await open('try')
    expect(screen.getByText('/actron hello')).toBeInTheDocument()
    await open('create')
    expect(screen.getAllByRole('button', { name: 'Copy manifest' }).length).toBeGreaterThan(0)
    const link = screen.getByRole('link', { name: /Open Slack app creation \(opens/ })
    expect(link).toHaveAttribute('href', 'https://api.slack.com/apps?new_app=1')
    expect(link).toHaveAttribute('target', '_blank')
  })

  it('C-AC-54 the GitHub guide has four steps with the permissions table and the token deep link', async () => {
    const user = userEvent.setup()
    openGuide('github')
    const guide = await screen.findByTestId('guide-github')
    expect(within(guide).getAllByTestId('guide-step')).toHaveLength(4)
    const tokenStep = document.querySelector('[data-step="token"] button[aria-expanded]') as HTMLButtonElement
    if (tokenStep.getAttribute('aria-expanded') === 'false') await user.click(tokenStep)
    expect(screen.getByTestId('permission-table')).toHaveTextContent('Contents: read and write')
    expect(screen.getByRole('link', { name: /Open GitHub token creation/ })).toHaveAttribute(
      'href',
      'https://github.com/settings/personal-access-tokens/new',
    )
  })

  it('C-AC-54 the Linear guide has three steps and links to security settings', async () => {
    const user = userEvent.setup()
    openGuide('linear')
    const guide = await screen.findByTestId('guide-linear')
    expect(within(guide).getAllByTestId('guide-step')).toHaveLength(3)
    const step = document.querySelector('[data-step="key"] button[aria-expanded]') as HTMLButtonElement
    if (step.getAttribute('aria-expanded') === 'false') await user.click(step)
    expect(screen.getByRole('link', { name: /Open Linear security settings/ })).toHaveAttribute(
      'href',
      'https://linear.app/settings/account/security',
    )
  })

  it('C-AC-55 passing checks turn steps green and the progress counts them', async () => {
    openGuide('linear')
    await screen.findAllByTestId('guide-step')
    await vi.waitFor(() => {
      const statuses = screen.getAllByTestId('guide-step').map((s) => s.getAttribute('data-status'))
      expect(statuses).toEqual(['done', 'done', 'done'])
    })
    expect(screen.getByText(/3 of 3 done/)).toBeInTheDocument()
  })

  it('C-AC-55 a failing check shows its mapped troubleshooting text and highlights the error code', async () => {
    outcome.value = 'auth_failed'
    openGuide('slack')
    const alert = await screen.findByTestId('guide-troubleshooting')
    expect(alert).toHaveTextContent('The token is wrong or was revoked. Copy it again from OAuth & Permissions.')
    const active = screen.getAllByTestId('troubleshoot').filter((t) => t.getAttribute('data-active') === 'true')
    expect(active.map((t) => t.getAttribute('data-code'))).toContain('invalid_auth')
  })

  it('C-AC-55 Check again re-runs the checks', async () => {
    const user = userEvent.setup()
    openGuide('github')
    await screen.findAllByTestId('guide-check')
    const before = mocks.connectorChecks.mock.calls.length
    await user.click(screen.getAllByRole('button', { name: 'Check again' })[0] as HTMLElement)
    await vi.waitFor(() => expect(mocks.connectorChecks.mock.calls.length).toBeGreaterThan(before))
  })

  it('C-AC-56 the Slack permissions step lists missing scopes from the token', async () => {
    outcome.value = 'missing_scope'
    openGuide('slack')
    const text = await screen.findByTestId('guide-troubleshooting')
    for (const scope of MISSING_SCOPES) expect(text).toHaveTextContent(scope)
    expect(text).toHaveTextContent('Reinstall the app after adding these scopes.')
  })

  it('C-AC-56 the GitHub step detects a token that cannot write to the push target', async () => {
    outcome.value = 'readonly'
    openGuide('github')
    const text = await screen.findByTestId('guide-troubleshooting')
    expect(text).toHaveTextContent('Contents: Read and write on the push target')
    expect(document.querySelector('[data-step="repository"]')).toHaveAttribute('data-status', 'failed')
  })

  it('C-AC-57 the guide keeps its open step after closing and reopening', async () => {
    const user = userEvent.setup()
    openGuide('slack')
    await screen.findAllByTestId('guide-step')
    const invite = document.querySelector('[data-step="invite"] button[aria-expanded]') as HTMLButtonElement
    await user.click(invite)
    expect(invite).toHaveAttribute('aria-expanded', 'true')
    act(() => useGuideStore.getState().setOpen(null))
    expect(screen.queryByTestId('guide-slack')).not.toBeInTheDocument()
    act(() => useGuideStore.getState().setOpen('slack'))
    const again = (await screen.findByTestId('guide-slack')).querySelector('[data-step="invite"] button[aria-expanded]')
    expect(again).toHaveAttribute('aria-expanded', 'true')
  })

  it('C-AC-57 Esc closes the panel and steps are buttons reachable by keyboard', async () => {
    openGuide('linear')
    const guide = await screen.findByTestId('guide-linear')
    const buttons = within(guide).getAllByRole('button', { expanded: false }).concat(within(guide).queryAllByRole('button', { expanded: true }))
    expect(buttons.length).toBeGreaterThanOrEqual(3)
    const dialog = document.querySelector('dialog') as HTMLDialogElement
    fireEvent(dialog, new Event('cancel', { cancelable: true }))
    expect(useGuideStore.getState().open).toBeNull()
  })
})

describe('guide logic', () => {
  it('hides the Socket Mode step when Actron has a public HTTPS address', () => {
    expect(visibleGuideSteps(def('slack'), false)).toHaveLength(6)
    expect(visibleGuideSteps(def('slack'), true).map((s) => s.id)).not.toContain('socket')
  })

  it('counts progress from passing checks', () => {
    expect(guideProgress(def('slack'), checksFixture('slack', 'connected'), false)).toEqual({ done: 5, total: 6, requiredLeft: 1 })
    expect(guideProgress(def('slack'), checksFixture('slack', 'pending'), false)).toEqual({ done: 0, total: 6, requiredLeft: 6 })
    expect(guideProgress(def('github'), undefined, false)).toEqual({ done: 0, total: 4, requiredLeft: 3 })
  })

  it('treats the webhook step as optional: only it left means nothing required is left', () => {
    const checks = def('github')
      .guide.filter((s) => s.checkId && s.checkId !== 'webhook_ping')
      .map((s) => ({ id: s.checkId as string, ok: true, message: 'ok' }))
    expect(guideProgress(def('github'), checks, false)).toMatchObject({ done: 3, total: 4, requiredLeft: 0 })
  })

  it('reads error codes from failing checks', () => {
    expect([...failingCodes(checksFixture('slack', 'not_in_channel'))]).toContain('not_in_channel')
    expect([...failingCodes(checksFixture('github', 'readonly'))]).toContain('403')
    expect(failingCodes(checksFixture('linear', 'connected')).size).toBe(0)
  })
})
