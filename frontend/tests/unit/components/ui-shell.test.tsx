import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { useState } from 'react'

const push = vi.fn()
const replace = vi.fn()
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push, replace, prefetch: vi.fn(), back: vi.fn() }),
  usePathname: () => '/app',
  useSearchParams: () => new URLSearchParams(),
}))

import { Button, LinkButton } from '@/components/ui/Button'
import { Dialog } from '@/components/ui/Dialog'
import { Tabs } from '@/components/ui/Tabs'
import { Tooltip } from '@/components/ui/Tooltip'
import { EmptyState, ErrorState, OfflineBanner, PartialState, ReconnectingBanner } from '@/components/states/States'
import { SkeletonBlock, SkeletonCanvas, SkeletonColumn, SkeletonHeader, SkeletonRows, SkeletonText } from '@/components/states/Skeleton'
import { OnboardingChecklist, onboardingSteps } from '@/components/core/OnboardingChecklist'
import { UnsavedChangesGuard, UNSAVED_MESSAGE } from '@/components/core/UnsavedChangesGuard'
import { ReplayControls, SPEEDS } from '@/components/replay/ReplayControls'
import { NotFoundContent, ServerErrorContent } from '@/components/states/NotFound'
import { SmallScreenNotice, SMALL_SCREEN_TEXT } from '@/components/shell/SmallScreenNotice'
import { RequestRow, pipelineStatus, Avatar } from '@/components/home/RequestRow'
import { RequestComposer } from '@/components/home/RequestComposer'
import { CommandPalette } from '@/components/shell/CommandPalette'
import { useUi } from '@/lib/store'
import type { ConnectionView } from '@/lib/api/types'
import { makeRequestDetail, renderWithClient } from '../helpers/render'

beforeEach(() => {
  push.mockReset()
  replace.mockReset()
  window.localStorage.clear()
})
afterEach(() => vi.unstubAllGlobals())

describe('C-AC-8 Button, Dialog, Tabs, Tooltip', () => {
  it('loading buttons are disabled, busy and show the loading text', () => {
    render(
      <Button loading loadingText="Saving" variant="primary">
        Save
      </Button>,
    )
    const b = screen.getByRole('button', { name: 'Saving' })
    expect(b).toBeDisabled()
    expect(b).toHaveAttribute('aria-busy', 'true')
  })

  it('shortcut hints are exposed to assistive technology', () => {
    const onClick = vi.fn()
    render(
      <Button shortcut="A" onClick={onClick}>
        Approve
      </Button>,
    )
    const b = screen.getByRole('button', { name: /Approve/ })
    expect(b).toHaveAttribute('aria-keyshortcuts', 'A')
    expect(b).toHaveAttribute('type', 'button')
    fireEvent.click(b)
    expect(onClick).toHaveBeenCalled()
  })

  it('external link buttons open in a new tab', () => {
    render(
      <LinkButton href="https://github.com" external>
        GitHub
      </LinkButton>,
    )
    expect(screen.getByRole('link', { name: 'GitHub' })).toHaveAttribute('target', '_blank')
  })

  it('Dialog opens modally with its title, and Esc or Close calls onClose', () => {
    function Harness() {
      const [open, setOpen] = useState(true)
      return (
        <Dialog open={open} onClose={() => setOpen(false)} title="Cancel this request?" label="CANCEL" footer={<button>Keep</button>}>
          <p>The build stops.</p>
        </Dialog>
      )
    }
    render(<Harness />)
    const dialog = screen.getByRole('dialog', { name: 'Cancel this request?' })
    expect(dialog).toHaveAttribute('open')
    expect(screen.getByText('The build stops.')).toBeInTheDocument()
    fireEvent(dialog, new Event('cancel', { cancelable: true }))
    expect(screen.queryByText('The build stops.')).toBeNull()
  })

  it('Dialog close button calls onClose', () => {
    const onClose = vi.fn()
    render(
      <Dialog open onClose={onClose} title="T">
        x
      </Dialog>,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Close' }))
    expect(onClose).toHaveBeenCalled()
  })

  it('Tabs: arrow keys, Home and End move the selection', () => {
    function Harness() {
      const [v, setV] = useState<'a' | 'b' | 'c'>('a')
      return (
        <Tabs items={[{ id: 'a', label: 'Evidence' }, { id: 'b', label: 'Ticket' }, { id: 'c', label: 'Build' }]} value={v} onChange={setV} label="Details">
          <p>panel {v}</p>
        </Tabs>
      )
    }
    render(<Harness />)
    const first = screen.getByRole('tab', { name: 'Evidence' })
    expect(first).toHaveAttribute('aria-selected', 'true')
    expect(first).toHaveAttribute('tabindex', '0')
    fireEvent.keyDown(first, { key: 'ArrowRight' })
    expect(screen.getByRole('tab', { name: 'Ticket' })).toHaveAttribute('aria-selected', 'true')
    fireEvent.keyDown(screen.getByRole('tab', { name: 'Ticket' }), { key: 'End' })
    expect(screen.getByText('panel c')).toBeInTheDocument()
    fireEvent.keyDown(screen.getByRole('tab', { name: 'Build' }), { key: 'ArrowRight' })
    expect(screen.getByText('panel a')).toBeInTheDocument()
    fireEvent.keyDown(screen.getByRole('tab', { name: 'Evidence' }), { key: 'ArrowLeft' })
    expect(screen.getByText('panel c')).toBeInTheDocument()
    expect(screen.getByRole('tabpanel')).toBeInTheDocument()
  })

  it('Tooltip shows on hover and focus, links by aria-describedby, closes on Escape', () => {
    render(
      <Tooltip content="Exact time">
        <button>4 min ago</button>
      </Tooltip>,
    )
    const trigger = screen.getByRole('button')
    fireEvent.mouseEnter(trigger)
    const tip = screen.getByRole('tooltip')
    expect(trigger).toHaveAttribute('aria-describedby', tip.id)
    fireEvent.keyDown(trigger, { key: 'Escape' })
    expect(screen.queryByRole('tooltip')).toBeNull()
    fireEvent.focus(trigger)
    expect(screen.getByRole('tooltip')).toHaveTextContent('Exact time')
    fireEvent.blur(trigger)
    expect(screen.queryByRole('tooltip')).toBeNull()
  })
})

describe('C-AC-8 designed states', () => {
  it('EmptyState teaches the next step', () => {
    render(<EmptyState title="No requests yet." body="Ask for a change above." action={<button>Ask</button>} size="page" />)
    expect(screen.getByRole('heading', { name: 'No requests yet.' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Ask' })).toBeInTheDocument()
  })
  it('ErrorState is an alert', () => {
    render(<ErrorState title="The inbox could not be loaded." body="Retry in a moment." />)
    expect(screen.getByRole('alert')).toHaveTextContent('Retry in a moment.')
  })
  it('PartialState is a status with its reason', () => {
    render(<PartialState title="Linear is partly synced." body="Rate limit reached." />)
    expect(screen.getByRole('status')).toHaveTextContent('Rate limit reached.')
  })
  it('Reconnecting and offline banners are status messages with actions', () => {
    render(<ReconnectingBanner />)
    expect(screen.getByTestId('reconnecting-banner')).toHaveTextContent('Nothing is lost')
    render(<OfflineBanner action={<button>Reload</button>} />)
    expect(screen.getByTestId('offline-banner')).toHaveTextContent('Live updates are offline')
    expect(screen.getByRole('button', { name: 'Reload' })).toBeInTheDocument()
  })
  it('skeletons are busy and hidden from content', () => {
    render(
      <>
        <SkeletonHeader />
        <SkeletonRows rows={3} />
        <SkeletonColumn items={2} />
        <SkeletonCanvas />
        <SkeletonText lines={4} />
        <SkeletonBlock className="h-4" />
      </>,
    )
    expect(screen.getByTestId('skeleton-rows').querySelectorAll('li')).toHaveLength(3)
    expect(screen.getByTestId('skeleton-header')).toHaveAttribute('aria-busy', 'true')
    expect(screen.getByTestId('skeleton-canvas')).toHaveAttribute('aria-label', 'Loading the graph')
  })
  it('C-AC-40 404 and 500 speak in the product voice', () => {
    render(<NotFoundContent />)
    expect(screen.getByRole('heading', { name: 'This page isn’t in Actron’s memory.' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Back to requests' })).toHaveAttribute('href', '/app')
    const onRetry = vi.fn()
    render(<ServerErrorContent digest="abc123" onRetry={onRetry} />)
    expect(screen.getByText('abc123').parentElement).toHaveTextContent('Reference abc123')
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(onRetry).toHaveBeenCalled()
  })
  it('C-AC-45 the small-screen notice uses the agreed sentence', () => {
    render(<SmallScreenNotice />)
    expect(SMALL_SCREEN_TEXT).toBe('Actron works best on a larger screen. Approvals also work in Slack.')
    expect(screen.getByTestId('small-screen-notice')).toHaveTextContent(SMALL_SCREEN_TEXT)
    expect(screen.getByTestId('small-screen-notice')).toHaveClass('lg:hidden')
  })
})

const conn = (provider: ConnectionView['provider'], config: Record<string, unknown> = {}): ConnectionView => ({
  id: provider,
  provider,
  status: 'connected',
  config,
  secretLast4: null,
  createdAt: '',
  updatedAt: '',
  sync: { state: 'UP TO DATE', lastSyncedAt: null, reason: null, perMinute: 0, counts: {} },
})

describe('C-AC-39 onboarding checklist', () => {
  it('C-AC-39 steps tick themselves from connections and requests', () => {
    expect(onboardingSteps([], false).map((s) => s.done)).toEqual([false, false, false, false, false])
    const steps = onboardingSteps([conn('github', { workingBranch: 'dev' }), conn('slack')], false)
    expect(steps.map((s) => s.done)).toEqual([true, true, true, false, false])
    expect(onboardingSteps([conn('github', { workingBranch: '' }), conn('slack_export'), conn('linear')], true).map((s) => s.done)).toEqual([true, false, true, true, true])
  })

  it('C-AC-39 shows progress and the next step; no dismiss until complete', () => {
    render(<OnboardingChecklist steps={onboardingSteps([conn('github', { workingBranch: 'dev' })], false)} />)
    expect(screen.getByText(/2 of 5 done/)).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Next: connect Slack.' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Dismiss' })).toBeNull()
  })

  it('compact shows one line with the next step; done steps come before Next', () => {
    const steps = onboardingSteps([conn('github', { workingBranch: 'dev' })], true)
    const { unmount } = render(<OnboardingChecklist steps={steps} compact />)
    expect(screen.getByRole('heading', { name: 'Getting started: 3 of 5 done' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Next: connect Slack' })).toHaveAttribute('href', '/app/connect')
    unmount()
    render(<OnboardingChecklist steps={steps} />)
    const done = screen.getAllByRole('listitem').map((li) => li.getAttribute('data-done'))
    expect(done).toEqual(['true', 'true', 'true', 'false', 'false'])
  })

  it('C-AC-39 once complete it can be dismissed, and stays dismissed', async () => {
    const all = onboardingSteps([conn('github', { workingBranch: 'dev' }), conn('slack'), conn('linear')], true)
    const { unmount } = render(<OnboardingChecklist steps={all} />)
    expect(screen.getByRole('heading', { name: 'Actron is set up.' })).toBeInTheDocument()
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Dismiss' }))
    })
    expect(screen.queryByTestId('onboarding')).toBeNull()
    unmount()
    render(<OnboardingChecklist steps={all} />)
    await waitFor(() => expect(screen.queryByTestId('onboarding')).toBeNull())
  })
})

describe('C-AC-43 unsaved changes guard', () => {
  it('C-AC-43 warns on unload only while dirty', () => {
    const add = vi.spyOn(window, 'addEventListener')
    const { rerender } = render(<UnsavedChangesGuard when={false} />)
    expect(add.mock.calls.some(([t]) => String(t) === 'beforeunload')).toBe(false)
    rerender(<UnsavedChangesGuard when />)
    expect(add.mock.calls.some(([t]) => String(t) === 'beforeunload')).toBe(true)
    const ev = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(ev)
    expect(ev.defaultPrevented).toBe(true)
  })

  it('C-AC-43 confirms before following an in-app link and cancels when refused', () => {
    const confirm = vi.fn().mockReturnValue(false)
    vi.stubGlobal('confirm', confirm)
    render(
      <>
        <UnsavedChangesGuard when />
        {/* A plain anchor on purpose: the guard intercepts any same-origin link click. */}
        {/* eslint-disable-next-line @next/next/no-html-link-for-pages */}
        <a href="/app/inbox">Inbox</a>
      </>,
    )
    const ev = new MouseEvent('click', { bubbles: true, cancelable: true, button: 0 })
    screen.getByRole('link', { name: 'Inbox' }).dispatchEvent(ev)
    expect(confirm).toHaveBeenCalledWith(UNSAVED_MESSAGE)
    expect(ev.defaultPrevented).toBe(true)
  })
})

describe('C-AC-20 dev fixtures badge', () => {
  afterEach(() => {
    vi.unstubAllEnvs()
    vi.resetModules()
  })
  it('C-AC-20 renders nothing without the flag', async () => {
    vi.stubEnv('NEXT_PUBLIC_ACTRON_DEV_FIXTURES', '0')
    vi.resetModules()
    const { DevFixturesBadge } = await import('@/components/shell/DevFixturesBadge')
    const { container } = render(<DevFixturesBadge />)
    expect(container).toBeEmptyDOMElement()
  })
  it('C-AC-20 renders a visible badge with the flag on', async () => {
    vi.stubEnv('NEXT_PUBLIC_ACTRON_DEV_FIXTURES', '1')
    vi.resetModules()
    const { DevFixturesBadge } = await import('@/components/shell/DevFixturesBadge')
    render(<DevFixturesBadge />)
    expect(screen.getByTestId('dev-fixtures-badge')).toHaveTextContent('DEV FIXTURES')
  })
})

describe('C-AC-8 replay controls', () => {
  it('play, step, speed and seek call back with the right values', () => {
    const cb = { onPlayPause: vi.fn(), onStep: vi.fn(), onSpeed: vi.fn(), onSeek: vi.fn() }
    render(<ReplayControls playing={false} speed={1} position={3} total={10} {...cb} />)
    fireEvent.click(screen.getByTestId('replay-play'))
    expect(cb.onPlayPause).toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Step forward' }))
    fireEvent.click(screen.getByRole('button', { name: 'Step back' }))
    expect(cb.onStep.mock.calls).toEqual([[1], [-1]])
    fireEvent.click(screen.getByRole('radio', { name: '4×' }))
    expect(cb.onSpeed).toHaveBeenCalledWith(4)
    fireEvent.change(screen.getByRole('slider'), { target: { value: '7' } })
    expect(cb.onSeek).toHaveBeenCalledWith(7)
    expect(screen.getByTestId('replay-position')).toHaveTextContent('3 / 10')
    expect(SPEEDS).toEqual([0.5, 1, 2, 4])
  })
  it('steps disable at the ends; the play button reads Pause and Again', () => {
    const noop = () => undefined
    const { rerender } = render(<ReplayControls playing={false} speed={1} position={0} total={5} onPlayPause={noop} onStep={noop} onSpeed={noop} onSeek={noop} />)
    expect(screen.getByRole('button', { name: 'Step back' })).toBeDisabled()
    rerender(<ReplayControls playing speed={2} position={2} total={5} onPlayPause={noop} onStep={noop} onSpeed={noop} onSeek={noop} />)
    expect(screen.getByTestId('replay-play')).toHaveTextContent('Pause')
    expect(screen.getByRole('radio', { name: '2×' })).toHaveAttribute('aria-checked', 'true')
    rerender(<ReplayControls playing={false} speed={1} position={5} total={5} onPlayPause={noop} onStep={noop} onSpeed={noop} onSeek={noop} />)
    expect(screen.getByTestId('replay-play')).toHaveTextContent('Again')
    expect(screen.getByRole('button', { name: 'Step forward' })).toBeDisabled()
  })
})

describe('C-AC-8 Home rows and composer', () => {
  it('RequestRow shows title, state chip, last event, requester and a mini pipeline', () => {
    const r = makeRequestDetail({ state: 'Building', pipelineStep: 5, lastEvent: { type: 'build.step', sentence: 'Editing src/evaluate.ts', at: new Date().toISOString() } })
    render(
      <ul>
        <RequestRow request={r} />
      </ul>,
    )
    const link = screen.getByRole('link')
    expect(link).toHaveAttribute('href', `/app/requests/${r.id}`)
    expect(link).toHaveAttribute('data-row')
    expect(link).toHaveTextContent('Show evaluation results inline')
    expect(link).toHaveTextContent('Building')
    expect(link).toHaveTextContent('Editing src/evaluate.ts')
    expect(screen.getByTestId('pipeline-step')).toHaveTextContent('Step 5 of 6 · Build')
    expect(link.querySelector('[tabindex="0"]')).toBeNull()
  })

  it('pipeline status and avatars', () => {
    expect(pipelineStatus({ state: 'Done' })).toBe('done')
    expect(pipelineStatus({ state: 'Needs attention' })).toBe('failed')
    expect(pipelineStatus({ state: 'Cancelled' })).toBe('cancelled')
    expect(pipelineStatus({ state: 'Building' })).toBe('active')
    render(<Avatar name="Sam Okoro" />)
    expect(screen.getByText('SO')).toBeInTheDocument()
  })

  it('the composer detects the kind, lets the user change it and submits with Cmd+Enter', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ request: makeRequestDetail({ id: 'req_new' }) }), { status: 201, headers: { 'Content-Type': 'application/json' } }),
    )
    vi.stubGlobal('fetch', fetchMock)
    renderWithClient(<RequestComposer />)
    const box = screen.getByLabelText('New request')
    expect(screen.getByRole('button', { name: /Ask Actron/ })).toBeDisabled()
    expect(screen.getByRole('button', { name: /Ask Actron/ })).toHaveAttribute('title', 'Type a request first.')
    expect(screen.getByRole('radiogroup', { name: 'Kind' })).toBeInTheDocument()
    fireEvent.change(box, { target: { value: 'Why does evaluate trim comments?' } })
    expect(screen.getByRole('button', { name: 'Auto' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('radio', { name: 'Question' })).toHaveAttribute('aria-checked', 'true')
    fireEvent.click(screen.getByRole('radio', { name: 'Bug' }))
    expect(screen.getByRole('button', { name: 'Auto' })).toHaveAttribute('aria-pressed', 'false')
    expect(screen.getByText('Kind set by you.')).toBeInTheDocument()
    await act(async () => {
      fireEvent.keyDown(box, { key: 'Enter', metaKey: true })
    })
    await waitFor(() => expect(push).toHaveBeenCalledWith('/app/requests/req_new'))
    const body = JSON.parse(String((fetchMock.mock.calls[0]?.[1] as RequestInit).body)) as { text: string; kindHint: string }
    expect(body).toEqual({ text: 'Why does evaluate trim comments?', kindHint: 'bug' })
  })

  it('the composer explains why it is disabled', () => {
    renderWithClient(<RequestComposer disabledReason="Connect a repository first so Actron has code to check against." />)
    fireEvent.change(screen.getByLabelText('New request'), { target: { value: 'Add a setting' } })
    expect(screen.getByText(/Connect a repository first/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Ask Actron/ })).toBeDisabled()
  })
})

describe('C-AC-8 command palette', () => {
  it('opens from the store, filters and navigates with Enter', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation(async () => new Response(JSON.stringify({ requests: [], counts: { needsYou: 0, running: 0, done: 0 }, connections: [], results: [] }), { status: 200 })),
    )
    renderWithClient(<CommandPalette />)
    act(() => useUi.getState().setPaletteOpen(true))
    const input = await screen.findByRole('combobox', { name: /Search requests/ })
    expect(screen.getAllByRole('option').length).toBeGreaterThan(5)
    fireEvent.change(input, { target: { value: 'inbox' } })
    await waitFor(() => expect(screen.getAllByRole('option')[0]).toHaveTextContent('Inbox'))
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(push).toHaveBeenCalledWith('/app/inbox')
    expect(useUi.getState().paletteOpen).toBe(false)
  })

  it('arrow keys move the active option; no match explains itself', async () => {
    vi.stubGlobal('fetch', vi.fn().mockImplementation(async () => new Response(JSON.stringify({ requests: [], results: [] }), { status: 200 })))
    renderWithClient(<CommandPalette canApprove />)
    act(() => useUi.getState().setPaletteOpen(true))
    const input = await screen.findByRole('combobox')
    fireEvent.change(input, { target: { value: 'approve' } })
    await waitFor(() => expect(screen.getAllByRole('option')[0]).toHaveTextContent('Approve current'))
    const before = useUi.getState().approveSignal
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(useUi.getState().approveSignal).toBe(before + 1)
    act(() => useUi.getState().setPaletteOpen(true))
    const again = await screen.findByRole('combobox')
    fireEvent.change(again, { target: { value: 'zzzzqqq' } })
    await waitFor(() => expect(screen.getByText(/Nothing matches/)).toBeInTheDocument())
    fireEvent.change(again, { target: { value: '' } })
    fireEvent.keyDown(again, { key: 'ArrowDown' })
    expect(again.getAttribute('aria-activedescendant')).toMatch(/-1$/)
    act(() => useUi.getState().setPaletteOpen(false))
  })
})
