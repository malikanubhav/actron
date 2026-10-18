// Runs the force layout off the main thread (spec C, C-AC-12).
import { computeLayout, type LayoutRequest } from './layout'

// Typed narrowly so the DOM and worker libs never mix in one program.
declare const self: { onmessage: ((event: MessageEvent) => void) | null; postMessage: (message: unknown) => void }

self.onmessage = (event: MessageEvent<{ id: number; request: LayoutRequest }>) => {
  const { id, request } = event.data
  const started = performance.now()
  const positions = computeLayout(request)
  self.postMessage({ id, positions, ms: performance.now() - started })
}
