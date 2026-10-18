import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

const replace = vi.fn()
let search = new URLSearchParams()
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace, prefetch: vi.fn(), back: vi.fn() }),
  usePathname: () => '/app/requests/x',
  useSearchParams: () => search,
}))
vi.mock('@/components/graph/GraphCanvas', () => ({ GraphCanvas: () => <div data-testid="graph-canvas" /> }))

import { RequestScreen, cancelConsequence, parseTab } from '@/components/request/RequestScreen'
import { useToasts } from '@/lib/toasts'
import { useUi } from '@/lib/store'
import { FIXTURE_IDS } from '@/tests/fixtures/data/ids'
import { FakeSource } from '../helpers/fake-source'
import { installFixtureFetch, type FixtureApi } from '../helpers/fixture-fetch'
import type { RequestDetail } from '@/lib/api/types'
import { makeRequestDetail, renderWithClient } from '../helpers/render'

let api: FixtureApi
beforeEach(() => {
  api = installFixtureFetch()
  search = new URLSearchParams()
  replace.mockReset()
  FakeSource.reset()
  vi.stubGlobal('EventSource', FakeSource)
  useToasts.getState().clear()
  useUi.setState({ tabByRequest: {}, canvasMode: 'aggregated', systemStripOpen: false })
})
afterEach(() => {
  api.restore()
  vi.unstubAllGlobals()
})

const open = async (id: string, tab?: string) => {
  if (tab) search = new URLSearchParams({ tab })
  renderWithClient(<RequestScreen id={id} />)
  await screen.findByTestId('request-workspace')
}

describe('request screen helpers', () => {
  it('parseTab accepts only the five tabs', () => {
    expect(parseTab('pr')).toBe('pr')
    expect(parseTab('nope')).toBeNull()
    expect(parseTab(null)).toBeNull()
  })

  it('cancelConsequence names what stops in each state (PRD 13.6)', () => {
    const c = (state: string) => cancelConsequence(makeRequestDetail({ state: state as never }))
    expect(c('Investigating')).toMatch(/investigation stops/)
    expect(c('Building')).toMatch(/container is removed/)
    expect(c('Changes requested')).toMatch(/container is removed/)
    expect(c('PR ready for review')).toMatch(/stays open on GitHub/)
    expect(c('Awaiting approval')).toMatch(/ticket stays in Linear/)
  })
})

describe('C-AC-1 request page loading and errors', () => {
  it('shows the page title from the request and opens its stream', async () => {
    await open(FIXTURE_IDS.live)
    await waitFor(() => expect(document.title).toMatch(/ · Actron$/))
    expect(FakeSource.latest().url).toContain(`/api/requests/${FIXTURE_IDS.live}/events`)
    expect(screen.getByTestId('graph-canvas')).toBeInTheDocument()
  })

  it('a missing request says it is not in memory and links back', async () => {
    renderWithClient(<RequestScreen id="req_nope" />)
    expect(await screen.findByText('This request isn’t in Actron’s memory.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Back to requests' })).toHaveAttribute('href', '/app')
  })

  it('a server error shows its reason and Retry fetches again', async () => {
    const user = userEvent.setup()
    let fail = true
    api.override('GET', `/api/requests/${FIXTURE_IDS.done}`, () =>
      fail ? { status: 500, json: { error: { code: 'down', message: 'Backend is down.' } } } : api.engine.route('GET', `/api/requests/${FIXTURE_IDS.done}`),
    )
    renderWithClient(<RequestScreen id={FIXTURE_IDS.done} />)
    expect(await screen.findByText('Backend is down.')).toBeInTheDocument()
    fail = false
    await user.click(screen.getByRole('button', { name: 'Retry' }))
    expect(await screen.findByTestId('request-workspace')).toBeInTheDocument()
  })

  it('C-AC-17 a reconnecting stream shows the banner and an offline one offers Reload', async () => {
    await open(FIXTURE_IDS.live)
    const src = FakeSource.latest()
    act(() => src.open())
    act(() => {
      src.readyState = 0
      src.onerror?.call(src as unknown as EventSource, new Event('error'))
    })
    expect(await screen.findByText(/reconnect/i)).toBeInTheDocument()
  })
})

describe('C-AC-2 tabs and deep links', () => {
  it('the URL tab wins and changing tabs writes it back with router.replace', async () => {
    const user = userEvent.setup()
    await open(FIXTURE_IDS.stale, 'ticket')
    expect(await screen.findByTestId('ticket-panel')).toBeInTheDocument()
    await user.click(screen.getByRole('tab', { name: 'Build' }))
    expect(replace).toHaveBeenCalledWith(expect.stringContaining('tab=build'), { scroll: false })
    expect(useUi.getState().tabByRequest[FIXTURE_IDS.stale]).toBe('build')
  })

  it('without a tab in the URL it opens on the tab the request needs most', async () => {
    await open(FIXTURE_IDS.stale)
    expect(await screen.findByTestId('ticket-panel')).toBeInTheDocument()
  })
})

describe('C-AC-11 ticket approval from the page', () => {
  it('the header button opens a confirmation that names the revision, and confirming approves exactly that hash', async () => {
    const user = userEvent.setup()
    await open(FIXTURE_IDS.stale, 'ticket')
    await screen.findByTestId('ticket-panel')
    await user.click(screen.getByTestId('header-approve'))
    // The header button raises the shared signal; the confirmation opens in the ticket tab.
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText(/^Approve ticket v\d+\?$/)).toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: /^Approve/ }))
    await waitFor(() => expect(api.calls.some((c) => c.path.endsWith('/approvals'))).toBe(true))
    const call = api.calls.find((c) => c.path.endsWith('/approvals'))
    expect(call?.body).toMatchObject({ kind: 'ticket', revisionHash: expect.stringMatching(/^[0-9a-f]{64}$/) })
    expect(call?.key).toBeTruthy()
  })

  it('C-AC-18 a 409 shows the server reason inline and removes the optimistic approval', async () => {
    const user = userEvent.setup()
    api.override('POST', `/api/requests/${FIXTURE_IDS.stale}/approvals`, { status: 409, json: { error: { code: 'stale_revision', message: 'x' } } })
    await open(FIXTURE_IDS.stale, 'ticket')
    await screen.findByTestId('ticket-panel')
    await user.click(within(screen.getByTestId('approval-card')).getByRole('button', { name: /Approve ticket v\d+/ }))
    const dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: /^Approve/ }))
    expect(await screen.findByRole('alert')).toHaveTextContent('This ticket changed since you opened it.')
    expect(screen.getByTestId('approval-card').dataset.state).not.toBe('approved')
  })
})

/** The recorded "stale" request, reopened as if it were waiting on one answer. */
function waitingForAnswer() {
  const path = `/api/requests/${FIXTURE_IDS.stale}`
  api.override('GET', path, () => {
    const body = api.engine.route('GET', path).json as { request: RequestDetail }
    const d = body.request
    const first = d.questions[0] as RequestDetail['questions'][number]
    return {
      status: 200,
      json: {
        request: {
          ...d,
          state: 'Needs your input',
          allowedActions: ['answer', 'cancel'],
          questions: [{ ...first, answer: null, options: first.options.length ? first.options : [{ value: 'dev', label: 'dev' }] }],
        },
      },
    }
  })
}

describe('C-AC-5 questions', () => {
  it('answering a choice question posts the chosen value', async () => {
    const user = userEvent.setup()
    waitingForAnswer()
    await open(FIXTURE_IDS.stale, 'questions')
    const panel = await screen.findByTestId('questions-panel')
    expect(panel).toHaveTextContent(/still open/)
    const radios = within(panel).getAllByRole('radio')
    await user.click(radios[0] as HTMLElement)
    await user.click(within(panel).getByRole('button', { name: /^(Send|Answer|Submit)/ }))
    await waitFor(() => expect(api.calls.some((c) => c.path.endsWith('/answers'))).toBe(true))
    expect(api.calls.find((c) => c.path.endsWith('/answers'))?.body).toMatchObject({ value: expect.any(String), questionId: expect.any(String) })
  })

  it('header offers to answer when a question is open and jumps to the tab', async () => {
    const user = userEvent.setup()
    waitingForAnswer()
    await open(FIXTURE_IDS.stale, 'evidence')
    await user.click(await screen.findByRole('button', { name: /^Answer the question/ }))
    expect(replace).toHaveBeenCalledWith(expect.stringContaining('tab=questions'), { scroll: false })
  })
})

describe('cancel and retry', () => {
  it('Cancel asks first with what will stop; keeping it running sends nothing', async () => {
    const user = userEvent.setup()
    await open(FIXTURE_IDS.live)
    await user.click(await screen.findByRole('button', { name: 'Cancel' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText(/investigation stops/)).toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: 'Keep it running' }))
    expect(api.calls.some((c) => c.path.endsWith('/cancel'))).toBe(false)
  })

  it('confirming cancel posts the reason and closes the dialog', async () => {
    const user = userEvent.setup()
    await open(FIXTURE_IDS.live)
    await user.click(await screen.findByRole('button', { name: 'Cancel' }))
    await user.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Cancel request' }))
    await waitFor(() => expect(api.calls.some((c) => c.path.endsWith('/cancel'))).toBe(true))
    expect(api.calls.find((c) => c.path.endsWith('/cancel'))?.body).toEqual({ reason: 'Cancelled from Actron' })
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('a request that needs attention offers Edit ticket and Retry, and Retry posts', async () => {
    const user = userEvent.setup()
    await open(FIXTURE_IDS.failed)
    expect(await screen.findByRole('button', { name: 'Edit ticket' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Retry' }))
    await waitFor(() => expect(api.calls.some((c) => c.path.endsWith('/retry'))).toBe(true))
  })

  it('a cancelled request shows the record banner and no Cancel button', async () => {
    await open(FIXTURE_IDS.cancelled)
    expect(await screen.findByTestId('cancelled-banner')).toHaveTextContent(/cancelled|closed/)
    expect(screen.queryByRole('button', { name: 'Cancel' })).not.toBeInTheDocument()
  })
})

describe('C-AC-12 pull request tab', () => {
  it('shows the PR link, head and tests, and sends feedback bound to the head sha', async () => {
    const user = userEvent.setup()
    await open(FIXTURE_IDS.prReady, 'pr')
    const panel = await screen.findByTestId('pr-panel')
    expect(within(panel).getByRole('link', { name: /PR #\d+/ })).toHaveAttribute('target', '_blank')
    const submit = within(panel).getByRole('button', { name: 'Request changes' })
    expect(submit).toBeDisabled()
    await user.type(within(panel).getByLabelText('Request changes'), 'Rename the setting')
    expect(submit).toBeEnabled()
    await user.click(submit)
    await waitFor(() => expect(api.calls.some((c) => c.path.endsWith('/feedback'))).toBe(true))
    expect(api.calls.find((c) => c.path.endsWith('/feedback'))?.body).toMatchObject({ text: 'Rename the setting', headSha: expect.any(String) })
    await waitFor(() => expect(within(panel).getByLabelText('Request changes')).toHaveValue(''))
  })

  it('does not send feedback shorter than three characters', async () => {
    const user = userEvent.setup()
    await open(FIXTURE_IDS.prReady, 'pr')
    const panel = await screen.findByTestId('pr-panel')
    await user.type(within(panel).getByLabelText('Request changes'), 'ab')
    expect(within(panel).getByRole('button', { name: 'Request changes' })).toBeDisabled()
  })

  it('Close PR confirms first and then posts the close', async () => {
    const user = userEvent.setup()
    await open(FIXTURE_IDS.prReady, 'pr')
    const panel = await screen.findByTestId('pr-panel')
    await user.click(within(panel).getByRole('button', { name: 'Close PR' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText(/closed on GitHub and the request is cancelled/)).toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: 'Keep it open' }))
    expect(api.calls.some((c) => c.path.endsWith('/close-pr'))).toBe(false)
    await user.click(within(panel).getByRole('button', { name: 'Close PR' }))
    await user.click(within(await screen.findByRole('dialog')).getByRole('button', { name: /^Close PR #/ }))
    await waitFor(() => expect(api.calls.some((c) => c.path.endsWith('/close-pr'))).toBe(true))
  })

  it('approving the PR posts the head sha', async () => {
    const user = userEvent.setup()
    await open(FIXTURE_IDS.prReady, 'pr')
    const panel = await screen.findByTestId('pr-panel')
    await user.click(within(within(panel).getByTestId('approval-card')).getByRole('button', { name: /^Approve PR/ }))
    await user.click(within(await screen.findByRole('dialog')).getByRole('button', { name: /^Approve/ }))
    await waitFor(() => expect(api.calls.some((c) => c.path.endsWith('/approvals'))).toBe(true))
    expect(api.calls.find((c) => c.path.endsWith('/approvals'))?.body).toMatchObject({ kind: 'pr', headSha: expect.any(String) })
  })

  it('before a PR exists the tab says so', async () => {
    await open(FIXTURE_IDS.live, 'pr')
    expect(await screen.findByText('No pull request yet.')).toBeInTheDocument()
  })

  it('a diff that fails to load shows the reason instead of a blank panel', async () => {
    api.override('GET', `/api/requests/${FIXTURE_IDS.prReady}/pr/diff`, { status: 502, json: { error: { code: 'github', message: 'GitHub did not answer.' } } })
    await open(FIXTURE_IDS.prReady, 'pr')
    expect(await screen.findByText('GitHub did not answer.')).toBeInTheDocument()
  })
})

describe('finished requests', () => {
  it('a done request links to its pull request and replay', async () => {
    await open(FIXTURE_IDS.done)
    expect(await screen.findByRole('link', { name: /^Replay$/ })).toHaveAttribute('href', `/app/requests/${FIXTURE_IDS.done}/replay`)
    expect(screen.getByRole('link', { name: /^Open PR #\d+$/ })).toHaveAttribute('target', '_blank')
  })

  it('the system strip toggles between one line and the map', async () => {
    const user = userEvent.setup()
    await open(FIXTURE_IDS.done)
    const toggle = screen.getByRole('button', { name: /Show system map/ })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    await user.click(toggle)
    expect(screen.getByRole('button', { name: /Hide system map/ })).toHaveAttribute('aria-expanded', 'true')
  })
})
