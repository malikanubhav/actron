'use client'
import { useSyncExternalStore } from 'react'

/**
 * A clock that ticks every `stepMs` (default 30 s). Snapshots are rounded to the step, so renders stay pure and
 * every component sharing the same step sees the same time.
 */
const listeners = new Map<number, Set<() => void>>()
const timers = new Map<number, ReturnType<typeof setInterval>>()

function subscribe(stepMs: number, listener: () => void): () => void {
  let set = listeners.get(stepMs)
  if (!set) {
    set = new Set()
    listeners.set(stepMs, set)
    timers.set(
      stepMs,
      setInterval(() => listeners.get(stepMs)?.forEach((l) => l()), stepMs),
    )
  }
  set.add(listener)
  return () => {
    set?.delete(listener)
    if (set && set.size === 0) {
      clearInterval(timers.get(stepMs))
      timers.delete(stepMs)
      listeners.delete(stepMs)
    }
  }
}

export function roundedNow(stepMs: number): number {
  return Math.floor(Date.now() / stepMs) * stepMs
}

export function useNow(stepMs = 30_000): number {
  return useSyncExternalStore(
    (l) => subscribe(stepMs, l),
    () => roundedNow(stepMs),
    () => roundedNow(stepMs),
  )
}
