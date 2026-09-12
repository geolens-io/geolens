import { defineConfig, devices } from '@playwright/test';

const configuredBaseURL = process.env.E2E_DEMO_BASE_URL;

if (!configuredBaseURL) {
  throw new Error(
    'E2E_DEMO_BASE_URL is required. Example: E2E_DEMO_BASE_URL=https://demo.getgeolens.com npm run e2e:smoke:demo',
  );
}

const demoBaseURL = new URL(configuredBaseURL);
if (!['http:', 'https:'].includes(demoBaseURL.protocol)) {
  throw new Error('E2E_DEMO_BASE_URL must use http:// or https://');
}
if (demoBaseURL.username || demoBaseURL.password) {
  throw new Error('E2E_DEMO_BASE_URL must not contain credentials');
}
if (demoBaseURL.pathname !== '/' || demoBaseURL.search || demoBaseURL.hash) {
  throw new Error('E2E_DEMO_BASE_URL must be an origin without a path, query, or fragment');
}

export default defineConfig({
  testDir: './e2e',
  testMatch: 'demo-smoke.spec.ts',
  timeout: 90_000,
  expect: { timeout: 30_000 },
  fullyParallel: false,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  outputDir: 'test-results/demo',
  reporter: process.env.CI
    ? [
        ['github'],
        ['html', { outputFolder: 'playwright-report/demo', open: 'never' }],
      ]
    : [
        ['list'],
        ['html', { outputFolder: 'playwright-report/demo', open: 'never' }],
      ],
  use: {
    baseURL: demoBaseURL.origin,
    locale: 'en-US',
    storageState: { cookies: [], origins: [] },
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  projects: [
    {
      name: 'demo-chromium',
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
    },
  ],
});
