/**
 * Build-time flags. NEXT_PUBLIC_* values are inlined by Next.js, so code behind `DEV_FIXTURES` is removed from
 * production bundles when the flag is off.
 */
export const DEV_FIXTURES = process.env.NEXT_PUBLIC_ACTRON_DEV_FIXTURES === '1'

/** Server-only: where server components reach the backend directly. */
export function apiInternalUrl(): string {
  return (process.env.API_INTERNAL_URL ?? 'http://127.0.0.1:8080').replace(/\/$/, '')
}

export const SITE_URL = (process.env.NEXT_PUBLIC_SITE_URL ?? process.env.ACTRON_PUBLIC_URL ?? 'http://localhost:3000').replace(/\/$/, '')

export const REPOSITORY_URL = 'https://github.com/vikram/actron'
