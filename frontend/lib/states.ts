/**
 * Shared state map (spec C, C2 StateChip; C-AC-10). The data lives in states.json so the backend's Slack blocks
 * read the same names and colours.
 */
import data from './states.json'
import type { Label, PipelineStep, State, SyncState, Tier } from './api/types'

export type Tone = 'running' | 'ok' | 'conflict' | 'possible' | 'idle' | 'needs_you'

export interface StateStyle {
  tone: Tone
  text: string
}

export const TONES = data.tones as Record<Tone, { token: string; hex: string }>

const requestStates = data.requestStates as Record<State, StateStyle & { needsYou: boolean; final: boolean }>
const ingestionStates = data.ingestionStates as Record<SyncState, StateStyle>
const labels = data.labels as Record<Label, StateStyle>
const tiers = data.tiers as Record<Tier, { text: string; min: number; bars: number }>

export const PIPELINE = data.pipeline as { n: PipelineStep; text: string }[]

export type AnyState = State | SyncState

export function isRequestState(value: string): value is State {
  return Object.prototype.hasOwnProperty.call(requestStates, value)
}

export function isSyncState(value: string): value is SyncState {
  return Object.prototype.hasOwnProperty.call(ingestionStates, value)
}

export function stateStyle(state: AnyState): StateStyle {
  if (isRequestState(state)) return requestStates[state]
  if (isSyncState(state)) return ingestionStates[state]
  return { tone: 'idle', text: String(state).toUpperCase() }
}

/** Chip text in sentence case for the UI ("NEEDS YOUR INPUT" → "Needs your input"); Slack keeps its own casing. */
export function sentenceCase(text: string): string {
  const lower = text.toLowerCase()
  const cased = lower.charAt(0).toUpperCase() + lower.slice(1)
  return cased.replace(/\b(pr|sha|ci)\b/gi, (w) => w.toUpperCase()).replace(/\bgithub\b/gi, 'GitHub').replace(/\b(slack|linear|jev)\b/gi, (w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
}

export function labelStyle(label: Label): StateStyle {
  return labels[label]
}

export function isFinal(state: State): boolean {
  return requestStates[state].final
}

export function needsYou(state: State): boolean {
  return requestStates[state].needsYou
}

/** CSS variable for a tone, for use in style props and canvas drawing. */
export function toneVar(tone: Tone): string {
  return `var(${TONES[tone].token})`
}

export function toneHex(tone: Tone): string {
  return TONES[tone].hex
}

export function tierFor(confidence: number, flagged = false): Tier {
  if (flagged) return 'POSSIBLE'
  if (confidence >= tiers.HIGH.min) return 'HIGH'
  if (confidence >= tiers.MEDIUM.min) return 'MEDIUM'
  return 'POSSIBLE'
}

export function tierBars(tier: Tier): number {
  return tiers[tier].bars
}

/** Pipeline step for a state: 01 Investigate · 02 Clarify · 03 Ticket · 04 Approve · 05 Build · 06 Review. */
export function stepForState(state: State): PipelineStep {
  switch (state) {
    case 'Investigating':
      return 1
    case 'Needs your input':
      return 2
    case 'Ticket ready':
      return 3
    case 'Awaiting approval':
      return 4
    case 'Building':
    case 'Changes requested':
      return 5
    case 'PR ready for review':
    case 'Done':
      return 6
    case 'Needs attention':
    case 'Cancelled':
      return 1
  }
}
