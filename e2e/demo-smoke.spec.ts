/**
 * e2e/demo-smoke.spec.ts — themed-demo smoke test (Plan 218-05).
 *
 * For each of the 9 signature demo maps:
 *   1. Discover the map ID by name via GET /api/maps/?limit=50 in beforeAll
 *      (resilient to UUID instability across re-seeds).
 *   2. Navigate to /maps/{id} using the authenticated storage state.
 *   3. Wait for the map canvas + tiles to settle.
 *   4. Assert no console errors (filtering known noise).
 *   5. Assert no tile request returned 4xx/5xx.
 *
 * The suite is gated by E2E_DEMO_SEEDED=1 so it self-skips when running
 * against a non-demo environment (e.g. plain dev or CI without the seeder).
 *
 * Required maps fail the test if missing. Optional maps (Theme 1 raster
 * stories that may not be in every snapshot) are skipped gracefully.
 */

import { test, expect, type Page } from '@playwright/test';

const DEMO_MAP_NAMES = [
  // Theme 1 — Planet Earth
  'Earth as Seen from Space',
  'Global Bathymetry',
  // Theme 2 — Global Development & People
  'Population at a Glance',
  'GDP per Capita PPP 2023',
  // Theme 3 — Borders, Boundaries & Contested Space
  "The World's Disputed Places",
  'One Territory, Multiple Official Maps',
  'Conflict Events 2024 (UCDP GED)',
  'Refugees by Country of Origin 2023',
];

// Optional maps from Phase 218's "stretch slot" — not shipped yet, the
// spec hosts them as test.skip() so future additions don't require spec
// changes.
const OPTIONAL_DEMO_MAPS = [
  'Where the Ice Is',
  'Life Expectancy & Income',
];

// Console messages to ignore (browser noise that has nothing to do with us).
const CONSOLE_NOISE_PATTERNS = [
  /ResizeObserver loop/i,
  /favicon/i,
  /Failed to load resource:.*sprite/i,  // basemap sprite atlas misses
  /circle-11/i,                          // dark-matter basemap sprite
  /styleimagemissing/i,
  /React DevTools/i,
];

const isConsoleNoise = (text: string) =>
  CONSOLE_NOISE_PATTERNS.some((re) => re.test(text));

// Map name → live UUID, populated in beforeAll.
const mapIdByName: Record<string, string> = {};

const isDemoSeeded = process.env.E2E_DEMO_SEEDED === '1';

test.describe('themed-demo smoke', () => {
  test.skip(
    !isDemoSeeded,
    'Demo data not seeded — set E2E_DEMO_SEEDED=1 to enable',
  );

  test.beforeAll(async ({ request }) => {
    // Discover all demo maps by name. We use the unauthenticated public
    // listing first since the demo maps are public.
    const resp = await request.get('/api/maps/?limit=100');
    expect(
      resp.ok(),
      `/api/maps/ returned HTTP ${resp.status()} — API is not reachable or the list endpoint is broken`,
    ).toBeTruthy();
    const body = await resp.json();
    const items: Array<{ id: string; name: string }> =
      body.maps || body.items || body.results || [];

    for (const item of items) {
      mapIdByName[item.name] = item.id;
    }

    expect(
      Object.keys(mapIdByName).length,
      `No demo maps parsed from /api/maps/ (HTTP ${resp.status()}, ${items.length} items in body). ` +
        'Either the seeder has not run OR the response shape has changed (expected items[] with {id,name}).',
    ).toBeGreaterThan(0);
  });

  for (const name of DEMO_MAP_NAMES) {
    test(`required map renders: ${name}`, async ({ page }) => {
      const id = mapIdByName[name];
      expect(
        id,
        `Map "${name}" not found in /api/maps/ — seeder may have failed`,
      ).toBeTruthy();
      // Narrow id for TS: after the expect above, TS still infers string|undefined.
      // Assert explicitly so subsequent uses of `id` are typed string.
      if (!id) throw new Error(`unreachable: id for ${name} is undefined`);

      const consoleErrors: string[] = [];
      const failedRequests: Array<{ url: string; status: number }> = [];

      page.on('console', (msg) => {
        if (msg.type() === 'error' && !isConsoleNoise(msg.text())) {
          consoleErrors.push(msg.text());
        }
      });
      page.on('response', (resp) => {
        const url = resp.url();
        // Track only tile requests (.pbf, .png, .jpg under /api/tiles or titiler)
        if (
          /\/api\/tiles\/|\.pbf(\?|$)|titiler/.test(url) &&
          resp.status() >= 400
        ) {
          failedRequests.push({ url, status: resp.status() });
        }
      });

      await page.goto(`/maps/${id}`);

      // Wait for the map container to render
      await expect(page.locator('.maplibregl-canvas').first()).toBeVisible({
        timeout: 30_000,
      });

      // ViewerMap.tsx flips `data-tiles-loaded="true"` on the outer div when
      // the first `idle` event fires (no tiles loading, no transitions, no
      // animations). This replaces the previous arbitrary 2 s wait-after-
      // networkidle fallback — deterministic signal, saves ~16 s per run.
      await page
        .locator('[data-tiles-loaded]')
        .first()
        .waitFor({ state: 'attached', timeout: 30_000 });
      await expect
        .poll(
          async () =>
            page
              .locator('[data-tiles-loaded]')
              .first()
              .getAttribute('data-tiles-loaded'),
          {
            message: `Map ${name} never reached idle state within 30 s`,
            timeout: 30_000,
          },
        )
        .toBe('true');

      expect(
        consoleErrors,
        `Console errors on ${name}:\n${consoleErrors.join('\n')}`,
      ).toEqual([]);

      expect(
        failedRequests,
        `Failed tile requests on ${name}:\n${failedRequests
          .map((r) => `  ${r.status} ${r.url}`)
          .join('\n')}`,
      ).toEqual([]);
    });
  }

  for (const name of OPTIONAL_DEMO_MAPS) {
    test(`optional map renders: ${name}`, async ({ page }) => {
      const id = mapIdByName[name];
      test.skip(
        !id,
        `Optional map "${name}" not present in this snapshot — skipping`,
      );

      await page.goto(`/maps/${id}`);
      await expect(page.locator('.maplibregl-canvas').first()).toBeVisible({
        timeout: 30_000,
      });
    });
  }
});
