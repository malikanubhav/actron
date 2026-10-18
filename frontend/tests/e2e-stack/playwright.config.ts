import { defineConfig, devices } from '@playwright/test'

/**
 * Full-stack e2e (PROMPT 9.6): the production frontend build (.next-e2e) on :3300, the real backend and worker on
 * :18080 against fake Slack, GitHub and Linear, the fake Pi image, and real FalkorDB, PostgreSQL, Redis and
 * Temporal. `scripts/e2e_stack.sh run` starts everything from an empty e2e world; an already running stack
 * (`scripts/e2e_stack.sh start`) is reused. Spec files run in name order in one worker: 01 connects the sources
 * that the later files use.
 */
const baseURL = process.env.E2E_STACK_URL ?? 'http://127.0.0.1:3300'

export default defineConfig({
  testDir: '.',
  testMatch: /\d\d-.*\.spec\.ts/,
  timeout: 120_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  outputDir: '../../test-results/e2e-stack',
  reporter: [['list'], ['json', { outputFile: '../../test-results/e2e-stack.json' }]],
  use: {
    baseURL,
    viewport: { width: 1440, height: 900 },
    colorScheme: 'dark',
    trace: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } } }],
  webServer: {
    command: 'bash ../scripts/e2e_stack.sh run',
    cwd: '../..',
    url: `${baseURL}/app/signin`,
    reuseExistingServer: true,
    timeout: 600_000,
    stdout: 'pipe',
    stderr: 'pipe',
  },
})
