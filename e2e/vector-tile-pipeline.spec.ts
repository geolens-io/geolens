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
let tableName: string;

/**
 * fix(#1624): match ONLY this dataset's own tiles.
 *
 * A bare `.pbf` test is worthless here: on the default OpenFreeMap basemap,
 * 27 of the 35 `.pbf` responses on this page are third party (19 glyph ranges
 * under /fonts/, 8 basemap planet tiles). A `> 0` assertion over all of them
 * passes with the dataset's own tile pipeline completely dead, which is the
 * exact failure this spec exists to catch.
 *
 * Covers both the plain and clustered routes:
 *   /tiles/data.<table>/{z}/{x}/{y}.pbf
 *   /tiles/clusters/data.<table>/{z}/{x}/{y}.pbf
 *
 * Matched by ROUTE, not by origin: buildSignedTileUrl()/buildClusterTileUrl()
 * use TILE_BASE_URL or the server-provided cdn_base_url when configured, so a
 * healthy deployment can legitimately serve these from https://cdn.example/.
 * `data.<table>/` is specific enough on its own; no third-party basemap URL
 * contains it.
 */
const isDatasetTile = (url: string): boolean =>
  url.includes('/tiles/') && url.includes(`data.${tableName}/`) && url.includes('.pbf');

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
    tableName = vector[0].table_name;
    expect(tableName, 'dataset exposes no table_name to scope tile URLs by').toBeTruthy();
    // Surfaced deliberately: if this ever drops to a trivial number the spec is
    // still green but has stopped being a meaningful canary.
    console.log(
      `[vector-tile-pipeline] fixture: ${datasetId} / ${tableName} (${vector[0].feature_count} features)`,
    );
  });

  test('MVT tiles are requested and served for a vector dataset', async ({ page }) => {
    const mvt: { url: string; status: number }[] = [];
    const thirdPartyPbf: string[] = [];

    page.on('response', (r) => {
      const url = r.url();
      if (isDatasetTile(url)) mvt.push({ url, status: r.status() });
      else if (url.includes('.pbf')) thirdPartyPbf.push(url);
    });

    await page.goto(`/datasets/${datasetId}`);
    await page.waitForURL(new RegExp(`/datasets/${datasetId}$`));
    // The map fits to the dataset's bounds on load, so tiles for the data's own
    // extent are requested without needing an explicit zoom-to-layer.
    await expect(page.locator('canvas.maplibregl-canvas')).toBeVisible({ timeout: 20_000 });
    await page.waitForLoadState('networkidle');

    // THE assertion. Zero here is the #8186 silent-worker signature. Scoped to
    // this dataset's own route, so third-party basemap/glyph .pbf traffic
    // cannot satisfy it.
    expect(
      mvt.length,
      `no tiles requested for data.${tableName} — the maplibre worker is not ` +
        `resolving vector sources (${thirdPartyPbf.length} unrelated .pbf responses were ignored)`,
    ).toBeGreaterThan(0);

    // A 204 is a legitimately empty tile; anything else is a real failure.
    const bad = mvt.filter((t) => t.status !== 200 && t.status !== 204);
    expect(bad, `non-OK tile responses: ${JSON.stringify(bad.slice(0, 5))}`).toHaveLength(0);
  });

  test('the tile worker still serves the dataset after a basemap change', async ({ page }) => {
    // Regression guard for the worker being orphaned when the style changes.
    // Relevant to v6 specifically: Style construction re-reads the map's
    // missing-image resolver, so a basemap change re-runs that path.
    await page.goto(`/datasets/${datasetId}`);
    await expect(page.locator('canvas.maplibregl-canvas')).toBeVisible({ timeout: 20_000 });
    await page.waitForLoadState('networkidle');

    // Same first-party scoping as above: a basemap swap necessarily pulls a
    // fresh set of THIRD-PARTY .pbf tiles, so an unscoped predicate here would
    // be satisfied by the very thing the swap causes and could never fail.
    const afterSwap: number[] = [];
    page.on('response', (r) => {
      if (isDatasetTile(r.url())) afterSwap.push(r.status());
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
    const group = page.getByRole('group', { name: 'Change basemap' });
    await expect(group.getByRole('button').first()).toBeVisible({ timeout: 5000 });
    // fix(#1624): pick an option that is genuinely NOT active, rather than
    // assuming nth(0) is. BasemapToggle marks the active one with aria-current
    // (BasemapToggle.tsx:97), and which one that is depends on theme — under
    // the dark theme nth(1) IS the active basemap, so clicking it leaves the
    // basemap identity unchanged, DatasetMap never calls setStyle, and the zoom
    // below still populates afterSwap. The test would pass having swapped
    // nothing.
    const activeBefore = await group.locator('button[aria-current]').first().textContent();
    const inactive = group.locator('button:not([aria-current])');
    const inactiveCount = await inactive.count();
    expect(inactiveCount, 'basemap picker exposed no inactive option to switch to').toBeGreaterThan(0);
    const targetName = (await inactive.first().textContent())?.trim();
    await inactive.first().click();
    await page.waitForTimeout(3000);

    // The swap must have actually occurred, or everything below is vacuous.
    // Asserted against the DOM rather than by counting basemap tile traffic:
    // a configured basemap may be a raster XYZ style that emits no .pbf at all
    // (CI's does), so tile-format-based proof fails on a perfectly healthy
    // swap. aria-current moving is what actually means setStyle ran.
    await toggle.click();
    const activeAfter = await group.locator('button[aria-current]').first().textContent();
    expect(
      activeAfter?.trim(),
      `basemap did not change (still "${activeBefore?.trim()}") — setStyle never ran, ` +
        'so the assertion below would be measuring an unchanged style',
    ).toBe(targetName);
    await page.keyboard.press('Escape');

    // Then force NEW tiles to be needed. A basemap change alone proves nothing
    // here: this app mutates basemap layers rather than rebuilding the dataset
    // source, so already-cached tiles are correctly never re-fetched, and an
    // assertion on the swap alone measures the basemap's traffic instead of the
    // dataset's. Zooming after the swap is what actually exercises "the worker
    // still serves THIS source once the style has changed underneath it."
    // Must be the NavigationControl button, NOT mouse.wheel: DatasetMap sets
    // `scrollZoom={isFullscreen}` (DatasetMap.tsx:936), so wheel zoom is off
    // outside fullscreen and a wheel-based zoom silently does nothing, which
    // makes this assertion fail for a reason that has nothing to do with tiles.
    const zoomIn = page.getByRole('button', { name: /zoom in/i }).first();
    await expect(zoomIn).toBeVisible({ timeout: 5000 });
    await zoomIn.click();
    await page.waitForTimeout(2000);
    await zoomIn.click();
    await page.waitForTimeout(5000);

    expect(
      afterSwap.length,
      `no data.${tableName} tiles after a basemap change plus zoom — the worker ` +
        'stopped serving this source once the style changed underneath it',
    ).toBeGreaterThan(0);
  });
});
