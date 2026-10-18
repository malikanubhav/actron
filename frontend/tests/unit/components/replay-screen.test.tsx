import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn(), back: vi.fn() }),
  usePathname: () => '/app/requests/x/replay',
  useSearchParams: () => new URLSearchParams(),
}))
vi.mock('@/components/graph/GraphCanvas', () => ({ GraphCanvas: () => <div data-testid="graph-canvas" /> }))

import { ReplayScreen, tabForEvent } from '@/components/replay/ReplayScreen'
import { FIXTURE_IDS } from '@/tests/fixtures/data/ids'
import { installFixtureFetch, type FixtureApi } from '../helpers/fixture-fetch'
import { makeEvent, renderWithClient } from '../helpers/render'

let api: FixtureApi
beforeEach(() => {
  api = installFixtureFetch()
})
afterEach(() => api.restore())

const step = () => screen.getByTestId('replay-sentence').textContent
const label = () => screen.getByTestId('request-workspace').querySelector('[data-testid="screen-header"]')?.textContent ?? ''

describe('tabForEvent (C-AC-26)', () => {
  it.each([
    ['evidence.found', 'evidence'],
    ['investigation.completed', 'evidence'],
    ['question.asked', 'questions'],
    ['answer.received', 'questions'],
    ['ticket.revised', 'ticket'],
    ['approval.recorded', 'ticket'],
    ['build.step', 'build'],
    ['tests.result', 'build'],
    ['handoff.created', 'build'],
    ['pr.opened', 'pr'],
    ['writeback.done', 'pr'],
    ['tool.called', null],
  ])('%s opens the %s tab', (type, tab) => {
    expect(tabForEvent(makeEvent(type))).toBe(tab)
  })
  it('no event, no tab', () => expect(tabForEvent(undefined)).toBeNull())
})

describe('C-AC-26 replay screen', () => {
  it('starts at step 0 with a prompt to press play and nothing in the timeline', async () => {
    renderWithClient(<ReplayScreen id={FIXTURE_IDS.done} />)
    await screen.findByTestId('replay-caption')
    expect(screen.getByText('Press play to start. Each step is a real recorded event.')).toBeInTheDocument()
    expect(label()).toMatch(/Replay · step 0 of \d+/)
    expect(screen.getByRole('heading', { level: 1 }).textContent).toMatch(/^Replay: .+\.$/)
    await waitFor(() => expect(document.title).toMatch(/^Replay: .+ · Actron$/))
  })

  it('stepping forward shows each recorded event as a sentence and stepping back removes it', async () => {
    const user = userEvent.setup()
    renderWithClient(<ReplayScreen id={FIXTURE_IDS.done} />)
    await screen.findByTestId('replay-caption')
    await user.click(screen.getByRole('button', { name: 'Step forward' }))
    expect(label()).toMatch(/step 1 of/)
    const first = step()
    expect(first).toBeTruthy()
    await user.click(screen.getByRole('button', { name: 'Step forward' }))
    expect(step()).not.toBe('')
    expect(label()).toMatch(/step 2 of/)
    await user.click(screen.getByRole('button', { name: 'Step back' }))
    expect(step()).toBe(first)
    await user.click(screen.getByRole('button', { name: 'Step back' }))
    expect(screen.getByRole('button', { name: 'Step back' })).toBeDisabled()
  })

  it('seeking to the end shows REPLAY · DONE, disables Step forward and offers Again', async () => {
    renderWithClient(<ReplayScreen id={FIXTURE_IDS.done} />)
    await screen.findByTestId('replay-caption')
    const slider = screen.getByRole('slider')
    const max = Number(slider.getAttribute('max'))
    fireEvent.change(slider, { target: { value: String(max) } })
    expect(label()).toContain('Replay · done')
    expect(screen.getByRole('button', { name: 'Step forward' })).toBeDisabled()
    expect(screen.getByTestId('replay-play')).toHaveTextContent('Again')
  })

  it('Play advances by itself and Pause stops it; the speed buttons are a radio group', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    try {
      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
      renderWithClient(<ReplayScreen id={FIXTURE_IDS.done} />)
      await screen.findByTestId('replay-caption')
      const speed = within(screen.getByRole('radiogroup', { name: 'Speed' }))
      await user.click(speed.getAllByRole('radio').at(-1) as HTMLElement)
      expect(speed.getAllByRole('radio').at(-1)).toHaveAttribute('aria-checked', 'true')
      await user.click(screen.getByTestId('replay-play'))
      expect(screen.getByTestId('replay-play')).toHaveTextContent('Pause')
      await act(async () => {
        await vi.advanceTimersByTimeAsync(5000)
      })
      expect(label()).not.toMatch(/step 0 of/)
      await user.click(screen.getByTestId('replay-play'))
      const frozen = label()
      await act(async () => {
        await vi.advanceTimersByTimeAsync(5000)
      })
      expect(label()).toBe(frozen)
    } finally {
      vi.useRealTimers()
    }
  })

  it('the details panel follows the story: a ticket event switches to the Ticket tab, and a clicked tab sticks', async () => {
    const user = userEvent.setup()
    renderWithClient(<ReplayScreen id={FIXTURE_IDS.done} />)
    await screen.findByTestId('replay-caption')
    const slider = screen.getByRole('slider')
    fireEvent.change(slider, { target: { value: slider.getAttribute('max') as string } })
    expect(screen.getByTestId('pr-panel')).toBeInTheDocument()
    await user.click(screen.getByRole('tab', { name: 'Build' }))
    expect(screen.queryByTestId('pr-panel')).not.toBeInTheDocument()
  })

  it('a replay of a request that is still running says so and links to the live request', async () => {
    renderWithClient(<ReplayScreen id={FIXTURE_IDS.live} />)
    expect(await screen.findByText('This request is still running.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Open the live request' })).toHaveAttribute('href', `/app/requests/${FIXTURE_IDS.live}`)
  })

  it('an unknown replay says it is not available', async () => {
    renderWithClient(<ReplayScreen id="req_missing" />)
    expect(await screen.findByText('This replay is not available.')).toBeInTheDocument()
  })

  it('a public replay uses the public route and has no link to the live request', async () => {
    api.override('GET', `/api/public/replays/${FIXTURE_IDS.done}`, () => api.engine.route('GET', `/api/requests/${FIXTURE_IDS.done}/replay`))
    renderWithClient(<ReplayScreen id={FIXTURE_IDS.done} isPublic />)
    await screen.findByTestId('replay-caption')
    expect(api.calls.some((c) => c.path === `/api/public/replays/${FIXTURE_IDS.done}`)).toBe(true)
    expect(api.calls.some((c) => c.path.startsWith('/api/graph/subgraph'))).toBe(false)
  })

  it('a failed public replay offers no way into the live app', async () => {
    api.override('GET', '/api/public/replays/req_x', { status: 500, json: { error: { code: 'down', message: 'Nope.' } } })
    renderWithClient(<ReplayScreen id="req_x" isPublic />)
    expect(await screen.findByText('Nope.')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Open the live request' })).not.toBeInTheDocument()
  })
})
