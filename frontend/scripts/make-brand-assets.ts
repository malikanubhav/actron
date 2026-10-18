/**
 * Renders the Actron brand PNGs and the landing hero's static fallback with Playwright's Chromium.
 *   npx tsx scripts/make-brand-assets.ts
 * Inputs: public/actron-brand/favicon.svg and logo.svg (hand-drawn from components/brand/ActronLogo.tsx), and the
 * ontology type graph (lib/ontology-snapshot.json) laid out exactly as the 3D hero lays it out.
 * Outputs: public/actron-brand/{favicon-16,favicon-32,apple-touch-icon,icon-192,icon-512}.png and
 * public/landing/hero-fallback.png.
 */
import { readFileSync, mkdirSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from '@playwright/test'
import { graphFromOntology, layout3d, project, type OntologySnapshotLike } from '../components/hero/layout3d'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const brandDir = join(root, 'public', 'actron-brand')
const landingDir = join(root, 'public', 'landing')
mkdirSync(landingDir, { recursive: true })

// Colours come from styles/tokens.css, the only place they are defined.
const tokensCss = readFileSync(join(root, 'styles', 'tokens.css'), 'utf8')
function token(name: string): string {
  const m = tokensCss.match(new RegExp(`${name}:\\s*(#[0-9a-fA-F]{6})`))
  if (!m?.[1]) throw new Error(`token ${name} not found in tokens.css`)
  return m[1]
}
const COLOURS: Record<string, string> = Object.fromEntries(
  ['code', 'github', 'slack', 'linear', 'core'].map((g) => [g, token(`--node-${g}`)]),
)
const LINK = token('--graph-link')
const ACCENT = token('--accent')
const INK0 = token('--ink-0')
const TEXT2 = token('--text-2')

export function heroFallbackSvg(size = 1200): string {
  const snapshot = JSON.parse(readFileSync(join(root, 'lib', 'ontology-snapshot.json'), 'utf8')) as OntologySnapshotLike
  const graph = graphFromOntology(snapshot)
  const pts = project(layout3d(graph.nodes, graph.links), size, size, 0.6, 0.35, 80)
  const index = new Map(graph.nodes.map((n, i) => [n.id, i]))
  const onPath = new Set(graph.path)
  const links = graph.links
    .map((l) => {
      const a = pts[index.get(l.from) ?? -1]
      const b = pts[index.get(l.to) ?? -1]
      return a && b ? `<line x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}" stroke="${LINK}" stroke-opacity="0.35" stroke-width="1.5"/>` : ''
    })
    .join('')
  const nodes = graph.nodes
    .map((n, i) => {
      const p = pts[i]
      if (!p || onPath.has(n.id)) return ''
      return `<circle cx="${p.x}" cy="${p.y}" r="7" fill="${COLOURS[n.group] ?? COLOURS.code}" fill-opacity="0.85"/>`
    })
    .join('')
  const pathIds = graph.path.filter((id) => pts[index.get(id) ?? -1])
  const path = pathIds.map((id) => pts[index.get(id) ?? -1]) as { x: number; y: number }[]
  const poly = path.map((p) => `${p.x},${p.y}`).join(' ')
  // The path is a plain accent line (no glow). Its start is the request (a larger rose square), its end the function
  // (an accent ring); the hops between keep their source colour. Both ends are named.
  const start = path[0]
  const end = path[path.length - 1]
  const middle = pathIds
    .slice(1, -1)
    .map((id) => {
      const p = pts[index.get(id) ?? -1] as { x: number; y: number }
      const n = graph.nodes[index.get(id) ?? -1]
      return `<circle cx="${p.x}" cy="${p.y}" r="10" fill="${COLOURS[n?.group ?? 'code'] ?? COLOURS.code}" stroke="${ACCENT}" stroke-width="3"/>`
    })
    .join('')
  const label = (p: { x: number; y: number }, text: string, dy: number) =>
    `<text x="${p.x}" y="${p.y + dy}" text-anchor="middle" font-family="Public Sans, sans-serif" font-size="30" font-weight="500" fill="${TEXT2}" stroke="${INK0}" stroke-width="8" paint-order="stroke">${text}</text>`
  const ends =
    start && end
      ? `<rect x="${start.x - 18}" y="${start.y - 18}" width="36" height="36" rx="5" fill="${COLOURS.core}"/>` +
        `<circle cx="${end.x}" cy="${end.y}" r="16" fill="${INK0}" stroke="${ACCENT}" stroke-width="6"/>` +
        label(start, 'Request', start.y > end.y ? 56 : -32) +
        label(end, 'Function', end.y >= start.y ? 60 : -34)
      : ''
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
<rect width="${size}" height="${size}" fill="${INK0}"/>${links}${nodes}
<polyline points="${poly}" fill="none" stroke="${ACCENT}" stroke-width="4" stroke-linejoin="round" stroke-linecap="round"/>${middle}${ends}
</svg>`
}

async function main() {
  const browser = await chromium.launch()
  const page = await browser.newPage({ deviceScaleFactor: 1 })
  const render = async (svg: string, size: number, out: string, background = 'transparent') => {
    await page.setViewportSize({ width: size, height: size })
    await page.setContent(
      `<html><body style="margin:0;background:${background}"><div style="width:${size}px;height:${size}px">${svg.replace(
        /<svg /,
        `<svg width="${size}" height="${size}" `,
      )}</div></body></html>`,
    )
    await page.screenshot({ path: out, omitBackground: background === 'transparent', clip: { x: 0, y: 0, width: size, height: size } })
    console.log('wrote', out)
  }
  // --hero-only re-renders the landing fallback without touching the brand icons.
  if (!process.argv.includes('--hero-only')) {
    const favicon = readFileSync(join(brandDir, 'favicon.svg'), 'utf8').replace(/ width="32" height="32"/, '')
    for (const [name, size] of [
      ['favicon-16.png', 16],
      ['favicon-32.png', 32],
      ['apple-touch-icon.png', 180],
      ['icon-192.png', 192],
      ['icon-512.png', 512],
    ] as const) {
      await render(favicon, size, join(brandDir, name))
    }
  }
  await render(heroFallbackSvg(1200), 1200, join(landingDir, 'hero-fallback.png'), INK0)
  await browser.close()
}

void main()
