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

    // fix(#1624): register this wait before navigation. The `page.on('response')`
    // collector above sees every tile regardless of timing, but a
    // `waitForResponse` registered after `goto` cannot match a response that
    // already arrived during navigation or before the canvas check completes —
    // a healthy fast run would then burn the full timeout for nothing.
    const firstDatasetTile = page.waitForResponse((r) => isDatasetTile(r.url()), {
      timeout: 20_000,
    });

    await page.goto(`/datasets/${datasetId}`);
    await page.waitForURL(new RegExp(`/datasets/${datasetId}$`));
    // The map fits to the dataset's bounds on load, so tiles for the data's own
    // extent are requested without needing an explicit zoom-to-layer.
    await expect(page.locator('canvas.maplibregl-canvas')).toBeVisible({ timeout: 20_000 });

    // fix(#1624): wait for the dataset's own first tile instead of `networkidle`.
    // A trace on the dev stack showed basemap tiles finish, then a ~580ms
    // client-side gap (map load event, transformRequest install, dataset source
    // add) before the six signed dataset tile requests fire — well inside
    // networkidle's 500ms quiet window under host load. That let the assertion
    // below run before the dataset source was even added, reporting "no tiles
    // requested" with a perfectly healthy pipeline. A timeout here falls
    // through to the length assertion, which still reports the real #8186
    // signature.
    await firstDatasetTile.catch(() => undefined);
    // The dataset source is now confirmed added, so the remaining tiles in
    // this batch are already in flight or complete: networkidle here waits
    // out that trailing traffic instead of racing its start, so the status
    // check below sees every response, not just the first.
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
});
