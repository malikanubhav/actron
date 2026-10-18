import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { OG_COLOURS, OG_TOKENS } from '@/components/landing/og'

const css = readFileSync(join(__dirname, '../../../styles/tokens.css'), 'utf8')

function token(name: string): string | undefined {
  const match = css.match(new RegExp(`${name}:\\s*(#[0-9a-fA-F]{6})`))
  return match?.[1]?.toUpperCase()
}

describe('Open Graph colours', () => {
  it.each(Object.keys(OG_COLOURS) as (keyof typeof OG_COLOURS)[])('%s equals its tokens.css value', (key) => {
    expect(token(OG_TOKENS[key])).toBe(OG_COLOURS[key].toUpperCase())
  })
})
