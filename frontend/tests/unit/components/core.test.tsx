import { describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen } from '@testing-library/react'
import { Eyebrow } from '@/components/core/Eyebrow'
import { ScreenHeader } from '@/components/core/ScreenHeader'
import { PanelLabelTitle } from '@/components/core/PanelLabelTitle'
import { Chip, LabelChip, StateChip } from '@/components/core/StateChip'
import { Pipeline } from '@/components/core/Pipeline'
import { CountTicker } from '@/components/core/CountTicker'
import { CopyButton, CostBadge, RelativeTime, TruncatedText } from '@/components/core/Formatting'
import { LABELS, STATES } from '@/lib/api/types'
import { sentenceCase } from '@/lib/states'

const SYNC = ['NOT CONNECTED', 'BACKFILLING', 'SYNCING', 'PARTIAL', 'FAILED', 'UP TO DATE'] as const

describe('C-AC-8 Eyebrow, ScreenHeader, PanelLabelTitle', () => {
  it('Eyebrow renders mono label text', () => {
    render(<Eyebrow>REQUESTS</Eyebrow>)
    expect(screen.getByText('REQUESTS')).toHaveClass('eyebrow')
  })

  it('ScreenHeader shows eyebrow, h1 headline, purpose and actions; headline region is polite live', () => {
    const { rerender } = render(<ScreenHeader eyebrow="REQUESTS" headline="2 requests need you." purpose="Ask in Slack." actions={<button>Go</button>} />)
    const h1 = screen.getByRole('heading', { level: 1, name: '2 requests need you.' })
    expect(h1.parentElement).toHaveAttribute('aria-live', 'polite')
    expect(screen.getByText('REQUESTS')).toBeInTheDocument()
    expect(screen.getByText('Ask in Slack.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Go' })).toBeInTheDocument()
    rerender(<ScreenHeader eyebrow="REQUESTS" headline="Nothing needs you right now." purpose="Ask in Slack." />)
    expect(screen.getByRole('heading', { level: 1, name: 'Nothing needs you right now.' })).toBeInTheDocument()
  })

  it('C-AC-33 a headline that follows live data can keep two lines of height (no layout shift)', () => {
    const { rerender } = render(<ScreenHeader eyebrow="MEMORY" headline="Your memory is 100% built." purpose="p" headlineLines={2} />)
    expect(screen.getByRole('heading', { level: 1 })).toHaveClass('min-h-[2lh]')
    rerender(<ScreenHeader eyebrow="MEMORY" headline="Memory is up to date." purpose="p" />)
    expect(screen.getByRole('heading', { level: 1 })).not.toHaveClass('min-h-[2lh]')
  })

  it('PanelLabelTitle renders a mono label and a display heading', () => {
    render(<PanelLabelTitle label="TIMELINE" title="What happened" as="h3" aside={<span>x</span>} />)
    expect(screen.getByRole('heading', { level: 3, name: 'What happened' })).toHaveClass('display')
    expect(screen.getByText('TIMELINE')).toHaveClass('eyebrow')
  })
})

describe('C-AC-8 C-AC-10 StateChip', () => {
  it.each([...STATES, ...SYNC])('renders %s with its shared text and tone', (state) => {
    const { container } = render(<StateChip state={state} />)
    expect(screen.getByText(sentenceCase(state))).toBeInTheDocument()
    expect(container.firstElementChild?.getAttribute('data-tone')).toBeTruthy()
  })

  it('tones: needs-you states use the accent, Done is ok, Needs attention is conflict', () => {
    const tone = (s: (typeof STATES)[number]) => render(<StateChip state={s} />).container.firstElementChild?.getAttribute('data-tone')
    expect(tone('Awaiting approval')).toBe('needs_you')
    expect(tone('Done')).toBe('ok')
    expect(tone('Needs attention')).toBe('conflict')
    expect(tone('Cancelled')).toBe('idle')
  })

  it.each([...LABELS])('LabelChip %s', (label) => {
    render(<LabelChip label={label} />)
    expect(screen.getByText(sentenceCase(label.replace('_', ' ')))).toBeInTheDocument()
  })

  it('live running chips pulse; Chip carries a title', () => {
    const { container } = render(<StateChip state="Building" live />)
    expect(container.querySelector('.motion-safe\\:animate-pulse')).not.toBeNull()
    render(<Chip tone="ok" text="LIVE" title="Stream live" />)
    expect(screen.getByTitle('Stream live')).toHaveTextContent('Live')
  })
})

describe('C-AC-8 Pipeline', () => {
  it('marks the current step with aria-current and labels progress', () => {
    render(<Pipeline current={4} />)
    const list = screen.getByRole('list', { name: 'Step 4 of 6: Approve' })
    const items = list.querySelectorAll('li')
    expect(items).toHaveLength(6)
    expect(items[3]).toHaveAttribute('aria-current', 'step')
    expect(items[0]?.getAttribute('data-state')).toBe('done')
    expect(items[5]?.getAttribute('data-state')).toBe('todo')
    expect(screen.getByText('04')).toBeInTheDocument()
  })

  it('failed step is stopped; done marks every step done', () => {
    render(<Pipeline current={5} status="failed" />)
    expect(screen.getByRole('list', { name: 'Step 5 of 6: Build, stopped' }).querySelectorAll('li')[4]?.getAttribute('data-state')).toBe('failed')
    render(<Pipeline current={6} status="done" mini />)
    const mini = screen.getByTestId('pipeline-mini')
    expect([...mini.querySelectorAll('li')].every((li) => li.getAttribute('data-state') === 'done')).toBe(true)
  })

  it('cancelled pipelines show no current step', () => {
    render(<Pipeline current={2} status="cancelled" />)
    expect(screen.getByTestId('pipeline').querySelector('[aria-current]')).toBeNull()
  })
})

describe('C-AC-8 tickers and formatting components', () => {
  it('CountTicker shows tabular formatted numbers and an accessible label', () => {
    render(<CountTicker value={41203} label="Nodes" />)
    expect(screen.getByText('Nodes: 41,203')).toHaveClass('sr-only')
  })

  it('CountTicker updates to the new value', async () => {
    vi.useFakeTimers()
    const { rerender } = render(<CountTicker value={1} />)
    rerender(<CountTicker value={10} />)
    await act(async () => {
      vi.advanceTimersByTime(600)
    })
    expect(screen.getByText('10')).toBeInTheDocument()
    vi.useRealTimers()
  })

  it('RelativeTime is focusable with an exact-time tooltip; the non-focusable variant uses a title', () => {
    const at = new Date(Date.now() - 4 * 60_000).toISOString()
    render(<RelativeTime value={at} />)
    const time = screen.getByText('4 min ago')
    expect(time.tagName).toBe('TIME')
    expect(time).toHaveAttribute('tabindex', '0')
    fireEvent.focus(time)
    expect(screen.getByRole('tooltip')).toHaveTextContent(/2026|20\d\d/)
    render(<RelativeTime value={at} focusable={false} />)
    const plain = screen.getAllByText('4 min ago')[1] as HTMLElement
    expect(plain).not.toHaveAttribute('tabindex')
    expect(plain.getAttribute('title')).toBeTruthy()
  })

  it('TruncatedText truncates in the middle and keeps the full text accessible', () => {
    render(<TruncatedText text="code:fn:src/nrepl/repl-session/evaluate.ts#evaluateCode" max={20} />)
    expect(screen.getByLabelText('code:fn:src/nrepl/repl-session/evaluate.ts#evaluateCode')).toHaveTextContent('…')
    expect(screen.getByRole('button', { name: 'Copy' })).toBeInTheDocument()
  })

  it('CopyButton writes to the clipboard and confirms', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
    render(<CopyButton value="/invite @Actron" />)
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Copy' }))
    })
    expect(writeText).toHaveBeenCalledWith('/invite @Actron')
    expect(screen.getByRole('button', { name: 'Copied' })).toBeInTheDocument()
  })

  it('C-AC-46 CostBadge shows tokens and estimated cost', () => {
    render(<CostBadge label="Build" tokens={{ input: 120000, output: 30000 }} costUsd={1.234} />)
    const badge = screen.getByTestId('cost-badge')
    expect(badge).toHaveTextContent('Build')
    expect(badge).toHaveTextContent('150k tokens')
    expect(badge).toHaveTextContent('estimated cost $1.23')
  })
})
