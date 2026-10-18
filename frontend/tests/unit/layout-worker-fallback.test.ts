import { afterEach, describe, expect, it, vi } from 'vitest'

const request = {
  nodes: [
    { id: 'a', group: 'core' as const },
    { id: 'b', group: 'code' as const },
  ],
  links: [{ from: 'a', to: 'b' }],
  width: 400,
  height: 300,
}

class SilentWorker {
  onmessage: ((e: MessageEvent) => void) | null = null
  onerror: ((e: Event) => void) | null = null
  onmessageerror: ((e: MessageEvent) => void) | null = null
  posted = 0
  postMessage(): void {
    this.posted += 1
  }
  terminate(): void {}
}

describe('graph layout worker fallback', () => {
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
    vi.resetModules()
  })

  it('C-AC-12 lays out on the main thread when the worker never answers', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('Worker', SilentWorker)
    const { requestLayout } = await import('../../components/graph/useLayout')
    const done = requestLayout(request)
    await vi.advanceTimersByTimeAsync(3100)
    const positions = await done
    expect(Object.keys(positions).sort()).toEqual(['a', 'b'])
  })

  it('C-AC-12 settles pending layouts when the worker fails to load', async () => {
    const created: SilentWorker[] = []
    vi.stubGlobal(
      'Worker',
      // A constructor function (arrow functions cannot be called with `new`).
      vi.fn(function makeWorker() {
        const w = new SilentWorker()
        created.push(w)
        return w
      }),
    )
    const { requestLayout } = await import('../../components/graph/useLayout')
    const done = requestLayout(request)
    expect(created).toHaveLength(1)
    created[0]?.onerror?.(new Event('error'))
    const positions = await done
    expect(Object.keys(positions)).toHaveLength(2)
  })
})
