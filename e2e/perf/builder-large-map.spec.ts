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

  // Plan 04 (PERF-01): will attach first-paint / FCP timing assertion here
  // test('first-paint completes within PERF-01 target (< 2500ms)', async ({ page }) => { … });

  // Plan 04 (PERF-02): will attach hover input-latency assertion here
  // test('hover latency on 50-layer stack is under 16ms', async ({ page }) => { … });

  // Plan 04 (PERF-03): will attach bulk-delete batching timing here
  // test('bulk-delete 50 layers via single API call completes in < 3s', async ({ page }) => { … });
});
