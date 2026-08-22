/**
 * feat(#846): vector-tile pipeline regression spec.
 *
 * Why this exists: nothing else in the suite asserts that MVT tiles are ever
 * actually requested. Every other map spec checks DOM/canvas presence, which a
 * map with a dead tile worker satisfies perfectly — the canvas mounts, the
 * basemap raster renders, and no error is thrown. The full suite was verified
 * green against exactly that condition.
 *
 * The failure this catches (upstream maplibre-gl-js#8186): when maplibre's web
 * worker fails to resolve, vector sources go completely silent — zero tile
 * requests, no console message, no exception. Raster and GeoJSON sources keep
 * rendering, so the map still looks broadly alive. The only observable signal
 * is the absence of `.pbf` traffic, which is what this spec asserts.
 */
import { test, expect } from '@playwright/test';
import fs from 'fs';
import path from 'path';

const AUTH_FILE = path.join(__dirname, '../playwright/.auth/user.json');
const BASE_URL = process.env.E2E_BASE_URL ?? 'http://localhost:8080';

function getAuthToken(): string {
  const state = JSON.parse(fs.readFileSync(AUTH_FILE, 'utf-8'));
  for (const origin of state.origins ?? []) {
    for (const entry of origin.localStorage ?? []) {
      if (entry.name === 'geolens-auth') {
        return JSON.parse(entry.value).state?.token ?? '';
      }
    }
  }
  throw new Error('Could not extract auth token from storage state');
}

let datasetId: string;

test.describe('Vector tile pipeline', () => {
  test.beforeAll(async () => {
    // limit=100, not 10: the sort below is client-side, so a small page can hand
    // back a 1-feature upload artifact that fits in a single tile and makes the
    // "> 0 requests" assertion far weaker than it looks.
    const res = await fetch(`${BASE_URL}/api/datasets/?limit=100`, {
      headers: { Authorization: `Bearer ${getAuthToken()}` },
    });
    expect(res.ok).toBe(true);
    const data = await res.json();
    const datasets = data.datasets ?? data.items ?? data;
    const vector = datasets
      .filter((ds: { record_type?: string }) => ds.record_type === 'vector_dataset')
      .sort(
        (a: { feature_count?: number }, b: { feature_count?: number }) =>
          (b.feature_count ?? 0) - (a.feature_count ?? 0),
      );
    expect(vector[0]).toBeTruthy();
    datasetId = vector[0].id;
    // Surfaced deliberately: if this ever drops to a trivial number the spec is
    // still green but has stopped being a meaningful canary.
    console.log(`[vector-tile-pipeline] fixture: ${datasetId} (${vector[0].feature_count} features)`);
  });

  test('MVT tiles are requested and served for a vector dataset', async ({ page }) => {
    const mvt: { url: string; status: number }[] = [];
    const raster: number[] = [];

    page.on('response', (r) => {
      const url = r.url();
      if (url.includes('.pbf')) mvt.push({ url, status: r.status() });
      else if (url.includes('/raster-tiles/')) raster.push(r.status());
    });

    await page.goto(`/datasets/${datasetId}`);
    await page.waitForURL(new RegExp(`/datasets/${datasetId}$`));
    // The map fits to the dataset's bounds on load, so tiles for the data's own
    // extent are requested without needing an explicit zoom-to-layer.
    await expect(page.locator('canvas.maplibregl-canvas')).toBeVisible({ timeout: 20_000 });
    await page.waitForLoadState('networkidle');

    // THE assertion. Zero here is the #8186 silent-worker signature.
    expect(
      mvt.length,
      'no .pbf requests were made — the maplibre worker is not resolving vector sources',
    ).toBeGreaterThan(0);

    // A 204 is a legitimately empty tile; anything else is a real failure.
    const bad = mvt.filter((t) => t.status !== 200 && t.status !== 204);
    expect(bad, `non-OK tile responses: ${JSON.stringify(bad.slice(0, 5))}`).toHaveLength(0);
  });

  test('the tile worker survives a style swap (basemap change)', async ({ page }) => {
    // Regression guard for the worker being torn down or orphaned when the
    // style is replaced — setStyle() rebuilds Style, which re-reads the
    // missing-image resolver and re-attaches sources to the worker pool.
    await page.goto(`/datasets/${datasetId}`);
    await expect(page.locator('canvas.maplibregl-canvas')).toBeVisible({ timeout: 20_000 });
    await page.waitForLoadState('networkidle');

    const afterSwap: number[] = [];
    page.on('response', (r) => {
      if (r.url().includes('.pbf')) afterSwap.push(r.status());
    });

    const toggle = page.getByRole('button', { name: 'Change basemap' });
    if (!(await toggle.isVisible().catch(() => false))) {
      test.skip(true, 'no basemap toggle on this surface');
    }
    await toggle.click();
    // The options are plain buttons inside the picker's group, NOT option/
    // menuitem roles. Scope to the group and let a selector miss FAIL here —
    // swallowing it would report "no tiles after swap" for a swap that never
    // happened, i.e. a test bug wearing a product bug's error message.
    const options = page.getByRole('group', { name: 'Change basemap' }).getByRole('button');
    await expect(options.first()).toBeVisible({ timeout: 5000 });
    const count = await options.count();
    expect(count, 'basemap picker exposed no options').toBeGreaterThan(1);
    // nth(1) is a different basemap than the default-active nth(0), so setStyle
    // genuinely runs.
    await options.nth(1).click();
    await page.waitForTimeout(5000);

    expect(
      afterSwap.length,
      'no .pbf requests after a style swap — worker orphaned by setStyle()',
    ).toBeGreaterThan(0);
  });
});
