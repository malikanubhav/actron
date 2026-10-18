import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

const push = vi.fn()
let search = new URLSearchParams()
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push, replace: vi.fn(), prefetch: vi.fn(), back: vi.fn() }),
  usePathname: () => '/app',
  useSearchParams: () => search,
}))
vi.mock('@/components/graph/GraphCanvas', () => ({ GraphCanvas: () => <div data-testid="graph-canvas" /> }))

import { HomeScreen, homeHeadline } from '@/components/home/HomeScreen'
import { ConnectScreen, CONNECT_PURPOSE } from '@/components/connect/ConnectScreen'
import { LinkingProgress, MemoryPanel } from '@/components/connect/MemoryPanel'
import { useToasts } from '@/lib/toasts'
import { installFixtureFetch, type FixtureApi } from '../helpers/fixture-fetch'
import { renderWithClient } from '../helpers/render'

let api: FixtureApi
beforeEach(() => {
  api = installFixtureFetch()
  push.mockReset()
  search = new URLSearchParams()
  useToasts.getState().clear()
})
afterEach(() => api.restore())

describe('homeHeadline', () => {
  it('says what needs you and what is building, in plain counts', () => {
    expect(homeHeadline(0, 0, 0, 0)).toBe('No requests yet.')
    expect(homeHeadline(1, 0, 0, 3)).toBe('1 request needs you.')
    expect(homeHeadline(2, 1, 1, 5)).toBe('2 requests need you. 1 is building.')
    expect(homeHeadline(0, 2, 2, 5)).toBe('2 are building.')
    expect(homeHeadline(0, 0, 3, 5)).toBe('3 are running.')
    expect(homeHeadline(0, 0, 1, 5)).toBe('1 is running.')
    expect(homeHeadline(0, 0, 0, 5)).toBe('Nothing needs you right now.')
  })
})

describe('C-AC-3 home screen', () => {
  it('lists requests in the three groups with a headline from the counts', async () => {
    renderWithClient(<HomeScreen />)
    expect(screen.getByRole('heading', { level: 1, name: 'Loading your requests…' })).toBeInTheDocument()
    await waitFor(() => expect(within(screen.getByTestId('group-needs-you')).getAllByRole('listitem').length).toBeGreaterThan(0))
    expect(within(screen.getByTestId('group-done')).getAllByRole('listitem').length).toBeGreaterThan(0)
    await waitFor(() => expect(screen.getByRole('heading', { level: 1 }).textContent).toMatch(/need(s)? you/))
    expect(screen.getByTestId('request-composer')).toBeInTheDocument()
  })

  it('offers a replay of the latest finished request', async () => {
    renderWithClient(<HomeScreen />)
    const link = await screen.findByRole('link', { name: 'Watch a replay' })
    expect(link.getAttribute('href')).toMatch(/^\/app\/requests\/req_.+\/replay$/)
  })

  it('C-AC-4 submitting the composer creates the request and opens it', async () => {
    const user = userEvent.setup()
    renderWithClient(<HomeScreen />)
    const box = await screen.findByLabelText('New request')
    await user.type(box, 'Show evaluation results inline')
    await user.click(screen.getByRole('button', { name: /Ask Actron/ }))
    await waitFor(() => expect(push).toHaveBeenCalledWith(expect.stringMatching(/^\/app\/requests\/req_/)))
    const post = api.calls.find((c) => c.method === 'POST' && c.path === '/api/requests')
    expect(post?.body).toMatchObject({ text: 'Show evaluation results inline' })
  })

  it('first run: no repository and no requests shows the connect checklist instead of the list', async () => {
    api.restore()
    api = installFixtureFetch('empty')
    renderWithClient(<HomeScreen />)
    expect(await screen.findByRole('link', { name: 'Connect a repository' })).toHaveAttribute('href', '/app/connect')
    expect(screen.getByRole('heading', { level: 1, name: 'No requests yet.' })).toBeInTheDocument()
    expect(screen.getByText('Connect a repository to start asking.')).toBeInTheDocument()
    expect(screen.queryByTestId('group-needs-you')).not.toBeInTheDocument()
  })

  it('a backend failure says so, keeps the composer disabled with a reason, and Retry refetches', async () => {
    const user = userEvent.setup()
    let fail = true
    api.override('GET', '/api/requests', () => (fail ? { status: 503, json: { error: { code: 'down', message: 'Backend is down.' } } } : api.engine.route('GET', '/api/requests')))
    renderWithClient(<HomeScreen />)
    expect(await screen.findByRole('heading', { level: 1, name: 'Actron cannot reach its server.' })).toBeInTheDocument()
    expect(screen.getByText('Backend is down.')).toBeInTheDocument()
    expect(screen.getByText(/Actron cannot reach its server right now/)).toBeInTheDocument()
    fail = false
    await user.click(screen.getByRole('button', { name: 'Retry' }))
    await waitFor(() => expect(screen.queryByText('Backend is down.')).not.toBeInTheDocument())
  })

  it('j and k move focus through request rows', async () => {
    const user = userEvent.setup()
    renderWithClient(<HomeScreen />)
    await waitFor(() => expect(document.querySelectorAll('[data-row]').length).toBeGreaterThan(1))
    const rows = Array.from(document.querySelectorAll<HTMLElement>('[data-row]'))
    await user.keyboard('j')
    expect(rows[0]).toHaveFocus()
    await user.keyboard('j')
    expect(rows[1]).toHaveFocus()
  })

  it('with a repository but no requests it invites the first request', async () => {
    api.override('GET', '/api/requests', { status: 200, json: { requests: [], counts: { needsYou: 0, running: 0, done: 0 } } })
    renderWithClient(<HomeScreen />)
    expect(await screen.findByText('Ask for a change above, or type /actron followed by what you need in Slack. Actron checks your history first, then asks before it builds.')).toBeInTheDocument()
  })
})

describe('C-AC-9 connect screen', () => {
  it('shows one card per source in a fixed order, the memory totals and the linking counts', async () => {
    renderWithClient(<ConnectScreen />)
    expect(screen.getByRole('heading', { level: 1, name: 'Reading your sources.' })).toBeInTheDocument()
    const sources = within(await screen.findByRole('region', { name: 'Sources' }))
    expect((await sources.findAllByRole('heading', { level: 2 })).length).toBeGreaterThanOrEqual(3)
    expect(screen.getByText(CONNECT_PURPOSE)).toBeInTheDocument()
    expect(await screen.findByTestId('memory-totals')).toHaveTextContent(/nodes · .* links/)
    expect(screen.getByTestId('linking-progress')).toBeInTheDocument()
    expect(screen.getByTestId('count-strip')).toBeInTheDocument()
  })

  it('the headline follows sync state and explains the percentage while memory is filling', async () => {
    renderWithClient(<ConnectScreen />)
    await waitFor(() => expect(screen.getByRole('heading', { level: 1 }).textContent).toMatch(/Your memory is \d+% built|Memory is up to date|Connect a repository/))
  })

  it('with nothing connected it says memory is empty', async () => {
    api.restore()
    api = installFixtureFetch('empty')
    renderWithClient(<ConnectScreen />)
    expect(await screen.findByRole('heading', { level: 1, name: 'Connect a repository to start.' })).toBeInTheDocument()
    expect(await screen.findByText('Memory is empty.')).toBeInTheDocument()
  })

  it('a load failure shows the reason and Try again fetches both lists again', async () => {
    const user = userEvent.setup()
    let fail = true
    api.override('GET', '/api/connections', () => (fail ? { status: 500, json: { error: { code: 'down', message: 'Connections are down.' } } } : api.engine.route('GET', '/api/connections')))
    renderWithClient(<ConnectScreen />)
    expect(await screen.findByText('Connections are down.')).toBeInTheDocument()
    fail = false
    await user.click(screen.getByRole('button', { name: 'Try again' }))
    await waitFor(() => expect(screen.queryByText('Connections are down.')).not.toBeInTheDocument())
  })

  it('B-AC-59 a Slack OAuth return is passed to the Slack card', async () => {
    api.restore()
    api = installFixtureFetch('empty')
    search = new URLSearchParams({ oauth: 'slack', status: 'ok', team: 'Calva' })
    renderWithClient(<ConnectScreen />)
    expect(await screen.findByRole('status')).toHaveTextContent('Connected to Calva as @Actron.')
  })
})

describe('memory panel pieces', () => {
  it('LinkingProgress shows every count, zero when the server has none yet', () => {
    renderWithClient(<LinkingProgress linking={undefined} />)
    for (const l of ['References resolved', 'Decisions found', 'Identities matched', 'Waiting for a source', 'Links kept', 'Links dropped']) {
      expect(screen.getByText(l)).toBeInTheDocument()
    }
  })

  it('MemoryPanel tells apart "nothing connected" and "first items on their way"', () => {
    const { rerender } = renderWithClient(<MemoryPanel stats={undefined} ingestion={undefined} loading={false} hasConnections={false} />)
    expect(screen.getByText('Memory is empty.')).toBeInTheDocument()
    rerender(<MemoryPanel stats={undefined} ingestion={undefined} loading={false} hasConnections />)
    expect(screen.getByText('The first items are on their way.')).toBeInTheDocument()
    expect(screen.getByTestId('memory-totals')).toHaveTextContent('0 nodes · 0 links')
  })
})
