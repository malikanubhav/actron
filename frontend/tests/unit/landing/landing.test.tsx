import { render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

vi.mock('next/dynamic', () => ({ default: () => () => null }))

import { Landing, CallToAction, STACK } from '@/components/landing/Landing'
import { HERO_HEADLINE } from '@/components/landing/copy'
import { replayHref, JOURNEY_FILES } from '@/components/landing/journey'
import { CYPHER_EXAMPLES, ontologyLabel, ontologyTotals, summariseOntology, ONTOLOGY } from '@/components/landing/ontology'
import type { GraphStats } from '@/lib/api/types'

const noShots = [false, false, false, false, false]

describe('landing page (spec C, C5.1)', () => {
  it('C-AC-21 renders all six sections in order', () => {
    const { container } = render(<Landing replay={null} stats={null} screenshots={noShots} />)
    const sections = [...container.querySelectorAll('[data-section]')].map((s) => s.getAttribute('data-section'))
    expect(sections).toEqual(['hero', 'problem', 'journey', 'graph', 'stack', 'close'])
  })

  it('C-AC-21 shows the hero headline as the page h1', () => {
    render(<Landing replay={null} stats={null} screenshots={noShots} />)
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(HERO_HEADLINE)
  })

  it('C-AC-21 lists the five journey steps in order', () => {
    const { container } = render(<Landing replay={null} stats={null} screenshots={noShots} />)
    const steps = [...container.querySelectorAll('[data-step]')].map((li) => li.querySelector('h3')?.textContent)
    expect(steps).toEqual(['Ask, and Actron investigates', 'Evidence from the graph', 'You decide', 'Pi builds', 'Review the PR'])
  })

  it('C-AC-21 uses real screenshots when the capture files exist', () => {
    render(<Landing replay={null} stats={null} screenshots={[true, true, true, true, true]} />)
    expect(screen.getAllByRole('img', { name: /^Actron screen:/ })).toHaveLength(5)
  })

  it('C-AC-21 renders no screenshot slot and no invented example when files are missing in production', () => {
    render(<Landing replay={null} stats={null} screenshots={noShots} />)
    expect(screen.queryAllByRole('img', { name: /^Actron screen:/ })).toHaveLength(0)
    expect(screen.queryByTestId('journey-composition')).toBeNull()
  })

  it('C-AC-21 shows the real logos for every built-with entry', () => {
    render(<Landing replay={null} stats={null} screenshots={noShots} />)
    const list = screen.getByTestId('stack-list')
    expect(within(list).getAllByRole('listitem')).toHaveLength(STACK.length)
    for (const name of ['FalkorDB', 'Jev by TypeSafe', 'Pi', 'Model Context Protocol', 'Temporal', 'Slack', 'GitHub', 'Linear']) {
      expect(within(list).getByText(name)).toBeInTheDocument()
    }
    expect(list.querySelectorAll('[data-brand], svg').length).toBeGreaterThanOrEqual(STACK.length)
  })

  it('C-AC-21 shows three Cypher examples with explanations', () => {
    render(<Landing replay={null} stats={null} screenshots={noShots} />)
    expect(screen.getAllByTestId('cypher-example')).toHaveLength(3)
    expect(CYPHER_EXAMPLES[0]?.query).toMatch(/\[:CALLS\*1\.\.3\]->/)
    expect(CYPHER_EXAMPLES[2]?.query).toMatch(/algo\.SPpaths/)
  })

  it('C-AC-21 labels the ontology fallback when the API gave no counts', () => {
    render(<Landing replay={null} stats={null} screenshots={noShots} />)
    expect(screen.getByTestId('ontology-label')).toHaveTextContent('Ontology: 96 node types, 507 relationships')
  })

  it('C-AC-21 adds the live workspace counts when the API answers', () => {
    const stats: GraphStats = {
      nodeTypes: 96,
      nodes: 41203,
      links: 188911,
      byType: [
        { type: 'CodeFunction', group: 'code', count: 30000 },
        { type: 'SlackMessage', group: 'slack', count: 11203 },
      ],
      ontology: { types: 96, relationships: 507 },
    }
    render(<Landing replay={null} stats={stats} screenshots={noShots} />)
    expect(screen.getByTestId('ontology-label')).toHaveTextContent('41,203 nodes, 188,911 links')
    expect(screen.getByText(/30,000 nodes/)).toBeInTheDocument()
  })

  it('renders a footer with the track and the AI-use note', () => {
    render(<Landing replay={null} stats={null} screenshots={noShots} />)
    expect(screen.getByText(/FalkorDB Graph Hacks hackathon, Track 01/)).toBeInTheDocument()
    expect(screen.getByText(/^AI use:/)).toBeInTheDocument()
  })

  it('uses no exclamation marks or hype words in landing copy', () => {
    const { container } = render(<Landing replay="/replay/x" stats={null} screenshots={noShots} />)
    const text = container.textContent ?? ''
    expect(text).not.toMatch(/!/)
    expect(text.toLowerCase()).not.toMatch(/supercharge|unleash|seamless|ai-powered|revolutionary|magic/)
  })
})

describe('Watch a replay gate (C-AC-47)', () => {
  it('C-AC-47 hides "Watch a replay" when no finished request exists', () => {
    render(<CallToAction replay={null} />)
    expect(screen.queryByText('Watch a replay')).toBeNull()
    expect(screen.getByText('Open the app')).toBeInTheDocument()
  })

  it('C-AC-47 shows "Watch a replay" linking to the replay when one exists', () => {
    render(<CallToAction replay="/replay/req_1" />)
    expect(screen.getByText('Watch a replay').closest('a')).toHaveAttribute('href', '/replay/req_1')
  })

  it('C-AC-47 both calls to action follow the same rule on the whole page', () => {
    render(<Landing replay={null} stats={null} screenshots={noShots} />)
    expect(screen.queryAllByText('Watch a replay')).toHaveLength(0)
    expect(screen.getAllByText('Open the app')).toHaveLength(2)
  })

  it('C-AC-47 replayHref picks the public replay when allowed, else the in-app replay, else nothing', () => {
    expect(replayHref(null, true)).toBeNull()
    expect(replayHref('req_1', true)).toBe('/replay/req_1')
    expect(replayHref('req_1', false)).toBe('/app/requests/req_1/replay')
  })

  it('journey screenshot paths are journey-01 to journey-05', () => {
    expect(JOURNEY_FILES).toEqual(['/landing/journey-01.png', '/landing/journey-02.png', '/landing/journey-03.png', '/landing/journey-04.png', '/landing/journey-05.png'])
  })
})

describe('ontology summary', () => {
  it('counts 96 node types and 507 relationships from the snapshot', () => {
    expect(ontologyTotals()).toEqual({ types: 96, relationships: 507 })
    expect(ontologyLabel()).toBe('Ontology: 96 node types, 507 relationships')
  })

  it('groups node types by source and the groups add up to the total', () => {
    const sources = summariseOntology()
    expect(sources.map((s) => s.group)).toEqual(['code', 'github', 'slack', 'linear', 'core'])
    expect(sources.reduce((sum, s) => sum + s.typeCount, 0)).toBe(ONTOLOGY.types.length)
    expect(sources.every((s) => s.nodeCount === null)).toBe(true)
  })
})
