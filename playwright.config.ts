import { execSync } from 'node:child_process';
import { defineConfig, devices } from '@playwright/test';

// fix(#1480): a worktree e2e run silently tests `main`.
//
// The dev stack bind-mounts the MAIN checkout (`./frontend` -> /app, and
// `backend/app` -> /app/app with --reload), so localhost:8080 serves main's
// code no matter which branch this worktree is on. That yields false failures
// when your fix is absent from the stack, and — worse, because nothing
// distinguishes it from a real pass — false passes when your break is.
//
// Only the shared-stack case is guarded. Pointing E2E_BASE_URL at your own
// stack is already correct and is left alone, which doubles as the escape
// hatch. E2E_ALLOW_WORKTREE=1 overrides for setups this cannot foresee.
function assertWorktreeMatchesStack(): void {
  if (process.env.E2E_ALLOW_WORKTREE) return;
  const base = process.env.E2E_BASE_URL ?? 'http://localhost:8080';
  if (!/\/\/(localhost|127\.0\.0\.1):8080(\/|$)/.test(base)) return;

  const git = (args: string): string => {
    try {
      return execSync(`git ${args}`, {
        encoding: 'utf8',
        stdio: ['ignore', 'pipe', 'ignore'],
      }).trim();
    } catch {
      return '';
    }
  };

  // Equal in the main checkout; in a linked worktree git-dir is
  // <common>/worktrees/<name>. Cheaper than parsing `git worktree list`.
  const gitDir = git('rev-parse --absolute-git-dir');
  const commonDir = git('rev-parse --path-format=absolute --git-common-dir');
  if (!gitDir || !commonDir || gitDir === commonDir) return;

  const mergeBase = git('merge-base HEAD main') || git('merge-base HEAD origin/main');
  const changed = [
    ...(mergeBase ? git(`diff --name-only ${mergeBase}`).split('\n') : []),
    // Uncommitted changes count: they are equally absent from the stack.
    ...git('status --porcelain').split('\n').map((l) => l.slice(3)),
  ].filter(Boolean);

  // Only paths the stack actually serves to the browser can invalidate a run.
  // backend/tests and scripts are bind-mounted too but cannot affect one, and
  // docs / .github / e2e-spec-only branches are safe against the shared stack.
  const SERVED = ['frontend/', 'backend/app/', 'backend/alembic/'];
  const offending = [...new Set(changed.filter((p) => SERVED.some((s) => p.startsWith(s))))];
  if (offending.length === 0) return;

  throw new Error(
    `e2e from this worktree would test \`main\`, not your changes.\n\n` +
      `The dev stack bind-mounts the MAIN checkout, so ${base} serves main's code\n` +
      `regardless of this worktree's branch. These changed paths are served by the\n` +
      `stack and are NOT in it:\n\n` +
      offending.map((p) => `  ${p}`).join('\n') +
      `\n\nRun against a stack built from THIS worktree instead:\n` +
      `  cd frontend && API_PROXY_TARGET=http://localhost:8001 npm run dev -- --port 5174\n` +
      `  E2E_BASE_URL=http://localhost:5174 npx playwright test\n\n` +
      `Spec-only changes (e2e/**) are safe against the shared stack and are not blocked.\n` +
      `Set E2E_ALLOW_WORKTREE=1 to override.`,
  );
}

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
