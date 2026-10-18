'use client'
import { useEffect, useRef, useState } from 'react'
import { computeLayout, type LayoutRequest, type Positions } from './layout'

let worker: Worker | null = null
let workerFailed = false
let nextId = 1
const pending = new Map<number, { request: LayoutRequest; resolve: (p: Positions) => void }>()
// A worker that never answers (failed to load, or crashed) must not leave the canvas waiting forever.
const WORKER_TIMEOUT_MS = 3000

function settleOnMainThread(id: number): void {
  const job = pending.get(id)
  if (!job) return
  pending.delete(id)
  job.resolve(computeLayout(job.request))
}

function failWorker(): void {
  workerFailed = true
  worker?.terminate()
  worker = null
  for (const id of [...pending.keys()]) settleOnMainThread(id)
}

function getWorker(): Worker | null {
  if (workerFailed || typeof window === 'undefined' || typeof Worker === 'undefined') return null
  if (worker) return worker
  try {
    worker = new Worker(new URL('./layout.worker.ts', import.meta.url), { type: 'module' })
    worker.onmessage = (event: MessageEvent<{ id: number; positions: Positions }>) => {
      pending.get(event.data.id)?.resolve(event.data.positions)
      pending.delete(event.data.id)
    }
    worker.onerror = failWorker
    worker.onmessageerror = failWorker
    return worker
  } catch {
    workerFailed = true
    return null
  }
}

/** Layout off the main thread; falls back to an idle-time computation if workers are unavailable. */
export function requestLayout(request: LayoutRequest): Promise<Positions> {
  const w = getWorker()
  if (!w) {
    return new Promise((resolve) => setTimeout(() => resolve(computeLayout(request)), 0))
  }
  const id = nextId++
  return new Promise((resolve) => {
    pending.set(id, { request, resolve })
    w.postMessage({ id, request })
    setTimeout(() => {
      if (pending.has(id)) failWorker()
    }, WORKER_TIMEOUT_MS)
  })
}

export function useLayout(request: LayoutRequest | null): { positions: Positions; ready: boolean } {
  const [positions, setPositions] = useState<Positions>({})
  const [ready, setReady] = useState(false)
  const latest = useRef(0)
  const previous = useRef<Positions>({})
  const lastSize = useRef('')
  const signature = request
    ? `${request.width}x${request.height}|${request.anchorId ?? ''}|${request.nodes.map((n) => n.id).join(',')}|${request.links.length}`
    : ''

  useEffect(() => {
    if (!request || request.width <= 0 || request.height <= 0) return
    const ticket = ++latest.current
    // A new size starts fresh; new nodes on the same size keep existing positions (node entrance).
    const sizeKey = `${request.width}x${request.height}`
    if (sizeKey !== lastSize.current) previous.current = {}
    lastSize.current = sizeKey
    void requestLayout({ ...request, previous: previous.current }).then((next) => {
      if (ticket !== latest.current) return
      previous.current = next
      setPositions(next)
      setReady(true)
    })
    // The signature captures every input that changes the layout.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signature])

  return { positions, ready }
}
