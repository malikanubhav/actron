import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import data from '@/lib/states.json'
import { LABELS, STATES } from '@/lib/api/types'
import { isFinal, isRequestState, isSyncState, labelStyle, needsYou, stateStyle, stepForState, tierBars, tierFor, toneHex, toneVar, TONES } from '@/lib/states'

const SYNC = ['NOT CONNECTED', 'BACKFILLING', 'SYNCING', 'PARTIAL', 'FAILED', 'UP TO DATE'] as const
const tokens = readFileSync(join(__dirname, '..', '..', 'styles', 'tokens.css'), 'utf8')
const backendPath = join(__dirname, '..', '..', '..', 'backend', 'actron', 'flow', 'states.json')

describe('C-AC-10 shared state map', () => {
  it('C-AC-10 covers every request state, sync state and label', () => {
    expect(Object.keys(data.requestStates).sort()).toEqual([...STATES].sort())
    expect(Object.keys(data.ingestionStates).sort()).toEqual([...SYNC].sort())
    expect(Object.keys(data.labels).sort()).toEqual([...LABELS].sort())
  })

  it('C-AC-10 every tone hex equals its token in tokens.css', () => {
    for (const [, t] of Object.entries(TONES)) {
      const m = new RegExp(`${t.token}:\\s*(#[0-9a-fA-F]{6})`).exec(tokens)
      expect(m?.[1]?.toLowerCase(), t.token).toBe(t.hex.toLowerCase())
    }
  })

  it('C-AC-10 chip text is the uppercase state name', () => {
    for (const s of STATES) expect(stateStyle(s).text).toBe(s.toUpperCase())
    for (const s of SYNC) expect(stateStyle(s).text).toBe(s)
  })

  it.skipIf(!existsSync(backendPath))('C-AC-10 the backend Slack map uses the same names and colours', () => {
    const backend = JSON.parse(readFileSync(backendPath, 'utf8')) as {
      requestStates: Record<string, { tone: string; slackLabel: string; hex?: string }>
    }
    for (const s of STATES) {
      const b = backend.requestStates[s]
      expect(b, `backend is missing ${s}`).toBeTruthy()
      expect(b?.tone).toBe(stateStyle(s).tone)
      expect(b?.slackLabel).toBe(stateStyle(s).text)
      if (b?.hex) expect(b.hex.toLowerCase()).toBe(toneHex(stateStyle(s).tone).toLowerCase())
    }
  })

  it('needs-you and final flags match the flow', () => {
    expect(STATES.filter(needsYou)).toEqual(['Needs your input', 'Awaiting approval', 'Needs attention', 'PR ready for review'])
    expect(STATES.filter(isFinal)).toEqual(['Done', 'Cancelled'])
  })

  it('type guards, label styles, tone helpers and unknown states', () => {
    expect(isRequestState('Building')).toBe(true)
    expect(isRequestState('BUILDING')).toBe(false)
    expect(isSyncState('PARTIAL')).toBe(true)
    expect(labelStyle('possible_conflict')).toEqual({ tone: 'possible', text: 'POSSIBLE CONFLICT' })
    expect(toneVar('needs_you')).toBe('var(--accent)')
    expect(stateStyle('Whatever' as never)).toEqual({ tone: 'idle', text: 'WHATEVER' })
  })

  it('confidence tiers follow spec C2 thresholds', () => {
    expect(tierFor(0.8)).toBe('HIGH')
    expect(tierFor(0.79)).toBe('MEDIUM')
    expect(tierFor(0.6)).toBe('MEDIUM')
    expect(tierFor(0.59)).toBe('POSSIBLE')
    expect(tierFor(0.95, true)).toBe('POSSIBLE')
    expect([tierBars('HIGH'), tierBars('MEDIUM'), tierBars('POSSIBLE')]).toEqual([3, 2, 1])
  })

  it('pipeline step for each state', () => {
    expect(STATES.map(stepForState)).toEqual([1, 2, 3, 4, 5, 1, 6, 5, 6, 1])
  })
})
