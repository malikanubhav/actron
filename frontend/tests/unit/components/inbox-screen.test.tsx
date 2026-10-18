import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn(), back: vi.fn() }),
  usePathname: () => '/app/inbox',
  useSearchParams: () => new URLSearchParams(),
}))

import { InboxScreen } from '@/components/inbox/InboxScreen'
import { useToasts } from '@/lib/toasts'
import { installFixtureFetch, type FixtureApi } from '../helpers/fixture-fetch'
import { renderWithClient } from '../helpers/render'

let api: FixtureApi
beforeEach(() => {
  api = installFixtureFetch()
  useToasts.getState().clear()
})
afterEach(() => api.restore())

const groupOf = (name: string) => within(screen.getByRole('region', { name }))
const prItem = () => screen.getAllByTestId('inbox-item').find((i) => i.querySelector('a[href$="?tab=pr"]')) as HTMLElement
const prBlock = () => prItem().closest('[data-testid="inbox-request"]') as HTMLElement

/** Waits until the request list has arrived, so each block knows its current ask. */
async function loaded() {
  await waitFor(() => expect(document.querySelectorAll('[data-current="true"]').length).toBeGreaterThan(0))
  await waitFor(() => expect(screen.getByRole('heading', { level: 1 }).textContent).toMatch(/notice/))
}

describe('inbox screen', () => {
  it('shows a loading headline, then one block per request under the state groups Home uses', async () => {
    renderWithClient(<InboxScreen />)
    expect(screen.getByRole('heading', { name: 'Loading your inbox…' })).toBeInTheDocument()
    await loaded()
    expect(groupOf('Stopped').getByText('cider-nrepl no longer loads first.')).toBeInTheDocument()
    expect(groupOf('Waiting for a decision').getAllByTestId('inbox-request').length).toBeGreaterThanOrEqual(2)
    const blocks = screen.getAllByTestId('inbox-request').map((b) => b.dataset.request)
    expect(new Set(blocks).size).toBe(blocks.length)
  })

  it('the headline counts notices, the requests they are about and the new ones', async () => {
    renderWithClient(<InboxScreen />)
    await loaded()
    const items = screen.getAllByTestId('inbox-item')
    const unread = items.filter((i) => i.dataset.unread === 'true').length
    const requests = screen.getAllByTestId('inbox-request').length
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe(`${items.length} notices on ${requests} requests. ${unread} are new.`)
  })

  it('older notices on a request read as history, folded, with no action', async () => {
    api.override('GET', '/api/notifications', () => ({
      status: 200,
      json: {
        unread: 2,
        notifications: [
          { id: 'h1', kind: 'pr_ready', title: 'PR #16 is ready for review.', body: 'x', requestId: 'req_01JCALVA0PRRDY000000006', tab: 'pr', readAt: null, createdAt: '2026-10-17T09:00:00Z' },
          { id: 'h2', kind: 'awaiting_approval', title: 'Ticket v1 is ready for your approval.', body: 'x', requestId: 'req_01JCALVA0PRRDY000000006', tab: 'ticket', readAt: null, createdAt: '2026-10-16T09:00:00Z' },
        ],
      },
    }))
    renderWithClient(<InboxScreen />)
    await loaded()
    const past = screen.getAllByTestId('inbox-item').find((i) => i.dataset.current === 'false') as HTMLElement
    expect(past).toHaveTextContent(/^Ticket v1 was sent for approval · approved/)
    expect(past.closest('details')).not.toBeNull()
    expect(screen.getByText('History (1)')).toBeInTheDocument()
    expect(within(past).queryByText('Approve ticket')).toBeNull()
  })

  it('each ask leads with the fact, links to its tab and says what to do', async () => {
    renderWithClient(<InboxScreen />)
    await loaded()
    const pr = within(prItem()).getByRole('link')
    expect(pr).toHaveAttribute('href', expect.stringMatching(/^\/app\/requests\/req_.+\?tab=pr$/))
    expect(within(pr).getByText('PR #16 is ready for your review.')).toBeInTheDocument()
    expect(within(pr).getByText('Review PR')).toBeInTheDocument()
    expect(screen.queryByText(/J \/ K to move/i)).toBeNull()
  })

  it('Mark read on a block marks that request only, then goes away', async () => {
    const user = userEvent.setup()
    renderWithClient(<InboxScreen />)
    await loaded()
    await user.click(within(prBlock()).getByRole('button', { name: 'Mark read' }))
    await waitFor(() => expect(api.calls.filter((c) => c.method === 'POST' && c.path.endsWith('/read'))).toHaveLength(1))
    expect(api.calls.find((c) => c.path.endsWith('/read'))?.path).toBe('/api/notifications/ntf_fixture_1/read')
    await waitFor(() => expect(prItem().dataset.unread).toBe('false'))
    expect(within(prBlock()).queryByRole('button', { name: 'Mark read' })).toBeNull()
  })

  it('one Mark read per request marks every unread item in it', async () => {
    const user = userEvent.setup()
    const base = { title: 't', requestId: 'req_x', tab: 'questions', readAt: null }
    api.override('GET', '/api/notifications', () => ({
      status: 200,
      json: {
        unread: 2,
        notifications: [
          { ...base, id: 'a1', kind: 'needs_input', body: 'X: First?', createdAt: '2026-10-17T09:00:00Z' },
          { ...base, id: 'a2', kind: 'awaiting_approval', body: 'X', createdAt: '2026-10-17T08:00:00Z' },
        ],
      },
    }))
    renderWithClient(<InboxScreen />)
    const buttons = await screen.findAllByRole('button', { name: 'Mark read' })
    expect(buttons).toHaveLength(1)
    await user.click(buttons[0] as HTMLElement)
    await waitFor(() => expect(api.calls.filter((c) => c.path.endsWith('/read')).map((c) => c.path).sort()).toEqual(['/api/notifications/a1/read', '/api/notifications/a2/read']))
  })

  it('opening an unread item marks it read; opening a read item does not', async () => {
    renderWithClient(<InboxScreen />)
    await loaded()
    const readItem = screen.getAllByTestId('inbox-item').find((i) => i.dataset.unread === 'false') as HTMLElement
    const unreadItem = screen.getAllByTestId('inbox-item').find((i) => i.dataset.unread === 'true') as HTMLElement
    // jsdom cannot navigate; stop the default so only the click handler runs.
    const stop = (e: Event) => e.preventDefault()
    document.addEventListener('click', stop)
    fireEvent.click(within(readItem).getByRole('link'))
    expect(api.calls.some((c) => c.path.endsWith('/read'))).toBe(false)
    fireEvent.click(within(unreadItem).getByRole('link'))
    document.removeEventListener('click', stop)
    await waitFor(() => expect(api.calls.some((c) => c.path.endsWith('/read'))).toBe(true))
  })

  it('C-AC-18 when marking read fails the item stays unread and a toast gives the reason', async () => {
    const user = userEvent.setup()
    api.override('POST', '/api/notifications/ntf_fixture_1/read', { status: 500, json: { error: { code: 'down', message: 'Try again later.' } } })
    renderWithClient(<InboxScreen />)
    await loaded()
    await user.click(within(prBlock()).getByRole('button', { name: 'Mark read' }))
    await waitFor(() => expect(useToasts.getState().toasts[0]?.title).toBe('Marking as read did not go through.'))
    expect(useToasts.getState().toasts[0]?.body).toBe('Try again later.')
    await waitFor(() => expect(prItem().dataset.unread).toBe('true'))
  })

  it('j and k move focus through the rows', async () => {
    const user = userEvent.setup()
    renderWithClient(<InboxScreen />)
    await loaded()
    const rows = Array.from(document.querySelectorAll<HTMLElement>('[data-row]'))
    await user.keyboard('j')
    expect(rows[0]).toHaveFocus()
    await user.keyboard('j')
    expect(rows[1]).toHaveFocus()
    await user.keyboard('k')
    expect(rows[0]).toHaveFocus()
  })

  it('an empty inbox says there are no notices', async () => {
    api.restore()
    api = installFixtureFetch('empty')
    renderWithClient(<InboxScreen />)
    expect(await screen.findByRole('heading', { level: 1, name: 'No notices yet.' })).toBeInTheDocument()
    expect(screen.getByText(/Actron interrupts only for four things/)).toBeInTheDocument()
  })

  it('a failed load shows the reason and Retry loads the list again', async () => {
    const user = userEvent.setup()
    let fail = true
    api.override('GET', '/api/notifications', () =>
      fail ? { status: 500, json: { error: { code: 'down', message: 'Backend is down.' } } } : api.engine.route('GET', '/api/notifications'),
    )
    renderWithClient(<InboxScreen />)
    expect(await screen.findByText('Backend is down.')).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 1, name: 'The inbox could not be loaded.' })).toBeInTheDocument()
    fail = false
    await user.click(screen.getByRole('button', { name: 'Retry' }))
    expect((await screen.findAllByTestId('inbox-item')).length).toBeGreaterThan(0)
  })

  it('notifications for a request that no longer waits are earlier; empty groups take one line', async () => {
    api.override('GET', '/api/notifications', () => ({
      status: 200,
      json: {
        unread: 1,
        notifications: [{ id: 'n9', kind: 'pr_ready', title: 'PR #1 is ready.', body: 'Old request: merged', requestId: 'req_x', tab: 'pr', readAt: null, createdAt: '2026-10-17T09:00:00Z' }],
      },
    }))
    renderWithClient(<InboxScreen />)
    expect(await screen.findByRole('heading', { level: 1, name: '1 notice on 1 request. It is new.' })).toBeInTheDocument()
    await waitFor(() => expect(groupOf('No longer waiting').getAllByTestId('inbox-item')).toHaveLength(1))
    expect(groupOf('Waiting for a decision').getByText('No open questions, approvals or reviews.')).toBeInTheDocument()
  })
})
