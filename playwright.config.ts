import { defineConfig, devices } from '@playwright/test';
import { assertWorktreeMatchesStack } from './playwright.worktree-guard';

assertWorktreeMatchesStack();

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  retries: process.env.CI ? 2 : 0,
  workers: 1,
  // fix(#896): the json reporter feeds the nightly failure report, which
  // names the failing SPECS in the tracking issue instead of only saying
  // "e2e-test: failure" — a deterministic six-day-old spec break and a
  // one-off flake used to be indistinguishable without downloading traces.
  reporter: process.env.CI
    ? [
        ['github'],
        ['html', { open: 'never' }],
        ['json', { outputFile: 'playwright-summary.json' }],
      ]
    : 'html',
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:8080',
    locale: 'en-US',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'on-first-retry',
  },
  projects: [
    {
      name: 'setup',
      testMatch: /.*\.setup\.ts/,
      teardown: 'cleanup',
    },
    {
      name: 'cleanup',
      testMatch: /.*\.teardown\.ts/,
    },
    {
      name: 'chromium',
      testIgnore: /export-runtime\.spec\.ts/,
      use: {
        ...devices['Desktop Chrome'],
        storageState: 'playwright/.auth/user.json',
        // Enable WebGL via SwiftShader so MapLibre can render in headless mode.
        // Without these flags MapLibre throws webglcontextcreationerror and the
        // showcase smoke spec sees no canvas (218-05).
        launchOptions: {
          args: [
            '--enable-unsafe-swiftshader',
            '--use-gl=swiftshader',
            '--enable-webgl',
            '--ignore-gpu-blocklist',
          ],
        },
      },
      dependencies: ['setup'],
    },
    {
      name: 'api',
      testMatch: /export-runtime\.spec\.ts/,
      use: {
        baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:8080',
        trace: 'off',
        screenshot: 'off',
        video: 'off',
      },
    },
  ],
});
