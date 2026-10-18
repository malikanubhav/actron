import { describe, expect, it } from 'vitest'
import { askText, currentAsk, historyText, inboxSections, notificationDetail, rowFact, waitingOnYouCount } from '@/components/home/ask'
import { pipelineStepLabel } from '@/components/core/Pipeline'
import type { NotificationItem, RequestSummary } from '@/lib/api/types'

const TITLE = 'Make docFromTextNotation accept Windows line endings'

function note(id: string, requestId: string, kind: NotificationItem['kind'], title: string, body: string, createdAt: string): NotificationItem {
  return { id, requestId, kind, title, body, tab: 'questions', readAt: null, createdAt }
}

function req(id: string, state: RequestSummary['state'], sentence = `Now ${state}.`): RequestSummary {
  return {
    id,
    title: TITLE,
    kind: 'feature',
    state,
    label: null,
    requester: { name: 'Vikram', avatarUrl: null, personId: null, userId: 'u1' },
    source: 'ui',
    createdAt: '2026-10-17T19:00:00Z',
    updatedAt: '2026-10-17T19:30:00Z',
    lastEvent: { type: 'request.state_changed', sentence, at: '2026-10-17T19:30:00Z' },
    pipelineStep: 2,
    needsYou: true,
  }
}

const notes: NotificationItem[] = [
  note('n1', 'req_a', 'needs_input', 'Actron needs your input', `${TITLE}: Which branch should this change go into?`, '2026-10-17T19:23:00Z'),
  note('n2', 'req_b', 'needs_input', 'Actron needs your input', `${TITLE}: Should its current behaviour stay the same?`, '2026-10-17T19:28:00Z'),
  note('n3', 'req_b', 'awaiting_approval', 'Ticket v1 is ready for your approval', TITLE, '2026-10-18T02:11:36Z'),
  note('n4', 'req_b', 'build_failed', 'This request needs your attention', `${TITLE}: missing_identity`, '2026-10-18T02:11:40Z'),
  note('n5', 'req_gone', 'pr_ready', 'PR #12 is ready for review', `Old request: PR #12`, '2026-10-16T10:00:00Z'),
]

describe('ask text', () => {
  it('takes the detail after the request title', () => {
    expect(notificationDetail(notes[0]!, TITLE)).toBe('Which branch should this change go into?')
    expect(notificationDetail(notes[2]!, TITLE)).toBe('')
  })
  it('says the useful fact for each kind', () => {
    expect(askText(notes[0]!, TITLE)).toBe('Which branch should this change go into?')
    expect(askText(notes[2]!, TITLE)).toBe('Ticket v1 waits for your approval.')
    expect(askText(notes[3]!, TITLE)).toBe('The bot identity for commits is not set.')
    expect(askText(notes[4]!)).toBe('PR #12 is ready for your review.')
    expect(askText(note('x', 'r', 'build_failed', 't', `${TITLE}: disk_full`, ''), TITLE)).toBe('Stopped: disk full.')
  })
})

describe('history text', () => {
  it('states past notices in the past tense, resolved when the request moved on', () => {
    const atBuild = { state: 'Needs attention' as const, pipelineStep: 5 }
    expect(historyText(notes[2]!, TITLE, atBuild)).toBe('Ticket v1 was sent for approval · approved')
    expect(historyText(notes[1]!, TITLE, atBuild)).toBe('Asked: Should its current behaviour stay the same? · answered')
    expect(historyText(notes[2]!, TITLE, null)).toBe('Ticket v1 was sent for approval')
    expect(historyText(notes[3]!, TITLE, { state: 'Building', pipelineStep: 5 })).toBe('The build stopped: The bot identity for commits is not set · resolved')
  })
})

describe('current ask', () => {
  it('is the notification matching the current state; older kinds are not', () => {
    expect(currentAsk(req('req_b', 'Needs attention'), notes)?.id).toBe('n4')
    expect(currentAsk(req('req_b', 'Building'), notes)).toBeNull()
  })
  it('a row never shows "Now X." and falls back to a state sentence', () => {
    expect(rowFact(req('req_a', 'Needs your input'), notes)).toEqual({ text: 'Which branch should this change go into?', kind: 'needs_input' })
    expect(rowFact(req('req_z', 'Needs your input'), notes).text).toBe('Actron has a question.')
    const building = { ...req('req_z', 'Building'), lastEvent: { type: 'build.step', sentence: 'Editing src/a.ts.', at: '' } }
    expect(rowFact(building, []).text).toBe('Editing src/a.ts.')
  })
  it('Home and Inbox count the same requests', () => {
    const requests = [req('req_a', 'Needs your input'), req('req_b', 'Needs attention'), req('req_c', 'Awaiting approval')]
    expect(waitingOnYouCount(notes, requests)).toBe(2)
    const s = inboxSections(notes, requests)
    expect(s.waiting.map((b) => b.requestId)).toEqual(['req_a'])
    expect(s.stopped.map((b) => b.requestId)).toEqual(['req_b'])
    expect(s.stopped[0]?.earlier.map((n) => n.id)).toEqual(['n3', 'n2'])
    expect(s.earlier.map((b) => b.requestId)).toEqual(['req_gone'])
    expect(s.earlier[0]?.title).toBe('Old request')
  })
  it('without the request list the newest notification stands in', () => {
    const s = inboxSections(notes, null)
    expect(s.stopped.map((b) => b.requestId)).toEqual(['req_b'])
    expect(s.waiting.map((b) => b.requestId).sort()).toEqual(['req_a', 'req_gone'])
  })
})

describe('pipeline step label', () => {
  it('names the step', () => {
    expect(pipelineStepLabel(2)).toBe('Step 2 of 6 · Clarify')
    expect(pipelineStepLabel(5, 'failed')).toBe('Step 5 of 6 · Build')
    expect(pipelineStepLabel(6, 'done')).toBe('All 6 steps done')
  })
})
