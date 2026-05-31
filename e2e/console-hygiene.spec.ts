/**
 * MAPS-01 regression spec (#122):
 *
 * Asserts zero `createRoot() on a container that has already been passed to
 * createRoot()` React warnings under an HMR-like re-execution of main.tsx.
 *
 * Why forced re-import?
 *   A cold page load already produces 0 warnings (the bug fires only when
 *   main.tsx is re-evaluated, which Vite HMR does on every file-edit). This
 *   spec simulates that by dynamically importing `/src/main.tsx` with a
 *   cache-busting query string AFTER the initial load — causing the module to
 *   re-execute its `bootstrap()` → `createRoot()` call on an already-rooted
 *   container. Without the Plan-01 `__glRoot` guard that call would produce
 *   >= 1 warning; WITH the guard it reuses the existing root → 0 warnings.
 */
import { test, expect } from '@playwright/test';

test('MAPS-01: no duplicate createRoot warning under HMR-like re-exec', async ({
  page,
}) => {
  // Collect console errors and warnings emitted AFTER initial navigation.
  // The listener is attached before the forced re-exec so any re-root warning
  // is captured.
  const consoleMessages: string[] = [];

  // Navigate to the home/search route (main.tsx is the single shared entry,
  // so the regression surface is app-wide — '/' is the canonical target).
  await page.goto('/');
  await page.waitForLoadState('networkidle');

  // This regression only reproduces under the Vite dev server, which serves raw
  // TS source at `/src/main.tsx` and HMR-re-execs the entry. A production static
  // build (nginx + dist/) has no such path, so the forced import would 404 and
  // throw an unrelated error — skip cleanly there instead.
  const isViteDevServer = await page.evaluate(
    () => document.querySelector('script[src*="/@vite/client"]') !== null,
  );
  test.skip(!isViteDevServer, 'MAPS-01 HMR re-exec test requires the Vite dev server');

  // Attach the collector AFTER initial load (cold load is already clean).
  // We only care about messages produced by the HMR-like re-exec below.
  page.on('console', (msg) => {
    if (msg.type() === 'error' || msg.type() === 'warning') {
      consoleMessages.push(msg.text());
    }
  });

  // Force an HMR-like re-execution of the entry module.
  // Vite serves source over HTTP in dev; the cache-busting query forces a
  // fresh module evaluation, re-running bootstrap() → createRoot() path.
  await page.evaluate(() => import('/src/main.tsx?t=' + Date.now()));

  // createRoot()'s warning fires synchronously inside the awaited import above;
  // this short buffer only covers CDP console-event delivery to the test process.
  await page.waitForTimeout(100);

  // Assert 0 duplicate-createRoot warnings across errors and warnings.
  const dupRootWarnings = consoleMessages.filter((m) =>
    /createRoot\(\) on a container that has already been passed/.test(m),
  );

  expect(dupRootWarnings, dupRootWarnings.join('\n')).toHaveLength(0);
});
