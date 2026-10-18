import { describe, expect, it, vi } from 'vitest'

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }), usePathname: () => '/app', useSearchParams: () => new URLSearchParams() }))

import { homeHeadline } from '@/components/home/HomeScreen'
import { inboxHeadline, INBOX_GROUPS } from '@/components/inbox/InboxScreen'
import { draftFromSettings, settingsPatch, validateSettings } from '@/components/settings/SettingsScreen'
import { modelStatus, sourceLabel, streamText } from '@/components/shell/FooterStatusBar'
import { cancelConsequence, parseTab } from '@/components/request/RequestScreen'
import { quotesForTrace, tabsFor } from '@/components/request/RequestWorkspace'
import { tabForEvent } from '@/components/replay/ReplayScreen'
import { explorerHeadline, NODE_BUDGET } from '@/components/graph/GraphExplorer'
import { requestIdFromPath } from '@/components/shell/AppShell'
import { NAV } from '@/components/shell/Rail'
import type { Evidence, Settings } from '@/lib/api/types'
import { makeEvent, makeRequestDetail } from '../helpers/render'

const settings: Settings = {
  approvers: ['U04ABCDEF'],
  modelPrices: {},
  allowPublicReplays: false,
  thresholds: { conflict: 0.8, possibleConflict: 0.6, linkKeep: 0.6 },
  models: { decision: 'jev-1.13.0', writing: 'anthropic/x', agent: 'anthropic/x', coding: 'anthropic/x' },
  jobs: [
    { job: 'conflict', primitive: 'judge', provider: 'jev', status: 'live' },
    { job: 'ticket', primitive: 'write', provider: 'llm', status: 'stub' },
  ],
  botIdentity: { name: 'Actron', email: 'bot@example.com' },
  budget: { capUsd: 20, spentTodayUsd: 3 },
  schedules: { code: 'on push', github: 'every 15 min', linear: 'every 15 min', slack: 'live' },
}

describe('screen headlines (C-AC-22)', () => {
  it('Home summarises what needs you and what runs', () => {
    expect(homeHeadline(2, 1, 3, 9)).toBe('2 requests need you. 1 is building.')
    expect(homeHeadline(1, 0, 2, 3)).toBe('1 request needs you. 2 are running.')
    expect(homeHeadline(0, 0, 0, 4)).toBe('Nothing needs you right now.')
    expect(homeHeadline(0, 0, 0, 0)).toBe('No requests yet.')
    expect(homeHeadline(0, 2, 2, 2)).toBe('2 are building.')
  })
  it('Home names requests waiting on someone else apart from yours', () => {
    expect(homeHeadline(1, 0, 0, 4, 2)).toBe('1 request needs you. 2 more wait on someone else.')
    expect(homeHeadline(0, 0, 0, 4, 1)).toBe('1 waits on someone else.')
  })
  it('Inbox counts notices, requests and new ones, and groups like Home', () => {
    expect(inboxHeadline(7, 3, 3)).toBe('7 notices on 3 requests. 3 are new.')
    expect(inboxHeadline(1, 1, 1)).toBe('1 notice on 1 request. It is new.')
    expect(inboxHeadline(4, 2, 4)).toBe('4 notices on 2 requests. All are new.')
    expect(inboxHeadline(2, 1, 0)).toBe('2 notices on 1 request. None are new.')
    expect(inboxHeadline(0, 0, 0)).toBe('No notices yet.')
    expect(INBOX_GROUPS.map((g) => g.title)).toEqual(['Waiting for a decision', 'Stopped', 'No longer waiting'])
    expect(INBOX_GROUPS.map((g) => g.tone)).toEqual(['needs_you', 'conflict', 'idle'])
  })
  it('Graph explorer states real numbers or the empty memory', () => {
    expect(explorerHeadline({ nodeTypes: 96, nodes: 41203, links: 188911 })).toBe('96 node types, 41,203 nodes, 188,911 links.')
    expect(explorerHeadline({ nodeTypes: 96, nodes: 0, links: 0 })).toBe('The graph is empty. Connect a source to fill it.')
    expect(explorerHeadline(undefined)).toBe('Your memory, as a graph.')
    expect(NODE_BUDGET).toBe(300)
  })
})

describe('settings form (C-AC-43)', () => {
  it('round trips settings through the draft', () => {
    const d = draftFromSettings(settings)
    expect(d).toEqual({ conflict: '0.8', possibleConflict: '0.6', linkKeep: '0.6', approvers: 'U04ABCDEF', botName: 'Actron', botEmail: 'bot@example.com', allowPublicReplays: false })
    expect(settingsPatch(d)).toEqual({
      thresholds: settings.thresholds,
      approvers: ['U04ABCDEF'],
      botIdentity: settings.botIdentity,
      allowPublicReplays: false,
    })
    expect(validateSettings(d)).toEqual({})
  })
  it('validates thresholds, ordering, email and Slack ids in plain words', () => {
    const d = draftFromSettings(settings)
    expect(validateSettings({ ...d, conflict: '1.5' }).conflict).toMatch(/between 0 and 1/)
    expect(validateSettings({ ...d, conflict: '' }).conflict).toBeDefined()
    expect(validateSettings({ ...d, possibleConflict: '0.9' }).possibleConflict).toMatch(/at or below/)
    expect(validateSettings({ ...d, linkKeep: 'x' }).linkKeep).toBeDefined()
    expect(validateSettings({ ...d, botEmail: 'nope' }).botEmail).toMatch(/email address/)
    expect(validateSettings({ ...d, approvers: 'dana' }).approvers).toMatch(/Slack user ids/)
    expect(validateSettings({ ...d, approvers: '', botEmail: '' })).toEqual({})
  })
})

describe('footer status bar (PROMPT 8.7)', () => {
  const NOW = Date.parse('2026-10-17T12:00:00Z')
  const src = (state: 'UP TO DATE' | 'NOT CONNECTED' | 'BACKFILLING', provider: 'github' | 'slack' = 'github') => ({
    provider,
    state,
    counts: {},
    perMinute: 0,
    lastSyncedAt: new Date(NOW - 120_000).toISOString(),
    reason: null,
    runId: null,
  })
  it('labels each source like the reference', () => {
    expect(sourceLabel(src('UP TO DATE'), NOW)).toBe('GITHUB · SYNCED 2 MIN AGO')
    expect(sourceLabel(src('NOT CONNECTED', 'slack'), NOW)).toBe('SLACK · NOT CONNECTED')
    expect(sourceLabel(src('BACKFILLING', 'slack'), NOW)).toBe('SLACK · BACKFILLING')
  })
  it('model status reads JEV · LIVE or JEV · NO KEY', () => {
    expect(modelStatus(settings)).toEqual({ text: 'JEV · LIVE', tone: 'ok' })
    expect(modelStatus({ ...settings, jobs: [{ job: 'x', primitive: 'judge', provider: 'jev', status: 'stub' }] })).toEqual({ text: 'JEV · NO KEY', tone: 'possible' })
    expect(modelStatus(undefined).text).toBe('MODELS · UNKNOWN')
  })
  it('stream status words', () => {
    expect(streamText('live')).toEqual({ text: 'LIVE', tone: 'ok' })
    expect(streamText('reconnecting').text).toBe('RECONNECTING')
    expect(streamText('connecting').text).toBe('RECONNECTING')
    expect(streamText('offline')).toEqual({ text: 'OFFLINE', tone: 'conflict' })
    expect(streamText('closed').text).toBe('CLOSED')
  })
})

describe('request page helpers (C-AC-44)', () => {
  it('C-AC-44 deep-link tabs parse only known values', () => {
    expect(parseTab('build')).toBe('build')
    expect(parseTab('pr')).toBe('pr')
    expect(parseTab('nope')).toBeNull()
    expect(parseTab(null)).toBeNull()
  })
  it('cancelling names what stops for each stage', () => {
    expect(cancelConsequence(makeRequestDetail({ state: 'Investigating' }))).toMatch(/investigation stops/)
    expect(cancelConsequence(makeRequestDetail({ state: 'Building' }))).toMatch(/running build stops/)
    expect(cancelConsequence(makeRequestDetail({ state: 'PR ready for review' }))).toMatch(/stays open on GitHub/)
    expect(cancelConsequence(makeRequestDetail({ state: 'Awaiting approval' }))).toMatch(/ticket stays in Linear/)
  })
  it('the tab set is the same with or without questions, with the open count', () => {
    expect(tabsFor(makeRequestDetail()).map((t) => t.id)).toEqual(['evidence', 'questions', 'ticket', 'build', 'pr'])
    const withQ = makeRequestDetail({
      questions: [{ questionId: 'q', text: 't', kind: 'text', options: [], evidenceIds: [], required: true, answer: null }],
    })
    expect(tabsFor(withQ).map((t) => t.id)).toEqual(['evidence', 'questions', 'ticket', 'build', 'pr'])
  })
  it('quotes appear only for evidence on the traced path', () => {
    const ev = (id: string, quote: string | null, type = 'SlackMessage'): Evidence => ({
      evidenceId: id,
      role: 'constraint',
      nodeId: id,
      nodeType: 'Decision',
      title: id,
      quote,
      source: { type, id, url: null, author: 'Sam', at: null },
      confidence: 0.9,
      tier: 'HIGH',
      path: [],
    })
    const q = quotesForTrace([ev('a', 'Keep it'), ev('b', 'Off path'), ev('c', null), ev('d', 'Review note', 'GithubReview')], ['r', 'a', 'c', 'd'])
    expect(Object.keys(q).sort()).toEqual(['a', 'd'])
    expect(q.a).toEqual({ quote: 'Keep it', source: 'Slack', author: 'Sam', brand: 'slack' })
    expect(q.d?.source).toBe('Review')
  })
  it('replays move the side panel to the tab of the event being played', () => {
    expect(tabForEvent(makeEvent('evidence.found'))).toBe('evidence')
    expect(tabForEvent(makeEvent('question.asked'))).toBe('questions')
    expect(tabForEvent(makeEvent('ticket.revised'))).toBe('ticket')
    expect(tabForEvent(makeEvent('tests.result'))).toBe('build')
    expect(tabForEvent(makeEvent('pr.opened'))).toBe('pr')
    expect(tabForEvent(makeEvent('tool.called'))).toBeNull()
    expect(tabForEvent(undefined)).toBeNull()
  })
  it('the shell knows which request is open and which rail item is active', () => {
    expect(requestIdFromPath('/app/requests/req_1/replay')).toBe('req_1')
    expect(requestIdFromPath('/app/inbox')).toBeNull()
    const active = (p: string) => NAV.filter((n) => n.match(p)).map((n) => n.label)
    expect(active('/app')).toEqual(['Requests'])
    expect(active('/app/requests/req_1')).toEqual(['Requests'])
    expect(active('/app/graph')).toEqual(['Graph'])
    expect(NAV.map((n) => n.label)).toEqual(['Requests', 'Inbox', 'Graph', 'System', 'Connect', 'Settings'])
  })
})
