/**
 * First-load JavaScript per route from a Next.js (Turbopack) build: the root main files plus every entry chunk
 * listed in the route's client reference manifest, gzipped. Used by tests/unit/bundle-budget.test.ts (C-AC-16).
 */
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import { gzipSync } from 'node:zlib'
import { runInNewContext } from 'node:vm'

export interface RouteSize {
  route: string
  files: string[]
  gzipBytes: number
}

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) walk(p, out)
    else if (name.endsWith('page_client-reference-manifest.js')) out.push(p)
  }
  return out
}

export function routeSizes(distDir: string): RouteSize[] {
  const buildManifest = JSON.parse(readFileSync(join(distDir, 'build-manifest.json'), 'utf8')) as { rootMainFiles: string[] }
  const serverApp = join(distDir, 'server', 'app')
  if (!existsSync(serverApp)) return []
  const gz = new Map<string, number>()
  const size = (file: string) => {
    if (!gz.has(file)) gz.set(file, gzipSync(readFileSync(join(distDir, file))).length)
    return gz.get(file) as number
  }
  return walk(serverApp).map((manifestPath) => {
    const sandbox: { self: Record<string, unknown>; globalThis?: unknown } = { self: {} }
    sandbox.globalThis = sandbox
    runInNewContext(readFileSync(manifestPath, 'utf8'), sandbox)
    const all = (sandbox.self.__RSC_MANIFEST ?? (sandbox as Record<string, unknown>).__RSC_MANIFEST) as Record<string, { entryJSFiles: Record<string, string[]> }>
    const files = new Set<string>(buildManifest.rootMainFiles)
    for (const man of Object.values(all)) for (const list of Object.values(man.entryJSFiles)) list.forEach((f) => files.add(f))
    const route =
      '/' +
      relative(serverApp, manifestPath)
        .replace(/page_client-reference-manifest\.js$/, '')
        .replace(/\([^)]+\)\//g, '')
        .replace(/\/$/, '')
    const list = [...files]
    return { route: route === '/' ? '/' : route.replace(/\/$/, ''), files: list, gzipBytes: list.reduce((t, f) => t + size(f), 0) }
  })
}
