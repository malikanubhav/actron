import type { EventSourceLike } from '@/lib/stream/connection'
import type { EventEnvelope } from '@/lib/api/types'

/** A scriptable EventSource for stream hook tests. */
export class FakeSource implements EventSourceLike {
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
  static reset() {
    FakeSource.instances = []
  }
  static latest(): FakeSource {
    return FakeSource.instances[FakeSource.instances.length - 1] as FakeSource
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
  send(e: EventEnvelope) {
    const ev = new MessageEvent(e.type, { data: JSON.stringify(e) })
    for (const l of this.listeners.get(e.type) ?? []) l(ev)
  }
}

export const fakeFactory = (url: string) => new FakeSource(url)
