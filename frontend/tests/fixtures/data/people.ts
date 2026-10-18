// FIXTURE: recorded-style test data for development and tests only; never used in production builds.
// Fictional people working on the real Calva repository (BetterThanTomorrow/calva).
import type { PersonRef } from '@/lib/api/types'

export const PEOPLE = {
  dana: { personId: 'actron:person:dana-ilic', userId: 'usr_fixture_dana', name: 'Dana Ilić', avatarUrl: null },
  sam: { personId: 'actron:person:sam-okoro', userId: 'usr_fixture_sam', name: 'Sam Okoro', avatarUrl: null },
  priya: { personId: 'actron:person:priya-raman', userId: 'usr_fixture_priya', name: 'Priya Raman', avatarUrl: null },
  mateo: { personId: 'actron:person:mateo-ruiz', userId: 'usr_fixture_mateo', name: 'Mateo Ruiz', avatarUrl: null },
} satisfies Record<string, PersonRef>

export type PersonKey = keyof typeof PEOPLE

export const ME = {
  user: { ...PEOPLE.dana, email: 'dana.ilic@example.test', slackUserId: 'U0FIXDANA' },
  workspace: { id: 'dev', name: 'Calva team (fixture)', role: 'owner' },
  csrfToken: 'fixture-csrf-token-3b1f9c',
  env: 'dev' as const,
  devFixtures: true,
}
