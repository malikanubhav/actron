import type { MDXComponents } from 'mdx/types'
import { guideComponents } from '@/components/connect/GuideComponents'

/** Required by @next/mdx in the App Router. The setup guides (content/guides/*.mdx) use these components. */
export function useMDXComponents(components: MDXComponents): MDXComponents {
  return { ...(guideComponents as MDXComponents), ...components }
}
