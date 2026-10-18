'use client'
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ArrowSquareOut } from '@phosphor-icons/react/dist/ssr'
import type { GraphLink, NodeGroup } from '@/lib/api/types'
import { endpoints } from '@/lib/api/endpoints'
import { qk } from '@/lib/query-keys'
import { groupLinks } from '@/lib/subgraph'
import { idTail } from '@/lib/events'
import { reasonText } from '@/lib/api'
import { formatNumber, relativeTime } from '@/lib/format'
import { GROUP_LABEL, GROUP_TOKEN, codePath, displayLabel, groupOf, isInferred, kindOf } from './model'
import { ShapeIcon } from './ShapeIcon'
import { SkeletonText } from '../states/Skeleton'
import { Button } from '../ui/Button'

export type QuickQuery = 'callers' | 'owners' | 'decisions_for' | 'shortest_path'

/** Keys shown as plain fields above the fold, or never worth showing on their own. */
const SHOWN = new Set(['name', 'qualifiedName', 'path', 'startLine', 'endLine', 'signature', 'callerCount', 'criticalityPercentile', 'refreshedAt', 'ingestedAt', 'language', 'loc'])
const CODE_KEYS = new Set(['body', 'text', 'content', 'diff', 'patch'])

export interface Field {
  label: string
  value: string
  mono?: boolean
}

/** The plain fields a person reads first: what it is, where it lives, when it last changed, how linked it is. */
export function inspectorFields(
  node: { id: string; type: string; label: string; group: NodeGroup; props: Record<string, unknown> },
  links: { incoming: number; outgoing: number },
  now = Date.now(),
): Field[] {
  const p = node.props
  const out: Field[] = [{ label: 'Type', value: kindOf(node).name }]
  const name = typeof p.qualifiedName === 'string' ? p.qualifiedName : typeof p.name === 'string' ? p.name : null
  if (name && name !== node.label) out.push({ label: 'Name', value: name, mono: true })
  const path = typeof p.path === 'string' ? p.path : codePath(node.id)
  if (path) {
    const start = typeof p.startLine === 'number' ? p.startLine : null
    const end = typeof p.endLine === 'number' ? p.endLine : null
    out.push({ label: 'File', value: start ? `${path}:${start}${end && end !== start ? `–${end}` : ''}` : path, mono: true })
  }
  out.push({ label: 'Source', value: GROUP_LABEL[groupOf(node)] })
  if (typeof p.language === 'string') out.push({ label: 'Language', value: p.language })
  if (typeof p.loc === 'number') out.push({ label: 'Lines', value: formatNumber(p.loc), mono: true })
  const changed = typeof p.refreshedAt === 'string' ? p.refreshedAt : typeof p.ingestedAt === 'string' ? p.ingestedAt : null
  if (changed) out.push({ label: 'Last read', value: relativeTime(changed, now) })
  out.push({ label: 'Links', value: `${formatNumber(links.incoming)} in · ${formatNumber(links.outgoing)} out`, mono: true })
  if (typeof p.callerCount === 'number') out.push({ label: 'Callers', value: formatNumber(p.callerCount), mono: true })
  if (typeof p.criticalityPercentile === 'number' && p.criticalityPercentile >= 1) out.push({ label: 'Depended on', value: `more than ${Math.round(p.criticalityPercentile)}% of functions` })
  return out
}

function CodeBlock({ text }: { text: string }) {
  const [open, setOpen] = useState(false)
  const lines = text.split('\n')
  const long = lines.length > 6
  return (
    <div className="flex flex-col gap-1">
      <pre className="overflow-x-auto rounded-sm bg-ink-1 p-2 font-mono text-caption text-fg-2">{open || !long ? text : lines.slice(0, 6).join('\n')}</pre>
      {long ? (
        <button type="button" className="self-start text-caption text-fg-2 underline hover:text-fg-1" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
          {open ? 'Show less' : `Show ${lines.length - 6} more lines`}
        </button>
      ) : null}
    </div>
  )
}

function LinkRow({ link, direction, onOpen }: { link: GraphLink; direction: 'in' | 'out'; onOpen: (id: string) => void }) {
  const other = direction === 'out' ? link.to : link.from
  return (
    <li className="flex items-center gap-2 py-1 text-caption">
      <button type="button" onClick={() => onOpen(other)} className="min-w-0 flex-1 truncate text-left font-mono text-fg-1 hover:underline" title={other}>
        {idTail(other)}
      </button>
      <span className="shrink-0 text-fg-3" title="How this link was made">
        {isInferred(link) ? 'Inferred' : 'Explicit'}
      </span>
      <span className="w-10 shrink-0 text-right font-mono text-fg-3 tabular" title="Confidence">
        {link.confidence === null ? '—' : link.confidence.toFixed(2)}
      </span>
    </li>
  )
}

/** Selected node: plain fields, quick queries, sources, links with method and confidence, then raw properties (PROMPT 8.8 E). */
export function NodeInspector({
  id,
  onOpen,
  onQuick,
  pathFrom,
}: {
  id: string
  onOpen: (id: string) => void
  onQuick: (q: QuickQuery) => void
  pathFrom?: string | null
}) {
  const q = useQuery({ queryKey: qk.node(id), queryFn: () => endpoints.node(id) })
  if (q.isPending) return <SkeletonText lines={8} />
  if (q.isError) return <p className="text-small text-state-conflict">{reasonText(q.error)}</p>
  const { node, sources, incoming, outgoing } = q.data
  const props = node.props ?? {}
  const kind = kindOf(node)
  const group = groupOf(node)
  const fields = inspectorFields({ ...node, props }, { incoming: incoming.length, outgoing: outgoing.length })
  const code = Object.entries(props).find(([k, v]) => CODE_KEYS.has(k) && typeof v === 'string' && v.length > 0) as [string, string] | undefined
  const raw = Object.entries(props).filter(([k]) => k !== 'id' && !CODE_KEYS.has(k) && !SHOWN.has(k))
  return (
    <div className="flex flex-col gap-5" data-testid="node-inspector">
      <div className="flex min-w-0 flex-col gap-1">
        <span className="eyebrow inline-flex items-center gap-1.5">
          <ShapeIcon shape={kind.shape} color={`var(${GROUP_TOKEN[group]})`} />
          {kind.name} · {GROUP_LABEL[group]}
        </span>
        <h2 className="display line-clamp-3 break-words text-title-sm text-fg-1" title={node.label}>
          {displayLabel(node)}
        </h2>
      </div>

      <dl className="flex flex-col" aria-label="Details">
        {fields.map((f) => (
          <div key={f.label} className="grid grid-cols-3 gap-2 border-b border-line-1 py-1.5 text-caption">
            <dt className="text-fg-3">{f.label}</dt>
            <dd className={f.mono ? 'col-span-2 truncate font-mono text-fg-1' : 'col-span-2 text-fg-1'} title={f.value}>
              {f.value}
            </dd>
          </div>
        ))}
      </dl>

      {typeof props.signature === 'string' && props.signature.length > 3 && !code ? <CodeBlock text={props.signature} /> : null}
      {code ? (
        <section aria-label={code[0] === 'body' ? 'Code' : 'Content'} className="flex flex-col gap-1">
          <h3 className="eyebrow">{code[0] === 'body' ? 'Code' : 'Content'}</h3>
          <CodeBlock text={code[1]} />
        </section>
      ) : null}

      <section className="flex flex-col gap-2" aria-label="Quick queries">
        <h3 className="eyebrow">Ask the graph</h3>
        <div className="flex flex-wrap gap-1.5">
          <Button size="sm" onClick={() => onQuick('callers')}>
            Callers
          </Button>
          <Button size="sm" onClick={() => onQuick('owners')}>
            Who knows this
          </Button>
          <Button size="sm" onClick={() => onQuick('decisions_for')}>
            Decisions on this
          </Button>
          <Button size="sm" onClick={() => onQuick('shortest_path')} disabled={!pathFrom || pathFrom === id} title={pathFrom ? undefined : 'Select another node first, then this one.'}>
            Shortest path to here
          </Button>
        </div>
      </section>

      <section aria-label="Sources">
        <h3 className="eyebrow mb-1">Where it came from</h3>
        {sources.length ? (
          <ul className="flex flex-col gap-1">
            {sources.map((s) => (
              <li key={s.url}>
                <a href={s.url} target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-1 text-caption text-fg-2 underline hover:text-fg-1">
                  {s.type}
                  <ArrowSquareOut size={12} aria-hidden />
                </a>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-caption text-fg-3">Derived inside Actron; no external source.</p>
        )}
      </section>

      {[
        { label: 'Outgoing', links: outgoing, direction: 'out' as const },
        { label: 'Incoming', links: incoming, direction: 'in' as const },
      ].map((s) => (
        <section key={s.label} aria-label={`${s.label.toLowerCase()} links`}>
          <h3 className="eyebrow mb-1">
            {s.label} links · <span className="font-mono tabular">{s.links.length}</span>
          </h3>
          {groupLinks(s.links).map(([type, list]) => (
            <div key={type} className="mb-2">
              <p className="font-mono text-caption text-fg-2">{type}</p>
              <ul className="flex flex-col">
                {list.slice(0, 12).map((l, i) => (
                  <LinkRow key={`${l.from}-${l.to}-${i}`} link={l} direction={s.direction} onOpen={onOpen} />
                ))}
              </ul>
            </div>
          ))}
        </section>
      ))}

      {raw.length ? (
        <details className="group" data-testid="raw-properties">
          <summary className="cursor-pointer text-caption font-medium text-fg-2 hover:text-fg-1">Raw properties · {raw.length}</summary>
          <dl className="mt-2 flex flex-col">
            <div className="grid grid-cols-3 gap-2 border-b border-line-1 py-1 text-caption">
              <dt className="truncate font-mono text-fg-3">id</dt>
              <dd className="col-span-2 break-all font-mono text-fg-2">{node.id}</dd>
            </div>
            {raw.map(([k, v]) => (
              <div key={k} className="grid grid-cols-3 gap-2 border-b border-line-1 py-1 text-caption">
                <dt className="truncate font-mono text-fg-3" title={k}>
                  {k}
                </dt>
                <dd className="col-span-2 line-clamp-3 break-all font-mono text-fg-2">{typeof v === 'object' ? JSON.stringify(v) : String(v)}</dd>
              </div>
            ))}
          </dl>
        </details>
      ) : null}
    </div>
  )
}
