import { SIMPLE_PATHS, type SimpleBrand } from './simple-paths'
import { ActronMark } from './ActronLogo'

/** Real logos only (spec C, C1.5). Files and licences: public/brands/LICENSES.md. */
export const OFFICIAL_BRANDS = {
  slack: { title: 'Slack', src: '/brands/slack.svg', mono: null },
  falkordb: { title: 'FalkorDB', src: '/brands/falkordb.svg', mono: null },
  pi: { title: 'Pi', src: '/brands/pi.svg', mono: '/brands/pi-mono.svg' },
  typesafe: { title: 'Jev by TypeSafe', src: '/brands/typesafe.png', mono: null },
} as const

export type OfficialBrand = keyof typeof OFFICIAL_BRANDS
export type BrandName = SimpleBrand | OfficialBrand | 'jev' | 'actron' | 'llm'

export const BRAND_NAMES: BrandName[] = [
  ...(Object.keys(OFFICIAL_BRANDS) as OfficialBrand[]),
  ...(Object.keys(SIMPLE_PATHS) as SimpleBrand[]),
  'jev',
  'actron',
  'llm',
]

function luminance(hex: string): number {
  const value = hex.replace('#', '')
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(value.slice(i, i + 2), 16) / 255) as [number, number, number]
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

export function brandTitle(name: BrandName): string {
  if (name === 'jev') return OFFICIAL_BRANDS.typesafe.title
  if (name === 'actron') return 'Actron'
  if (name === 'llm') return 'Language model'
  if (name in OFFICIAL_BRANDS) return OFFICIAL_BRANDS[name as OfficialBrand].title
  return SIMPLE_PATHS[name as SimpleBrand].title
}

export interface BrandMarkProps {
  name: BrandName
  size?: number
  tone?: 'color' | 'mono'
  /** Hide from assistive technology when a visible label sits next to the mark. */
  decorative?: boolean
  className?: string
}

export function BrandMark({ name, size = 16, tone = 'color', decorative = false, className }: BrandMarkProps) {
  const title = brandTitle(name)
  const a11y = decorative ? { 'aria-hidden': true as const } : { role: 'img' as const, 'aria-label': title }
  const resolved: BrandName = name === 'jev' ? 'typesafe' : name

  if (resolved === 'actron') {
    return <ActronMark size={size} className={className} title={decorative ? undefined : title} />
  }

  if (resolved === 'llm') {
    // No vendor mark: the job may run on any provider through LiteLLM, so the UI names it in plain type.
    return (
      <span
        {...a11y}
        data-brand="llm"
        className={['inline-flex items-center justify-center rounded-sm border border-line-2 font-mono text-fg-2', className]
          .filter(Boolean)
          .join(' ')}
        style={{ width: size, height: size, fontSize: Math.max(7, Math.round(size * 0.38)) }}
      >
        LLM
      </span>
    )
  }

  if (resolved in OFFICIAL_BRANDS) {
    const brand = OFFICIAL_BRANDS[resolved as OfficialBrand]
    const src = tone === 'mono' && brand.mono ? brand.mono : brand.src
    return (
      // Official files are used as published; next/image adds nothing for 16-px SVGs.
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={src}
        width={size}
        height={size}
        alt={decorative ? '' : title}
        aria-hidden={decorative ? true : undefined}
        data-brand={resolved}
        className={['inline-block shrink-0 object-contain', className].filter(Boolean).join(' ')}
        decoding="async"
      />
    )
  }

  const simple = SIMPLE_PATHS[resolved as SimpleBrand]
  const dark = luminance(simple.hex) < 0.12
  const fill = tone === 'mono' || dark ? 'currentColor' : simple.hex
  return (
    <svg
      {...a11y}
      viewBox="0 0 24 24"
      width={size}
      height={size}
      data-brand={resolved}
      className={['inline-block shrink-0', className].filter(Boolean).join(' ')}
      focusable="false"
    >
      <path fill={fill} d={simple.d} />
    </svg>
  )
}

/** Language mark for a file path, used by the build theatre and diff viewer. */
export function languageFor(path: string): SimpleBrand | null {
  const ext = path.split('.').pop()?.toLowerCase() ?? ''
  switch (ext) {
    case 'ts':
    case 'tsx':
    case 'mts':
    case 'cts':
      return 'typescript'
    case 'js':
    case 'jsx':
    case 'mjs':
    case 'cjs':
      return 'javascript'
    case 'py':
      return 'python'
    case 'clj':
    case 'cljs':
    case 'cljc':
    case 'edn':
      return 'clojure'
    case 'json':
      return 'json'
    case 'md':
    case 'mdx':
      return 'markdown'
    case 'go':
      return 'go'
    case 'rs':
      return 'rust'
    default:
      return null
  }
}
