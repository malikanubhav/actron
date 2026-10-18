import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

const push = vi.fn()
const replace = vi.fn()
const refresh = vi.fn()
let pathname = '/app'
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push, replace, refresh, prefetch: vi.fn(), back: vi.fn() }),
  usePathname: () => pathname,
  useSearchParams: () => new URLSearchParams(),
}))

import { AppShell, requestIdFromPath } from '@/components/shell/AppShell'
import { Rail, NAV } from '@/components/shell/Rail'
import { FooterStatusBar, modelStatus, sourceLabel, streamText } from '@/components/shell/FooterStatusBar'
import { ToastViewport } from '@/components/shell/ToastViewport'
import { makeQueryClient } from '@/components/shell/Providers'
import { ApiError } from '@/lib/api'
import { toast, useToasts, AUTO_DISMISS_MS } from '@/lib/toasts'
import { useUi } from '@/lib/store'
import { FakeSource } from '../helpers/fake-source'
import { installFixtureFetch, type FixtureApi } from '../helpers/fixture-fetch'
import { renderWithClient } from '../helpers/render'

let api: FixtureApi
beforeEach(() => {
  api = installFixtureFetch()
  pathname = '/app'
  push.mockReset()
  replace.mockReset()
  refresh.mockReset()
  FakeSource.reset()
  vi.stubGlobal('EventSource', FakeSource)
  useToasts.getState().clear()
  useUi.setState({ paletteOpen: false, shortcutsOpen: false, approveSignal: 0, composeSignal: 0, workspaceStream: 'connecting' })
})
afterEach(() => {
  api.restore()
  vi.unstubAllGlobals()
})

describe('requestIdFromPath', () => {
  it('reads the request id from request routes only', () => {
    expect(requestIdFromPath('/app/requests/req_1')).toBe('req_1')
    expect(requestIdFromPath('/app/requests/req_1/replay')).toBe('req_1')
    expect(requestIdFromPath('/app/requests/a%20b')).toBe('a b')
    expect(requestIdFromPath('/app/inbox')).toBeNull()
  })
})

describe('C-AC-10 rail', () => {
  it('links the six screens and marks the current one', () => {
    pathname = '/app/graph'
    renderWithClient(<Rail />)
    const nav = within(screen.getByRole('navigation', { name: 'Main' }))
    for (const item of NAV) expect(nav.getByRole('link', { name: new RegExp(`^${item.label}`) })).toHaveAttribute('href', item.href)
    expect(nav.getByRole('link', { name: 'Graph' })).toHaveAttribute('aria-current', 'page')
    expect(nav.getByRole('link', { name: 'Requests' })).not.toHaveAttribute('aria-current')
  })

  it('Home stays current on request pages', () => {
    pathname = '/app/requests/req_1/replay'
    renderWithClient(<Rail />)
    expect(screen.getByRole('link', { name: 'Requests' })).toHaveAttribute('aria-current', 'page')
  })

  it('the inbox link carries the number of requests waiting on you', async () => {
    renderWithClient(<Rail />)
    expect(await screen.findByRole('link', { name: /^Inbox\s*,\s*\d+ requests? waits? on you$/ })).toBeInTheDocument()
  })

  it('the account menu shows who is signed in, and Escape closes it from inside the menu', async () => {
    const user = userEvent.setup()
    renderWithClient(<Rail />)
    const button = await screen.findByRole('button', { name: /^Account:/ })
    await user.click(button)
    const menu = screen.getByRole('menu', { name: 'Account' })
    expect(within(menu).getByRole('menuitem', { name: 'Settings' })).toHaveAttribute('href', '/app/settings')
    expect(button).toHaveAttribute('aria-expanded', 'true')
    within(menu).getByRole('menuitem', { name: 'Sign out' }).focus()
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  })

  // BUG: the Escape handler sits on the menu element, but opening the menu leaves focus on the trigger button,
  // which is outside it. A keyboard user who opens the menu and presses Escape sees nothing happen.
  it('Escape closes the account menu right after it is opened with the keyboard', async () => {
    const user = userEvent.setup()
    renderWithClient(<Rail />)
    const button = await screen.findByRole('button', { name: /^Account:/ })
    button.focus()
    await user.keyboard('{Enter}')
    expect(screen.getByRole('menu', { name: 'Account' })).toBeInTheDocument()
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  })

  it('Sign out calls logout, then goes to sign-in even when logout fails', async () => {
    const user = userEvent.setup()
    api.override('POST', '/api/auth/logout', { status: 500, json: { error: { code: 'down', message: 'x' } } })
    renderWithClient(<Rail />)
    await user.click(await screen.findByRole('button', { name: /^Account:/ }))
    await user.click(screen.getByRole('menuitem', { name: 'Sign out' }))
    await waitFor(() => expect(replace).toHaveBeenCalledWith('/app/signin'))
    expect(refresh).toHaveBeenCalled()
    expect(api.calls.some((c) => c.method === 'POST' && c.path === '/api/auth/logout')).toBe(true)
  })
})

describe('footer status bar', () => {
  it('sourceLabel names the source and its state', () => {
    const now = Date.parse('2026-10-17T10:00:00Z')
    const s = (provider: string, state: string, lastSyncedAt: string | null = null) => ({ provider, state, lastSyncedAt }) as never
    expect(sourceLabel(s('github', 'NOT CONNECTED'), now)).toBe('GITHUB · NOT CONNECTED')
    expect(sourceLabel(s('slack_export', 'BACKFILLING'), now)).toBe('SLACK EXPORT · BACKFILLING')
    expect(sourceLabel(s('code', 'UP TO DATE'), now)).toBe('CODE · SYNCED NOW')
    expect(sourceLabel(s('linear', 'UP TO DATE', '2026-10-17T09:55:00Z'), now)).toMatch(/^LINEAR · SYNCED /)
  })

  it('modelStatus says live only when a Jev job is live', () => {
    expect(modelStatus(undefined)).toEqual({ text: 'MODELS · UNKNOWN', tone: 'idle' })
    expect(modelStatus({ jobs: [{ provider: 'jev', status: 'live' }] } as never).text).toBe('JEV · LIVE')
    expect(modelStatus({ jobs: [{ provider: 'jev', status: 'stub' }, { provider: 'llm', status: 'live' }] } as never).text).toBe('JEV · NO KEY')
  })

  it('streamText covers every stream state', () => {
    expect(streamText('live').text).toBe('LIVE')
    expect(streamText('connecting').text).toBe('RECONNECTING')
    expect(streamText('reconnecting').tone).toBe('possible')
    expect(streamText('offline')).toEqual({ text: 'OFFLINE', tone: 'conflict' })
    expect(streamText('closed').text).toBe('CLOSED')
  })

  it('shows sources, models and the stream state from the server and the store', async () => {
    useUi.setState({ workspaceStream: 'live' })
    renderWithClient(<FooterStatusBar />)
    expect(await screen.findByText(/^\d+ SOURCES? CONNECTED$/)).toBeInTheDocument()
    expect(screen.getByTestId('stream-status')).toHaveTextContent('STREAM · LIVE')
    await waitFor(() => expect(screen.getByText(/^JEV · (LIVE|NO KEY)$/)).toBeInTheDocument())
  })

  it('says ingestion is unavailable when the status call fails', async () => {
    api.override('GET', '/api/ingestion/status', { status: 500, json: { error: { code: 'down', message: 'x' } } })
    renderWithClient(<FooterStatusBar />)
    expect(await screen.findByText('INGESTION · UNAVAILABLE')).toBeInTheDocument()
    expect(screen.getByText('SOURCES · UNKNOWN')).toBeInTheDocument()
  })

  it('warns when the daily budget is reached', async () => {
    api.override('GET', '/api/settings', () => {
      const body = api.engine.route('GET', '/api/settings').json as { settings: { budget: { spentTodayUsd: number; capUsd: number } } }
      return { status: 200, json: { settings: { ...body.settings, budget: { ...body.settings.budget, spentTodayUsd: body.settings.budget.capUsd } } } }
    })
    renderWithClient(<FooterStatusBar />)
    expect(await screen.findByText(/^DAILY BUDGET REACHED · /)).toBeInTheDocument()
  })
})

describe('toast viewport', () => {
  it('shows at most three toasts, newest last, errors as alerts', () => {
    renderWithClient(<ToastViewport />)
    act(() => {
      toast.info('one')
      toast.success('two')
      toast.error('three', { body: 'Because.' })
      toast.needsYou('four')
    })
    const items = screen.getAllByTestId('toast')
    expect(items.map((i) => i.textContent)).toEqual([expect.stringContaining('two'), expect.stringContaining('three'), expect.stringContaining('four')])
    expect(screen.getByRole('alert')).toHaveTextContent('Because.')
  })

  it('dismisses on click; info toasts leave by themselves after six seconds, errors stay', () => {
    vi.useFakeTimers()
    try {
      renderWithClient(<ToastViewport />)
      act(() => {
        toast.info('fades')
        toast.error('stays')
      })
      act(() => void vi.advanceTimersByTime(AUTO_DISMISS_MS + 10))
      expect(screen.queryByText('fades')).not.toBeInTheDocument()
      expect(screen.getByText('stays')).toBeInTheDocument()
      act(() => screen.getByRole('button', { name: 'Dismiss' }).click())
      expect(screen.queryByText('stays')).not.toBeInTheDocument()
    } finally {
      vi.useRealTimers()
    }
  })

  it('an action with a link opens it and dismisses; an action with a handler runs it', () => {
    const onClick = vi.fn()
    renderWithClient(<ToastViewport />)
    act(() => {
      toast.error('Linked', { action: { label: 'Open', href: '/app/requests/r1' }, delivery: 'Approved in Slack by Sam.' })
      toast.error('Handled', { action: { label: 'Do it', onClick } })
    })
    expect(screen.getByRole('link', { name: 'Open' })).toHaveAttribute('href', '/app/requests/r1')
    expect(screen.getByText('Approved in Slack by Sam.')).toBeInTheDocument()
    act(() => screen.getByRole('button', { name: 'Do it' }).click())
    expect(onClick).toHaveBeenCalledOnce()
    expect(screen.queryByText('Handled')).not.toBeInTheDocument()
  })
})

describe('C-AC-14 app shell shortcuts', () => {
  const renderShell = () =>
    renderWithClient(
      <AppShell>
        <p>page body</p>
      </AppShell>,
    )

  it('renders the page inside main with a skip link and opens the workspace stream', () => {
    renderShell()
    expect(within(screen.getByRole('main')).getByText('page body')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Skip to main content' })).toHaveAttribute('href', '#main')
    expect(FakeSource.latest().url).toBe('/api/stream')
  })

  it('g then i goes to the inbox; g then h to home', async () => {
    const user = userEvent.setup()
    renderShell()
    await user.keyboard('gi')
    expect(push).toHaveBeenLastCalledWith('/app/inbox')
    await user.keyboard('gh')
    expect(push).toHaveBeenLastCalledWith('/app')
  })

  it('? opens the shortcut sheet', async () => {
    const user = userEvent.setup()
    renderShell()
    await user.keyboard('?')
    expect(useUi.getState().shortcutsOpen).toBe(true)
    expect(await screen.findByRole('dialog', { name: /Shortcuts/ })).toBeInTheDocument()
  })

  it('Ctrl+K toggles the palette', async () => {
    const user = userEvent.setup()
    renderShell()
    await user.keyboard('{Control>}k{/Control}')
    expect(useUi.getState().paletteOpen).toBe(true)
    await user.keyboard('{Control>}k{/Control}')
    expect(useUi.getState().paletteOpen).toBe(false)
  })

  it('n goes home first when elsewhere and asks the composer to focus', async () => {
    const user = userEvent.setup()
    pathname = '/app/inbox'
    renderShell()
    await user.keyboard('n')
    expect(push).toHaveBeenCalledWith('/app')
    expect(useUi.getState().composeSignal).toBe(1)
  })

  it('a approves only on a request page', async () => {
    const user = userEvent.setup()
    renderShell()
    await user.keyboard('a')
    expect(useUi.getState().approveSignal).toBe(0)
  })

  it('a on a request page raises the approve signal', async () => {
    const user = userEvent.setup()
    pathname = '/app/requests/req_1'
    renderShell()
    await user.keyboard('a')
    expect(useUi.getState().approveSignal).toBe(1)
  })

  it('shortcuts do not fire while typing in a field', async () => {
    const user = userEvent.setup()
    render_with_input()
    await user.click(screen.getByRole('textbox'))
    await user.keyboard('gi')
    expect(push).not.toHaveBeenCalled()

    function render_with_input() {
      renderWithClient(
        <AppShell>
          <input aria-label="field" />
        </AppShell>,
      )
    }
  })
})

describe('makeQueryClient retry policy (C-AC-16)', () => {
  const retry = makeQueryClient().getDefaultOptions().queries?.retry as (n: number, e: unknown) => boolean
  it('never retries a client error', () => {
    expect(retry(0, new ApiError('not_found', 'x', 404))).toBe(false)
    expect(retry(0, new ApiError('conflict', 'x', 409))).toBe(false)
  })
  it('retries a server error once and other errors twice', () => {
    expect(retry(0, new ApiError('boom', 'x', 500))).toBe(true)
    expect(retry(1, new ApiError('boom', 'x', 500))).toBe(false)
    expect(retry(1, new Error('network'))).toBe(true)
    expect(retry(2, new Error('network'))).toBe(false)
  })
  it('never retries mutations', () => {
    expect(makeQueryClient().getDefaultOptions().mutations?.retry).toBe(false)
  })
})
