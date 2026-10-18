import 'server-only'
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { serverApiOrNull } from '@/lib/api/server'
import type { GraphStats, RequestSummary } from '@/lib/api/types'
import { JOURNEY_FILES, replayHref } from './journey'

/** Which journey screenshots exist (produced by scripts/capture-screens.ts from the running app). */
export function availableScreenshots(publicDir = join(/*turbopackIgnore: true*/ process.cwd(), 'public')): boolean[] {
  return JOURNEY_FILES.map((file) => existsSync(join(publicDir, file)))
}

/** Where the journey screenshots came from: "fixtures" until they are re-captured against a real workspace. */
export function screenshotSource(publicDir = join(/*turbopackIgnore: true*/ process.cwd(), 'public')): 'fixtures' | 'live' {
  try {
    const meta = JSON.parse(readFileSync(join(publicDir, 'landing', 'journey.json'), 'utf8')) as { source?: string }
    return meta.source === 'live' ? 'live' : 'fixtures'
  } catch {
    return 'fixtures'
  }
}

export interface LandingData {
  stats: GraphStats | null
  replay: string | null
  screenshots: boolean[]
  screenshotSource: 'fixtures' | 'live'
}

export async function loadLandingData(): Promise<LandingData> {
  const [stats, done] = await Promise.all([
    serverApiOrNull<GraphStats>('/api/graph/stats', { timeoutMs: 1500, withCookies: false }),
    serverApiOrNull<{ requests: RequestSummary[] }>('/api/requests?group=done&limit=1', { timeoutMs: 1500 }),
  ])
  const finished = done?.requests.find((r) => r.state === 'Done') ?? null
  let publicAllowed = false
  if (finished) {
    const pub = await serverApiOrNull<unknown>(`/api/public/replays/${encodeURIComponent(finished.id)}`, {
      timeoutMs: 1500,
      withCookies: false,
    })
    publicAllowed = pub !== null
  }
  return {
    stats: stats && stats.nodes > 0 ? stats : null,
    replay: replayHref(finished?.id ?? null, publicAllowed),
    screenshots: availableScreenshots(),
    screenshotSource: screenshotSource(),
  }
}
