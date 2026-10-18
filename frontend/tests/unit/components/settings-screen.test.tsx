import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn(), back: vi.fn() }),
  usePathname: () => '/app/settings',
  useSearchParams: () => new URLSearchParams(),
}))

import { SettingsScreen, modelsHeadline } from '@/components/settings/SettingsScreen'
import { useToasts } from '@/lib/toasts'
import { installFixtureFetch, type FixtureApi } from '../helpers/fixture-fetch'
import { renderWithClient } from '../helpers/render'
import { captureUnhandled, flushRejections } from '../helpers/unhandled'

let api: FixtureApi
beforeEach(() => {
  api = installFixtureFetch()
  useToasts.getState().clear()
})
afterEach(() => api.restore())

const settingsJobs = () => (api.engine.route('GET', '/api/settings').json as { settings: { jobs: { status: string }[] } }).settings.jobs
const settingsBody = () => (api.engine.route('GET', '/api/settings').json as { settings: { budget: { capUsd: number }; thresholds: { conflict: number } } }).settings

async function ready() {
  renderWithClient(<SettingsScreen />)
  await screen.findByRole('heading', { name: /fixed, cautious answers|Every model job uses a model/ })
}

describe('C-AC-43 settings screen', () => {
  it('shows a loading headline first, then the stub count from the server', async () => {
    renderWithClient(<SettingsScreen />)
    expect(screen.getByRole('heading', { name: 'Loading settings.' })).toBeInTheDocument()
    expect(await screen.findByRole('heading', { name: /fixed, cautious answers\.$/ })).toBeInTheDocument()
    expect(screen.getByTestId('model-keys-hint')).toHaveTextContent('TYPESAFE_API_KEY')
  })

  it('names the headline plainly for none, some and all jobs without a model key', () => {
    expect(modelsHeadline([{ status: 'live' }])).toBe('Every model job uses a model.')
    expect(modelsHeadline([{ status: 'stub' }, { status: 'stub' }])).toBe('No model keys are set, so all 2 jobs use fixed, cautious answers.')
    expect(modelsHeadline([{ status: 'stub' }, { status: 'live' }])).toBe('1 of 2 jobs have no model key and use fixed, cautious answers.')
  })

  it('lists connections with distinct names and schedules, and the models table says once what each job runs on', async () => {
    await ready()
    const conn = within(screen.getByRole('region', { name: /Sources and sync schedules/ }))
    const items = await conn.findAllByRole('listitem')
    expect(items).not.toHaveLength(0)
    const names = items.map((li) => li.querySelector('.font-medium')?.textContent)
    expect(new Set(names).size).toBe(names.length)
    const table = within(screen.getByRole('table'))
    expect(table.queryAllByText(/^(LIVE|STUB)$/)).toHaveLength(0)
    // When every job runs on the same fallback, the summary line above the table says it once and the column is left out.
    const headers = table.getAllByRole('columnheader').map((h) => h.textContent)
    const allFallback = settingsJobs().every((j) => j.status === 'stub')
    expect(headers).toEqual(allFallback ? ['Job', 'Kind'] : ['Job', 'Kind', 'Runs on'])
    if (allFallback) expect(screen.getByTestId('model-keys-hint')).toHaveTextContent('Every job below has no model key')
  })

  it('has a bot identity section at #bot-identity', async () => {
    await ready()
    const section = document.getElementById('bot-identity')
    expect(section).not.toBeNull()
    expect(within(section as HTMLElement).getByLabelText('Bot name for commits')).toBeInTheDocument()
  })

  it('Save stays disabled until something changes, then saves the patch and shows a toast', async () => {
    const user = userEvent.setup()
    await ready()
    const save = screen.getByRole('button', { name: 'Save changes' })
    expect(save).toBeDisabled()
    const name = screen.getByLabelText('Bot name for commits')
    await user.clear(name)
    await user.type(name, 'Actron Robot')
    expect(save).toBeEnabled()
    await user.click(save)
    await waitFor(() => expect(api.calls.some((c) => c.method === 'PUT' && c.path === '/api/settings')).toBe(true))
    const put = api.calls.find((c) => c.method === 'PUT')
    expect(put?.body).toMatchObject({ botIdentity: { name: 'Actron Robot' } })
    await waitFor(() => expect(useToasts.getState().toasts.some((t) => t.title === 'Settings saved.')).toBe(true))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Save changes' })).toBeDisabled())
    expect(screen.getByLabelText('Bot name for commits')).toHaveValue('Actron Robot')
  })

  it('shows a plain message under a threshold that is out of range and blocks saving', async () => {
    const user = userEvent.setup()
    await ready()
    const field = screen.getByLabelText('Conflict threshold')
    await user.clear(field)
    await user.type(field, '1.5')
    await user.tab()
    expect(await screen.findByText('Use a number between 0 and 1, such as 0.8.')).toBeInTheDocument()
    expect(field).toHaveAttribute('aria-invalid', 'true')
    expect(screen.getByRole('button', { name: 'Save changes' })).toBeDisabled()
  })

  it('rejects a possible-conflict threshold above the conflict threshold', async () => {
    const user = userEvent.setup()
    await ready()
    const conflict = screen.getByLabelText('Conflict threshold')
    await user.clear(conflict)
    await user.type(conflict, '0.4')
    await user.click(screen.getByLabelText('Bot name for commits'))
    expect(await screen.findByText('Keep this at or below the conflict threshold.')).toBeInTheDocument()
  })

  it('validates approver ids and the bot email on blur', async () => {
    const user = userEvent.setup()
    await ready()
    await user.type(screen.getByLabelText('Approvers'), ', nope')
    const email = screen.getByLabelText('Bot email for commits')
    await user.clear(email)
    await user.type(email, 'x')
    await user.tab()
    expect(await screen.findByText(/Use Slack user ids such as U04ABCDEF/)).toBeInTheDocument()
    expect(screen.getByText(/Use an email address such as/)).toBeInTheDocument()
  })

  it('the public replays checkbox is part of the saved patch', async () => {
    const user = userEvent.setup()
    await ready()
    const box = screen.getByRole('checkbox', { name: /Allow public replays/ })
    const before = (box as HTMLInputElement).checked
    await user.click(box)
    await user.click(screen.getByRole('button', { name: 'Save changes' }))
    await waitFor(() => expect(api.calls.some((c) => c.method === 'PUT')).toBe(true))
    expect(api.calls.find((c) => c.method === 'PUT')?.body).toMatchObject({ allowPublicReplays: !before })
  })

  it('C-AC-18 a refused save keeps the edits on screen and shows the reason', async () => {
    const user = userEvent.setup()
    api.override('PUT', '/api/settings', { status: 409, json: { error: { code: 'invalid_transition', message: 'busy' } } })
    await ready()
    const name = screen.getByLabelText('Bot name for commits')
    const unhandled = captureUnhandled()
    try {
      await user.type(name, ' 2')
      await user.click(screen.getByRole('button', { name: 'Save changes' }))
      await waitFor(() => expect(useToasts.getState().toasts[0]?.title).toBe('Saving settings was refused.'))
      await flushRejections()
    } finally {
      unhandled.stop()
    }
    expect((name as HTMLInputElement).value.endsWith(' 2')).toBe(true)
    expect(screen.getByRole('button', { name: 'Save changes' })).toBeEnabled()
  })

  // BUG: Save calls `put.run(...).then(...)` with no catch, so a refused save (409) also rejects the promise
  // nobody handles. The toast is right, but the browser logs an unhandled rejection. Same for Raise the cap,
  // Disconnect, Reset cursor and the branch change (`.finally` without `.catch`).
  it('a refused save does not leave an unhandled promise rejection', async () => {
    const user = userEvent.setup()
    api.override('PUT', '/api/settings', { status: 409, json: { error: { code: 'invalid_transition', message: 'busy' } } })
    await ready()
    const unhandled = captureUnhandled()
    try {
      await user.type(screen.getByLabelText('Bot name for commits'), ' 2')
      await user.click(screen.getByRole('button', { name: 'Save changes' }))
      await waitFor(() => expect(useToasts.getState().toasts[0]?.title).toBe('Saving settings was refused.'))
      await flushRejections()
    } finally {
      unhandled.stop()
    }
    expect(unhandled.errors).toHaveLength(0)
  })

  it('raising the budget needs a cap above the current one and clears the field after', async () => {
    const user = userEvent.setup()
    await ready()
    const current = settingsBody().budget.capUsd
    const raise = screen.getByRole('button', { name: 'Raise the cap' })
    const input = screen.getByLabelText('New daily cap in US dollars')
    expect(raise).toBeDisabled()
    await user.type(input, String(current - 1))
    expect(raise).toBeDisabled()
    await user.clear(input)
    await user.type(input, String(current + 5))
    await user.click(raise)
    await waitFor(() => expect(api.calls.some((c) => c.path === '/api/settings/budget')).toBe(true))
    expect(api.calls.find((c) => c.path === '/api/settings/budget')?.body).toEqual({ capUsd: current + 5 })
    await waitFor(() => expect(input).toHaveValue(''))
  })

  it('disconnect asks first, names the source, and only then calls the server', async () => {
    const user = userEvent.setup()
    await ready()
    await screen.findAllByRole('button', { name: 'Disconnect' })
    await user.click(screen.getAllByRole('button', { name: 'Disconnect' })[0] as HTMLElement)
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText(/^Disconnect .+\?$/)).toBeInTheDocument()
    expect(within(dialog).getByText(/stored token is deleted/)).toBeInTheDocument()
    expect(api.calls.some((c) => c.method === 'DELETE')).toBe(false)
    await user.click(within(dialog).getByRole('button', { name: 'Disconnect' }))
    await waitFor(() => expect(api.calls.some((c) => c.method === 'DELETE')).toBe(true))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('cancelling the re-read dialog does nothing; confirming resets the cursor', async () => {
    const user = userEvent.setup()
    await ready()
    await screen.findAllByRole('button', { name: 'Re-read from the start' })
    await user.click(screen.getAllByRole('button', { name: 'Re-read from the start' })[0] as HTMLElement)
    let dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }))
    expect(api.calls.some((c) => c.path.endsWith('/reset-cursor'))).toBe(false)
    await user.click(screen.getAllByRole('button', { name: 'Re-read from the start' })[0] as HTMLElement)
    dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: 'Re-read from the start' }))
    await waitFor(() => expect(api.calls.some((c) => c.path.endsWith('/reset-cursor'))).toBe(true))
  })

  it('changing the working branch asks for confirmation, then patches the connection', async () => {
    const user = userEvent.setup()
    await ready()
    const field = await screen.findByLabelText('Working branch')
    const change = screen.getByRole('button', { name: 'Change' })
    expect(change).toHaveAttribute('aria-disabled', 'true')
    await user.click(change)
    expect(screen.queryByRole('dialog')).toBeNull()
    const current = (field as HTMLInputElement).value
    await user.clear(field)
    await user.type(field, 'release')
    await user.click(change)
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText(`Switch from ${current} to release?`)).toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: 'Switch and rebuild' }))
    await waitFor(() => expect(api.calls.some((c) => c.method === 'PATCH')).toBe(true))
    expect(api.calls.find((c) => c.method === 'PATCH')?.body).toEqual({ config: { workingBranch: 'release' } })
  })

  it('keeping the current branch closes the dialog without a request', async () => {
    const user = userEvent.setup()
    await ready()
    const field = await screen.findByLabelText('Working branch')
    await user.type(field, 'x')
    await user.click(screen.getByRole('button', { name: 'Change' }))
    const dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: /^Keep / }))
    expect(api.calls.some((c) => c.method === 'PATCH')).toBe(false)
  })

  // BUG: SettingsScreen checks `!draft || !original` before `q.isError`. When the first load fails there is no data,
  // so the error branch is never reached and the screen shows "Loading settings." forever, with no Retry button.
  it('a load failure shows the reason and a retry that loads settings again', async () => {
    const user = userEvent.setup()
    let fail = true
    api.override('GET', '/api/settings', () => (fail ? { status: 500, json: { error: { code: 'down', message: 'Backend is down.' } } } : api.engine.route('GET', '/api/settings')))
    renderWithClient(<SettingsScreen />)
    expect(await screen.findByText('Backend is down.', undefined, { timeout: 500 })).toBeInTheDocument()
    fail = false
    await user.click(screen.getByRole('button', { name: 'Retry' }))
    expect(await screen.findByRole('button', { name: 'Save changes' })).toBeInTheDocument()
  })

  it('with no sources it says so', async () => {
    api.restore()
    api = installFixtureFetch('empty')
    await ready()
    expect(await screen.findByText(/No sources connected/)).toBeInTheDocument()
  })
})
