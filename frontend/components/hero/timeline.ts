/**
 * The hero's story, as a loop: a request arrives, Actron searches the FalkorDB graph, follows links to the code and
 * finds the evidence path. Pure functions of time so the 3D scene and the caption chip stay in step and the loop can
 * be tested without WebGL.
 */
export const HERO_LOOP_MS = 10_000

export type HeroStage = 'request' | 'search' | 'follow' | 'found'

export const HERO_STAGE_TEXT: Record<HeroStage, string> = {
  request: 'Request received',
  search: 'Searching the FalkorDB graph',
  follow: 'Following links to the code',
  found: 'Evidence path found',
}

/** Where each stage begins (ms into the loop) and when the path fades out. */
const SEARCH_AT = 1_500
const FOLLOW_AT = 4_000
const FOUND_AT = 7_000
const FADE_AT = 9_200

/** Query rings leave the request node at these times and take this long to reach the edge of the graph. */
const RING_STARTS = [0, 1_200, 2_400]
const RING_MS = 2_600

/** The end of the path pulses once when it is reached. */
const END_PULSE_MS = 1_100

export interface HeroFrame {
  stage: HeroStage
  /** How much of the evidence path is drawn, 0 to 1. */
  pathProgress: number
  /** Opacity of the drawn path (fades out at the end of the loop). */
  pathOpacity: number
  /** Active query rings as 0..1 phases; fewer entries when rings have finished. */
  rings: number[]
  /** 0..1 while the end of the path pulses, null otherwise. */
  endPulse: number | null
}

const easeInOut = (x: number) => (x < 0.5 ? 2 * x * x : 1 - (-2 * x + 2) ** 2 / 2)

export function heroFrame(timeMs: number): HeroFrame {
  const t = ((timeMs % HERO_LOOP_MS) + HERO_LOOP_MS) % HERO_LOOP_MS
  const stage: HeroStage = t < SEARCH_AT ? 'request' : t < FOLLOW_AT ? 'search' : t < FOUND_AT ? 'follow' : 'found'
  return {
    stage,
    pathProgress: t < FOLLOW_AT ? 0 : t >= FOUND_AT ? 1 : easeInOut((t - FOLLOW_AT) / (FOUND_AT - FOLLOW_AT)),
    pathOpacity: t < FADE_AT ? 1 : 1 - (t - FADE_AT) / (HERO_LOOP_MS - FADE_AT),
    rings: RING_STARTS.map((start) => (t - start) / RING_MS).filter((p) => p >= 0 && p < 1),
    endPulse: t >= FOUND_AT && t < FOUND_AT + END_PULSE_MS ? (t - FOUND_AT) / END_PULSE_MS : null,
  }
}
