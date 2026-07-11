import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import fs from 'fs';
import path from 'path';
import { deleteDataset, seedDemDataset, getAuthToken } from './helpers/catalog';

/**
 * fix(#451): E2E coverage for the composable two-switch DEM editor.
 *
 * Seeds a real single-band Float32 GeoTIFF (ingested as a DEM), builds a map
 * around it, and drives the builder UI through the states the composable model
 * introduced: Hillshade shading and "Use as 3D terrain" as independent
 * switches, the "Not shown" badge when both are off, and the HT-14 guarantee
 * that an eye-toggle + Save touches ONLY the layer's `visible` flag.
 */

const AUTH_FILE = path.join(__dirname, '../playwright/.auth/user.json');
const BASE_URL = process.env.E2E_BASE_URL ?? 'http://localhost:8080';

interface MapLayerDetails {
  id: string;
  dataset_id: string;
  visible?: boolean;
  style_config?: Record<string, unknown> | null;
}

interface MapDetails {
  id: string;
  terrain_config?: { enabled?: boolean; source_dataset_id?: string | null } | null;
  layers?: MapLayerDetails[];
}

function getAuthEntry() {
  const raw = fs.readFileSync(AUTH_FILE, 'utf-8');
  const state = JSON.parse(raw) as {
    origins?: Array<{ localStorage?: Array<{ name: string; value: string }> }>;
  };
  for (const origin of state.origins ?? []) {
    const entry = origin.localStorage?.find((candidate) => candidate.name === 'geolens-auth');
    if (entry?.value) return entry.value;
  }
  throw new Error('Could not extract geolens-auth localStorage entry');
}

function authHeaders() {
  return {
    Authorization: `Bearer ${getAuthToken()}`,
    'Content-Type': 'application/json',
  };
}

async function seedAuth(page: Page) {
  const authEntry = getAuthEntry();
  await page.addInitScript((value) => {
    window.localStorage.setItem('geolens-auth', value);
  }, authEntry);
}

async function waitForBuilder(page: Page) {
  await expect(page.locator('canvas.maplibregl-canvas')).toBeVisible({ timeout: 20_000 });
  await expect(page.getByTestId('builder-sidebar')).toBeVisible({ timeout: 15_000 });
}

async function getMapDetails(request: APIRequestContext, mapId: string): Promise<MapDetails> {
  const response = await request.get(`${BASE_URL}/api/maps/${mapId}`, { headers: authHeaders() });
  expect(response.ok(), `GET /api/maps/${mapId} failed: ${response.status()}`).toBe(true);
  return await response.json() as MapDetails;
}

async function saveMap(page: Page, mapId: string) {
  const saved = page.waitForResponse(
    (response) => response.url().includes(`/api/maps/${mapId}/layers`) && response.request().method() === 'PATCH',
  );
  await page.getByRole('button', { name: /save/i }).first().click();
  expect((await saved).ok()).toBe(true);
}

test.describe('builder DEM editor (composable hillshade + terrain)', () => {
  let datasetId = '';
  let datasetTitle = '';
  let mapId = '';

  test.beforeAll(async ({ request }) => {
    const seeded = await seedDemDataset();
    datasetId = seeded.id;
    datasetTitle = seeded.title;

    const created = await request.post(`${BASE_URL}/api/maps/`, {
      headers: authHeaders(),
      data: { name: `DEM editor e2e ${Date.now()}`, description: 'Two-switch DEM editor coverage' },
    });
    expect(created.ok(), `Create map failed: ${created.status()}`).toBe(true);
    mapId = ((await created.json()) as { id: string }).id;

    const layer = await request.post(`${BASE_URL}/api/maps/${mapId}/layers/`, {
      headers: authHeaders(),
      data: { dataset_id: datasetId },
    });
    expect(layer.ok(), `Add DEM layer failed: ${layer.status()}`).toBe(true);
  });

  test.afterAll(async ({ request }) => {
    if (mapId) {
      await request.delete(`${BASE_URL}/api/maps/${mapId}`, {
        headers: { Authorization: `Bearer ${getAuthToken()}` },
      }).catch(() => { /* best-effort */ });
    }
    if (datasetId) await deleteDataset(datasetId, datasetTitle);
  });

  test('the two switches compose: hillshade off shows the badge, terrain on binds map-level terrain', async ({ page, request }) => {
    await seedAuth(page);
    await page.goto(`/maps/${mapId}`);
    await waitForBuilder(page);

    // Open the DEM layer editor from its stack row.
    const demRow = page.locator('[id^="stack-row-"]').filter({ hasText: /DEM|Hillshade/i }).first();
    await demRow.click();
    const editor = page.getByTestId('builder-layer-editor');
    await expect(editor).toBeVisible();

    const hillshadeSwitch = editor.getByRole('switch', { name: 'Hillshade shading' });
    const terrainSwitch = editor.getByRole('switch', { name: 'Use as 3D terrain' });
    await expect(hillshadeSwitch).toBeVisible();
    await expect(terrainSwitch).toBeVisible();

    // Default DEM ingest renders hillshade; terrain is a separate opt-in.
    await expect(hillshadeSwitch).toBeChecked();
    await expect(terrainSwitch).not.toBeChecked();

    // Hillshade off + terrain off → the row draws nothing and says so.
    await hillshadeSwitch.click();
    await expect(demRow.getByTitle(/Not shown/)).toBeVisible();

    // Terrain on → the DEM contributes again (badge gone), independent of hillshade.
    await terrainSwitch.click();
    await expect(demRow.getByTitle(/Not shown/)).toHaveCount(0);

    await saveMap(page, mapId);
    const details = await getMapDetails(request, mapId);
    expect(details.terrain_config?.enabled).toBe(true);
    expect(details.terrain_config?.source_dataset_id).toBe(datasetId);

    // Restore hillshade + drop terrain so the map returns to its baseline.
    await hillshadeSwitch.click();
    await terrainSwitch.click();
    await saveMap(page, mapId);
    const restored = await getMapDetails(request, mapId);
    expect(restored.terrain_config?.enabled ?? false).toBe(false);
  });

  test('HT-14: eye-toggle + Save changes only the visible flag', async ({ page, request }) => {
    const before = await getMapDetails(request, mapId);
    const demBefore = before.layers?.find((l) => l.dataset_id === datasetId);
    expect(demBefore).toBeTruthy();

    await seedAuth(page);
    await page.goto(`/maps/${mapId}`);
    await waitForBuilder(page);

    await page.getByRole('button', { name: /^Toggle visibility for/ }).first().click();
    await saveMap(page, mapId);

    const after = await getMapDetails(request, mapId);
    const demAfter = after.layers?.find((l) => l.dataset_id === datasetId);
    expect(demAfter?.visible).toBe(!(demBefore?.visible ?? true));
    // The partial PATCH must not materialize or clear style metadata.
    expect(demAfter?.style_config ?? null).toEqual(demBefore?.style_config ?? null);
    expect(after.terrain_config ?? null).toEqual(before.terrain_config ?? null);

    // Restore visibility for any spec running after this one.
    await page.getByRole('button', { name: /^Toggle visibility for/ }).first().click();
    await saveMap(page, mapId);
  });
});
