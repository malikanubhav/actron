import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { QueryClient } from '@tanstack/react-query'
import { StreamConnection, backoffDelay, withLastEventId, type EventSourceLike, type StreamStatus } from '@/lib/stream/connection'
import { eventKey, highestKey, mergeEvents } from '@/lib/stream/merge'
import { ingestRequestEvents } from '@/lib/hooks/useRequestStream'
import type { EventEnvelope, RequestDetail } from '@/lib/api/types'
import { qk } from '@/lib/query-keys'
import { makeEvent, makeRequestDetail } from './helpers/render'

class FakeSource implements EventSourceLike {
  static instances: FakeSource[] = []
  readyState = 0
  onopen: EventSourceLike['onopen'] = null
  onerror: EventSourceLike['onerror'] = null
  onmessage: EventSourceLike['onmessage'] = null
  listeners = new Map<string, ((ev: MessageEvent) => void)[]>()
  closed = false
  constructor(public url: string) {
    FakeSource.instances.push(this)
  }
  addEventListener(type: string, l: (ev: MessageEvent) => void) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), l])
  }
  close() {
    this.closed = true
    this.readyState = 2
  }
  open() {
    this.readyState = 1
    this.onopen?.call(this as unknown as EventSource, new Event('open'))
  }
  emit(type: string, data: string) {
    const ev = new MessageEvent(type, { data })
    for (const l of this.listeners.get(type) ?? []) l(ev)
  }
  send(e: EventEnvelope) {
    this.emit(e.type, JSON.stringify(e))
  }
  fail(closed: boolean) {
    this.readyState = closed ? 2 : 0
    this.onerror?.call(this as unknown as EventSource, new Event('error'))
  }
}

const latest = () => FakeSource.instances[FakeSource.instances.length - 1] as FakeSource

function connect(extra: Partial<ConstructorParameters<typeof StreamConnection>[0]> = {}) {
  const received: EventEnvelope[] = []
  const statuses: StreamStatus[] = []
  let events: EventEnvelope[] = []
  const conn = new StreamConnection({
    url: '/api/requests/r1/events',
    factory: (url) => new FakeSource(url),
    onEvent: (e) => {
      received.push(e)
      events = mergeEvents(events, [e])
    },
    onStatus: (s) => statuses.push(s),
    lastEventId: () => highestKey(events),
    initialDelayMs: 100,
    maxDelayMs: 1000,
    offlineAfter: 3,
    ...extra,
  })
  conn.start()
  return { conn, received, statuses, merged: () => events }
}

beforeEach(() => {
  FakeSource.instances = []
  vi.useFakeTimers()
})
afterEach(() => vi.useRealTimers())

describe('C-AC-17 request stream', () => {
  it('C-AC-17 named events are delivered and the status goes live', () => {
    const { received, statuses } = connect()
    latest().open()
    latest().send(makeEvent('tool.called', { tool: 'search' }, 1))
    latest().send(makeEvent('build.step', { text: 'x' }, 2))
    expect(received.map((e) => e.seq)).toEqual([1, 2])
    expect(statuses).toEqual(['live'])
  })

  it('C-AC-17 malformed and empty messages are skipped', () => {
    const { received } = connect()
    latest().open()
    latest().emit('tool.called', '{not json')
    latest().emit('tool.called', '')
    latest().onmessage?.call(latest() as unknown as EventSource, new MessageEvent('message', { data: JSON.stringify(makeEvent('build.step', {}, 3)) }))
    expect(received.map((e) => e.seq)).toEqual([3])
  })

  it('C-AC-17 the first connect has no lastEventId', () => {
    connect()
    expect(latest().url).toBe('/api/requests/r1/events')
  })

  it('C-AC-17 drops mid-stream, reconnects with backoff and lastEventId, and loses or duplicates nothing', () => {
    const { merged, statuses } = connect()
    const first = latest()
    first.open()
    first.send(makeEvent('build.step', {}, 1))
    first.send(makeEvent('build.step', {}, 2))
    first.fail(true)
    expect(statuses.at(-1)).toBe('reconnecting')
    expect(FakeSource.instances).toHaveLength(1)
    vi.advanceTimersByTime(99)
    expect(FakeSource.instances).toHaveLength(1)
    vi.advanceTimersByTime(1)
    const second = latest()
    expect(second.url).toBe('/api/requests/r1/events?lastEventId=2')
    second.open()
    // The server replays from 3, and a duplicate 2 arrives too.
    second.send(makeEvent('build.step', {}, 2))
    second.send(makeEvent('build.step', {}, 3))
    second.send(makeEvent('build.step', {}, 4))
    expect(merged().map((e) => e.seq)).toEqual([1, 2, 3, 4])
    expect(statuses).toEqual(['live', 'reconnecting', 'live'])
  })

  it('C-AC-17 while the browser retries on its own the status is reconnecting', () => {
    const { statuses } = connect()
    latest().open()
    latest().fail(false)
    expect(statuses.at(-1)).toBe('reconnecting')
    expect(FakeSource.instances).toHaveLength(1)
  })

  it('C-AC-17 reports offline after repeated failures and keeps trying at the max delay', () => {
    const { statuses } = connect()
    latest().fail(true)
    vi.advanceTimersByTime(100)
    latest().fail(true)
    vi.advanceTimersByTime(200)
    latest().fail(true)
    expect(statuses.at(-1)).toBe('offline')
    vi.advanceTimersByTime(400)
    expect(FakeSource.instances).toHaveLength(4)
    latest().open()
    expect(statuses.at(-1)).toBe('live')
  })

  it('C-AC-17 stop() closes the source and prevents reconnecting', () => {
    const { conn, statuses } = connect()
    const s = latest()
    s.fail(true)
    conn.stop()
    vi.advanceTimersByTime(5000)
    expect(FakeSource.instances).toHaveLength(1)
    expect(statuses.at(-1)).toBe('closed')
    expect(conn.currentStatus).toBe('closed')
  })

  it('C-AC-17 a factory that throws schedules a reconnect', () => {
    let calls = 0
    const conn = new StreamConnection({
      url: '/x',
      onEvent: () => undefined,
      initialDelayMs: 50,
      factory: (url) => {
        calls += 1
        if (calls === 1) throw new Error('blocked')
        return new FakeSource(url)
      },
    })
    conn.start()
    vi.advanceTimersByTime(50)
    expect(calls).toBe(2)
    conn.stop()
  })

  it('backoff doubles up to the max; lastEventId is appended correctly', () => {
    expect([1, 2, 3, 4, 10].map((a) => backoffDelay(a, 500, 15000))).toEqual([500, 1000, 2000, 4000, 15000])
    expect(withLastEventId('/api/stream', 7)).toBe('/api/stream?lastEventId=7')
    expect(withLastEventId('/x?a=1', 7)).toBe('/x?a=1&lastEventId=7')
    expect(withLastEventId('/x', null)).toBe('/x')
  })
})

describe('C-AC-17 merge and ingest', () => {
  it('C-AC-17 mergeEvents dedupes by seq and sorts out-of-order arrivals', () => {
    const a = mergeEvents([], [makeEvent('x', {}, 1), makeEvent('x', {}, 3)])
    const b = mergeEvents(a, [makeEvent('x', {}, 2), makeEvent('x', {}, 3)])
    expect(b.map(eventKey)).toEqual([1, 2, 3])
    expect(mergeEvents(b, [makeEvent('x', {}, 2)])).toBe(b)
    expect(highestKey(b)).toBe(3)
    expect(highestKey([])).toBeNull()
  })

  it('workspace events without seq use the global id', () => {
    const e = { ...makeEvent('ingestion.progress', {}, 1), seq: null, id: 77 }
    expect(eventKey(e)).toBe(77)
  })

  it('C-AC-17 ingestRequestEvents writes the events cache and applies only events newer than the fetched detail', () => {
    const client = new QueryClient()
    const detail: RequestDetail = makeRequestDetail({ updatedAt: '2026-10-17T09:00:05.000Z', investigation: { mode: 'agent', toolCalls: 4, tokens: { input: 0, output: 0 }, costUsd: 0, stub: false } })
    client.setQueryData(qk.request(detail.id), { request: detail })
    const old = Array.from({ length: 4 }, (_, i) => makeEvent('tool.called', { tool: 'search', callId: `c${i}` }, i + 1))
    const fresh = makeEvent('tool.called', { tool: 'callers', callId: 'c9' }, 9)
    const added = ingestRequestEvents(client, detail.id, [...old, fresh])
    expect(added).toHaveLength(5)
    expect(client.getQueryData<EventEnvelope[]>(qk.events(detail.id))?.map((e) => e.seq)).toEqual([1, 2, 3, 4, 9])
    expect(client.getQueryData<{ request: RequestDetail }>(qk.request(detail.id))?.request.investigation?.toolCalls).toBe(5)
    expect(ingestRequestEvents(client, detail.id, [fresh])).toEqual([])
  })
})
