import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  retries: process.env.CI ? 2 : 0,
  workers: 1,
  reporter: process.env.CI
    ? [['github'], ['html', { open: 'never' }]]
    : 'html',
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:8080',
    locale: 'en-US',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'on-first-retry',
  },
  projects: [
    { name: 'setup', testMatch: /.*\.setup\.ts/ },
    {
      name: 'chromium',
      testIgnore: /export-runtime\.spec\.ts/,
      use: {
        ...devices['Desktop Chrome'],
        storageState: 'playwright/.auth/user.json',
        // Enable WebGL via SwiftShader so MapLibre can render in headless mode.
        // Without these flags MapLibre throws webglcontextcreationerror and the
        // demo smoke spec sees no canvas (218-05).
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
