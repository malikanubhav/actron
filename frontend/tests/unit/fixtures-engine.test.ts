import { afterEach, describe, expect, it } from 'vitest'
import type { EventEnvelope, RequestDetail, Subgraph } from '@/lib/api/types'
import { FIXTURE_IDS } from '@/tests/fixtures/data/ids'
import { sha256 } from '@/tests/fixtures/data/util'
import { FixtureEngine, detectScenario, WS_KEY } from '@/tests/fixtures/msw/engine'
import { fixtureResponse } from '@/tests/fixtures/msw/router'

const engine = (scenario: 'default' | 'empty' | 'backend-down' | 'stream-drop' = 'default') =>
  new FixtureEngine({ scenario, timers: 'immediate' })

const detail = (e: FixtureEngine, id: string) => (e.route('GET', `/api/requests/${id}`).json as { request: RequestDetail }).request

afterEach(() => {
  window.history.replaceState(null, '', '/')
  window.sessionStorage.clear()
})

describe('fixture data', () => {
  it('derives the intended state for every fixture request', () => {
    const e = engine()
    expect(detail(e, FIXTURE_IDS.done).state).toBe('Done')
    expect(detail(e, FIXTURE_IDS.live).state).toBe('Investigating')
    expect(detail(e, FIXTURE_IDS.stale).state).toBe('Awaiting approval')
    expect(detail(e, FIXTURE_IDS.building).state).toBe('Building')
    expect(detail(e, FIXTURE_IDS.failed).state).toBe('Needs attention')
    expect(detail(e, FIXTURE_IDS.prReady).state).toBe('PR ready for review')
    expect(detail(e, FIXTURE_IDS.cancelled).state).toBe('Cancelled')
    expect(detail(e, FIXTURE_IDS.answered).state).toBe('Done')
    expect(detail(e, FIXTURE_IDS.answered).answer?.citations.length).toBe(2)
    expect(detail(e, FIXTURE_IDS.nothing).label).toBe('nothing_found')
    expect(detail(e, FIXTURE_IDS.nothing).state).toBe('Awaiting approval')
  })

  it('starts the live request with only request.created and investigation.started', () => {
    expect(engine().events(FIXTURE_IDS.live).map((x) => x.type)).toEqual(['request.created', 'investigation.started'])
  })

  it('keeps seq gap-free and ids increasing in every recorded log', () => {
    const e = engine()
    for (const id of Object.values(FIXTURE_IDS)) {
      const events = e.events(id)
      events.forEach((ev, i) => expect(ev.seq).toBe(i + 1))
      for (let i = 1; i < events.length; i++) expect((events[i] as EventEnvelope).id).toBeGreaterThan((events[i - 1] as EventEnvelope).id)
    }
  })

  it('makes the stale request show an approval for an earlier revision', () => {
    const d = detail(engine(), FIXTURE_IDS.stale)
    const accepted = d.approvals.filter((a) => a.kind === 'ticket' && a.status === 'accepted')
    expect(d.currentRevision?.n).toBe(2)
    expect(accepted.at(-1)?.target).toBe(d.revisions[0]?.hash)
    expect(accepted.at(-1)?.target).not.toBe(d.currentRevision?.hash)
  })

  it('hashes tickets with SHA-256', () => {
    expect(sha256('abc')).toBe('ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad')
    expect(detail(engine(), FIXTURE_IDS.done).currentRevision?.hash).toMatch(/^[0-9a-f]{64}$/)
  })

  it('keeps evidence paths on the aggregated subgraph with the request as anchor', () => {
    const e = engine()
    const sub = e.route('GET', `/api/graph/subgraph?requestId=${FIXTURE_IDS.done}&mode=aggregated`).json as Subgraph
    const ids = new Set(sub.nodes.map((n) => n.id))
    expect(ids.has(`actron:request:${FIXTURE_IDS.done}`)).toBe(true)
    for (const ev of detail(e, FIXTURE_IDS.done).evidence) for (const id of ev.path) expect(ids.has(id)).toBe(true)
    const expanded = e.route('GET', `/api/graph/subgraph?requestId=${FIXTURE_IDS.done}&mode=expanded`).json as Subgraph
    expect(expanded.nodes.length).toBeGreaterThanOrEqual(sub.nodes.length)
  })
})

describe('scenarios', () => {
  it('reads the scenario from the URL and remembers it', () => {
    window.history.replaceState(null, '', '/app?fixture=empty')
    expect(detectScenario()).toBe('empty')
    window.history.replaceState(null, '', '/app')
    expect(detectScenario()).toBe('empty')
    window.sessionStorage.clear()
    expect(detectScenario()).toBe('default')
  })

  it('empty: no requests, no connections, zero counts', () => {
    const e = engine('empty')
    expect((e.route('GET', '/api/requests').json as { requests: unknown[] }).requests).toHaveLength(0)
    expect((e.route('GET', '/api/connections').json as { connections: unknown[] }).connections).toHaveLength(0)
    expect((e.route('GET', '/api/graph/stats').json as { nodes: number }).nodes).toBe(0)
    expect((e.route('GET', '/api/ingestion/status').json as { memoryPercent: number }).memoryPercent).toBe(0)
  })

  it('backend-down: 503 everywhere except /api/me', () => {
    const e = engine('backend-down')
    expect(e.route('GET', '/api/me').status).toBe(200)
    const res = e.route('GET', '/api/requests')
    expect(res.status).toBe(503)
    expect(res.json).toEqual({ error: { code: 'unavailable', message: 'Actron could not reach the API. Retry in a moment.' } })
  })

  it('stream-drop: the first open of a stream drops after two events, the next does not', () => {
    const e = engine('stream-drop')
    expect(e.openStream(FIXTURE_IDS.done).dropAfter).toBe(2)
    expect(e.openStream(FIXTURE_IDS.done).dropAfter).toBeNull()
    expect(engine().openStream(FIXTURE_IDS.done).dropAfter).toBeNull()
  })
})

describe('live request', () => {
  it('investigates, asks, writes the ticket, refuses a stale approval and builds to a PR, then finishes', () => {
    const e = engine()
    e.startLive()
    let d = detail(e, FIXTURE_IDS.live)
    expect(d.state).toBe('Needs your input')
    expect(d.label).toBe('conflict')
    expect(d.questions).toHaveLength(2)
    expect(d.evidence.length).toBeGreaterThanOrEqual(5)
    const types = e.events(FIXTURE_IDS.live).map((x) => x.type)
    expect(types.filter((t) => t === 'tool.called').length).toBeGreaterThanOrEqual(8)
    expect(types).toContain('judgment.made')

    for (const q of d.questions) {
      const res = e.route('POST', `/api/requests/${FIXTURE_IDS.live}/answers`, { questionId: q.questionId, value: q.options[0]?.value })
      expect(res.status).toBe(200)
    }
    d = detail(e, FIXTURE_IDS.live)
    expect(d.state).toBe('Awaiting approval')
    expect(d.revisions[0]?.linear?.identifier).toBe('CAL-214')

    const stale = e.route('POST', `/api/requests/${FIXTURE_IDS.live}/approvals`, { kind: 'ticket', revisionHash: 'deadbeef' })
    expect(stale.status).toBe(409)
    expect((stale.json as { error: { code: string } }).error.code).toBe('stale_revision')

    const okRes = e.route('POST', `/api/requests/${FIXTURE_IDS.live}/approvals`, { kind: 'ticket', revisionHash: d.currentRevision?.hash })
    expect(okRes.status).toBe(200)
    d = detail(e, FIXTURE_IDS.live)
    expect(d.state).toBe('PR ready for review')
    expect(d.pr?.number).toBe(18)
    const liveTypes = e.events(FIXTURE_IDS.live).map((x) => x.type)
    expect(liveTypes).toContain('build.repair')
    expect(liveTypes).toContain('handoff.created')

    expect(e.route('POST', `/api/requests/${FIXTURE_IDS.live}/approvals`, { kind: 'pr', headSha: 'abc1234' }).status).toBe(409)
    expect(e.route('POST', `/api/requests/${FIXTURE_IDS.live}/approvals`, { kind: 'pr', headSha: d.pr?.headSha }).status).toBe(200)
    d = detail(e, FIXTURE_IDS.live)
    expect(d.state).toBe('Done')
    expect(d.outcome).toBe('approved')
  })

  it('a ticket edit creates a new revision and makes the earlier approval stale', () => {
    const e = engine()
    const before = detail(e, FIXTURE_IDS.nothing)
    const content = { ...(before.revisions[0]?.content as NonNullable<RequestDetail['revisions'][number]>['content']), objective: 'Name the REPL type and its version in the tooltip.' }
    const res = e.route('POST', `/api/requests/${FIXTURE_IDS.nothing}/ticket/revisions`, { content })
    expect(res.status).toBe(200)
    const after = detail(e, FIXTURE_IDS.nothing)
    expect(after.currentRevision?.n).toBe(2)
    const revs = e.route('GET', `/api/requests/${FIXTURE_IDS.nothing}/ticket/revisions`).json as { diffs: { changes: { field: string }[] }[] }
    expect(revs.diffs[0]?.changes.map((c) => c.field)).toEqual(['objective'])
  })

  it('refuses actions that are not valid in the current state', () => {
    const e = engine()
    expect(e.route('POST', `/api/requests/${FIXTURE_IDS.done}/cancel`, {}).status).toBe(409)
    expect(e.route('POST', `/api/requests/${FIXTURE_IDS.building}/retry`, {}).status).toBe(409)
    expect(e.route('POST', `/api/requests/${FIXTURE_IDS.failed}/retry`, {}).status).toBe(200)
  })

  it('creates a new request from the UI and runs it to approval', () => {
    const e = engine()
    const res = e.route('POST', '/api/requests', { text: 'Add a command that restarts the REPL' })
    expect(res.status).toBe(201)
    const id = (res.json as { request: RequestDetail }).request.id
    expect(detail(e, id).state).toBe('Awaiting approval')
  })
})

describe('streams', () => {
  it('replays events after lastEventId, then delivers new ones', () => {
    const e = engine()
    const received: number[] = []
    const sub = e.subscribe(FIXTURE_IDS.done, 5, (ev) => received.push(ev.seq ?? -1))
    expect(sub.replay[0]?.seq).toBe(6)
    expect(sub.replay.at(-1)?.seq).toBe(e.events(FIXTURE_IDS.done).length)
    e.startLive()
    expect(received).toEqual([])
    const live: string[] = []
    e.subscribe(FIXTURE_IDS.prReady, null, (ev) => live.push(ev.type))
    e.route('POST', `/api/requests/${FIXTURE_IDS.prReady}/cancel`, {})
    expect(live).toEqual(['request.cancelled', 'request.state_changed'])
  })

  it('forwards state changes to the workspace stream', () => {
    const e = engine()
    const ws: string[] = []
    e.subscribe(WS_KEY, null, (ev) => ws.push(ev.type))
    e.route('POST', `/api/requests/${FIXTURE_IDS.prReady}/cancel`, {})
    expect(ws).toContain('request.state_changed')
  })

  it('serves server components through the router', () => {
    const res = fixtureResponse('GET', '/api/requests?group=needs_you')
    expect(res.status).toBe(200)
    expect((res.json as { counts: { needsYou: number } }).counts.needsYou).toBeGreaterThan(0)
  })
})
