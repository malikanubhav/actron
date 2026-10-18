/**
 * Tailwind theme mirroring styles/tokens.css (spec C, C1). Every value is a CSS variable, so the tokens file
 * stays the single source of truth. Loaded from app/globals.css with `@config`.
 */
const v = (name: string) => `var(--${name})`

export const colors = {
  transparent: 'transparent',
  current: 'currentColor',
  ink: { 0: v('ink-0'), 1: v('ink-1'), 2: v('ink-2'), 3: v('ink-3') },
  line: { 1: v('line-1'), 2: v('line-2') },
  fg: { 1: v('text-1'), 2: v('text-2'), 3: v('text-3'), disabled: v('text-disabled') },
  accent: { DEFAULT: v('accent'), ink: v('accent-ink'), wash: v('accent-wash') },
  state: {
    ok: v('state-ok'),
    conflict: v('state-conflict'),
    possible: v('state-possible'),
    running: v('state-running'),
    idle: v('state-idle'),
  },
  node: {
    code: v('node-code'),
    github: v('node-github'),
    slack: v('node-slack'),
    linear: v('node-linear'),
    core: v('node-core'),
  },
  graph: { link: v('graph-link'), 'link-focus': v('graph-link-focus') },
} as const

type FontSize = [string, { lineHeight: string; letterSpacing?: string }]
const fs = (name: string, tracking?: string): FontSize => [
  v(`fs-${name}`),
  tracking ? { lineHeight: v(`lh-${name}`), letterSpacing: tracking } : { lineHeight: v(`lh-${name}`) },
]

export const fontSize = {
  eyebrow: fs('eyebrow', v('tracking-eyebrow')),
  caption: fs('caption'),
  small: fs('small'),
  body: fs('body'),
  lead: fs('lead'),
  'title-sm': fs('title-sm'),
  title: fs('title', v('tracking-display')),
  'title-lg': fs('title-lg', v('tracking-display')),
  'headline-sm': fs('headline-sm', v('tracking-display')),
  headline: fs('headline', v('tracking-display')),
  hero: fs('hero', v('tracking-display')),
} as const

export const fontFamily = {
  display: [v('font-display')],
  ui: [v('font-ui')],
  mono: [v('font-mono')],
} as const

export const borderRadius = {
  none: '0',
  sm: v('radius-sm'),
  md: v('radius-md'),
  lg: v('radius-lg'),
  full: '9999px',
} as const

export const boxShadow = {
  none: 'none',
  overlay: v('shadow-overlay'),
} as const

export const transitionDuration = {
  1: v('dur-1'),
  2: v('dur-2'),
  3: v('dur-3'),
  4: v('dur-4'),
  5: v('dur-5'),
} as const

export const transitionTimingFunction = {
  standard: v('ease-standard'),
  emphasized: v('ease-emphasized'),
  exit: v('ease-exit'),
} as const

export const maxWidth = {
  content: v('content-max'),
  measure: '68ch',
  prose: '60ch',
} as const

const config = {
  content: ['./app/**/*.{ts,tsx,mdx}', './components/**/*.{ts,tsx}', './content/**/*.mdx', './lib/**/*.{ts,tsx}'],
  theme: {
    colors,
    fontSize,
    fontFamily,
    borderRadius,
    boxShadow,
    extend: {
      transitionDuration,
      transitionTimingFunction,
      maxWidth,
      spacing: {
        rail: v('rail-w'),
        status: v('status-h'),
        guide: v('panel-guide-w'),
        page: v('page-pad'),
        gutter: v('gutter'),
      },
    },
  },
  plugins: [],
}

export default config
