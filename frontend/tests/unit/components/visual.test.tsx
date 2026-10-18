import { describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen } from '@testing-library/react'
import { GraphCanvas, ShapeIcon } from '@/components/graph/GraphCanvas'
import { SystemMap, EDGES, edgeId } from '@/components/system/SystemMap'
import { BrandMark, BRAND_NAMES, brandTitle, languageFor } from '@/components/brand/BrandMark'
import { Glyph, glyphNames } from '@/components/glyphs/Glyph'
import { GLYPH_NAMES, GLYPH_MOTION } from '@/components/glyphs/names'
import { ActronMark, ActronWordmark } from '@/components/brand/ActronLogo'
import type { Subgraph } from '@/lib/api/types'
import { makeEvent } from '../helpers/render'
import { PAYLOADS } from '../helpers/payloads'

const graph: Subgraph = {
  mode: 'aggregated',
  truncated: false,
  nodes: [
    { id: 'actron:request:r', type: 'Request', label: 'Inline results', group: 'core' },
    { id: 'd1', type: 'Decision', label: 'Keep output window', group: 'core' },
    { id: 'f1', type: 'CodeFunction', label: 'evaluateCode', group: 'code', count: 12 },
    { id: 's1', type: 'SlackMessage', label: 'thread', group: 'slack' },
  ],
  links: [
    { from: 'actron:request:r', to: 'd1', type: 'CONSTRAINED_BY', method: 'jev', confidence: 0.8 },
    { from: 'd1', to: 'f1', type: 'CONSTRAINS', method: null, confidence: null },
  ],
}

describe('C-AC-8 GraphCanvas', () => {
  it('renders the toolbar, counts, mode radios and the legend', () => {
    const onModeChange = vi.fn()
    render(<GraphCanvas graph={graph} onModeChange={onModeChange} onViewChange={() => undefined} anchorId="actron:request:r" />)
    expect(screen.getByTestId('graph-counts')).toHaveTextContent('4 groups shown · 2 links')
    const radios = screen.getAllByRole('radio')
    expect(radios.map((r) => r.getAttribute('aria-checked'))).toEqual(['true', 'false'])
    fireEvent.click(screen.getByRole('radio', { name: 'Expanded' }))
    expect(onModeChange).toHaveBeenCalledWith('expanded')
    expect(screen.getByRole('button', { name: 'Zoom in' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Fit to view' })).toBeInTheDocument()
    expect(screen.getByLabelText('Legend')).toHaveTextContent(/Explicit.*Inferred/)
  })

  it('C-AC-12 measures the canvas when the graph arrives after the first render', () => {
    // Real request pages render before the subgraph query returns; the canvas wrapper only exists once there
    // are nodes, so the size observer must attach then (a missed attach left "Laying out the graph…" forever).
    const observed: Element[] = []
    const original = window.ResizeObserver
    window.ResizeObserver = class {
      observe(el: Element) {
        observed.push(el)
      }
      unobserve() {}
      disconnect() {}
    } as unknown as typeof ResizeObserver
    try {
      const empty: Subgraph = { mode: 'aggregated', truncated: false, nodes: [], links: [] }
      const { rerender } = render(<GraphCanvas graph={empty} onViewChange={() => undefined} />)
      expect(observed).toHaveLength(0)
      rerender(<GraphCanvas graph={graph} onViewChange={() => undefined} />)
      expect(observed).toHaveLength(1)
      expect(observed[0]?.querySelector('canvas')).not.toBeNull()
    } finally {
      window.ResizeObserver = original
    }
  })

  it('C-AC-32 the canvas is a labelled keyboard target with a list-view alternative', () => {
    const onViewChange = vi.fn()
    render(<GraphCanvas graph={graph} onViewChange={onViewChange} label="Request graph" />)
    expect(screen.getByRole('img', { name: /Request graph\. 4 nodes\. Use arrow keys/ })).toHaveAttribute('tabindex', '0')
    fireEvent.click(screen.getByRole('button', { name: 'List view' }))
    expect(onViewChange).toHaveBeenCalledWith('list')
  })

  it('C-AC-32 list view groups nodes by type, shows counts and selects on click', () => {
    const onSelect = vi.fn()
    render(<GraphCanvas graph={graph} view="list" onViewChange={() => undefined} onSelect={onSelect} selectedId="d1" pathToTrace={['actron:request:r', 'd1']} />)
    const list = screen.getByTestId('graph-list')
    expect(list).toHaveTextContent('Decision · 1')
    expect(list).toHaveTextContent('12')
    expect(screen.getByRole('button', { name: /Keep output window/ })).toHaveAttribute('aria-current', 'true')
    fireEvent.click(screen.getByRole('button', { name: /evaluateCode/ }))
    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ id: 'f1' }))
    expect(screen.getByRole('button', { name: 'Canvas view' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByText('Evidence path')).toBeInTheDocument()
  })

  it('never draws more than the budget without asking', () => {
    const big: Subgraph = { ...graph, nodes: Array.from({ length: 12 }, (_, i) => ({ id: `n${i}`, type: 'CodeFunction', label: `n${i}`, group: 'code' as const })), links: [] }
    render(<GraphCanvas graph={big} budget={5} view="list" />)
    expect(screen.getByRole('status')).toHaveTextContent('Showing 5 of 12 nodes')
    expect(screen.getByTestId('graph-counts')).toHaveTextContent('5 nodes')
    fireEvent.click(screen.getByRole('button', { name: 'Show all' }))
    expect(screen.getByTestId('graph-counts')).toHaveTextContent('12 nodes')
  })

  it('an empty graph shows the provided empty state', () => {
    render(<GraphCanvas graph={null} empty={<p>Nodes appear as the agent reads the graph.</p>} />)
    expect(screen.getByText('Nodes appear as the agent reads the graph.')).toBeInTheDocument()
  })

  it('ShapeIcon draws each shape', () => {
    for (const s of ['square', 'diamond', 'triangle', 'hexagon', 'circle', 'ring', 'speech'] as const) {
      const { container } = render(<ShapeIcon shape={s} color="red" />)
      expect(container.querySelector('svg')?.firstElementChild).not.toBeNull()
    }
  })
})

describe('C-AC-14 SystemMap', () => {
  it('C-AC-14 at rest with no events: no active edge or actor, and it says so', () => {
    const { container } = render(<SystemMap events={[]} />)
    expect(container.querySelectorAll('[data-active="true"]')).toHaveLength(0)
    expect(screen.getByText('No activity yet.')).toBeInTheDocument()
    expect(container.querySelectorAll('[data-edge]')).toHaveLength(EDGES.length)
    expect(container.querySelectorAll('[data-actor]')).toHaveLength(9)
  })

  it.each([
    ['tool.called', 'actron-falkordb', 'falkordb', 'callers(evaluateCode, depth 3)'],
    ['pr.opened', 'actron-github', 'github', 'PR #18 opened'],
    ['handoff.created', 'actron-pi', 'pi', 'Evidence handed to the build'],
    ['ticket.synced', 'actron-linear', 'linear', 'Ticket CAL-214 v1'],
    ['judgment.made', 'actron-jev', 'jev', 'Judging 3 decisions'],
  ])('C-AC-14 %s lights edge %s and captions %s', (type, edge, actor, caption) => {
    const { container } = render(<SystemMap events={[makeEvent(type, PAYLOADS[type])]} />)
    expect(container.querySelector(`[data-edge="${edge}"]`)).toHaveAttribute('data-active', 'true')
    expect(container.querySelector(`[data-actor="${actor}"]`)).toHaveAttribute('data-active', 'true')
    expect(screen.getByTestId(`caption-${actor}`)).toHaveTextContent(caption)
  })

  it('C-AC-14 new events after mount create a pulse on the right edge', async () => {
    const { container, rerender } = render(<SystemMap events={[]} />)
    rerender(<SystemMap events={[makeEvent('pr.opened', PAYLOADS['pr.opened'], 1)]} />)
    await act(async () => {
      await new Promise((r) => setTimeout(r, 30))
    })
    expect(container.querySelector('[data-pulse="actron-github"]')).not.toBeNull()
  })

  it('compact strip shows only the active caption', () => {
    const events = [makeEvent('request.created', PAYLOADS['request.created'], 1), makeEvent('pr.opened', PAYLOADS['pr.opened'], 2)]
    render(<SystemMap events={events} compact />)
    expect(screen.getByTestId('system-map')).toHaveAttribute('data-compact', 'true')
    expect(screen.getByTestId('caption-github')).toBeInTheDocument()
    expect(screen.queryByTestId('caption-actron')).toBeNull()
    expect(edgeId('slack', 'actron')).toBe('actron-slack')
  })
})

describe('C-AC-4 C-AC-5 glyphs and brand marks', () => {
  it('C-AC-4 every glyph renders on a 24-px grid with one stroke weight', () => {
    expect(glyphNames().sort()).toEqual([...GLYPH_NAMES].sort())
    for (const name of GLYPH_NAMES) {
      const { container } = render(<Glyph name={name} />)
      const svg = container.querySelector('svg') as SVGElement
      expect(svg.getAttribute('viewBox')).toBe('0 0 24 24')
      expect(svg.getAttribute('stroke-width')).toBe('1.5')
      expect(svg.getAttribute('stroke-linecap')).toBe('round')
      expect(svg.getAttribute('data-glyph')).toBe(name)
      expect(svg.getAttribute('aria-hidden')).toBe('true')
    }
  })

  it('C-AC-4 every glyph has an animated state with parts that move', () => {
    for (const name of GLYPH_NAMES) {
      const { container } = render(<Glyph name={name} animated title={name} />)
      const svg = container.querySelector('svg') as SVGElement
      expect(svg.getAttribute('data-animated')).toBe('true')
      expect(svg.getAttribute('data-motion')).toBe(GLYPH_MOTION[name])
      expect(svg.querySelector('.g-a'), name).not.toBeNull()
      expect(screen.getByRole('img', { name })).toBe(svg)
    }
  })

  it('C-AC-4 no glyph uses a hard-coded colour', () => {
    for (const name of GLYPH_NAMES) {
      const { container } = render(<Glyph name={name} />)
      expect(container.innerHTML).not.toMatch(/(fill|stroke)="#/)
    }
  })

  it('C-AC-5 every brand mark renders with an accessible name', () => {
    for (const name of BRAND_NAMES) {
      const { container } = render(<BrandMark name={name} />)
      const el = container.firstElementChild as HTMLElement
      const label = el.getAttribute('aria-label') ?? el.getAttribute('alt')
      expect(label, name).toBe(brandTitle(name))
    }
  })

  it('C-AC-5 decorative marks are hidden; official marks load from /brands; dark marks use the text colour', () => {
    const { container } = render(<BrandMark name="slack" decorative />)
    const img = container.querySelector('img') as HTMLImageElement
    expect(img.getAttribute('src')).toBe('/brands/slack.svg')
    expect(img.getAttribute('alt')).toBe('')
    const gh = render(<BrandMark name="github" />).container.querySelector('path')
    expect(gh?.getAttribute('fill')).toBe('currentColor')
    const ts = render(<BrandMark name="typescript" />).container.querySelector('path')
    expect(ts?.getAttribute('fill')).toMatch(/^#/)
    const pi = render(<BrandMark name="pi" tone="mono" />).container.querySelector('img')
    expect(pi?.getAttribute('src')).toBe('/brands/pi-mono.svg')
    expect(brandTitle('jev')).toBe('Jev by TypeSafe')
  })

  it('language marks follow file extensions', () => {
    expect(languageFor('src/evaluate.ts')).toBe('typescript')
    expect(languageFor('src/calva/fmt.cljs')).toBe('clojure')
    expect(languageFor('a.py')).toBe('python')
    expect(languageFor('README.md')).toBe('markdown')
    expect(languageFor('Makefile')).toBeNull()
  })

  it('the Actron mark is the evidence path with a highlighted end node; the wordmark names it', () => {
    const { container } = render(<ActronMark title="Actron" drawOnce />)
    expect(screen.getByRole('img', { name: 'Actron' })).toHaveAttribute('data-draw', 'true')
    expect(container.querySelectorAll('circle')).toHaveLength(4)
    expect(container.querySelector('.actron-mark-end')?.getAttribute('fill')).toBe('var(--accent)')
    render(<ActronWordmark />)
    expect(screen.getByText('Actron')).toBeInTheDocument()
  })
})
