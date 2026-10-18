import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, waitFor, within, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ConnectorForm, oauthMessage } from '@/components/connect/ConnectorForm'
import { def, installEndpoints, renderWithClient } from './helpers'
import type { ConnectorDefinition } from '@/lib/api/types'

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
})

const tokenPath = async (user: ReturnType<typeof userEvent.setup>) => {
  await user.click(screen.getByRole('button', { name: 'Connect with tokens' }))
}

describe('ConnectorForm (spec C, C12)', () => {
  it('C-AC-49 renders every root GitHub field from the definition with label, description, placeholder and default', () => {
    renderWithClient(<ConnectorForm def={def('github')} />)
    const token = screen.getByLabelText('Access token')
    expect(token).toHaveAttribute('placeholder', 'github_pat_…')
    expect(token).toHaveAccessibleDescription(/fine-grained personal access token/i)
    expect(screen.getByLabelText('Repository')).toHaveAttribute('placeholder', 'owner/name')
    expect(screen.getByLabelText(/History to read/)).toHaveValue(90)
    expect(screen.getAllByText('Where do I find this?').length).toBeGreaterThan(0)
  })

  it('C-AC-49 shows the "Where do I find this?" info text with the exact steps', async () => {
    const user = userEvent.setup()
    renderWithClient(<ConnectorForm def={def('github')} />)
    await user.click(screen.getByText('Where do I find this?'))
    expect(screen.getByText(/Developer settings → Fine-grained tokens/)).toBeVisible()
  })

  it('C-AC-49 renders no field that the definition does not list', () => {
    const custom: ConnectorDefinition = {
      provider: 'linear',
      title: 'Linear',
      label: 'X',
      guide: [],
      fields: [{ field_id: 'only', type: 'string', required: true, label: 'Only field', ui_component: 'text' }],
    }
    renderWithClient(<ConnectorForm def={custom} />)
    expect(screen.getByLabelText('Only field')).toBeInTheDocument()
    expect(screen.queryByLabelText('API key')).not.toBeInTheDocument()
  })

  it('C-AC-50 hides dependent fields until the parent validates, then fills options from the options endpoint', async () => {
    const user = userEvent.setup()
    renderWithClient(<ConnectorForm def={def('github')} />)
    expect(screen.queryByLabelText('Working branch')).not.toBeInTheDocument()
    expect(screen.queryByTestId('webhook-panel')).not.toBeInTheDocument()
    await user.type(screen.getByLabelText('Access token'), 'github_pat_good1234')
    await user.type(screen.getByLabelText('Repository'), 'BetterThanTomorrow/calva')
    await user.click(screen.getByRole('button', { name: 'Check connection' }))
    expect(await screen.findByTestId('validate-found')).toHaveTextContent('Repository found: BetterThanTomorrow/calva, default branch dev, 1,296 PRs.')
    const branch = await screen.findByLabelText('Working branch')
    await waitFor(() => expect(branch).toHaveValue('dev'))
    const options = within(branch).getAllByRole('option').map((o) => o.textContent)
    expect(options[1]).toContain('dev (default)')
    expect(options.some((o) => o?.includes('master (protected)'))).toBe(true)
    expect(mocks.connectorOptions).toHaveBeenCalledWith('github', 'working_branch', expect.objectContaining({ repository: 'BetterThanTomorrow/calva' }))
    expect(screen.getByText('Actron reads and keeps this branch in memory. Choose the branch your team builds on.')).toBeInTheDocument()
  })

  it('C-AC-50 shows a failed validation in plain words and keeps dependent fields hidden', async () => {
    const user = userEvent.setup()
    renderWithClient(<ConnectorForm def={def('github')} />)
    await user.type(screen.getByLabelText('Access token'), 'github_pat_bad')
    await user.type(screen.getByLabelText('Repository'), 'BetterThanTomorrow/calva')
    await user.click(screen.getByRole('button', { name: 'Check connection' }))
    expect(await screen.findByText(/the token is wrong or has expired/i)).toBeInTheDocument()
    expect(screen.queryByLabelText('Working branch')).not.toBeInTheDocument()
  })

  it('C-AC-50 never sends secrets to the options endpoint', async () => {
    const user = userEvent.setup()
    renderWithClient(<ConnectorForm def={def('github')} />)
    await user.type(screen.getByLabelText('Access token'), 'github_pat_secret9')
    await user.type(screen.getByLabelText('Repository'), 'BetterThanTomorrow/calva')
    await user.click(screen.getByRole('button', { name: 'Check connection' }))
    await screen.findByLabelText('Working branch')
    for (const call of mocks.connectorOptions.mock.calls) expect(JSON.stringify(call)).not.toContain('github_pat_secret9')
  })

  it('validates inline: wrong repository form and the check button stays disabled until fields are valid', async () => {
    const user = userEvent.setup()
    renderWithClient(<ConnectorForm def={def('github')} />)
    const check = screen.getByRole('button', { name: 'Check connection' })
    expect(check).toBeDisabled()
    await user.type(screen.getByLabelText('Repository'), 'calva')
    await user.tab()
    expect(screen.getByText('Use the form owner/name.')).toBeInTheDocument()
    expect(screen.getByLabelText('Repository')).toHaveAttribute('aria-invalid', 'true')
  })

  it('C-AC-51 secret fields are password inputs and are cleared after saving; only the last four characters come back', async () => {
    const user = userEvent.setup()
    renderWithClient(<ConnectorForm def={def('linear')} />)
    const key = screen.getByLabelText('API key')
    expect(key).toHaveAttribute('type', 'password')
    await user.type(key, 'lin_api_abcd9f2e')
    await user.click(screen.getByRole('button', { name: 'Check connection' }))
    await screen.findByText('Signed in as Dana Ilić, Calva team.')
    await waitFor(() => expect(screen.getByLabelText('Team')).toHaveValue('team_cal'))
    await user.click(screen.getByRole('button', { name: 'Connect' }))
    expect(await screen.findByTestId('saved-secret')).toHaveTextContent('ending in 9f2e')
    const body = mocks.createConnection.mock.calls[0]?.[0] as { config: Record<string, unknown>; secret: Record<string, string> }
    expect(body.secret.api_key).toBe('lin_api_abcd9f2e')
    expect(JSON.stringify(body.config)).not.toContain('lin_api_abcd9f2e')
    expect(screen.getByLabelText('API key')).toHaveValue('')
    expect(document.body.textContent).not.toContain('lin_api_abcd9f2e')
  })

  it('C-AC-51 sends a fresh idempotency key for each action', async () => {
    const user = userEvent.setup()
    renderWithClient(<ConnectorForm def={def('linear')} />)
    await user.type(screen.getByLabelText('API key'), 'lin_api_one')
    await user.click(screen.getByRole('button', { name: 'Check connection' }))
    await screen.findByText('Signed in as Dana Ilić, Calva team.')
    await user.click(screen.getByRole('button', { name: 'Connect' }))
    await screen.findByTestId('saved-secret')
    const validateKey = mocks.validateConnector.mock.calls[0]?.[2]
    const createKey = mocks.createConnection.mock.calls[0]?.[1]
    expect(validateKey).toMatch(/[0-9a-f-]{36}/)
    expect(createKey).toMatch(/[0-9a-f-]{36}/)
    expect(validateKey).not.toBe(createKey)
  })

  it('C-AC-52 the GitHub webhook panel shows the payload URL, a generated secret with copy, and the event list', async () => {
    const user = userEvent.setup()
    renderWithClient(<ConnectorForm def={def('github')} />)
    await user.type(screen.getByLabelText('Access token'), 'github_pat_good')
    await user.type(screen.getByLabelText('Repository'), 'BetterThanTomorrow/calva')
    await user.click(screen.getByRole('button', { name: 'Check connection' }))
    const panel = await screen.findByTestId('webhook-panel')
    expect(within(panel).getByTestId('webhook-url').textContent).toMatch(/\/webhooks\/github$/)
    expect(within(panel).getByTestId('webhook-secret').textContent).toMatch(/^whsec_/)
    expect(within(panel).getByRole('button', { name: 'Copy secret' })).toBeInTheDocument()
    expect(within(panel).getByTestId('webhook-events')).toHaveTextContent('Pull request reviews')
    expect(within(panel).getByText('application/json')).toBeInTheDocument()
  })

  it('C-AC-52 the Slack manifest panel copies the manifest', async () => {
    const user = userEvent.setup()
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
    renderWithClient(<ConnectorForm def={def('slack')} />)
    await tokenPath(user)
    const panel = screen.getByTestId('manifest-panel')
    fireEvent.click(within(panel).getByRole('button', { name: 'Copy manifest' }))
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(expect.stringContaining('socket_mode_enabled: true')))
  })

  it('C-AC-53 with OAuth configured shows both "Add to Slack" and "Connect with tokens"', async () => {
    const user = userEvent.setup()
    renderWithClient(<ConnectorForm def={def('slack')} />)
    expect(screen.getByTestId('add-to-slack')).toHaveAttribute('href', '/api/slack/install')
    expect(screen.queryByLabelText('Bot token')).not.toBeInTheDocument()
    await tokenPath(user)
    expect(screen.getByLabelText('Bot token')).toHaveAttribute('type', 'password')
    expect(screen.getByLabelText(/App-level token/)).toHaveAttribute('type', 'password')
  })

  it('C-AC-53 the token path validates the bot token and then shows the channel picker', async () => {
    const user = userEvent.setup()
    renderWithClient(<ConnectorForm def={def('slack')} />)
    await tokenPath(user)
    await user.type(screen.getByLabelText('Bot token'), 'xoxb-good-token')
    await user.click(screen.getByRole('button', { name: 'Check connection' }))
    expect(await screen.findByText('Connected to Calva team (fixture) as @Actron.')).toBeInTheDocument()
    expect(await screen.findByRole('checkbox', { name: /#calva-dev/ })).toBeInTheDocument()
  })

  it('C-AC-53 a bot token with the wrong prefix gets an inline message', async () => {
    const user = userEvent.setup()
    renderWithClient(<ConnectorForm def={def('slack')} />)
    await tokenPath(user)
    await user.type(screen.getByLabelText('Bot token'), 'xapp-wrong')
    await user.tab()
    expect(screen.getByText('This should start with xoxb-')).toBeInTheDocument()
  })

  it('C-AC-53 after a successful OAuth round trip shows the workspace and the channel picker', async () => {
    renderWithClient(<ConnectorForm def={def('slack')} oauthReturn={{ status: 'ok', team: 'Calva team (fixture)' }} />)
    expect(screen.getByTestId('oauth-result')).toHaveTextContent('Connected to Calva team (fixture) as @Actron.')
    expect(await screen.findAllByRole('checkbox', { name: /#calva/ })).toHaveLength(2)
  })

  it('C-AC-53 cancelled and expired approvals show plain errors', () => {
    expect(oauthMessage({ status: 'cancelled' }).text).toBe("You cancelled the Slack approval. Try again when you're ready.")
    expect(oauthMessage({ status: 'expired' }).text).toBe('Slack says the request expired. Start again.')
    renderWithClient(<ConnectorForm def={def('slack')} oauthReturn={{ status: 'expired' }} />)
    expect(screen.getByRole('alert')).toHaveTextContent('Slack says the request expired. Start again.')
  })

  it('C-AC-53 without OAuth configured only the token path is shown', () => {
    const slack = def('slack')
    renderWithClient(<ConnectorForm def={{ ...slack, oauth: { enabled: false, url: '' } }} />)
    expect(screen.queryByTestId('add-to-slack')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Connect with tokens' })).not.toBeInTheDocument()
    expect(screen.getByLabelText('Bot token')).toBeInTheDocument()
  })

  it('the Slack export form uploads a .zip as multipart and rejects other files', async () => {
    const user = userEvent.setup({ applyAccept: false })
    renderWithClient(<ConnectorForm def={def('slack_export')} />)
    const input = screen.getByLabelText('Slack export')
    await user.upload(input, new File(['x'], 'export.txt', { type: 'text/plain' }))
    await user.tab()
    expect(screen.getByText('Choose a .zip file.')).toBeInTheDocument()
    await user.upload(input, new File(['zip'], 'calva-export.zip', { type: 'application/zip' }))
    await user.click(screen.getByRole('button', { name: 'Import export' }))
    await waitFor(() => expect(mocks.createConnection).toHaveBeenCalled())
    expect(mocks.createConnection.mock.calls[0]?.[0]).toBeInstanceOf(FormData)
  })
})
