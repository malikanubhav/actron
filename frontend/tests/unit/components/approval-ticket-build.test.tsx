import { describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { ApprovalCard, isStale } from '@/components/request/ApprovalCard'
import { TicketView } from '@/components/request/TicketView'
import { BuildTheatre } from '@/components/request/BuildTheatre'
import type { Approval, Build, Revision } from '@/lib/api/types'
import { makeEvent, PERSON, TICKET } from '../helpers/render'

const HASH_V1 = '1a1a000000000000000000000000000000000000000000000000000000001b1b'
const HASH_V2 = '3f2a00000000000000000000000000000000000000000000000000000000c91e'
const approval = (target: string, o: Partial<Approval> = {}): Approval => ({
  id: 'a1',
  kind: 'ticket',
  target,
  status: 'accepted',
  reason: null,
  by: PERSON,
  surface: 'slack',
  at: new Date(Date.now() - 120_000).toISOString(),
  ...o,
})

describe('C-AC-11 ApprovalCard', () => {
  it('C-AC-11 shows the revision and short hash and opens a confirmation naming the full hash', () => {
    const onApprove = vi.fn()
    render(<ApprovalCard kind="ticket" current={{ n: 2, value: HASH_V2 }} onApprove={onApprove} />)
    expect(screen.getByTestId('approval-target')).toHaveTextContent('Revision v2 · SHA-256 3f2a…c91e')
    expect(screen.getByTestId('approval-card')).toHaveAttribute('data-state', 'open')
    fireEvent.click(screen.getByRole('button', { name: /Approve ticket v2/ }))
    expect(screen.getByTestId('confirm-target')).toHaveTextContent(`v2 · ${HASH_V2}`)
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Approve ticket v2' }))
    expect(onApprove).toHaveBeenCalledWith(HASH_V2)
  })

  it('C-AC-11 shows the stale state when the approved target differs from the current one', () => {
    render(<ApprovalCard kind="ticket" current={{ n: 2, value: HASH_V2 }} approval={{ ...approval(HASH_V1), n: 1 }} onApprove={() => undefined} />)
    expect(screen.getByTestId('approval-card')).toHaveAttribute('data-state', 'stale')
    expect(screen.getByTestId('stale-text')).toHaveTextContent('You approved v1. This is v2. Approve again to build.')
    expect(screen.getByRole('button', { name: /^Approve ticket v2/ })).toBeInTheDocument()
    expect(isStale(approval(HASH_V1), { n: 2, value: HASH_V2 })).toBe(true)
    expect(isStale(null, { n: 2, value: HASH_V2 })).toBe(false)
  })

  it('C-AC-11 surfaces the 409 reason inline', () => {
    render(<ApprovalCard kind="ticket" current={{ n: 2, value: HASH_V2 }} onApprove={() => undefined} error="This ticket changed since you opened it." />)
    expect(screen.getByRole('alert')).toHaveTextContent('This ticket changed since you opened it.')
  })

  it('approved for the current target shows who and where, with no button', () => {
    render(<ApprovalCard kind="ticket" current={{ n: 2, value: HASH_V2 }} approval={approval(HASH_V2)} onApprove={() => undefined} />)
    expect(screen.getByTestId('approval-card')).toHaveAttribute('data-state', 'approved')
    expect(screen.getByText(/Approved by Dana Ilić in Slack/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Approve/ })).toBeNull()
  })

  it('PR approvals bind to the head SHA; stale head text names both heads', () => {
    render(<ApprovalCard kind="pr" current={{ n: 18, value: '9f8e7d6c5b4a' }} approval={approval('1111111aaaa', { kind: 'pr' })} onApprove={() => undefined} />)
    expect(screen.getByTestId('approval-target')).toHaveTextContent('PR #18 · head 9f8e7d6')
    expect(screen.getByTestId('stale-text')).toHaveTextContent('You approved head 1111111. The PR now has head 9f8e7d6.')
  })

  it('openSignal opens the confirmation; disabled approvals explain why', () => {
    const { rerender } = render(<ApprovalCard kind="ticket" current={{ n: 2, value: HASH_V2 }} onApprove={() => undefined} openSignal={0} />)
    expect(screen.queryByRole('dialog')).toBeNull()
    rerender(<ApprovalCard kind="ticket" current={{ n: 2, value: HASH_V2 }} onApprove={() => undefined} openSignal={1} />)
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    rerender(<ApprovalCard kind="ticket" current={{ n: 2, value: HASH_V2 }} onApprove={() => undefined} canApprove={false} openSignal={1} />)
    expect(screen.getByText('Not available in this state.')).toBeInTheDocument()
  })

  it('pending shows the loading state', () => {
    render(<ApprovalCard kind="ticket" current={{ n: 2, value: HASH_V2 }} onApprove={() => undefined} pending />)
    expect(screen.getByRole('button', { name: /Approving/ })).toBeDisabled()
  })
})

const rev = (n: number, hash: string, patch: Partial<typeof TICKET> = {}): Revision => ({
  n,
  hash,
  content: { ...TICKET, ...patch },
  createdBy: 'Actron',
  createdAt: new Date().toISOString(),
  linear: n === 2 ? { issueId: 'l', identifier: 'CAL-214', url: 'https://linear.app/x' } : null,
  externalEdit: false,
})

describe('C-AC-8 TicketView', () => {
  const revisions = [rev(1, HASH_V1, { targetBranch: 'main' }), rev(2, HASH_V2)]

  it('shows every ticket section and the Linear link', () => {
    render(<TicketView revision={revisions[1] as Revision} revisions={revisions} />)
    for (const s of ['Objective', 'Acceptance criteria', 'Constraints to preserve', 'Affected functions', 'Test plan', 'Out of scope', 'Target branch']) {
      expect(screen.getByText(s)).toBeInTheDocument()
    }
    expect(screen.getByRole('link', { name: /CAL-214/ })).toHaveAttribute('href', 'https://linear.app/x')
    expect(screen.getByText('Existing test')).toBeInTheDocument()
  })

  it('the revision selector and compare view show a field diff', () => {
    render(<TicketView revision={revisions[1] as Revision} revisions={revisions} />)
    fireEvent.change(screen.getByLabelText('Compare with'), { target: { value: '1' } })
    const diff = screen.getByTestId('ticket-diff')
    expect(diff).toHaveTextContent('Changes · v1 → v2')
    expect(within(diff).getByText('Target branch')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Revision'), { target: { value: '1' } })
    expect(screen.queryByTestId('ticket-diff')).toBeNull()
    expect(screen.getByText('Not synced to Linear', { exact: false })).toBeInTheDocument()
  })

  it('affected functions select nodes on the canvas', () => {
    const onSelectNode = vi.fn()
    render(<TicketView revision={revisions[1] as Revision} revisions={revisions} onSelectNode={onSelectNode} />)
    fireEvent.click(screen.getByRole('button', { name: 'evaluateCode' }))
    expect(onSelectNode).toHaveBeenCalledWith('code:fn:src/evaluate.ts#evaluateCode')
  })

  it('C-AC-43 the edit form validates inline and keeps submit disabled until valid and changed', async () => {
    const onEdit = vi.fn().mockResolvedValue(undefined)
    render(<TicketView revision={revisions[1] as Revision} revisions={revisions} canEdit onEdit={onEdit} />)
    fireEvent.click(screen.getByRole('button', { name: 'Edit ticket' }))
    const save = screen.getByRole('button', { name: 'Save as new revision' })
    expect(save).toBeDisabled()
    expect(screen.getByText('No changes yet.')).toBeInTheDocument()
    const objective = screen.getByLabelText('Objective')
    fireEvent.change(objective, { target: { value: 'short' } })
    fireEvent.blur(objective)
    expect(screen.getByText('Write the objective as one full sentence.')).toBeInTheDocument()
    expect(objective).toHaveAttribute('aria-invalid', 'true')
    expect(save).toBeDisabled()
    fireEvent.change(objective, { target: { value: 'Show evaluation results inline next to every evaluated form.' } })
    expect(save).toBeEnabled()
    await act(async () => {
      fireEvent.click(save)
    })
    expect(onEdit).toHaveBeenCalledWith(expect.objectContaining({ objective: 'Show evaluation results inline next to every evaluated form.' }))
    await waitFor(() => expect(screen.getByTestId('ticket-view')).toBeInTheDocument())
  })

  it('edits are not offered on older revisions', () => {
    render(<TicketView revision={revisions[1] as Revision} revisions={revisions} canEdit />)
    fireEvent.change(screen.getByLabelText('Revision'), { target: { value: '1' } })
    expect(screen.queryByRole('button', { name: 'Edit ticket' })).toBeNull()
  })
})

const build = (o: Partial<Build> = {}): Build => ({
  id: 'b1',
  status: 'running',
  queuePosition: null,
  branch: 'actron/inline-results',
  baseSha: 'a1b2c3d4e5f6',
  headSha: null,
  testsPassed: 0,
  testsFailed: 0,
  attempts: 0,
  startedAt: new Date(Date.now() - 90_000).toISOString(),
  finishedAt: null,
  stopReason: null,
  tokens: { input: 50000, output: 12000 },
  costUsd: 0.42,
  report: null,
  ...o,
})

describe('C-AC-8 BuildTheatre', () => {
  it('no build yet', () => {
    render(<BuildTheatre build={null} events={[]} />)
    expect(screen.getByTestId('build-theatre')).toHaveAttribute('data-state', 'none')
    expect(screen.getByText('No build yet.')).toBeInTheDocument()
  })

  it('queued and waiting for budget', () => {
    render(<BuildTheatre build={build({ status: 'queued', queuePosition: 2 })} events={[]} />)
    expect(screen.getByText(/Queued at position 2/)).toBeInTheDocument()
    render(<BuildTheatre build={build({ status: 'waiting_budget' })} events={[]} />)
    expect(screen.getByText(/daily model budget is spent/)).toBeInTheDocument()
  })

  it('running: current step, file with its language mark, live diff, tickers, repairs, Pi tool calls and cost', () => {
    const events = [
      makeEvent('build.step', { buildId: 'b1', text: 'Reading the ticket', step: 'read' }, 1),
      makeEvent('build.step', { buildId: 'b1', text: 'Editing src/evaluate.ts', file: 'src/evaluate.ts', detail: { diff: '-old\n+new' } }, 2),
      makeEvent('tool.called', { callId: 'p1', tool: 'tests_for', args: { ids: ['code:fn:a#run'] }, by: 'pi' }, 3),
      makeEvent('tool.result', { callId: 'p1', ok: true, summary: '3 tests', nodeIds: [], durationMs: 40 }, 4),
      makeEvent('tests.result', { buildId: 'b1', passed: 12, failed: 2, failing: [{ name: 'inline result', output: 'expected 1' }] }, 5),
      makeEvent('build.repair', { buildId: 'b1', attempt: 1, reason: 'fixing two failing tests' }, 6),
      makeEvent('build.step', { buildId: 'other', text: 'not this build' }, 7),
    ]
    render(<BuildTheatre build={build({ attempts: 1 })} events={events} />)
    expect(screen.getByTestId('current-step')).toHaveTextContent('Editing src/evaluate.ts')
    expect(screen.getByTitle('src/evaluate.ts')).toBeInTheDocument()
    expect(screen.getByRole('img', { name: 'TypeScript' })).toBeInTheDocument()
    expect(screen.getByTestId('live-diff')).toHaveTextContent('+new')
    expect(screen.getByText('Tests passed: 12')).toBeInTheDocument()
    expect(screen.getByText('Tests failed: 2')).toBeInTheDocument()
    expect(screen.getByText(/Attempt 1: fixing two failing tests/)).toBeInTheDocument()
    expect(screen.getByText('Graph tools Pi called')).toBeInTheDocument()
    expect(screen.getByText('inline result')).toBeInTheDocument()
    expect(screen.queryByText('not this build')).toBeNull()
    expect(screen.getByTestId('cost-badge')).toHaveTextContent('$0.42')
  })

  it('passed, failed and stopped builds say so in plain words', () => {
    render(<BuildTheatre build={build({ status: 'passed', headSha: '9f8e7d6c5b4a', finishedAt: new Date().toISOString() })} events={[]} />)
    expect(screen.getByText(/Passed at 9f8e7d6/)).toBeInTheDocument()
    render(<BuildTheatre build={build({ status: 'failed', stopReason: 'failed_after_repairs' })} events={[]} />)
    expect(screen.getByText(/Tests still failed after two repair attempts/)).toBeInTheDocument()
    render(<BuildTheatre build={build({ status: 'stopped', stopReason: 'scope_change' })} events={[]} />)
    expect(screen.getByText(/grew beyond the approved ticket/)).toBeInTheDocument()
  })

  it('a build that stopped before it started says so once, with the error line, and hides the empty tickers', () => {
    const events = [makeEvent('build.failed', { buildId: 'b1', reason: 'missing_identity', message: 'ACTRON_BOT_NAME and ACTRON_BOT_EMAIL must be set to commit.' }, 1)]
    render(<BuildTheatre build={build({ status: 'stopped', stopReason: 'missing_identity', attempts: 0 })} events={events} />)
    expect(screen.getByText('Stopped before the build started')).toBeInTheDocument()
    expect(screen.getByText('The bot identity for commits is not set.')).toBeInTheDocument()
    expect(screen.getByText(/must be set to commit/)).toBeInTheDocument()
    expect(screen.getByTestId('build-next-step')).toHaveTextContent(/restart Actron, then Retry/)
    expect(screen.queryByTestId('test-tickers')).toBeNull()
    expect(screen.queryByText('No steps reported yet.')).toBeNull()
  })

  it('the raw log loads when opened, and failures are explained', async () => {
    const onLoadLog = vi.fn().mockResolvedValue('$ npm test\nok')
    render(<BuildTheatre build={build()} events={[]} onLoadLog={onLoadLog} />)
    const details = screen.getByText('Raw log').closest('details') as HTMLDetailsElement
    await act(async () => {
      details.open = true
      fireEvent(details, new Event('toggle'))
    })
    await waitFor(() => expect(screen.getByTestId('raw-log')).toHaveTextContent('$ npm test'))
    expect(onLoadLog).toHaveBeenCalledTimes(1)
  })

  it('report tests and procedures are shown when present', () => {
    render(
      <BuildTheatre
        build={build({ status: 'passed', report: { tests: [{ name: 'results doc', status: 'pass' }], procedures: [{ title: 'Calva unit tests', testCommand: 'npm run unit-test' }] } })}
        events={[]}
      />,
    )
    expect(screen.getByText('results doc')).toBeInTheDocument()
    expect(screen.getByText('npm run unit-test')).toBeInTheDocument()
  })
})
