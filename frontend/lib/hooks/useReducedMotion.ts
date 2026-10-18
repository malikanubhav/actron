'use client'
import { useSyncExternalStore } from 'react'

const QUERY = '(prefers-reduced-motion: reduce)'

/** True when the person asked the system for less motion. False on the server. */
export function useReducedMotion(): boolean {
  return useSyncExternalStore(
    (listener) => {
      const mq = window.matchMedia?.(QUERY)
      mq?.addEventListener?.('change', listener)
      return () => mq?.removeEventListener?.('change', listener)
    },
    () => window.matchMedia?.(QUERY).matches === true,
    () => false,
  )
}
