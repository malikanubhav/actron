import type { EventEnvelope } from '../api/types'

/** The ordering key: `seq` on request streams, the global `id` on the workspace stream. */
export function eventKey(event: EventEnvelope): number {
  return event.seq ?? event.id
}

/** Merge incoming envelopes into a list: dedupe by key, keep ascending order. Returns the same array if nothing new. */
export function mergeEvents(existing: readonly EventEnvelope[] | undefined, incoming: readonly EventEnvelope[]): EventEnvelope[] {
  const base = existing ?? []
  const seen = new Set(base.map(eventKey))
  const fresh: EventEnvelope[] = []
  for (const event of incoming) {
    const key = eventKey(event)
    if (seen.has(key)) continue
    seen.add(key)
    fresh.push(event)
  }
  if (fresh.length === 0) return base as EventEnvelope[]
  const merged = [...base, ...fresh]
  const last = base.length ? eventKey(base[base.length - 1] as EventEnvelope) : -Infinity
  const appendOnly = fresh.every((e, i) => eventKey(e) > (i === 0 ? last : eventKey(fresh[i - 1] as EventEnvelope)))
  if (!appendOnly) merged.sort((a, b) => eventKey(a) - eventKey(b))
  return merged
}

export function highestKey(events: readonly EventEnvelope[] | undefined): number | null {
  if (!events || events.length === 0) return null
  return eventKey(events[events.length - 1] as EventEnvelope)
}
