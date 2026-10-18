import { beforeEach, describe, expect, it } from 'vitest'
import { ACTION_COMMANDS, SCREEN_COMMANDS, commandScore, fuzzyScore, nodeCommand, pushRecent, rankCommands, readRecent, requestCommand } from '@/lib/palette'
import { ShortcutMatcher, hrefFor, isTypingTarget, SEQUENCE_TIMEOUT_MS, SHORTCUTS } from '@/lib/shortcuts'
import { makeRequestDetail } from './helpers/render'

describe('command palette (PROMPT 8.7)', () => {
  beforeEach(() => window.localStorage.clear())

  it('fuzzyScore ranks exact, prefix, contiguous and subsequence matches in that order', () => {
    const exact = fuzzyScore('inbox', 'Inbox') as number
    const prefix = fuzzyScore('inb', 'Inbox') as number
    const contains = fuzzyScore('box', 'Inbox') as number
    const subseq = fuzzyScore('ibx', 'Inbox') as number
    expect(exact).toBeGreaterThan(prefix)
    expect(prefix).toBeGreaterThan(contains)
    expect(contains).toBeGreaterThan(subseq)
    expect(fuzzyScore('zzz', 'Inbox')).toBeNull()
    expect(fuzzyScore('', 'Inbox')).toBe(0)
  })

  it('word starts score higher than mid-word matches', () => {
    expect(fuzzyScore('ec', 'evaluate code') as number).toBeGreaterThan(fuzzyScore('ec', 'aebxc') as number)
  })

  it('rankCommands filters and ranks; titles beat subtitles', () => {
    const ranked = rankCommands('graph', [...SCREEN_COMMANDS, ...ACTION_COMMANDS])
    expect(ranked[0]?.title).toBe('Graph')
    expect(rankCommands('qqqq', SCREEN_COMMANDS)).toEqual([])
    expect(commandScore('memory', SCREEN_COMMANDS.find((c) => c.title === 'Graph') as (typeof SCREEN_COMMANDS)[number])).not.toBeNull()
  })

  it('recent items come first with no query and get a boost with one', () => {
    const recent = ['screen:settings']
    expect(rankCommands('', SCREEN_COMMANDS, recent)[0]?.id).toBe('screen:settings')
    expect(rankCommands('', SCREEN_COMMANDS)[0]?.id).toBe('screen:home')
  })

  it('request and node commands link to the right place', () => {
    const r = makeRequestDetail({ id: 'req_1', state: 'Building' })
    expect(requestCommand(r)).toMatchObject({ kind: 'request', href: '/app/requests/req_1', subtitle: 'Building · Dana Ilić' })
    expect(nodeCommand({ id: 'code:fn:a#b', type: 'CodeFunction', label: 'b', snippet: '', score: 1 })).toMatchObject({
      href: '/app/graph?node=code%3Afn%3Aa%23b',
      subtitle: 'CodeFunction',
    })
  })

  it('recents are stored newest first, deduped and capped', () => {
    for (const id of ['a', 'b', 'a', 'c']) pushRecent(id, 2)
    expect(readRecent()).toEqual(['c', 'a'])
    window.localStorage.setItem('actron.palette.recent', '{bad')
    expect(readRecent()).toEqual([])
  })
})

describe('keyboard shortcuts (PROMPT 8.7)', () => {
  let t = 0
  const m = () => new ShortcutMatcher(() => t)
  const key = (k: string, extra: Partial<KeyboardEvent> = {}) => ({ key: k, ...extra })

  beforeEach(() => {
    t = 1000
  })

  it.each([
    ['h', 'go-home'],
    ['i', 'go-inbox'],
    ['g', 'go-graph'],
    ['s', 'go-system'],
    ['c', 'go-connect'],
  ])('g then %s → %s', (second, action) => {
    const matcher = m()
    expect(matcher.feed(key('g'))).toBeNull()
    t += 300
    expect(matcher.feed(key(second))).toBe(action)
  })

  it('a sequence times out', () => {
    const matcher = m()
    matcher.feed(key('g'))
    t += SEQUENCE_TIMEOUT_MS + 1
    expect(matcher.feed(key('h'))).toBeNull()
  })

  it('single keys: n, a and ?; Cmd/Ctrl+K opens the palette anywhere', () => {
    const matcher = m()
    expect(matcher.feed(key('n'))).toBe('new-request')
    expect(matcher.feed(key('a'))).toBe('approve')
    expect(matcher.feed(key('?', { shiftKey: true }))).toBe('shortcuts')
    expect(matcher.feed(key('k', { metaKey: true }))).toBe('palette')
    expect(matcher.feed(key('K', { ctrlKey: true }))).toBe('palette')
    expect(matcher.feed(key('x'))).toBeNull()
    expect(matcher.feed(key('n', { altKey: true }))).toBeNull()
  })

  it('typing in fields never triggers shortcuts, except the palette', () => {
    const input = document.createElement('input')
    const textarea = document.createElement('textarea')
    const div = document.createElement('div')
    expect(isTypingTarget(input)).toBe(true)
    expect(isTypingTarget(textarea)).toBe(true)
    expect(isTypingTarget(div)).toBe(false)
    expect(isTypingTarget(null)).toBe(false)
    const matcher = m()
    expect(matcher.feed(key('n', { target: input }))).toBeNull()
    expect(matcher.feed(key('k', { ctrlKey: true, target: input }))).toBe('palette')
  })

  it('every navigation shortcut has a route and the sheet lists them all', () => {
    expect(hrefFor('go-home')).toBe('/app')
    expect(hrefFor('go-inbox')).toBe('/app/inbox')
    expect(hrefFor('go-graph')).toBe('/app/graph')
    expect(hrefFor('approve')).toBeNull()
    expect(SHORTCUTS.map((s) => s.keys)).toEqual(expect.arrayContaining(['mod+k', 'g h', 'g i', 'g g', 'n', 'a', '?']))
  })
})
