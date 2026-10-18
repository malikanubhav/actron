import { readFileSync, readdirSync, statSync, existsSync } from 'node:fs'
import { join, relative } from 'node:path'
import { describe, expect, it } from 'vitest'

const root = join(__dirname, '..', '..')

function walk(dir: string, out: string[] = []): string[] {
  if (!existsSync(dir)) return out
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) walk(p, out)
    else if (/\.(tsx?|mdx)$/.test(name)) out.push(p)
  }
  return out
}

const files = [
  ...walk(join(root, 'components')),
  ...walk(join(root, 'app')),
  ...walk(join(root, 'content', 'guides')),
  join(root, 'lib', 'events.ts'),
  join(root, 'lib', 'request-view.ts'),
  join(root, 'lib', 'api.ts'),
].filter((f) => !/simple-paths\.ts$/.test(f) && !/\.d\.ts$/.test(f))

/** User copy: string literals and JSX text (outside code), heuristically. */
export function userCopy(source: string, isMdx: boolean): string[] {
  if (isMdx) {
    return source
      .replace(/```[\s\S]*?```/g, '')
      .replace(/`[^`]*`/g, '')
      .replace(/^\s*(import|export)\b.*$/gm, '')
      .split('\n')
  }
  const out: string[] = []
  const noComments = source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/.*$/gm, '$1')
  for (const m of noComments.matchAll(/'([^'\\\n]|\\.)*'|"([^"\\\n]|\\.)*"|`([^`\\]|\\.)*`/g)) out.push(m[0].slice(1, -1))
  for (const m of noComments.matchAll(/>([^<>{}]+)</g)) out.push(m[1] as string)
  return out
}

const BANNED = /\b(supercharge|unleash|seamless|ai-powered|revolutionary|magic)\b/i
const EMOJI = /\p{Extended_Pictographic}/u
const ICONS = /\b(Sparkle|Sparkles|Robot|MagicWand|Brain)\b/

describe('C-AC-6 copy lint', () => {
  it('C-AC-6 scans components, app routes, guides and event copy', () => {
    expect(files.length).toBeGreaterThan(40)
  })

  it('C-AC-6 no banned hype words in UI copy', () => {
    const hits: string[] = []
    for (const f of files) for (const s of userCopy(readFileSync(f, 'utf8'), f.endsWith('.mdx'))) if (BANNED.test(s)) hits.push(`${relative(root, f)}: ${s.trim()}`)
    expect(hits).toEqual([])
  })

  it('C-AC-6 no exclamation marks in UI copy', () => {
    const hits: string[] = []
    for (const f of files) {
      for (const s of userCopy(readFileSync(f, 'utf8'), f.endsWith('.mdx'))) {
        // Sentences ending in "!" or "! ": not code operators, which never sit in string literals or JSX text.
        if (/[A-Za-z)]![\s"'.]|[A-Za-z)]!$/.test(s.trim()) && !/!=/.test(s)) hits.push(`${relative(root, f)}: ${s.trim()}`)
      }
    }
    expect(hits).toEqual([])
  })

  it('C-AC-6 no emoji anywhere in UI sources', () => {
    const hits = files.filter((f) => EMOJI.test(readFileSync(f, 'utf8').replace(/[←→↑↓⌘↵·…“”’–—−]/g, '')))
    expect(hits.map((f) => relative(root, f))).toEqual([])
  })

  it('C-AC-6 no sparkle, robot, wand or brain icons are imported', () => {
    const hits: string[] = []
    for (const f of files) {
      const text = readFileSync(f, 'utf8')
      for (const imp of text.matchAll(/import[^;]*from\s+['"]@phosphor-icons\/react[^'"]*['"]/g)) if (ICONS.test(imp[0])) hits.push(relative(root, f))
    }
    expect(hits).toEqual([])
  })

  it('C-AC-6 the copy heuristic itself catches violations', () => {
    expect(userCopy(`const a = 'Unleash your team!'`, false).some((s) => BANNED.test(s))).toBe(true)
    expect(userCopy(`<p>Done!</p>`, false).some((s) => /[A-Za-z]!$/.test(s.trim()))).toBe(true)
    expect(userCopy(`if (a !== b) {}`, false)).toEqual([])
  })
})
