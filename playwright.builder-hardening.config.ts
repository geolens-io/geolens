import { defineConfig, devices } from '@playwright/test';
import { assertWorktreeMatchesStack } from './playwright.worktree-guard';

// fix(#1480): every config must call this, not just playwright.config.ts —
// this one is selected with `-c` by `npm run e2e:smoke:builder-hardening`.
assertWorktreeMatchesStack();

export default defineConfig({
  testDir: './e2e',
  testMatch: /builder-hardening\.spec\.ts/,
  timeout: 75_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  retries: 0,
  workers: 1,
  reporter: 'html',
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:8080',
    locale: 'en-US',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'off',
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
      name: 'chromium-hardening',
      use: {
        ...devices['Desktop Chrome'],
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
    // fix(#1778): this config set no colorScheme, so the whole suite ran
    // light-mode only (the same gap #1782 closed for playwright.config.ts).
    // One dark chromium project closes it here too, without tripling
    // wall-clock by adding a dark pass to firefox-hardening and
    // webkit-hardening as well -- those exist for cross-browser rendering
    // parity, not theme parity.
    {
      name: 'chromium-hardening-dark',
      use: {
        ...devices['Desktop Chrome'],
        colorScheme: 'dark',
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
      name: 'firefox-hardening',
      use: {
        ...devices['Desktop Firefox'],
      },
      dependencies: ['setup'],
    },
    {
      name: 'webkit-hardening',
      use: {
        ...devices['Desktop Safari'],
      },
      dependencies: ['setup'],
    },
  ],
});
