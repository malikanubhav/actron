import { describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen, within, waitFor } from '@testing-library/react'
import { Timeline, buildTimelineRows } from '@/components/request/Timeline'
import { ToolCallCard } from '@/components/request/ToolCallCard'
import { ConfidenceTier, EvidenceCard, LabelBanner, sortEvidence, sourceBrand } from '@/components/request/Evidence'
import { QuestionCard } from '@/components/request/QuestionCard'
import { TestList } from '@/components/request/TestList'
import { ConstraintsChecklist } from '@/components/request/ConstraintsChecklist'
import { ALL_EVENT_TYPES } from '@/lib/events'
import type { Evidence, Question } from '@/lib/api/types'
import { makeEvent, PERSON } from '../helpers/render'
import { PAYLOADS } from '../helpers/payloads'

const evidence = (o: Partial<Evidence> = {}): Evidence => ({
  evidenceId: 'e1',
  role: 'conflict',
  nodeId: 'actron:decision:1',
  nodeType: 'Decision',
  title: 'Results stay in the output window',
  quote: 'We keep results in the output window so screen readers find them.',
  source: { type: 'SlackMessage', id: 's1', url: 'https://slack.example/1', author: 'Sam Okoro', at: '2026-03-02T10:00:00Z' },
  confidence: 0.86,
  tier: 'HIGH',
  path: ['actron:request:r', 'actron:decision:1'],
  ...o,
})

describe('C-AC-9 Timeline renders every event type', () => {
  it.each([...ALL_EVENT_TYPES].filter((t) => t !== 'tool.result'))('C-AC-9 %s renders a sentence and a glyph', (type) => {
    render(<Timeline events={[makeEvent(type, PAYLOADS[type])]} />)
    const item = screen.getByTestId('timeline-item')
    expect(item.textContent?.trim().length).toBeGreaterThan(3)
    expect(item.textContent).not.toMatch(/undefined|NaN/)
    if (type !== 'request.state_changed') expect(item.querySelector('svg[data-glyph]')).not.toBeNull()
  })

  it('the list is a polite live region and shows a waiting line when empty', () => {
    render(<Timeline events={[]} />)
    expect(screen.getByRole('list', { name: 'Request timeline' })).toHaveAttribute('aria-live', 'polite')
    expect(screen.getByText('Waiting for the first event.')).toBeInTheDocument()
  })

  it('pairs tool.called with its tool.result in one card', () => {
    const events = [makeEvent('tool.called', PAYLOADS['tool.called'], 1), makeEvent('tool.result', PAYLOADS['tool.result'], 2)]
    expect(buildTimelineRows(events)).toHaveLength(1)
    render(<Timeline events={events} />)
    expect(screen.getAllByTestId('timeline-item')).toHaveLength(1)
    expect(screen.getByTestId('tool-call-card')).toHaveAttribute('data-state', 'ok')
    expect(screen.getByText('Found 12 callers in 5 files')).toBeInTheDocument()
  })

  it('an orphan result still shows as its own row', () => {
    expect(buildTimelineRows([makeEvent('tool.result', { callId: 'zz', summary: 's' }, 1)])[0]?.kind).toBe('event')
  })

  it('the handoff is a distinct, wider item with the evidence count (B-AC-67)', () => {
    render(<Timeline events={[makeEvent('handoff.created', PAYLOADS['handoff.created'])]} />)
    expect(screen.getByText('Handoff to the build')).toBeInTheDocument()
    expect(screen.getByText('5')).toBeInTheDocument()
  })

  it('hovering an event emits its node ids; Enter and click pin them', () => {
    const onHighlight = vi.fn()
    const onPin = vi.fn()
    render(<Timeline events={[makeEvent('evidence.found', PAYLOADS['evidence.found'])]} onHighlight={onHighlight} onPin={onPin} />)
    const row = screen.getByRole('button', { name: /Highlights 3 nodes/ })
    fireEvent.mouseEnter(row)
    expect(onHighlight).toHaveBeenLastCalledWith(['actron:decision:1', 'r', 'd'])
    fireEvent.mouseLeave(row)
    expect(onHighlight).toHaveBeenLastCalledWith([])
    fireEvent.keyDown(row, { key: 'Enter' })
    fireEvent.click(row)
    expect(onPin).toHaveBeenCalledTimes(2)
  })

  it('pinned rows are pressed', () => {
    render(<Timeline events={[makeEvent('evidence.found', PAYLOADS['evidence.found'])]} pinnedIds={['actron:decision:1', 'r', 'd']} onPin={() => undefined} />)
    expect(screen.getByRole('button', { name: /Highlight/ })).toHaveAttribute('aria-pressed', 'true')
  })

  it('state changes can be hidden', () => {
    render(<Timeline events={[makeEvent('request.state_changed', { to: 'Building' })]} hideStateChanges />)
    expect(screen.queryAllByTestId('timeline-item')).toHaveLength(0)
  })
})

describe('C-AC-8 ToolCallCard', () => {
  const call = { callId: 'c1', tool: 'impact', args: { ids: ['code:fn:a#evaluateCode'], depth: 3 }, by: 'investigator' as const, at: 'x' }
  it('running state shows Running and an animated glyph', () => {
    const { container } = render(<ToolCallCard call={call} />)
    expect(screen.getByTestId('tool-call-card')).toHaveAttribute('data-state', 'running')
    expect(screen.getByText('Running')).toBeInTheDocument()
    expect(container.querySelector('[data-animated="true"]')).not.toBeNull()
  })
  it('ok state shows the summary and duration', () => {
    render(<ToolCallCard call={call} result={{ ok: true, summary: '27 functions', nodeIds: [], durationMs: 1840 }} />)
    expect(screen.getByText('27 functions')).toBeInTheDocument()
    expect(screen.getByText('2s')).toBeInTheDocument()
  })
  it('failed state shows the error', () => {
    render(<ToolCallCard call={call} result={{ ok: false, summary: '', nodeIds: [], durationMs: 2000, error: 'timeout after 2 s' }} />)
    expect(screen.getByTestId('tool-call-card')).toHaveAttribute('data-state', 'failed')
    expect(screen.getByText('Failed: timeout after 2 s')).toBeInTheDocument()
  })
  it('compact mode has no nested focus stop and keeps the full call in a title; Pi calls are labelled', () => {
    render(<ToolCallCard call={{ ...call, by: 'pi' }} compact />)
    const code = screen.getByTitle(/^impact\(/)
    expect(code).not.toHaveAttribute('tabindex')
    expect(screen.getByText('Pi · graph tool')).toBeInTheDocument()
  })
})

describe('C-AC-8 evidence', () => {
  it('EvidenceCard shows role, quote, source with author, tier and actions', () => {
    const onShowPath = vi.fn()
    render(<EvidenceCard evidence={evidence()} onShowPath={onShowPath} />)
    const card = screen.getByRole('article', { name: 'Results stay in the output window' })
    expect(within(card).getByText('Conflict')).toBeInTheDocument()
    expect(within(card).getByText(/screen readers find them/)).toBeInTheDocument()
    expect(within(card).getByText('Sam Okoro')).toBeInTheDocument()
    expect(within(card).getByText('Slack')).toBeInTheDocument()
    expect(card.querySelector('img[data-brand="slack"]')).not.toBeNull()
    fireEvent.click(within(card).getByRole('button', { name: /Show path/ }))
    expect(onShowPath).toHaveBeenCalledWith(expect.objectContaining({ evidenceId: 'e1' }))
    const link = within(card).getByRole('link', { name: /Open source/ })
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noreferrer noopener')
  })

  it('tracing marks the card and highlights the quote; no path or URL hides the actions', () => {
    const { container } = render(<EvidenceCard evidence={evidence()} onShowPath={() => undefined} tracing />)
    expect(screen.getByRole('button', { name: /Tracing path/ })).toHaveAttribute('aria-pressed', 'true')
    expect(container.querySelector('.quote-highlight')).not.toBeNull()
    render(<EvidenceCard evidence={evidence({ evidenceId: 'e2', title: 'No path', path: ['x'], source: { type: 'CodeFunction', id: 'f', url: null, author: null, at: null } })} onShowPath={() => undefined} />)
    const card = screen.getByRole('article', { name: 'No path' })
    expect(within(card).queryByRole('button', { name: /Show path/ })).toBeNull()
    expect(within(card).queryByRole('link')).toBeNull()
  })

  it.each([
    [0.85, false, 'HIGH'],
    [0.7, false, 'MEDIUM'],
    [0.4, false, 'POSSIBLE'],
    [0.9, true, 'POSSIBLE'],
  ])('ConfidenceTier %s (flag %s) → %s', (value, flag, tier) => {
    render(<ConfidenceTier value={value} flag={flag} />)
    const el = screen.getByLabelText(new RegExp(`Confidence ${tier.toLowerCase()}`))
    expect(el).toHaveAttribute('data-tier', tier)
    fireEvent.focus(el)
    expect(screen.getByRole('tooltip')).toHaveTextContent(`Score ${value.toFixed(2)}`)
  })

  it.each([
    ['conflict', 'Conflict', /conflicts with this request/],
    ['possible_conflict', 'Possible conflict', /may conflict/],
    ['nothing_found', 'Nothing found', /No earlier decision touches this request/],
    ['clear', 'Clear', /Nothing here conflicts/],
  ] as const)('LabelBanner %s', (label, text, sentence) => {
    render(<LabelBanner label={label} />)
    expect(screen.getByTestId('label-banner')).toHaveAttribute('data-label', label)
    expect(screen.getByText(text)).toBeInTheDocument()
    expect(screen.getByText(sentence)).toBeInTheDocument()
  })

  it('evidence sorts by role then confidence; sources map to brands', () => {
    const sorted = sortEvidence([evidence({ evidenceId: 'a', role: 'test' }), evidence({ evidenceId: 'b', role: 'impact', confidence: 0.5 }), evidence({ evidenceId: 'c', role: 'impact', confidence: 0.9 }), evidence({ evidenceId: 'd', role: 'conflict' })])
    expect(sorted.map((e) => e.evidenceId)).toEqual(['d', 'c', 'b', 'a'])
    expect(sourceBrand('GithubReview')).toEqual({ brand: 'github', name: 'Review' })
    expect(sourceBrand('GithubPullRequest')).toEqual({ brand: 'github', name: 'PR' })
    expect(sourceBrand('LinearIssue')).toEqual({ brand: 'linear', name: 'Ticket' })
    expect(sourceBrand('CodeFunction')).toEqual({ brand: null, name: 'Code' })
  })
})

describe('C-AC-8 QuestionCard', () => {
  const choice: Question = {
    questionId: 'q1',
    text: 'Which branch should this change go into?',
    kind: 'choice',
    options: [
      { value: 'dev', label: 'dev', note: "tracked by Actron's memory", preselected: true },
      { value: 'main', label: 'main', note: 'protected' },
    ],
    evidenceIds: ['e1'],
    required: true,
    answer: null,
  }

  it('choice questions preselect, explain why and submit the chosen value', () => {
    const onAnswer = vi.fn()
    render(<QuestionCard question={choice} onAnswer={onAnswer} evidence={[evidence()]} index={0} />)
    expect(screen.getByRole('radio', { name: /dev/ })).toBeChecked()
    expect(screen.getByText('Asked because of: Results stay in the output window.')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('radio', { name: /main/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Send answer' }))
    expect(onAnswer).toHaveBeenCalledWith('q1', 'main')
    expect(screen.getByText('Question 1')).toBeInTheDocument()
  })

  it('without a preselected option the submit stays disabled until one is chosen', () => {
    render(<QuestionCard question={{ ...choice, options: choice.options.map((o) => ({ ...o, preselected: false })) }} onAnswer={() => undefined} />)
    expect(screen.getByRole('button', { name: 'Send answer' })).toBeDisabled()
    fireEvent.click(screen.getByRole('radio', { name: /dev/ }))
    expect(screen.getByRole('button', { name: 'Send answer' })).toBeEnabled()
  })

  it('text questions validate inline', () => {
    const onAnswer = vi.fn()
    render(<QuestionCard question={{ ...choice, kind: 'text', options: [], required: false }} onAnswer={onAnswer} />)
    const box = screen.getByLabelText('Your answer')
    fireEvent.change(box, { target: { value: 'x' } })
    expect(screen.getByText('Write at least two characters.')).toBeInTheDocument()
    expect(box).toHaveAttribute('aria-invalid', 'true')
    fireEvent.change(box, { target: { value: 'Use dev' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send answer' }))
    expect(onAnswer).toHaveBeenCalledWith('q1', 'Use dev')
    expect(screen.getByText(/optional/)).toBeInTheDocument()
  })

  it('answered questions show who answered and where', () => {
    render(<QuestionCard question={{ ...choice, answer: { value: 'dev', by: PERSON, surface: 'slack', at: new Date().toISOString() } }} />)
    expect(screen.getByTestId('question-card')).toHaveAttribute('data-answered', 'true')
    expect(screen.getByTestId('answer')).toHaveTextContent(/Dana Ilić · Slack/)
    expect(screen.queryByRole('button', { name: 'Send answer' })).toBeNull()
  })

  it('pending shows the loading label', () => {
    render(<QuestionCard question={choice} onAnswer={() => undefined} pending />)
    expect(screen.getByRole('button', { name: 'Sending' })).toHaveAttribute('aria-busy', 'true')
  })
})

describe('C-AC-8 TestList and ConstraintsChecklist', () => {
  it('failing tests come first with folded output; counts are shown', () => {
    render(
      <TestList
        results={[
          { name: 'b passes', status: 'pass' },
          { name: 'a fails', status: 'fail', output: 'expected 1 got 2' },
          { name: 'c skipped', status: 'skip' },
        ]}
      />,
    )
    const items = screen.getByTestId('test-list').querySelectorAll('li')
    expect(items[0]?.getAttribute('data-status')).toBe('fail')
    expect(screen.getByText('1 passed')).toBeInTheDocument()
    expect(screen.getByText('1 failed')).toBeInTheDocument()
    expect(screen.getByText('expected 1 got 2').closest('details')).not.toHaveAttribute('open')
  })

  it('empty results say so', () => {
    render(<TestList results={[]} />)
    expect(screen.getByText('No test results yet.')).toBeInTheDocument()
  })

  it('constraints show their proof and status', () => {
    render(
      <ConstraintsChecklist
        constraints={[
          { text: 'Results stay in the output window.', status: 'holds', proof: { kind: 'test', label: 'output-window.test.ts' } },
          { text: 'No new settings without docs.', status: 'unverified', proof: null },
          { text: 'Keep Paredit untouched.', status: 'broken', proof: { kind: 'evidence', label: 'PR #812', url: 'https://github.com/x' } },
        ]}
      />,
    )
    expect(screen.getByText('Holds')).toBeInTheDocument()
    expect(screen.getByText('Not verified')).toBeInTheDocument()
    expect(screen.getByText('Broken')).toBeInTheDocument()
    expect(screen.getByText('No test proves this yet.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'PR #812' })).toHaveAttribute('target', '_blank')
  })

  it('no constraints is an explicit empty state', () => {
    render(<ConstraintsChecklist constraints={[]} />)
    expect(screen.getByText(/listed no constraints/)).toBeInTheDocument()
  })
})

describe('C-AC-8 DiffViewer', () => {
  it('lists files and shows numbered rows in plain text while Shiki loads', async () => {
    vi.doMock('shiki', () => ({ codeToTokens: () => new Promise(() => undefined) }))
    const { DiffViewer } = await import('@/components/request/DiffViewer')
    render(
      <DiffViewer
        files={[
          { path: 'src/evaluate.ts', status: 'modified', additions: 1, deletions: 1, patch: '@@ -1,2 +1,2 @@\n keep\n-old\n+new' },
          { path: 'package.json', status: 'modified', additions: 3, deletions: 0, patch: '@@ -1 +1,3 @@\n+a\n+b\n+c' },
        ]}
      />,
    )
    const tabs = screen.getAllByRole('tab')
    expect(tabs).toHaveLength(2)
    expect(tabs[0]).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByText('old')).toBeInTheDocument()
    expect(screen.getByText('new')).toBeInTheDocument()
    expect(screen.getByText('+1')).toBeInTheDocument()
    await act(async () => {
      fireEvent.click(tabs[1] as HTMLElement)
    })
    await waitFor(() => expect(screen.getByRole('tabpanel', { name: 'package.json' })).toBeInTheDocument())
    expect(screen.getAllByText('Added:').length).toBe(3)
    vi.doUnmock('shiki')
  })

  it('no files is stated plainly', async () => {
    const { DiffViewer } = await import('@/components/request/DiffViewer')
    render(<DiffViewer files={[]} />)
    expect(screen.getByText('No file changes.')).toBeInTheDocument()
  })
})
