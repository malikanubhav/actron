'use client'
import { useSyncExternalStore, type ComponentType } from 'react'
import { useQuery } from '@tanstack/react-query'
import { endpoints } from '@/lib/api/endpoints'
import type { ConnectorDefinition } from '@/lib/api/types'
import { qk } from '@/lib/query-keys'
import SlackGuide from '@/content/guides/slack.mdx'
import GithubGuide from '@/content/guides/github.mdx'
import LinearGuide from '@/content/guides/linear.mdx'
import { Dialog } from '../ui/Dialog'
import { GuideContext, guideComponents } from './GuideComponents'
import { guideProgress } from './form-logic'
import { useGuideStore } from './guide-store'

type MdxContent = ComponentType<{ components?: Record<string, unknown> }>

export const GUIDES: Record<string, MdxContent> = {
  slack: SlackGuide as MdxContent,
  github: GithubGuide as MdxContent,
  linear: LinearGuide as MdxContent,
}

export function hasGuide(provider: string): boolean {
  return provider in GUIDES
}

const noSubscribe = () => () => undefined

/** True when the page itself is served over HTTPS (then Slack needs no Socket Mode). */
export function usePageIsHttps(): boolean {
  return useSyncExternalStore(
    noSubscribe,
    () => window.location.protocol === 'https:',
    () => false,
  )
}

export function useGuideChecks(provider: string, enabled = true) {
  return useQuery({
    queryKey: qk.connectorChecks(provider),
    queryFn: () => endpoints.connectorChecks(provider),
    enabled: enabled && hasGuide(provider),
    staleTime: 15_000,
  })
}

/**
 * Setup progress beside a card's guide button: "Setup: 3 of 6 steps done". It is a different fact from the sync
 * state chip. With `onlyWhenRequiredLeft`, it hides once only optional steps (instant updates) remain.
 */
export function GuideProgress({ def, className, onlyWhenRequiredLeft = false }: { def: ConnectorDefinition; className?: string; onlyWhenRequiredLeft?: boolean }) {
  const isHttps = usePageIsHttps()
  const { data } = useGuideChecks(def.provider)
  if (!hasGuide(def.provider) || def.guide.length === 0) return null
  const { done, total, requiredLeft } = guideProgress(def, data?.checks, isHttps)
  if (onlyWhenRequiredLeft && (!data || requiredLeft === 0)) return null
  return (
    <span className={className} data-testid="guide-progress">
      Setup: {done} of {total} steps done
    </span>
  )
}

/** The step-by-step setup guide in a 720 px side panel (spec C, C13). */
export function SetupGuide({ def }: { def: ConnectorDefinition }) {
  const open = useGuideStore((s) => s.open === def.provider)
  const setOpen = useGuideStore((s) => s.setOpen)
  const isHttps = usePageIsHttps()
  const checks = useGuideChecks(def.provider, open)
  const Content = GUIDES[def.provider]
  if (!Content) return null
  const { done, total } = guideProgress(def, checks.data?.checks, isHttps)
  return (
    <Dialog
      open={open}
      onClose={() => setOpen(null)}
      variant="panel"
      label={`Set up ${def.title} · ${done} of ${total} done`}
      title={`Connect your ${def.title.toLowerCase()} step by step`}
    >
      <GuideContext.Provider
        value={{
          def,
          checks: checks.data?.checks,
          isHttps,
          checking: checks.isFetching,
          recheck: () => void checks.refetch(),
          origin: typeof window !== 'undefined' ? window.location.origin : '',
        }}
      >
        <div data-testid={`guide-${def.provider}`} className="flex flex-col">
          <div className="mb-4 h-1 w-full overflow-hidden rounded-full bg-line-2" aria-hidden>
            <div className="h-full bg-state-ok transition-[width] duration-3" style={{ width: `${total ? (done / total) * 100 : 0}%` }} />
          </div>
          <p className="mb-2 text-small text-fg-2">
            Each step checks itself as soon as Actron can confirm it. Paste tokens only into the form on the card.
          </p>
          {checks.isError ? (
            <p role="alert" className="mb-2 text-small text-state-conflict">
              The checks could not run. Try Check again in a moment.
            </p>
          ) : null}
          <Content components={guideComponents} />
        </div>
      </GuideContext.Provider>
    </Dialog>
  )
}
