// Lays out the hero graph off the main thread (spec C, C6).
import { layout3d, type HeroLink, type HeroNode } from './layout3d'

// Typed narrowly so the DOM and worker libs never mix in one program.
declare const self: { onmessage: ((event: MessageEvent) => void) | null; postMessage: (message: unknown, transfer?: Transferable[]) => void }

self.onmessage = (event: MessageEvent<{ nodes: HeroNode[]; links: HeroLink[] }>) => {
  const positions = layout3d(event.data.nodes, event.data.links)
  self.postMessage({ positions }, [positions.buffer])
}
