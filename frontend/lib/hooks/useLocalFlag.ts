'use client'
import { useCallback, useSyncExternalStore } from 'react'

const EVENT = 'actron:local-flag'

function read(key: string): boolean {
  try {
    return window.localStorage.getItem(key) === '1'
  } catch {
    return false
  }
}

/** A boolean kept in localStorage, safe for server rendering (false on the server). */
export function useLocalFlag(key: string): [boolean, (value: boolean) => void] {
  const value = useSyncExternalStore(
    (listener) => {
      window.addEventListener('storage', listener)
      window.addEventListener(EVENT, listener)
      return () => {
        window.removeEventListener('storage', listener)
        window.removeEventListener(EVENT, listener)
      }
    },
    () => read(key),
    () => false,
  )
  const set = useCallback(
    (next: boolean) => {
      try {
        window.localStorage.setItem(key, next ? '1' : '0')
      } catch {
        // Storage unavailable: the change lasts until reload through the event below.
      }
      window.dispatchEvent(new Event(EVENT))
    },
    [key],
  )
  return [value, set]
}
