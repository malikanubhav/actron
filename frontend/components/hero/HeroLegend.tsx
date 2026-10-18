import type { NodeGroup } from '@/lib/api/types'

const ORDER: NodeGroup[] = ['code', 'github', 'slack', 'linear', 'core']
const NAME: Record<NodeGroup, string> = { code: 'Code', github: 'GitHub', slack: 'Slack', linear: 'Linear', core: "Core (Actron's records)" }
const DOT: Record<NodeGroup, string> = {
  code: 'bg-node-code',
  github: 'bg-node-github',
  slack: 'bg-node-slack',
  linear: 'bg-node-linear',
  core: 'bg-node-core',
}

/** The colour key for the hero graph: one dot per source, in the same tokens the 3D scene reads. */
export function HeroLegend({ className }: { className?: string }) {
  return (
    <ul className={['flex flex-wrap items-center gap-x-4 gap-y-1 text-caption text-fg-2', className].filter(Boolean).join(' ')} aria-label="Colour shows the source" data-testid="hero-legend">
      {ORDER.map((g) => (
        <li key={g} className="inline-flex items-center gap-1.5" title={g === 'core' ? 'Requests, investigations, decisions and people Actron creates' : undefined}>
          <span aria-hidden className={`inline-block size-2 rounded-full ${DOT[g]}`} />
          {NAME[g]}
        </li>
      ))}
      <li className="inline-flex items-center gap-1.5 text-accent">
        <span aria-hidden className="inline-block h-0.5 w-4 rounded-full bg-accent" />
        Evidence path
      </li>
    </ul>
  )
}
