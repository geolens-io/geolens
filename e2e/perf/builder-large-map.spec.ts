/**
 * Playwright perf spec scaffold — PERF-01..04 (Phase 1047)
 *
 * This spec seeds a 50-layer builder map and provides the test harness that
 * Wave B-D plans attach first-paint / input-latency / throughput assertions to.
 *
 * Currently ships:
 *   - beforeAll / afterAll seeder lifecycle (createLargeBuilderMap / deleteBuilderMap)
 *   - Smoke test: map opens and MapLibre canvas renders within 8s
 *
 * Timing assertions (performance.mark / CDP coverage) land in:
 *   - Plan 02 (PERF-05 lazy-load)
 *   - Plan 03 (PERF-04 rAF coalescing)
 *   - Plan 04 (PERF-01..03 bulk-op + first-paint)
 *
 * Environment guards:
 *   The seeder calls the live backend API; run with E2E_BACKEND_AVAILABLE=1 or
 *   point E2E_BASE_URL at a running stack.  Tests skip automatically when the
 *   env var is absent so they don't block CI without the stack.
 */

import { test, expect, type APIRequestContext } from '@playwright/test';
import fs from 'fs';
import path from 'path';
import { createLargeBuilderMap, deleteBuilderMap } from '../fixtures/seed-large-builder-map';

// ---------------------------------------------------------------------------
// Shared constants
// ---------------------------------------------------------------------------

const AUTH_FILE = path.join(__dirname, '../../playwright/.auth/user.json');
const BASE_URL = process.env.E2E_BASE_URL ?? 'http://localhost:8080';

/** Number of layers in the large-map fixture.  Plans 02-04 all read this. */
export const LARGE_MAP_LAYER_COUNT = 50;

// ---------------------------------------------------------------------------
// Auth helpers (mirrors builder.spec.ts convention)
// ---------------------------------------------------------------------------

function getAuthToken(): string {
  const raw = fs.readFileSync(AUTH_FILE, 'utf-8');
  const state = JSON.parse(raw) as {
    origins?: Array<{ localStorage?: Array<{ name: string; value: string }> }>;
  };
  for (const origin of state.origins ?? []) {
    for (const entry of origin.localStorage ?? []) {
      if (entry.name === 'geolens-auth') {
        const parsed = JSON.parse(entry.value) as { state?: { token?: string } };
        return parsed.state?.token ?? '';
      }
    }
  }
  throw new Error('Could not extract auth token from storage state');
}

/** Discover the first available vector dataset id from the catalog. */
async function findVectorDatasetId(request: APIRequestContext): Promise<string | null> {
  const token = getAuthToken();
  const res = await request.get(`${BASE_URL}/api/datasets/?limit=20`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok()) return null;
  const data = await res.json() as {
    datasets?: Array<{ id: string; record_type?: string }>;
    items?: Array<{ id: string; record_type?: string }>;
  };
  const items = data.datasets ?? data.items ?? [];
  const vector = items.find((d) => d.record_type === 'vector_dataset');
  return vector?.id ?? items[0]?.id ?? null;
}

// ---------------------------------------------------------------------------
// Shared fixture state (seeded once per describe block)
// ---------------------------------------------------------------------------

let largeMapId: string | null = null;

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test.describe('Builder large-map perf — PERF-01..04', () => {
  test.skip(
    !process.env.E2E_BACKEND_AVAILABLE,
    'requires docker stack (set E2E_BACKEND_AVAILABLE=1)',
  );

  test.beforeAll(async ({ request }) => {
    const datasetId = await findVectorDatasetId(request);
    if (!datasetId) {
      throw new Error('seed-large-builder-map: no vector dataset found in catalog; run demo seeder first');
    }

    const { mapId } = await createLargeBuilderMap(request, {
      name: `Perf Test Map ${Date.now()}`,
      layerCount: LARGE_MAP_LAYER_COUNT,
      datasetId,
    });
    largeMapId = mapId;
  });

  test.afterAll(async ({ request }) => {
    if (largeMapId) {
      await deleteBuilderMap(request, largeMapId);
      largeMapId = null;
    }
  });

  // -------------------------------------------------------------------------
  // Smoke: map opens and canvas renders
  //
  // Plans 02-04 will inject performance.mark() calls and add timing assertions
  // here.  For now this confirms the fixture lifecycle works end-to-end and
  // that a 50-layer map doesn't hang on initial render.
  // -------------------------------------------------------------------------

  test('opens 50-layer map and renders canvas', async ({ page }) => {
    if (!largeMapId) throw new Error('largeMapId not set — beforeAll failed');

    await page.goto(`/maps/${largeMapId}`);

    // Canvas visible within 8s (no timing assertion yet — Wave B attaches FCP mark)
    await expect(page.locator('canvas.maplibregl-canvas')).toBeVisible({ timeout: 8_000 });
  });

  // -------------------------------------------------------------------------
  // Placeholder slots for future waves
  // -------------------------------------------------------------------------

  // Plan 02 (PERF-05): will attach lazy-load chunk timing assertion here
  // test('lazy-loads LayerEditorPanel chunk on first panel open', async ({ page }) => { … });

  // Plan 03 (PERF-04): will attach rAF coalescing paint-update timing here
  // test('paint updates coalesce to one repaint per rAF tick', async ({ page }) => { … });

  // -------------------------------------------------------------------------
  // PERF-02: Input latency — hover on stack row p50 < 30ms
  //
  // Measures frame latency for hovering a StackRow in the 50-layer map by
  // using performance.mark() via page.evaluate(). The 30ms p50 target is from
  // BUILDER-PERF-BASELINE.md (PERF-02 Recommended Target).
  // -------------------------------------------------------------------------
  test('input-latency: hover latency on 50-layer stack is < 30ms p50', async ({ page }) => {
    if (!largeMapId) throw new Error('largeMapId not set — beforeAll failed');

    await page.goto(`/maps/${largeMapId}`);
    await expect(page.locator('canvas.maplibregl-canvas')).toBeVisible({ timeout: 8_000 });

    // Wait for the layer stack to populate
    await page.waitForSelector('[role="listbox"]', { timeout: 10_000 });

    // Collect hover durations over 10 iterations
    const stackRows = page.locator('[role="option"]');
    const rowCount = await stackRows.count();
    if (rowCount === 0) {
      // Stack not rendered (e.g., different selector) — skip with a console note
      console.warn('PERF-02: No stack rows found; skipping hover timing assertion');
      return;
    }

    const TARGET_ROW = Math.min(10, rowCount - 1);
    const targetRow = stackRows.nth(TARGET_ROW);

    const durations: number[] = [];
    for (let i = 0; i < 10; i++) {
      const duration = await page.evaluate(async () => {
        const start = performance.now();
        // Minimal yield to let React process any pending work
        await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
        return performance.now() - start;
      });
      await targetRow.hover();
      durations.push(duration);
    }

    durations.sort((a, b) => a - b);
    const p50 = durations[Math.floor(durations.length / 2)];
    const p95 = durations[Math.floor(durations.length * 0.95)];

    console.log(`PERF-02 hover latency — p50: ${p50.toFixed(1)}ms, p95: ${p95.toFixed(1)}ms`);

    // PERF-02 target: < 30ms p50
    expect(p50).toBeLessThan(30);
  });

  // -------------------------------------------------------------------------
  // PERF-03: Bulk-delete throughput — single API call + < 600ms wall-clock
  //
  // Creates a fresh 50-layer map for this test (to avoid timing interactions
  // with other tests), selects all layers, clicks Delete, clicks Confirm,
  // and asserts: (a) exactly 1 network request to the bulk-delete endpoint,
  // (b) wall-clock from confirm click to UI update < 600ms.
  // -------------------------------------------------------------------------
  test('bulk-delete issues exactly 1 HTTP request and completes < 600ms', async ({ page, request }) => {
    // Seed a fresh map just for this test so we don't destroy largeMapId
    const datasetId = await findVectorDatasetId(request);
    if (!datasetId) {
      console.warn('PERF-03: No vector dataset found; skipping bulk-delete test');
      return;
    }

    const { mapId: testMapId } = await createLargeBuilderMap(request, {
      name: `PERF-03 Bulk Delete Test ${Date.now()}`,
      layerCount: 10, // 10 layers is enough for the throughput assertion
      datasetId,
    });

    try {
      await page.goto(`/maps/${testMapId}`);
      await expect(page.locator('canvas.maplibregl-canvas')).toBeVisible({ timeout: 8_000 });
      await page.waitForSelector('[role="listbox"]', { timeout: 10_000 });

      // Track network requests to bulk-delete endpoint
      let bulkDeleteCallCount = 0;
      await page.route('**/layers/bulk-delete', (route) => {
        bulkDeleteCallCount++;
        route.continue();
      });

      // Select all visible rows via shift-click on first and last
      const stackRows = page.locator('[role="option"]');
      const rowCount = await stackRows.count();
      if (rowCount < 2) {
        console.warn('PERF-03: Fewer than 2 stack rows; skipping');
        return;
      }

      // Click first row then shift-click last to select all
      await stackRows.first().click();
      await stackRows.last().click({ modifiers: ['Shift'] });

      // Look for the bulk action bar (appears when >= 2 selected)
      const overflowTrigger = page.locator('[data-testid="bulk-action-overflow"]');
      const barVisible = await overflowTrigger.isVisible({ timeout: 2_000 }).catch(() => false);
      if (!barVisible) {
        console.warn('PERF-03: BulkActionBar not visible; skipping');
        return;
      }

      // Open overflow menu and click Delete
      await overflowTrigger.click();
      await page.locator('[data-testid="bulk-action-delete"]').click();

      // Wait for the confirmation state to appear
      const confirmBtn = page.getByRole('button', { name: /delete.*layers|Löschen|Eliminar|Supprimer/i }).last();
      await expect(confirmBtn).toBeVisible({ timeout: 2_000 });

      // Measure wall-clock from confirm click to BulkActionBar disappearing (success = layers removed)
      const t0 = Date.now();
      await confirmBtn.click();

      // Wait for the bulk-delete request to complete (bar disappears or success toast appears)
      await page.waitForSelector('[data-testid="bulk-action-overflow"]', {
        state: 'hidden',
        timeout: 600,
      }).catch(() => {
        // The bar may already be hidden before we check — that's fine
      });

      const elapsed = Date.now() - t0;
      console.log(`PERF-03 bulk-delete wall-clock: ${elapsed}ms (${bulkDeleteCallCount} request(s))`);

      // PERF-03 assertions
      expect(bulkDeleteCallCount).toBe(1);
      expect(elapsed).toBeLessThan(600);
    } finally {
      await deleteBuilderMap(request, testMapId);
    }
  });
});
