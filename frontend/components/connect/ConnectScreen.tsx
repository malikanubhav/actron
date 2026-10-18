'use client'
import { useSearchParams } from 'next/navigation'
import { useConnections, useConnectors, useGraphStats, useIngestion, useRequests } from '@/lib/hooks/queries'
import { OnboardingChecklist, onboardingSteps } from '../core/OnboardingChecklist'
import { reasonText } from '@/lib/api'
import { ScreenHeader } from '../core/ScreenHeader'
import { PageFrame, Grid12 } from '../shell/PageFrame'
import { ErrorState } from '../states/States'
import { SkeletonColumn, SkeletonHeader } from '../states/Skeleton'
import { Button } from '../ui/Button'
import { SourceCard } from './SourceCard'
import { SetupGuide } from './SetupGuide'
import { MemoryPanel } from './MemoryPanel'
import { connectHeadline, connectionFor, connectionRows, memoryExplainer, SOURCE_ORDER } from './form-logic'
import type { OAuthReturn } from './ConnectorForm'

export const CONNECT_PURPOSE = 'Each source you connect is read into one graph. Linking runs as data arrives.'

/** Connect and memory (PROMPT 8.8 B): sources on the left, the memory graph filling on the right. */
export function ConnectScreen() {
  const params = useSearchParams()
  const connectors = useConnectors()
  const connections = useConnections()
  const ingestion = useIngestion()
  const stats = useGraphStats()

  const oauthReturn: OAuthReturn | null =
    params?.get('oauth') === 'slack' ? { status: params.get('status') ?? 'ok', team: params.get('team') } : null

  const list = connections.data?.connections ?? []
  const defs = [...(connectors.data?.providers ?? [])].sort(
    (a, b) => SOURCE_ORDER.indexOf(a.provider as (typeof SOURCE_ORDER)[number]) - SOURCE_ORDER.indexOf(b.provider as (typeof SOURCE_ORDER)[number]),
  )
  const loading = connectors.isLoading || connections.isLoading
  const headline = loading ? 'Reading your sources.' : connectHeadline(list, ingestion.data)
  const requests = useRequests(undefined, 1)
  const explainer = memoryExplainer(ingestion.data)
  const steps = onboardingSteps(list, (requests.data?.requests.length ?? 0) > 0)

  return (
    <PageFrame>
      <ScreenHeader
        eyebrow="Connect"
        headline={headline}
        purpose={
          explainer ? (
            <>
              {CONNECT_PURPOSE} <span data-testid="memory-explainer">{explainer}</span>
            </>
          ) : (
            CONNECT_PURPOSE
          )
        }
      />
      {/* Once a repository is in, the checklist shrinks to one line so the memory graph stays above the fold. */}
      {connections.isSuccess && steps.some((s) => !s.done) ? <OnboardingChecklist steps={steps} compact={steps[0]?.done === true} /> : null}
      <Grid12>
        <section className="col-span-5 flex flex-col gap-8" aria-label="Sources">
          {connectors.isError || connections.isError ? (
            <ErrorState
              title="The sources could not be loaded."
              body={reasonText(connectors.error ?? connections.error)}
              action={
                <Button
                  onClick={() => {
                    void connectors.refetch()
                    void connections.refetch()
                  }}
                >
                  Try again
                </Button>
              }
            />
          ) : loading ? (
            <>
              <SkeletonHeader />
              <SkeletonColumn items={4} />
            </>
          ) : (
            defs.map((def) => (
              <SourceCard
                key={def.provider}
                def={def}
                connection={connectionFor(def.provider, list)}
                rows={connectionRows(def.provider, list)}
                oauthReturn={def.provider === 'slack' ? oauthReturn : null}
              />
            ))
          )}
        </section>
        <section className="col-span-7" aria-label="Memory">
          <MemoryPanel
            stats={stats.data}
            ingestion={ingestion.data}
            loading={stats.isLoading}
            hasConnections={list.some((c) => c.sync.state !== 'NOT CONNECTED' && c.status !== 'disconnected')}
          />
        </section>
      </Grid12>
      {defs.map((def) => (
        <SetupGuide key={def.provider} def={def} />
      ))}
    </PageFrame>
  )
}
