import Image from 'next/image'
import Link from 'next/link'
import { ArrowSquareOut } from '@phosphor-icons/react/dist/ssr'
import { DEV_FIXTURES, REPOSITORY_URL } from '@/lib/env'
import { formatNumber } from '@/lib/format'
import type { GraphStats, NodeGroup } from '@/lib/api/types'
import { ActronMark, ActronWordmark } from '../brand/ActronLogo'
import { BrandMark, type BrandName } from '../brand/BrandMark'
import { Glyph } from '../glyphs/Glyph'
import type { GlyphName } from '../glyphs/names'
import { LinkButton } from '../ui/Button'
import { StateChip, LabelChip } from '../core/StateChip'
import { Pipeline } from '../core/Pipeline'
import { HeroVisual } from '../hero/HeroVisual'
import { ProblemIllustration } from './ProblemIllustration'
import { Reveal } from './Reveal'
import { CYPHER_EXAMPLES, ONTOLOGY, SOURCE_LINE, SOURCE_NAME, ontologyLabel, ontologyTotals, summariseOntology } from './ontology'
import { JOURNEY_FILES } from './journey'
import { HERO_HEADLINE, HERO_PURPOSE } from './copy'
import { cx } from '../ui/cx'
import { HeroLegend } from '../hero/HeroLegend'

export { HERO_HEADLINE, HERO_PURPOSE }

const frame = 'mx-auto w-full max-w-content px-4 sm:px-8 xl:px-12'

function SectionHead({ eyebrow, title, id }: { eyebrow: string; title: string; id: string }) {
  return (
    <div className="flex flex-col gap-3">
      <p className="eyebrow">{eyebrow}</p>
      <h2 id={id} className="display max-w-3xl text-title-lg text-fg-1 lg:text-headline-sm">
        {title}
      </h2>
    </div>
  )
}

/** "Watch a replay" only when a finished request exists (C-AC-47); "Open the app" always. */
export function CallToAction({ replay, className }: { replay: string | null; className?: string }) {
  return (
    <div className={cx('flex flex-wrap items-center gap-3', className)} data-testid="landing-cta">
      {replay ? (
        <LinkButton href={replay} variant="primary" icon={<Glyph name="ShortestPath" size={16} />} data-testid="watch-replay">
          Watch a replay
        </LinkButton>
      ) : null}
      <LinkButton href="/app" variant={replay ? 'secondary' : 'primary'} data-testid="open-app">
        Open the app
      </LinkButton>
    </div>
  )
}

function Nav() {
  return (
    <header className={cx(frame, 'flex h-16 items-center justify-between')}>
      {/* Newsreader sits high in its box; the nudge lines the wordmark up with the nav links. */}
      <Link href="/" aria-label="Actron home" className="flex translate-y-0.5 items-center rounded-sm">
        <ActronWordmark size={24} />
      </Link>
      <nav aria-label="Landing" className="hidden items-center gap-6 text-small text-fg-2 md:flex">
        <a href="#how" className="no-underline hover:text-fg-1">
          How it works
        </a>
        <a href="#graph" className="no-underline hover:text-fg-1">
          The graph
        </a>
        <a href="#stack" className="no-underline hover:text-fg-1">
          Built with
        </a>
      </nav>
      <LinkButton href="/app" variant="ghost" size="sm">
        Sign in
      </LinkButton>
    </header>
  )
}

function Hero({ replay }: { replay: string | null }) {
  const totals = ontologyTotals()
  return (
    // The whole hero (graph, status chip, caption and key) fits the first screen: the graph is sized from the viewport
    // height, so the text can centre against it without dropping below the fold.
    <section aria-labelledby="hero-title" className={cx(frame, 'grid grid-cols-1 items-start gap-8 pb-12 pt-8 lg:grid-cols-12 lg:items-center lg:gap-10 lg:pt-6')} data-section="hero">
      <div className="flex flex-col gap-6 lg:col-span-6">
        {/* One step below the hero size on wide screens: five lines at 80 px crowded the graph. */}
        <h1 id="hero-title" className="display text-title-lg text-fg-1 sm:text-headline-sm xl:text-headline">
          {HERO_HEADLINE}
        </h1>
        <p className="max-w-measure text-lead text-fg-2">{HERO_PURPOSE}</p>
        <CallToAction replay={replay} className="pt-2" />
      </div>
      <figure className="flex flex-col gap-3 lg:col-span-6">
        <HeroVisual className="mx-auto max-w-3xl lg:w-[min(100%,48rem,max(20rem,calc(100dvh-12.5rem)))]" />
        <figcaption className="flex flex-col gap-2 text-caption text-fg-3">
          <span>
            A FalkorDB graph of {totals.types} node types, coloured by source. <span className="text-accent">Evidence path</span>:
            from a request to a function.
          </span>
          <HeroLegend />
        </figcaption>
      </figure>
    </section>
  )
}

function Problem() {
  return (
    <section aria-labelledby="problem-title" className="border-t border-line-1" data-section="problem">
      <div className={cx(frame, 'grid grid-cols-1 items-center gap-10 py-20 lg:grid-cols-12')}>
        <div className="flex flex-col gap-4 lg:col-span-5">
          <p className="eyebrow">The problem</p>
          <h2 id="problem-title" className="display text-title-lg text-fg-1">
            A coding agent can satisfy a request and quietly break a decision your team made months ago in a Slack thread.
          </h2>
        </div>
        <div className="lg:col-span-7">
          <ProblemIllustration className="h-auto w-full" />
        </div>
      </div>
    </section>
  )
}

const JOURNEY: { title: string; caption: string; glyph: GlyphName }[] = [
  {
    title: 'Ask, and Actron investigates',
    caption: 'Type /actron in Slack with the change you want. Actron replies in the thread, then reads the graph; the timeline shows each step as it happens.',
    glyph: 'Request',
  },
  { title: 'Evidence from the graph', caption: 'The investigator chooses graph tools, follows callers, decisions and earlier pull requests, and shows each finding with its quote and source.', glyph: 'Evidence' },
  { title: 'You decide', caption: 'Answer its questions, read the ticket, and approve the exact revision, in Slack or in Actron.', glyph: 'Approval' },
  { title: 'Pi builds', caption: 'Pi makes the change in a container with only the checkout, runs the tests, and repairs what fails.', glyph: 'Build' },
  { title: 'Review the PR', caption: 'The pull request arrives with the diff, the test results and every constraint it had to keep, each with its proof.', glyph: 'PullRequest' },
]

/** Vocabulary-only composition shown in dev fixture builds until the real screenshot exists. No records invented. */
function StepComposition({ index }: { index: number }) {
  const step = (index + 1) as 1 | 2 | 3 | 4 | 5
  return (
    <div className="flex h-full flex-col justify-between gap-6 rounded-lg border border-dashed border-line-2 p-6" data-testid="journey-composition">
      <p className="eyebrow">Example from the fixture workspace · screenshot pending</p>
      <div className="flex flex-wrap items-center gap-3">
        {step === 1 ? <StateChip state="Investigating" /> : null}
        {step === 2 ? (
          <>
            <LabelChip label="conflict" />
            <LabelChip label="possible_conflict" />
          </>
        ) : null}
        {step === 3 ? <StateChip state="Awaiting approval" /> : null}
        {step === 4 ? <StateChip state="Building" /> : null}
        {step === 5 ? <StateChip state="PR ready for review" /> : null}
      </div>
      <Pipeline current={Math.min(6, step === 5 ? 6 : step === 4 ? 5 : step === 3 ? 4 : step) as 1 | 2 | 3 | 4 | 5 | 6} />
    </div>
  )
}

function Journey({ screenshots, source }: { screenshots: boolean[]; source: 'fixtures' | 'live' }) {
  return (
    <section id="how" aria-labelledby="how-title" className="border-t border-line-1" data-section="journey">
      <div className={cx(frame, 'flex flex-col gap-12 py-20')}>
        <div className="flex flex-col gap-3">
          <SectionHead eyebrow="How it works" title="From a sentence in Slack to a tested pull request, with the reasons attached." id="how-title" />
          {source === 'fixtures' && screenshots.some(Boolean) ? (
            <p className="text-small text-fg-2" data-testid="journey-source">
              The screens below are captured from the development fixtures, not a live workspace.
            </p>
          ) : null}
        </div>
        <Reveal className="flex flex-col">
          {JOURNEY.map((s, i) => {
            const has = screenshots[i] === true
            const showComposition = !has && DEV_FIXTURES
            return (
              <li
                key={s.title}
                data-step={i + 1}
                className="grid grid-cols-1 gap-6 border-t border-line-1 py-10 lg:grid-cols-12 lg:gap-gutter"
              >
                <div className="flex flex-col gap-3 lg:col-span-4">
                  <div className="flex items-center gap-3 text-fg-2">
                    <span className="font-mono text-caption text-fg-3 tabular">{String(i + 1).padStart(2, '0')}</span>
                    <Glyph name={s.glyph} size={20} />
                  </div>
                  <h3 className="display text-title text-fg-1">{s.title}</h3>
                  <p className="max-w-prose text-body text-fg-2">{s.caption}</p>
                </div>
                {has || showComposition ? (
                  <div className="lg:col-span-8">
                    {has ? (
                      // The frame keeps a background while the image loads, so it never looks broken.
                      <div className="min-h-48 overflow-hidden rounded-lg border border-line-1 bg-ink-1">
                        <Image
                          src={JOURNEY_FILES[i] as string}
                          alt={`Actron screen: ${s.title}`}
                          width={1600}
                          height={900}
                          sizes="(min-width: 1024px) 60vw, 100vw"
                          loading="eager"
                          className="block h-auto w-full"
                        />                      </div>
                    ) : (
                      <StepComposition index={i} />
                    )}
                  </div>
                ) : null}
              </li>
            )
          })}
        </Reveal>
      </div>
    </section>
  )
}

/** Node types with at least one node in the workspace (the ontology defines more than any one workspace uses). */
function usedTypes(stats: GraphStats): number {
  return stats.byType.filter((b) => b.count > 0).length
}

/** The same colour the app's graph gives the group (tokens.css `--node-<group>`). */
const groupColour = (group: NodeGroup) => ({ backgroundColor: `var(--node-${group})` })

function GraphModel({ stats }: { stats: GraphStats | null }) {
  const sources = summariseOntology(ONTOLOGY, stats)
  return (
    <section id="graph" aria-labelledby="graph-title" className="border-t border-line-1" data-section="graph">
      <div className={cx(frame, 'grid grid-cols-1 gap-12 py-20 lg:grid-cols-12 lg:gap-gutter')}>
        <div className="flex flex-col gap-8 lg:col-span-5">
          <SectionHead eyebrow="The graph" title="One graph holds what your team decided and what it built." id="graph-title" />
          <p className="text-small text-fg-2 tabular" data-testid="ontology-label">
            {ontologyLabel()}
            {stats ? `. This workspace uses ${usedTypes(stats)} of those types: ${formatNumber(stats.nodes)} nodes, ${formatNumber(stats.links)} links.` : '.'}
          </p>
          <ul className="flex flex-col" data-testid="ontology-sources">
            {sources.map((s) => (
              <li key={s.group} className="flex flex-col gap-1 border-t border-line-1 py-4" data-group={s.group}>
                <div className="flex items-baseline gap-3">
                  <span aria-hidden className="inline-block size-2.5 shrink-0 rounded-full" style={groupColour(s.group)} />
                  <span className="text-body font-medium text-fg-1">{SOURCE_NAME[s.group]}</span>
                  <span className="font-mono text-caption text-fg-3 tabular">
                    {s.typeCount} types{s.nodeCount !== null ? ` · ${formatNumber(s.nodeCount)} nodes` : ''}
                  </span>
                </div>
                <p className="text-small text-fg-2">{SOURCE_LINE[s.group]}</p>
                <ul className="flex flex-wrap gap-x-4 gap-y-1 font-mono text-caption text-fg-3" aria-label={`${SOURCE_NAME[s.group]} node types, for example`}>
                  {s.examples.map((t) => (
                    <li key={t} className="inline-flex items-center gap-1.5">
                      <span aria-hidden className="inline-block size-1.5 rounded-full" style={groupColour(s.group)} />
                      {t}
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        </div>
        <div className="flex flex-col gap-8 lg:col-span-7">
          {CYPHER_EXAMPLES.map((q) => (
            <article key={q.title} className="flex flex-col gap-3" data-testid="cypher-example">
              <h3 className="display text-title-sm text-fg-1">{q.title}</h3>
              <p className="max-w-prose text-small text-fg-2">{q.explanation}</p>
              <pre tabIndex={0} className="overflow-x-auto rounded-md border border-line-1 bg-ink-1 p-4 font-mono text-caption text-fg-1">
                <code>{q.query}</code>
              </pre>
            </article>
          ))}
        </div>
      </div>
    </section>
  )
}

export const STACK: { brand: BrandName; name: string; line: string }[] = [
  { brand: 'falkordb', name: 'FalkorDB', line: 'The memory: one graph per workspace, multi-hop queries, PageRank and shortest paths.' },
  { brand: 'typesafe', name: 'Jev by TypeSafe', line: 'Narrow judgments with probabilities: is this a decision, does it conflict, which link is real.' },
  { brand: 'pi', name: 'Pi', line: 'The coding agent. It builds the change inside Docker with only the checkout.' },
  { brand: 'mcp', name: 'Model Context Protocol', line: 'How the investigator and Pi call graph tools such as callers, impact and the decisions behind a function.' },
  { brand: 'temporal', name: 'Temporal', line: 'Durable workflows for ingestion and every request, so nothing is lost on a restart.' },
  { brand: 'slack', name: 'Slack', line: 'Where requests start, questions are answered and approvals happen, also on a phone.' },
  { brand: 'github', name: 'GitHub', line: 'Code, history and reviews in; branches and pull requests out, to your fork only.' },
  { brand: 'linear', name: 'Linear', line: 'Issues and comments in; every approved ticket out, with its hash.' },
]

function BuiltWith() {
  return (
    <section id="stack" aria-labelledby="stack-title" className="border-t border-line-1" data-section="stack">
      <div className={cx(frame, 'grid grid-cols-1 gap-10 py-20 lg:grid-cols-12 lg:gap-gutter')}>
        <div className="lg:col-span-4">
          <SectionHead eyebrow="Built with" title="Each part does one job." id="stack-title" />
        </div>
        <ul className="flex flex-col lg:col-span-8" data-testid="stack-list">
          {STACK.map((s) => (
            <li key={s.name} className="grid grid-cols-12 items-center gap-4 border-t border-line-1 py-4" data-brand-row={s.brand}>
              <span className="col-span-12 flex items-center gap-3 sm:col-span-4">
                <BrandMark name={s.brand} size={20} decorative />
                <span className="text-body font-medium text-fg-1">{s.name}</span>
              </span>
              <span className="col-span-12 text-small text-fg-2 sm:col-span-8">{s.line}</span>
            </li>
          ))}
        </ul>
      </div>
    </section>
  )
}

function Close({ replay }: { replay: string | null }) {
  return (
    <section aria-labelledby="close-title" className="border-t border-line-1" data-section="close">
      <div className={cx(frame, 'flex flex-col items-start gap-6 py-24')}>
        <ActronMark size={40} />
        <h2 id="close-title" className="display max-w-3xl text-title-lg text-fg-1 lg:text-headline-sm">
          {replay ? 'Watch Actron handle a real request, step by step.' : 'Connect a repository and ask your first request.'}
        </h2>
        <CallToAction replay={replay} />
      </div>
    </section>
  )
}

function Footer() {
  return (
    <footer className="border-t border-line-1">
      <div className={cx(frame, 'flex flex-col gap-4 py-10 text-small text-fg-3 md:flex-row md:items-start md:justify-between')}>
        <div className="flex flex-col gap-1">
          <p className="text-fg-2">Built for the FalkorDB Graph Hacks hackathon, Track 01.</p>
          <p>AI use: Actron calls language models and Jev for judgments and code. Every finding links to its source, and nothing is merged without a person approving it.</p>
        </div>
        <a href={REPOSITORY_URL} target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-2 text-fg-2 hover:text-fg-1">
          <BrandMark name="github" size={16} decorative />
          Source code
          <ArrowSquareOut size={12} aria-hidden />
          <span className="sr-only">(opens in a new tab)</span>
        </a>
      </div>
    </footer>
  )
}

export interface LandingProps {
  replay: string | null
  stats: GraphStats | null
  screenshots: boolean[]
  screenshotSource?: 'fixtures' | 'live'
}

/** The public landing page (spec C, C5.1): six sections in order, then the footer. */
export function Landing({ replay, stats, screenshots, screenshotSource = 'fixtures' }: LandingProps) {
  return (
    <div className="min-h-dvh overflow-x-clip bg-ink-0">
      <a href="#main" className="sr-only-focusable fixed left-3 top-3 z-50 rounded-md bg-accent px-3 py-2 text-small font-medium text-accent-ink">
        Skip to main content
      </a>
      <Nav />
      <main id="main">
        <Hero replay={replay} />
        <Problem />
        <Journey screenshots={screenshots} source={screenshotSource} />
        <GraphModel stats={stats} />
        <BuiltWith />
        <Close replay={replay} />
      </main>
      <Footer />
    </div>
  )
}
