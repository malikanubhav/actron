import type { Metadata } from 'next'
import { ActronMark } from '@/components/brand/ActronLogo'
import { SlackSignIn } from './SlackSignIn'
import { DevLogin } from './DevLogin'
import { DEV_FIXTURES } from '@/lib/env'

export const metadata: Metadata = {
  title: 'Sign in',
  description: 'Sign in to Actron with Slack to see what your team already decided.',
}

function safeNext(value: string | undefined): string {
  if (!value || !value.startsWith('/app') || value.startsWith('//')) return '/app'
  return value
}

/** PROMPT 8.8 A. The dev login exists only when ACTRON_ENV is not prod (the backend route is absent in prod too). */
export default async function SignInPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const params = await searchParams
  const next = safeNext(typeof params.next === 'string' ? params.next : undefined)
  const error = params.error === 'slack'
  const devMode = DEV_FIXTURES || (process.env.ACTRON_ENV ?? 'dev') !== 'prod'
  return (
    <main id="main" className="flex min-h-dvh items-center bg-ink-0 px-6">
      <div className="mx-auto flex w-full max-w-xl flex-col gap-6 py-24">
        <ActronMark size={44} drawOnce className="text-fg-1" />
        <p className="eyebrow">Sign in</p>
        <h1 className="display text-headline-sm text-fg-1">Sign in to see what your team already decided.</h1>
        <p className="max-w-measure text-lead text-fg-2">
          Actron reads your code, PRs, tickets and Slack, and checks them before an AI writes code.
        </p>
        {error ? (
          <p role="alert" className="rounded-md border border-state-conflict/50 px-4 py-3 text-small text-fg-1">
            Slack did not complete the sign-in. Try again.
          </p>
        ) : null}
        <div className="flex flex-wrap items-center gap-3 pt-2">
          <SlackSignIn next={next} />
          {devMode ? <DevLogin next={next} /> : null}
        </div>
        <p className="text-caption text-fg-3">
          The first person from a Slack workspace creates the Actron workspace and becomes its owner. Others join as members.
        </p>
      </div>
    </main>
  )
}
