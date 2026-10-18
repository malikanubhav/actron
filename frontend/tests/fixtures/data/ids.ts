// FIXTURE: recorded-style test data for development and tests only; never used in production builds.
export const FIXTURE_IDS = {
  done: 'req_01JCALVA0DONE0000000001',
  live: 'req_01JCALVA0LIVE0000000002',
  stale: 'req_01JCALVA0STALE000000003',
  building: 'req_01JCALVA0BUILD000000004',
  failed: 'req_01JCALVA0FAIL0000000005',
  prReady: 'req_01JCALVA0PRRDY000000006',
  cancelled: 'req_01JCALVA0CANCL000000007',
  answered: 'req_01JCALVA0ANSWR000000008',
  nothing: 'req_01JCALVA0NTHNG000000009',
} as const

export type FixtureKey = keyof typeof FIXTURE_IDS
export type FixtureRequestId = (typeof FIXTURE_IDS)[FixtureKey]
