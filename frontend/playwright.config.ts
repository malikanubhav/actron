import { defineConfig, devices } from '@playwright/test'

/**
 * E2E against `next start` on a fixture build (NEXT_PUBLIC_ACTRON_DEV_FIXTURES=1, MSW). Build it first with
 * `npm run build:fixtures`. Set E2E_BASE_URL to run the same specs against a real stack.
 */
const port = Number(process.env.E2E_PORT ?? 3100)
const baseURL = process.env.E2E_BASE_URL ?? `http://127.0.0.1:${port}`

export default defineConfig({
  testDir: './tests/e2e',
  timeout: 45_000,
  expect: { timeout: 10_000 },
  fullyParallel: true,
  workers: process.env.CI ? 2 : 4,
  retries: 0,
  reporter: [['list'], ['json', { outputFile: 'test-results/e2e.json' }]],
  use: {
    baseURL,
    viewport: { width: 1440, height: 900 },
    colorScheme: 'dark',
    trace: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } } }],
  webServer: process.env.E2E_BASE_URL
    ? undefined
    : {
        command: `node scripts/prepare-msw.mjs && npx next start --port ${port}`,
        url: baseURL,
        reuseExistingServer: true,
        timeout: 120_000,
        env: { NEXT_DIST_DIR: '.next-fixtures', NEXT_PUBLIC_ACTRON_DEV_FIXTURES: '1' },
      },
})
