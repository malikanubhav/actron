/**
 * One server-sent-events connection with resume (spec C, C4; spec B, B1).
 * - Listens to every named event type (the backend sends `event: <type>`), plus unnamed messages.
 * - Dedupe and order are the caller's job (see mergeEvents); this class only delivers envelopes.
 * - On error: the browser's own retry keeps `Last-Event-ID`; when the browser gives up (CLOSED), we reconnect
 *   with exponential backoff and pass `lastEventId` as a query parameter.
 * - Status: `live` while open, `reconnecting` while retrying, `offline` after several failures or when the
 *   browser reports no network.
 */
import type { EventEnvelope } from '../api/types'
import { ALL_EVENT_TYPES } from '../events'

export type StreamStatus = 'connecting' | 'live' | 'reconnecting' | 'offline' | 'closed'

export interface EventSourceLike {
  readonly readyState: number
  onopen: ((this: EventSource, ev: Event) => unknown) | null
  onerror: ((this: EventSource, ev: Event) => unknown) | null
  onmessage: ((this: EventSource, ev: MessageEvent) => unknown) | null
  addEventListener(type: string, listener: (ev: MessageEvent) => void): void
  close(): void
}

export type EventSourceFactory = (url: string) => EventSourceLike

export interface StreamOptions {
  url: string
  onEvent: (event: EventEnvelope) => void
  onStatus?: (status: StreamStatus) => void
  /** Highest id already received (seq for request streams, events.id for the workspace stream). */
  lastEventId?: () => number | null
  factory?: EventSourceFactory
  initialDelayMs?: number
  maxDelayMs?: number
  /** Failed attempts before the status turns `offline` (reconnecting continues at the max delay). */
  offlineAfter?: number
  extraEventTypes?: readonly string[]
}

const CLOSED = 2

export function backoffDelay(attempt: number, initialMs = 500, maxMs = 15_000): number {
  return Math.min(maxMs, initialMs * 2 ** Math.max(0, attempt - 1))
}

export function withLastEventId(url: string, lastId: number | null): string {
  if (lastId === null || lastId === undefined) return url
  const sep = url.includes('?') ? '&' : '?'
  return `${url}${sep}lastEventId=${lastId}`
}

const defaultFactory: EventSourceFactory = (url) =>
  new EventSource(url, { withCredentials: true }) as unknown as EventSourceLike

export class StreamConnection {
  private source: EventSourceLike | null = null
  private attempt = 0
  private timer: ReturnType<typeof setTimeout> | null = null
  private stopped = false
  private status: StreamStatus = 'connecting'
  private readonly opts: Required<Omit<StreamOptions, 'onStatus' | 'lastEventId' | 'extraEventTypes'>> &
    Pick<StreamOptions, 'onStatus' | 'lastEventId' | 'extraEventTypes'>

  constructor(options: StreamOptions) {
    // Options passed as `undefined` must not override the defaults.
    this.opts = {
      ...options,
      factory: options.factory ?? defaultFactory,
      initialDelayMs: options.initialDelayMs ?? 500,
      maxDelayMs: options.maxDelayMs ?? 15_000,
      offlineAfter: options.offlineAfter ?? 5,
    }
  }

  get currentStatus(): StreamStatus {
    return this.status
  }

  start(): void {
    this.stopped = false
    this.open()
  }

  stop(): void {
    this.stopped = true
    if (this.timer) clearTimeout(this.timer)
    this.timer = null
    this.source?.close()
    this.source = null
    this.setStatus('closed')
  }

  private setStatus(status: StreamStatus): void {
    if (this.status === status) return
    this.status = status
    this.opts.onStatus?.(status)
  }

  private open(): void {
    if (this.stopped) return
    const lastId = this.opts.lastEventId?.() ?? null
    const url = this.attempt === 0 && lastId === null ? this.opts.url : withLastEventId(this.opts.url, lastId)
    let source: EventSourceLike
    try {
      source = this.opts.factory(url)
    } catch {
      this.scheduleReconnect()
      return
    }
    this.source = source
    const handle = (ev: MessageEvent) => {
      if (typeof ev.data !== 'string' || ev.data === '') return
      try {
        const envelope = JSON.parse(ev.data) as EventEnvelope
        if (envelope && typeof envelope.type === 'string') this.opts.onEvent(envelope)
      } catch {
        // A malformed message is skipped; the next valid one still arrives.
      }
    }
    source.onopen = () => {
      this.attempt = 0
      this.setStatus('live')
    }
    source.onmessage = handle
    for (const type of [...ALL_EVENT_TYPES, ...(this.opts.extraEventTypes ?? [])]) source.addEventListener(type, handle)
    source.onerror = () => {
      if (this.stopped) return
      if (source.readyState === CLOSED) {
        source.close()
        if (this.source === source) this.source = null
        this.scheduleReconnect()
      } else {
        // The browser retries on its own and sends Last-Event-ID.
        this.attempt += 1
        this.setStatus(this.isOffline() ? 'offline' : 'reconnecting')
      }
    }
  }

  private isOffline(): boolean {
    const navigatorOffline = typeof navigator !== 'undefined' && navigator.onLine === false
    return navigatorOffline || this.attempt >= this.opts.offlineAfter
  }

  private scheduleReconnect(): void {
    if (this.stopped) return
    this.attempt += 1
    this.setStatus(this.isOffline() ? 'offline' : 'reconnecting')
    const delay = backoffDelay(this.attempt, this.opts.initialDelayMs, this.opts.maxDelayMs)
    this.timer = setTimeout(() => {
      this.timer = null
      this.open()
    }, delay)
  }
}
