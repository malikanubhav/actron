import { describe, expect, it, vi } from 'vitest'
import { createVisibilityController, heroMode } from '@/components/hero/mode'
import { graphFromOntology, layout3d, pickEvidencePath, project, hashSeed, type HeroNode } from '@/components/hero/layout3d'
import { cacheKey } from '@/components/hero/data'
import snapshot from '@/lib/ontology-snapshot.json'

const capable = { reducedMotion: false, hardwareConcurrency: 8, saveData: false, webgl: true }

describe('hero mode (C-AC-28)', () => {
  it('C-AC-28 runs in 3D on a capable device', () => {
    expect(heroMode(capable)).toBe('3d')
  })
  it('C-AC-28 uses the fallback image under reduced motion', () => {
    expect(heroMode({ ...capable, reducedMotion: true })).toBe('fallback')
  })
  it('C-AC-28 uses the fallback image without WebGL', () => {
    expect(heroMode({ ...capable, webgl: false })).toBe('fallback')
  })
  it('C-AC-28 uses the fallback image on four or fewer cores', () => {
    expect(heroMode({ ...capable, hardwareConcurrency: 4 })).toBe('fallback')
    expect(heroMode({ ...capable, hardwareConcurrency: 2 })).toBe('fallback')
  })
  it('C-AC-28 uses the fallback image with save-data on', () => {
    expect(heroMode({ ...capable, saveData: true })).toBe('fallback')
  })
  it('C-AC-28 keeps 3D when the core count is unknown', () => {
    expect(heroMode({ ...capable, hardwareConcurrency: undefined })).toBe('3d')
  })
})

describe('hero visibility controller (C-AC-29)', () => {
  it('C-AC-29 pauses when scrolled out of view and resumes when back', () => {
    const onChange = vi.fn()
    const c = createVisibilityController(onChange)
    expect(c.active).toBe(true)
    c.setIntersecting(false)
    expect(c.active).toBe(false)
    c.setIntersecting(true)
    expect(onChange.mock.calls.map((x) => x[0])).toEqual([false, true])
  })
  it('C-AC-29 pauses while the tab is hidden even when on screen', () => {
    const onChange = vi.fn()
    const c = createVisibilityController(onChange)
    c.setDocumentHidden(true)
    expect(c.active).toBe(false)
    c.setIntersecting(false)
    c.setDocumentHidden(false)
    expect(c.active).toBe(false)
    expect(onChange).toHaveBeenCalledTimes(1)
  })
  it('C-AC-29 does not report repeated identical signals', () => {
    const onChange = vi.fn()
    const c = createVisibilityController(onChange)
    c.setIntersecting(true)
    c.setDocumentHidden(false)
    expect(onChange).not.toHaveBeenCalled()
  })
})

describe('hero layout and evidence path (spec C, C6)', () => {
  const graph = graphFromOntology(snapshot as never)

  it('builds the ontology type graph with every type as a node', () => {
    expect(graph.nodes).toHaveLength(96)
    expect(graph.source).toBe('ontology')
    expect(graph.links.length).toBeGreaterThan(100)
  })

  it('traces a multi-hop evidence path from the request to a code function', () => {
    expect(graph.path[0]).toBe('Request')
    expect(graph.path[graph.path.length - 1]).toBe('CodeFunction')
    expect(graph.path.length).toBeGreaterThanOrEqual(4)
    const pairs = new Set(graph.links.flatMap((l) => [`${l.from}|${l.to}`, `${l.to}|${l.from}`]))
    for (let i = 0; i < graph.path.length - 1; i++) expect(pairs.has(`${graph.path[i]}|${graph.path[i + 1]}`)).toBe(true)
  })

  it('lays out deterministically within radius 11', () => {
    const a = layout3d(graph.nodes, graph.links, 40)
    const b = layout3d(graph.nodes, graph.links, 40)
    expect(Array.from(a)).toEqual(Array.from(b))
    for (let i = 0; i < a.length / 3; i++) expect(Math.hypot(a[i * 3]!, a[i * 3 + 1]!, a[i * 3 + 2]!)).toBeLessThanOrEqual(11.001)
  })

  it('projects positions inside the target box', () => {
    const pts = project(layout3d(graph.nodes, graph.links, 20), 400, 300, 0.6, 0.35, 10)
    for (const p of pts) {
      expect(p.x).toBeGreaterThanOrEqual(9.99)
      expect(p.x).toBeLessThanOrEqual(390.01)
      expect(p.y).toBeGreaterThanOrEqual(9.99)
      expect(p.y).toBeLessThanOrEqual(290.01)
    }
  })

  it('returns an empty path for an empty graph', () => {
    expect(pickEvidencePath([], [])).toEqual([])
  })

  it('cache keys change with the graph', () => {
    const small: HeroNode[] = [{ id: 'a', group: 'core' }]
    expect(cacheKey(graph)).not.toBe(cacheKey({ ...graph, nodes: small }))
    expect(hashSeed('a')).not.toBe(hashSeed('b'))
  })
})
