/**
 * The hero graph: the ontology type graph, coloured by source, with one evidence path. The landing page shows the
 * concept, not a workspace's data, so every visitor (signed in or not) sees the same picture and it never depends on
 * what a workspace has read so far (a sample of a real workspace is mostly code).
 */
import { graphFromOntology, hashSeed, layout3d, type HeroGraph, type OntologySnapshotLike } from './layout3d'

export async function loadHeroGraph(): Promise<HeroGraph> {
  const snapshot = (await import('@/lib/ontology-snapshot.json')).default as unknown as OntologySnapshotLike
  return graphFromOntology(snapshot)
}

const CACHE_PREFIX = 'actron.hero.v1.'

export function cacheKey(graph: HeroGraph): string {
  return `${CACHE_PREFIX}${hashSeed(`${graph.nodes.length}|${graph.links.length}|${graph.nodes.map((n) => n.id).join(',')}`)}`
}

/** Positions from sessionStorage, else computed in a worker (or inline as a last resort), then cached. */
export async function layoutHeroGraph(graph: HeroGraph): Promise<Float32Array> {
  const key = cacheKey(graph)
  try {
    const cached = sessionStorage.getItem(key)
    if (cached) {
      const parsed = JSON.parse(cached) as number[]
      if (parsed.length === graph.nodes.length * 3) return Float32Array.from(parsed)
    }
  } catch {
    // Storage unavailable; compute.
  }
  const positions = await computeInWorker(graph)
  try {
    sessionStorage.setItem(key, JSON.stringify(Array.from(positions, (v) => Math.round(v * 1000) / 1000)))
  } catch {
    // Quota or privacy mode: fine without the cache.
  }
  return positions
}

function computeInWorker(graph: HeroGraph): Promise<Float32Array> {
  if (typeof Worker === 'undefined') return Promise.resolve(layout3d(graph.nodes, graph.links))
  return new Promise((resolve) => {
    try {
      const worker = new Worker(new URL('./hero.worker.ts', import.meta.url), { type: 'module' })
      worker.onmessage = (event: MessageEvent<{ positions: Float32Array }>) => {
        resolve(event.data.positions)
        worker.terminate()
      }
      worker.onerror = () => {
        worker.terminate()
        resolve(layout3d(graph.nodes, graph.links))
      }
      worker.postMessage({ nodes: graph.nodes, links: graph.links })
    } catch {
      resolve(layout3d(graph.nodes, graph.links))
    }
  })
}
