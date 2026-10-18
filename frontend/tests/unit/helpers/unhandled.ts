/**
 * Collects unhandled promise rejections during a test instead of letting the runner fail the whole run.
 * Call the returned `stop()` in a `finally`; it puts the runner's own listeners back.
 */
export function captureUnhandled(): { errors: unknown[]; stop: () => void } {
  const errors: unknown[] = []
  const saved = process.listeners('unhandledRejection')
  process.removeAllListeners('unhandledRejection')
  const collect = (reason: unknown) => void errors.push(reason)
  process.on('unhandledRejection', collect)
  return {
    errors,
    stop: () => {
      process.removeListener('unhandledRejection', collect)
      for (const l of saved) process.on('unhandledRejection', l)
    },
  }
}

/** Lets a rejected promise reach the unhandled-rejection hook. */
export const flushRejections = () => new Promise<void>((resolve) => setTimeout(resolve, 20))
