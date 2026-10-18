/**
 * Shared drawing for Open Graph images (next/og). Inline styles and hex values are fine here: this renders a PNG,
 * not the UI, and satori reads no CSS variables. Each colour mirrors the styles/tokens.css token named beside it;
 * tests/unit/landing/og.test.ts fails when they drift apart.
 */
import snapshot from '@/lib/ontology-snapshot.json'
import { graphFromOntology, layout3d, project, type OntologySnapshotLike } from '../hero/layout3d'

export const OG_SIZE = { width: 1200, height: 630 }
export const OG_COLOURS = {
  ink: '#0A0A0A', // --ink-0
  text1: '#EDEDED', // --text-1
  text2: '#B4B4B4', // --text-2
  text3: '#858585', // --text-3
  line: '#6E6E6E', // --graph-link
  accent: '#E4F24C', // --accent
  code: '#97A8C0', // --node-code
  github: '#C8B08E', // --node-github
  slack: '#C77DDB', // --node-slack
  linear: '#6F8DF5', // --node-linear
  core: '#E58FA8', // --node-core
} as const

/** The tokens.css custom property each OG colour mirrors. */
export const OG_TOKENS: Record<keyof typeof OG_COLOURS, string> = {
  ink: '--ink-0',
  text1: '--text-1',
  text2: '--text-2',
  text3: '--text-3',
  line: '--graph-link',
  accent: '--accent',
  code: '--node-code',
  github: '--node-github',
  slack: '--node-slack',
  linear: '--node-linear',
  core: '--node-core',
}

const NEWSREADER_TTF =
  'https://fonts.gstatic.com/s/newsreader/v26/cY9qfjOCX1hbuyalUrK49dLac06G1ZGsZBt4ByzBDXXD9JVF438weI_ADA.ttf'

/** The display face for the image; null when Google Fonts cannot be reached (the default font is used). */
export async function loadDisplayFont(): Promise<ArrayBuffer | null> {
  try {
    const res = await fetch(NEWSREADER_TTF, { signal: AbortSignal.timeout(4000) })
    return res.ok ? await res.arrayBuffer() : null
  } catch {
    return null
  }
}

export function OgGraph({ width, height }: { width: number; height: number }) {
  const graph = graphFromOntology(snapshot as unknown as OntologySnapshotLike)
  const points = project(layout3d(graph.nodes, graph.links, 120), width, height, 0.6, 0.35, 16)
  const index = new Map(graph.nodes.map((n, i) => [n.id, i]))
  const pathPts = graph.path.map((id) => points[index.get(id) ?? 0]).filter(Boolean) as { x: number; y: number }[]
  const onPath = new Set(graph.path)
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
      {graph.links.map((l, i) => {
        const a = points[index.get(l.from) ?? -1]
        const b = points[index.get(l.to) ?? -1]
        return a && b ? <line key={i} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke={OG_COLOURS.line} strokeOpacity={0.45} strokeWidth={1} /> : null
      })}
      {graph.nodes.map((n, i) => {
        const p = points[i]
        return p && !onPath.has(n.id) ? <circle key={n.id} cx={p.x} cy={p.y} r={3.5} fill={OG_COLOURS[n.group]} opacity={0.8} /> : null
      })}
      <polyline points={pathPts.map((p) => `${p.x},${p.y}`).join(' ')} fill="none" stroke={OG_COLOURS.accent} strokeWidth={3} strokeLinejoin="round" />
      {pathPts.map((p, i) => (
        <circle key={`p${i}`} cx={p.x} cy={p.y} r={i === pathPts.length - 1 ? 8 : 5} fill={OG_COLOURS.accent} />
      ))}
    </svg>
  )
}

export function OgMark({ size = 40 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32">
      <path d="M6 25 L13 14.5 L19 19.5 L26 7.5" fill="none" stroke={OG_COLOURS.text1} strokeWidth={2.25} strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="6" cy="25" r="3" fill={OG_COLOURS.ink} stroke={OG_COLOURS.text1} strokeWidth={2} />
      <circle cx="13" cy="14.5" r="2.1" fill={OG_COLOURS.text1} />
      <circle cx="19" cy="19.5" r="2.1" fill={OG_COLOURS.text1} />
      <circle cx="26" cy="7.5" r="3.6" fill={OG_COLOURS.accent} />
    </svg>
  )
}

export function OgCard({ eyebrow, title, font }: { eyebrow: string; title: string; font: ArrayBuffer | null }) {
  return (
    <div style={{ width: '100%', height: '100%', display: 'flex', background: OG_COLOURS.ink, color: OG_COLOURS.text1, padding: 64 }}>
      <div style={{ display: 'flex', flexDirection: 'column', justifyContent: 'space-between', width: 640 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          <OgMark size={44} />
          <span style={{ fontSize: 30, fontFamily: font ? 'Newsreader' : undefined }}>Actron</span>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
          {eyebrow ? <span style={{ fontSize: 22, color: OG_COLOURS.text3 }}>{eyebrow}</span> : null}
          <span style={{ fontSize: title.length > 60 ? 54 : 62, lineHeight: 1.08, fontFamily: font ? 'Newsreader' : undefined }}>{title}</span>
        </div>
      </div>
      <div style={{ display: 'flex', marginLeft: 'auto', alignItems: 'center' }}>
        <OgGraph width={420} height={500} />
      </div>
    </div>
  )
}

export function replayTitle(title: string | null | undefined): string {
  return title ? `Replay: ${title}` : 'Replay of an Actron request'
}
