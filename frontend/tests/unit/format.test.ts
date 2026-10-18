import { describe, expect, it } from 'vitest'
import {
  clockTime,
  countWord,
  exactTime,
  formatCompact,
  formatDuration,
  formatNumber,
  formatPercent,
  formatTokens,
  formatUsd,
  initials,
  plural,
  relativeTime,
  relativeTimeShort,
  shortDate,
  shortHash,
  shortRequestId,
  shortSha,
  truncateMiddle,
} from '@/lib/format'

const NOW = Date.parse('2026-10-17T12:00:00Z')
const ago = (s: number) => new Date(NOW - s * 1000).toISOString()

describe('C-AC-42 format helpers', () => {
  it.each([
    [10, 'just now'],
    [44, 'just now'],
    [60, '1 min ago'],
    [4 * 60, '4 min ago'],
    [2 * 3600, '2 h ago'],
    [86400, 'yesterday'],
    [3 * 86400, '3 days ago'],
  ])('C-AC-42 relativeTime %i s → %s', (s, text) => {
    expect(relativeTime(ago(s), NOW)).toBe(text)
  })

  it('C-AC-42 relativeTime falls back to a date after two weeks and handles future and invalid input', () => {
    expect(relativeTime(ago(30 * 86400), NOW)).toMatch(/2026/)
    expect(relativeTime(new Date(NOW + 30_000).toISOString(), NOW)).toBe('in a moment')
    expect(relativeTime(new Date(NOW + 600_000).toISOString(), NOW)).toBe('in 10 min')
    expect(relativeTime('not a date', NOW)).toBe('unknown time')
  })

  it('C-AC-42 relativeTimeShort is uppercase mono text for the status bar', () => {
    expect(relativeTimeShort(ago(5), NOW)).toBe('JUST NOW')
    expect(relativeTimeShort(ago(120), NOW)).toBe('2M AGO')
    expect(relativeTimeShort(ago(7200), NOW)).toBe('2H AGO')
    expect(relativeTimeShort(ago(3 * 86400), NOW)).toBe('3D AGO')
    expect(relativeTimeShort('bad', NOW)).toBe('—')
  })

  it('C-AC-42 exactTime, clockTime and shortDate render or report invalid dates', () => {
    expect(exactTime('2026-10-17T09:12:03Z')).toMatch(/2026/)
    expect(exactTime('x')).toBe('Unknown time')
    expect(clockTime('2026-10-17T09:12:03Z')).toMatch(/^\d{2}:\d{2}:\d{2}$/)
    expect(clockTime('x')).toBe('--:--:--')
    expect(shortDate('2026-10-17T09:12:03Z')).toMatch(/Oct 2026/)
    expect(shortDate('x')).toBe('Unknown date')
  })

  it('C-AC-42 numbers use thousands separators and compact form', () => {
    expect(formatNumber(41203)).toBe('41,203')
    expect(formatNumber(Number.NaN)).toBe('—')
    expect(formatCompact(1500)).toBe('1.5k')
    expect(formatCompact(Infinity)).toBe('—')
  })

  it.each([
    [840, '840 ms'],
    [1000, '1s'],
    [134_000, '2m 14s'],
    [3_780_000, '1h 03m'],
    [-1, '—'],
  ])('C-AC-42 formatDuration(%i) → %s', (ms, text) => {
    expect(formatDuration(ms)).toBe(text)
  })

  it('C-AC-42 money, tokens and percent', () => {
    expect(formatUsd(1.234)).toBe('$1.23')
    expect(formatUsd(0.004)).toBe('<$0.01')
    expect(formatUsd(0)).toBe('$0.00')
    expect(formatTokens({ input: 12000, output: 3400 })).toBe('15.4k tokens')
    expect(formatPercent(62.4)).toBe('62%')
    expect(formatPercent(Number.NaN)).toBe('—')
  })

  it('C-AC-42 middle truncation keeps both ends', () => {
    expect(truncateMiddle('src/nrepl/repl-session/evaluate.ts', 20)).toBe('src/nrepl/…aluate.ts')
    expect(truncateMiddle('short', 20)).toBe('short')
    expect(truncateMiddle('abcdefghij', 3)).toBe('abcdefghij')
    expect(truncateMiddle('abcdefghijkl', 9).length).toBe(9)
  })

  it('C-AC-42 hashes, SHAs, ids, plurals, words and initials', () => {
    expect(shortHash('3f2a0000000000c91e')).toBe('3f2a…c91e')
    expect(shortHash('abc')).toBe('abc')
    expect(shortSha('3f2a1c9deadbeef')).toBe('3f2a1c9')
    expect(shortRequestId('req_01JCALVA0DONE0000000001')).toBe('000001')
    expect(plural(1, 'test')).toBe('1 test')
    expect(plural(14, 'test')).toBe('14 tests')
    expect(plural(2, 'query', 'queries')).toBe('2 queries')
    expect(countWord(2)).toBe('Two')
    expect(countWord(0)).toBe('No')
    expect(countWord(12)).toBe('12')
    expect(initials('Dana Ilić')).toBe('DI')
    expect(initials('Sam')).toBe('S')
    expect(initials('  ')).toBe('?')
  })
})
