import { describe, expect, it } from 'vitest'
import { HERO_LOOP_MS, HERO_STAGE_TEXT, heroFrame } from '@/components/hero/timeline'

describe('hero loop', () => {
  it('walks request → search → follow → found and starts again', () => {
    expect(heroFrame(0).stage).toBe('request')
    expect(heroFrame(2_000).stage).toBe('search')
    expect(heroFrame(5_000).stage).toBe('follow')
    expect(heroFrame(8_000).stage).toBe('found')
    expect(heroFrame(HERO_LOOP_MS).stage).toBe('request')
    expect(heroFrame(HERO_LOOP_MS + 5_000).stage).toBe('follow')
  })

  it('draws the evidence path only while Actron follows links, never backwards', () => {
    expect(heroFrame(3_999).pathProgress).toBe(0)
    let last = 0
    for (let t = 4_000; t <= 7_000; t += 100) {
      const p = heroFrame(t).pathProgress
      expect(p).toBeGreaterThanOrEqual(last)
      last = p
    }
    expect(heroFrame(7_000).pathProgress).toBe(1)
    expect(heroFrame(9_000).pathProgress).toBe(1)
  })

  it('fades the path out at the end of the loop so the next pass starts clean', () => {
    expect(heroFrame(9_000).pathOpacity).toBe(1)
    expect(heroFrame(9_600).pathOpacity).toBeCloseTo(0.5)
    expect(heroFrame(HERO_LOOP_MS - 1).pathOpacity).toBeLessThan(0.01)
    expect(heroFrame(HERO_LOOP_MS).pathOpacity).toBe(1)
  })

  it('sends query rings out of the request while searching, and pulses the end once when it is reached', () => {
    expect(heroFrame(100).rings).toHaveLength(1)
    expect(heroFrame(1_800).rings).toHaveLength(2)
    expect(heroFrame(2_500).rings).toHaveLength(3)
    expect(heroFrame(2_900).rings).toHaveLength(2)
    expect(heroFrame(6_000).rings).toHaveLength(0)
    expect(heroFrame(6_900).endPulse).toBeNull()
    expect(heroFrame(7_100).endPulse).toBeGreaterThan(0)
    expect(heroFrame(8_500).endPulse).toBeNull()
  })

  it('names every stage in plain words, FalkorDB included', () => {
    expect(Object.keys(HERO_STAGE_TEXT).sort()).toEqual(['follow', 'found', 'request', 'search'])
    expect(HERO_STAGE_TEXT.search).toMatch(/FalkorDB/)
  })

  it('treats negative times as a position in the loop', () => {
    expect(heroFrame(-1).stage).toBe('found')
  })
})
