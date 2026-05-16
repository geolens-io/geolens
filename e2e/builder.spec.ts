import { test, expect, type Page } from '@playwright/test';
import fs from 'fs';
import path from 'path';

const AUTH_FILE = path.join(__dirname, '../playwright/.auth/user.json');
const BASE_URL = process.env.E2E_BASE_URL ?? 'http://localhost:8080';
const TEXT_TYPES = ['character', 'text', 'varchar', 'char'];

interface DatasetListItem {
  id?: string;
  title?: string;
  record_type?: string;
  column_info?: { name: string; type: string }[] | null;
}

interface MapLayerListItem {
  id: string;
  dataset_id: string;
  dataset_name?: string | null;
  sort_order?: number | null;
  paint?: unknown;
  layout?: unknown;
  style_config?: unknown;
}

interface MapDetails {
  basemap_style?: string | null;
  show_basemap_labels?: boolean | null;
  basemap_config?: unknown;
  terrain_config?: unknown;
  layers?: MapLayerListItem[];
}

interface JobStatusPayload {
  status: string;
  dataset_id: string | null;
  error_message?: string | null;
}

/** Extract JWT token from the Playwright storage state file. */
function getAuthToken(): string {
  const raw = fs.readFileSync(AUTH_FILE, 'utf-8');
  const state = JSON.parse(raw);
  const origins = state.origins ?? [];
  for (const origin of origins) {
    for (const entry of origin.localStorage ?? []) {
      if (entry.name === 'geolens-auth') {
        const parsed = JSON.parse(entry.value);
        return parsed.state?.token ?? '';
      }
    }
  }
  throw new Error('Could not extract auth token from storage state');
}

function hasTextColumn(columns: { name: string; type: string }[] | null): boolean {
  if (!columns) return false;
  return columns.some((c) => TEXT_TYPES.some((t) => c.type.toLowerCase().includes(t)));
}

function extractDatasets(payload: unknown): DatasetListItem[] {
  if (Array.isArray(payload)) return payload as DatasetListItem[];
  if (!payload || typeof payload !== 'object') return [];
  const response = payload as { datasets?: DatasetListItem[]; items?: DatasetListItem[] };
  return response.datasets ?? response.items ?? [];
}

async function waitForBuilder(page: Page) {
  await expect(page.locator('canvas.maplibregl-canvas')).toBeVisible({ timeout: 15_000 });
}

async function waitForDatasetJob(jobId: string, authHeaders: Record<string, string>): Promise<string> {
  for (let attempt = 0; attempt < 45; attempt++) {
    const statusRes = await fetch(`${BASE_URL}/api/jobs/${jobId}`, { headers: authHeaders });
    expect(statusRes.ok).toBe(true);
    const status = await statusRes.json() as JobStatusPayload;
    if (status.status === 'complete' && status.dataset_id) return status.dataset_id;
    if (status.status === 'failed') {
      throw new Error(`Fallback dataset import failed: ${status.error_message ?? 'unknown error'}`);
    }
    await new Promise((resolve) => setTimeout(resolve, 1_000));
  }
  throw new Error('Fallback dataset import did not complete in time');
}

async function createFallbackVectorDataset(authHeaders: Record<string, string>) {
  const title = `E2E Builder Dataset ${Date.now()}`;
  const filename = `${title.toLowerCase().replace(/[^a-z0-9]+/g, '-')}.geojson`;
  const geojson = JSON.stringify({
    type: 'FeatureCollection',
    features: [
      { type: 'Feature', properties: { name: 'Alpha', category: 'A', value: 10 }, geometry: { type: 'Point', coordinates: [-73.9857, 40.7484] } },
      { type: 'Feature', properties: { name: 'Bravo', category: 'B', value: 20 }, geometry: { type: 'Point', coordinates: [-73.98, 40.75] } },
    ],
  });
  const formData = new FormData();
  formData.append('file', new Blob([geojson], { type: 'application/geo+json' }), filename);

  const uploadRes = await fetch(`${BASE_URL}/api/ingest/upload`, {
    method: 'POST',
    headers: authHeaders,
    body: formData,
  });
  expect(uploadRes.ok).toBe(true);
  const upload = await uploadRes.json() as { job_id: string };

  const previewRes = await fetch(`${BASE_URL}/api/ingest/preview/${upload.job_id}`, {
    method: 'POST',
    headers: authHeaders,
  });
  expect(previewRes.ok).toBe(true);
  const preview = await previewRes.json() as { layer_name?: string; geometry_type?: string | null };
  expect(preview.geometry_type).toBeTruthy();

  const commitRes = await fetch(`${BASE_URL}/api/ingest/commit/${upload.job_id}`, {
    method: 'POST',
    headers: { ...authHeaders, 'Content-Type': 'application/json' },
    body: JSON.stringify({
      title,
      summary: 'Temporary dataset for builder E2E regression coverage',
      visibility: 'private',
      layer_name: preview.layer_name,
    }),
  });
  expect(commitRes.ok).toBe(true);

  const datasetId = await waitForDatasetJob(upload.job_id, authHeaders);
  return { datasetId, title };
}

async function getMapDetails(mapId: string, authHeaders: Record<string, string>): Promise<MapDetails> {
  const response = await fetch(`${BASE_URL}/api/maps/${mapId}`, { headers: authHeaders });
  expect(response.ok).toBe(true);
  return await response.json() as MapDetails;
}

async function getMapLayers(mapId: string, authHeaders: Record<string, string>): Promise<MapLayerListItem[]> {
  const payload = await getMapDetails(mapId, authHeaders);
  return payload.layers ?? [];
}

function objectKeys(value: unknown): string[] {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return [];
  return Object.keys(value).sort();
}

let mapId: string;
let duplicatedMapId: string | null = null;
let fallbackDatasetId: string | null = null;
let fallbackDatasetTitle: string | null = null;

test.describe.serial('Map Builder', () => {
  test.slow();

  test.beforeAll(async () => {
    const token = getAuthToken();
    const headers = {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    };
    const authHeaders = { Authorization: `Bearer ${token}` };

    // Get a vector dataset with text columns so all layer editor tabs are available.
    const dsRes = await fetch(`${BASE_URL}/api/datasets/?limit=20`, { headers });
    expect(dsRes.ok).toBe(true);
    const dsData = await dsRes.json();
    const datasets = extractDatasets(dsData);
    const suitable = datasets.find(
      (ds) => ds.record_type === 'vector_dataset' && hasTextColumn(ds.column_info ?? null),
    );
    let datasetId = suitable?.id ?? datasets[0]?.id;
    if (!datasetId) {
      const fallback = await createFallbackVectorDataset(authHeaders);
      datasetId = fallback.datasetId;
      fallbackDatasetId = fallback.datasetId;
      fallbackDatasetTitle = fallback.title;
    }
    expect(datasetId).toBeTruthy();

    // Create a test map
    const mapRes = await fetch(`${BASE_URL}/api/maps/`, {
      method: 'POST',
      headers,
      body: JSON.stringify({
        name: 'E2E Builder Test Map',
        description: 'Auto-created for builder regression tests',
      }),
    });
    expect(mapRes.ok).toBe(true);
    const mapData = await mapRes.json();
    mapId = mapData.id;
    expect(mapId).toBeTruthy();

    // Add a vector layer
    const layerRes = await fetch(`${BASE_URL}/api/maps/${mapId}/layers/`, {
      method: 'POST',
      headers,
      body: JSON.stringify({ dataset_id: datasetId }),
    });
    expect(layerRes.ok).toBe(true);
  });

  test.afterAll(async () => {
    const token = getAuthToken();
    const headers = { Authorization: `Bearer ${token}` };

    // Clean up test map
    if (mapId) {
      await fetch(`${BASE_URL}/api/maps/${mapId}`, {
        method: 'DELETE',
        headers,
      });
    }
    // Clean up duplicated map
    if (duplicatedMapId) {
      await fetch(`${BASE_URL}/api/maps/${duplicatedMapId}`, {
        method: 'DELETE',
        headers,
      });
    }
    if (fallbackDatasetId && fallbackDatasetTitle) {
      await fetch(`${BASE_URL}/api/datasets/bulk-delete/`, {
        method: 'POST',
        headers: {
          ...headers,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          datasets: [{ dataset_id: fallbackDatasetId, confirm_title: fallbackDatasetTitle }],
        }),
      });
    }
  });

  test('loads existing map and canvas is visible', async ({ page }) => {
    await page.goto(`/maps/${mapId}`);
    await waitForBuilder(page);
  });

  test('asserts desktop and tablet builder shell states without screenshots', async ({ page }) => {
    for (const viewport of [
      { width: 1440, height: 900, label: 'desktop' },
      { width: 834, height: 1112, label: 'tablet' },
    ]) {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await page.goto(`/maps/${mapId}`);
      await waitForBuilder(page);

      await expect(page.getByTestId('builder-sidebar'), `${viewport.label} sidebar`).toBeVisible();
      // Phase 1034 retired the "Map Stack" / "Data" section headings. At
      // desktop (≥1100px) the unified stack renders with an h2 "Layers"
      // header + stack-row-* IDs. At tablet (<1100px) the sidebar collapses
      // to a 64px rail (SidebarRail) with icon buttons but no h2 and no
      // full-anatomy rows — assert the rail's "Add data" button instead.
      const sidebar = page.getByTestId('builder-sidebar');
      if (viewport.width >= 1100) {
        await expect(sidebar.getByRole('heading', { level: 2 }).first()).toBeVisible();
        await expect(page.locator('[id^="stack-row-"]').first()).toBeVisible();
      } else {
        await expect(sidebar.getByRole('button', { name: /add data/i }).first()).toBeVisible();
      }
      await expect(page.getByRole('button', { name: 'Share' })).toBeVisible();
      await expect(page.getByRole('button', { name: /save/i })).toBeVisible();
      await expect(page.locator('[inert]')).toHaveCount(0);

      if (viewport.label === 'tablet') {
        await page.evaluate(() => localStorage.setItem('geolens-builder-sidebar-width', '600'));
        await page.reload();
        await waitForBuilder(page);

        const sidebarWidth = await page.getByTestId('builder-sidebar').evaluate((el) => el.offsetWidth);
        expect(sidebarWidth).toBeLessThanOrEqual(470);
      }
    }
  });

  test('Add Dataset dialog exposes responsive v1 tabs and basemap states', async ({ page }) => {
    for (const viewport of [
      { width: 1440, height: 900, label: 'desktop' },
      { width: 834, height: 1112, label: 'tablet' },
    ]) {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await page.goto(`/maps/${mapId}`);
      await waitForBuilder(page);

      const addDataBtn = page.getByRole('button', { name: /add data/i }).first();
      await expect(addDataBtn, `${viewport.label} add data trigger`).toBeVisible();
      await addDataBtn.click();

      const dialog = page.getByRole('dialog', { name: /add dataset/i });
      await expect(dialog, `${viewport.label} Add Dataset dialog`).toBeVisible();
      await expect(dialog.getByLabel(/search datasets/i)).toBeVisible();

      for (const tab of ['All', 'Vector', 'Raster', 'Basemap']) {
        await expect(dialog.getByRole('radio', { name: tab })).toBeVisible();
      }

      await dialog.getByRole('radio', { name: 'Basemap' }).click();
      await expect(dialog.getByRole('button', { name: 'in use' })).toBeVisible();
      await expect(dialog.getByRole('button', { name: 'swap' }).first()).toBeVisible();
      await expect(dialog.getByRole('link', { name: /import data/i })).toBeVisible();

      await page.keyboard.press('Escape');
      await expect(dialog).not.toBeVisible();
    }
  });

  test('Add Dataset data rows expose supported filters, expansion, and import routing', async ({ page }) => {
    await page.goto(`/maps/${mapId}`);
    await waitForBuilder(page);

    await page.getByRole('button', { name: /add data/i }).first().click();
    const dialog = page.getByRole('dialog', { name: /add dataset/i });
    await expect(dialog).toBeVisible();

    for (const tab of ['All', 'Vector', 'Raster', 'Basemap']) {
      await expect(dialog.getByRole('radio', { name: tab })).toBeVisible();
    }
    await expect(dialog.getByRole('radio', { name: 'DEM' })).toHaveCount(0);
    for (const unsupportedScope of ['Curated', 'Your imports', 'Public']) {
      await expect(dialog.getByRole('button', { name: unsupportedScope })).toHaveCount(0);
    }

    const firstExpand = dialog.getByRole('button', { name: /^Expand / }).first();
    await expect(firstExpand).toBeVisible({ timeout: 10_000 });
    await firstExpand.focus();
    await expect(firstExpand).toBeFocused();
    await page.keyboard.press('Enter');

    await expect(dialog.getByText('Type').first()).toBeVisible();
    await expect(dialog.getByRole('img', { name: /preview/i }).first()).toBeVisible();
    await expect(dialog.getByRole('button', { name: /Add to map|another rendering/i }).first()).toBeVisible();

    await dialog.getByRole('link', { name: /import data/i }).click();
    await expect(page).toHaveURL(/\/import$/);
  });

  test('duplicates dataset renderings from row overflow and Add Dataset modal', async ({ page }) => {
    const token = getAuthToken();
    const headers = { Authorization: `Bearer ${token}` };
    const initialLayers = await getMapLayers(mapId, headers);
    const originalLayer = initialLayers[0];
    expect(originalLayer).toBeTruthy();

    await page.goto(`/maps/${mapId}`);
    await waitForBuilder(page);

    const initialDatasetCount = initialLayers.filter((layer) => layer.dataset_id === originalLayer.dataset_id).length;

    // Phase 1034 replaced per-layer LayerItem testids and the auto-grouped
    // "dataset-rendering-group" rollup with flat unified stack rows
    // (id="stack-row-{layerId}"). Duplicate is exposed via the row kebab.
    const originalRow = page.locator(`#stack-row-${originalLayer.id}`);
    await expect(originalRow).toBeVisible();
    await originalRow.hover();
    await originalRow.locator('[data-kebab-trigger]').click();

    const rowDuplicateResponse = page.waitForResponse(
      (resp) => resp.url().includes(`/api/maps/${mapId}/layers`) && resp.request().method() === 'POST',
    );
    await page.getByRole('menuitem', { name: /^Duplicate$/i }).click();
    expect([200, 201]).toContain((await rowDuplicateResponse).status());

    let afterRowLayers: MapLayerListItem[] = [];
    await expect.poll(async () => {
      afterRowLayers = await getMapLayers(mapId, headers);
      return afterRowLayers.length;
    }).toBe(initialLayers.length + 1);

    const rowDuplicate = afterRowLayers.find((layer) => !initialLayers.some((existing) => existing.id === layer.id));
    expect(rowDuplicate?.id).not.toBe(originalLayer.id);
    expect(rowDuplicate?.dataset_id).toBe(originalLayer.dataset_id);
    expect(rowDuplicate?.paint ?? null).toEqual(originalLayer.paint ?? null);
    expect(rowDuplicate?.layout ?? null).toEqual(originalLayer.layout ?? null);
    expect(rowDuplicate?.style_config ?? null).toEqual(originalLayer.style_config ?? null);
    expect(afterRowLayers.filter((layer) => layer.dataset_id === originalLayer.dataset_id)).toHaveLength(initialDatasetCount + 1);
    if (rowDuplicate?.id) {
      await expect(page.locator(`#stack-row-${rowDuplicate.id}`)).toBeVisible();
    }

    await page.getByRole('button', { name: /add data/i }).first().click();
    const dialog = page.getByRole('dialog', { name: /add dataset/i });
    await expect(dialog).toBeVisible();
    if (originalLayer.dataset_name) {
      await dialog.getByLabel(/search datasets/i).fill(originalLayer.dataset_name);
    }
    await expect(dialog.getByRole('button', { name: 'another rendering' }).first()).toBeVisible();

    const modalDuplicateResponse = page.waitForResponse(
      (resp) => resp.url().includes(`/api/maps/${mapId}/layers`) && resp.request().method() === 'POST',
    );
    await dialog.getByRole('button', { name: 'another rendering' }).first().click();
    expect([200, 201]).toContain((await modalDuplicateResponse).status());

    await page.keyboard.press('Escape');
    await expect(dialog).not.toBeVisible();

    await expect.poll(async () => {
      const layers = await getMapLayers(mapId, headers);
      return layers.filter((layer) => layer.dataset_id === originalLayer.dataset_id).length;
    }).toBe(initialDatasetCount + 2);
    await expect(page.locator('[data-sonner-toast][data-type="error"]')).toHaveCount(0);
  });

  test('swaps basemap from Add Dataset modal and persists after save', async ({ page }) => {
    const token = getAuthToken();
    const headers = { Authorization: `Bearer ${token}` };
    const before = await getMapDetails(mapId, headers);
    const beforeLayerIdentity = (before.layers ?? []).map((layer) => `${layer.id}:${layer.dataset_id}`);

    await page.goto(`/maps/${mapId}`);
    await waitForBuilder(page);

    await page.getByRole('button', { name: /add data/i }).first().click();
    const dialog = page.getByRole('dialog', { name: /add dataset/i });
    await expect(dialog).toBeVisible();
    await dialog.getByRole('radio', { name: 'Basemap' }).click();

    const darkExpand = dialog.getByRole('button', { name: 'Expand OpenFreeMap Dark' });
    await expect(darkExpand).toBeVisible();
    const darkRow = darkExpand.locator('xpath=ancestor::div[contains(@class,"rounded-md")][1]');

    await darkRow.getByRole('button', { name: 'swap' }).click();
    await expect(darkRow.getByRole('button', { name: 'in use' })).toBeVisible();

    await page.keyboard.press('Escape');
    await expect(dialog).not.toBeVisible();

    // Phase 1035 replaced the dedicated "Basemap" section heading with a
    // basemap-group row at the top of the unified stack (id=stack-row-basemap-group);
    // overlay layers are now flat stack-row-{layerId} entries.
    const basemapRow = page.locator('#stack-row-basemap-group');
    // Phase 1035 renders the basemap row as `Basemap · {derivedPresetName}`,
    // where the derived name strips the provider prefix (openfreemap-dark → "Dark").
    await expect(basemapRow).toContainText(/Basemap · Dark\b/);
    await expect(page.locator('[id^="stack-row-"]:not([id="stack-row-basemap-group"])'))
      .toHaveCount(beforeLayerIdentity.length);

    const saveResponsePromise = page.waitForResponse(
      (resp) => resp.url().includes(`/api/maps/${mapId}`) && resp.request().method() === 'PUT',
    );
    await page.getByRole('button', { name: /save/i }).first().click();
    expect((await saveResponsePromise).status()).toBe(200);

    let persisted: MapDetails = {};
    await expect.poll(async () => {
      persisted = await getMapDetails(mapId, headers);
      return persisted.basemap_style;
    }).toBe('openfreemap-dark');
    expect((persisted.layers ?? []).map((layer) => `${layer.id}:${layer.dataset_id}`)).toEqual(beforeLayerIdentity);

    await page.reload();
    await waitForBuilder(page);
    await expect(page.locator('#stack-row-basemap-group')).toContainText(/Basemap · Dark\b/);
    await expect(page.locator('[id^="stack-row-"]:not([id="stack-row-basemap-group"])'))
      .toHaveCount(beforeLayerIdentity.length);
    await expect(page.locator('[data-sonner-toast][data-type="error"]')).toHaveCount(0);
  });

  test('round-trips layer zoom range without schema drift', async ({ page }) => {
    const token = getAuthToken();
    const headers = { Authorization: `Bearer ${token}` };
    const before = await getMapDetails(mapId, headers);
    const layer = before.layers?.[0];
    expect(layer).toBeTruthy();
    const beforeMapKeys = objectKeys(before);
    const beforeLayerKeys = objectKeys(layer);

    await page.goto(`/maps/${mapId}`);
    await waitForBuilder(page);

    // Phase 1034 moved the zoom-range controls into the LayerEditorPanel's
    // always-expanded Visibility section; access them by opening the flyout.
    const layerRow = page.locator(`#stack-row-${layer!.id}`);
    await expect(layerRow).toBeVisible();
    await layerRow.click();

    const editor = page.getByTestId('builder-layer-editor');
    await expect(editor).toBeVisible({ timeout: 5_000 });

    const minInput = editor.getByLabel('Minimum zoom', { exact: true });
    const maxInput = editor.getByLabel('Maximum zoom', { exact: true });
    await minInput.fill('2');
    await maxInput.fill('18');
    await expect(minInput).toHaveValue('2');
    await expect(maxInput).toHaveValue('18');

    const layerPatchPromise = page.waitForResponse(
      (resp) => resp.url().includes(`/api/maps/${mapId}/layers`) && resp.request().method() === 'PATCH',
    );
    const mapSavePromise = page.waitForResponse(
      (resp) => resp.url().includes(`/api/maps/${mapId}`) && resp.request().method() === 'PUT',
    );
    await page.getByRole('button', { name: /save/i }).first().click();
    expect((await layerPatchPromise).status()).toBe(200);
    expect((await mapSavePromise).status()).toBe(200);

    let persisted: MapDetails = {};
    await expect.poll(async () => {
      persisted = await getMapDetails(mapId, headers);
      const savedLayer = persisted.layers?.find((candidate) => candidate.id === layer!.id);
      const layout = savedLayer?.layout as Record<string, unknown> | undefined;
      return `${layout?._minzoom}-${layout?._maxzoom}`;
    }).toBe('2-18');

    const persistedLayer = persisted.layers?.find((candidate) => candidate.id === layer!.id);
    expect(objectKeys(persisted)).toEqual(beforeMapKeys);
    expect(objectKeys(persistedLayer)).toEqual(beforeLayerKeys);

    await page.reload();
    await waitForBuilder(page);
    await page.locator(`#stack-row-${layer!.id}`).click();
    const reloadedEditor = page.getByTestId('builder-layer-editor');
    await expect(reloadedEditor).toBeVisible({ timeout: 5_000 });
    await expect(reloadedEditor.getByLabel('Minimum zoom', { exact: true })).toHaveValue('2');
    await expect(reloadedEditor.getByLabel('Maximum zoom', { exact: true })).toHaveValue('18');
    await expect(page.locator('[data-sonner-toast][data-type="error"]')).toHaveCount(0);
  });

  test('opens Map Info dialog', async ({ page }) => {
    await page.goto(`/maps/${mapId}`);
    await waitForBuilder(page);

    // Open "More actions" dropdown (the header tray one, not per-layer)
    const moreBtn = page.getByRole('button', { name: /more actions/i }).first();
    await expect(moreBtn).toBeVisible();
    await moreBtn.click();

    // Click "Map info" menu item
    const infoItem = page.getByRole('menuitem', { name: /map info/i });
    await expect(infoItem).toBeVisible();
    await infoItem.click();

    // Dialog should be visible
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();

    // Close dialog
    await page.keyboard.press('Escape');
    await expect(dialog).not.toBeVisible();
  });

  test('share is visible as a primary action and no longer hidden in overflow', async ({ page }) => {
    await page.goto(`/maps/${mapId}`);
    await waitForBuilder(page);

    const shareButton = page.getByRole('button', { name: 'Share' });
    await expect(shareButton).toBeVisible();
    await shareButton.click();
    await expect(page.getByRole('heading', { name: 'Share' })).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(page.getByRole('heading', { name: 'Share' })).toHaveCount(0);

    const moreBtn = page.getByRole('button', { name: /more actions/i }).first();
    await moreBtn.click();
    await expect(page.getByRole('menuitem', { name: 'Share' })).toHaveCount(0);
  });

  test('saves map without errors', async ({ page }) => {
    await page.goto(`/maps/${mapId}`);
    await waitForBuilder(page);

    // Click save button
    const saveBtn = page.getByRole('button', { name: /save/i });
    await expect(saveBtn).toBeVisible();

    // Set up response listener before clicking
    const saveResponsePromise = page.waitForResponse(
      (resp) => resp.url().includes('/api/maps/') && resp.request().method() === 'PUT',
    );
    await saveBtn.click();

    const saveResponse = await saveResponsePromise;
    expect(saveResponse.status()).toBe(200);

    // No error toasts
    await expect(page.locator('[data-sonner-toast][data-type="error"]')).toHaveCount(0);
  });

  test('duplicates map and navigates to new URL', async ({ page }) => {
    await page.goto(`/maps/${mapId}`);
    await waitForBuilder(page);

    // Open "More actions" dropdown (the header tray one, not per-layer)
    const moreBtn = page.getByRole('button', { name: /more actions/i }).first();
    await moreBtn.click();

    // Click "Duplicate map"
    const dupItem = page.getByRole('menuitem', { name: /duplicate/i });
    await expect(dupItem).toBeVisible();
    await dupItem.click();

    // Wait for URL to change to a different map
    await page.waitForURL((url) => {
      const path = url.pathname;
      return path.startsWith('/maps/') && !path.includes(mapId);
    }, { timeout: 15_000 });

    // Extract duplicated map ID for cleanup
    const newUrl = page.url();
    const match = newUrl.match(/\/maps\/([a-f0-9-]+)/);
    if (match) {
      duplicatedMapId = match[1];
    }

    // Canvas should be visible on the new map
    await waitForBuilder(page);
  });

  test('switches basemap without losing overlay layers', async ({ page }) => {
    await page.goto(`/maps/${mapId}`);
    await waitForBuilder(page);

    // Phase 1035 replaced the inline "Swap to ..." popover with a basemap-group
    // editor scene: click the basemap-group row to open the flyout, then pick a
    // preset from the PRESET grid.
    const overlaySelector = '[id^="stack-row-"]:not([id="stack-row-basemap-group"])';
    const layerItemsBefore = await page.locator(overlaySelector).count();
    expect(layerItemsBefore).toBeGreaterThan(0);

    const basemapRow = page.locator('#stack-row-basemap-group');
    const beforeBasemapText = await basemapRow.textContent();
    await basemapRow.click();

    const editor = page.getByTestId('builder-layer-editor');
    await expect(editor).toBeVisible({ timeout: 5_000 });
    const presetSection = editor.locator('section').filter({ hasText: /^PRESET/i }).first();
    await expect(presetSection).toBeVisible({ timeout: 5_000 });

    // Pick the first preset whose label does NOT match the currently active row.
    const presetButtons = presetSection.locator('button');
    const presetCount = await presetButtons.count();
    expect(presetCount).toBeGreaterThan(1);
    let swapped = false;
    for (let i = 0; i < presetCount; i++) {
      const btn = presetButtons.nth(i);
      const label = (await btn.textContent())?.trim() ?? '';
      if (label && beforeBasemapText && !beforeBasemapText.includes(label.split('\n')[0])) {
        await btn.click();
        swapped = true;
        break;
      }
    }
    expect(swapped).toBe(true);

    // Map canvas should still be present and overlay rows preserved.
    await expect(page.locator('canvas.maplibregl-canvas')).toBeVisible({ timeout: 5_000 });
    await expect(page.locator(overlaySelector)).toHaveCount(layerItemsBefore);
  });

  test('mobile drill-down opens layer editor sheet and returns via back button', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`/maps/${mapId}`);
    await waitForBuilder(page);

    // At <1100px the sidebar collapses to the 64px SidebarRail; layer buttons
    // sit after the Settings + Add data controls and open the LayerEditorPanel
    // in a drill-down Sheet (<800px viewport). The Sheet itself doesn't carry
    // builder-layer-editor — the LayerEditorPanel renders inside the dialog.
    // Phase 1043-03 added a basemap-group button at the bottom of the SidebarRail —
    // avoid `button.last()` which now selects the basemap button. Target user layer
    // buttons by excluding the fixed control buttons (Settings, Add data, Basemap group).
    const sidebar = page.getByTestId('builder-sidebar');
    await expect(sidebar).toBeVisible();

    const layerButton = sidebar.locator(
      'button:not([data-testid="settings-cog-btn"]):not([aria-label*="Add data"]):not([aria-label="Basemap group"])',
    ).first();
    await layerButton.click();

    const sheet = page.getByRole('dialog');
    await expect(sheet).toBeVisible({ timeout: 5_000 });
    await expect(sheet.getByTestId('layer-editor-header')).toBeVisible();

    const backBtn = sheet.getByRole('button', { name: /back to layers/i });
    await expect(backBtn).toBeVisible();

    // Phase 1034 replaced per-tab navigation with collapsible Filter/Labels
    // sections inside the editor body.
    await expect(sheet.getByRole('button', { name: /^Filter/i })).toBeVisible();
    await expect(sheet.getByRole('button', { name: /^Labels/i })).toBeVisible();

    await backBtn.click();
    await expect(sheet).not.toBeVisible();
  });

  test('filter condition field remains readable in the default inspector width', async ({ page }) => {
    await page.goto(`/maps/${mapId}`);
    await waitForBuilder(page);

    const dataRow = page
      .locator('[id^="stack-row-"]:not([id="stack-row-basemap-group"])')
      .first();
    await dataRow.click();

    const editor = page.getByTestId('builder-layer-editor');
    await expect(editor).toBeVisible({ timeout: 5_000 });

    await editor.getByRole('button', { name: /^Filter/i }).click();
    await editor.getByRole('button', { name: /add filter/i }).click();

    const fieldTrigger = editor.getByTestId('filter-field-row').locator('[role="combobox"]').first();
    const controlsRow = editor.getByTestId('filter-value-row').first();
    await expect(fieldTrigger).toBeVisible();
    await expect(controlsRow).toBeVisible();

    const fieldBox = await fieldTrigger.boundingBox();
    const controlsBox = await controlsRow.boundingBox();
    expect(fieldBox).toBeTruthy();
    expect(controlsBox).toBeTruthy();
    expect(fieldBox!.width).toBeGreaterThan(180);
    expect(controlsBox!.y).toBeGreaterThan(fieldBox!.y + fieldBox!.height - 2);
  });

  test('keyboard-only navigation through builder controls', async ({ page }) => {
    await page.goto(`/maps/${mapId}`);
    await waitForBuilder(page);

    // Click the body to establish a starting focus point, then use only keyboard
    await page.locator('body').click();

    // Tab through builder controls and collect focused elements
    const focusedTags: string[] = [];
    for (let i = 0; i < 20; i++) {
      await page.keyboard.press('Tab');
      const info = await page.evaluate(() => {
        const el = document.activeElement;
        if (!el || el === document.body) return null;
        // Check that the focused element is not inside an [inert] ancestor
        const inertAncestor = el.closest('[inert]');
        return {
          tag: el.tagName.toLowerCase(),
          role: el.getAttribute('role'),
          tabindex: el.getAttribute('tabindex'),
          insideInert: !!inertAncestor,
        };
      });
      if (info) {
        expect(info.insideInert).toBe(false);
        focusedTags.push(info.tag);
      }
    }

    // Verify we tabbed through at least 5 focusable elements
    expect(focusedTags.length).toBeGreaterThanOrEqual(5);

    // Test focus-return after dialog close:
    // Open the "Add data" dialog via click (only mouse action besides initial body click)
    const addDataBtn = page.getByRole('button', { name: /add data/i });
    await expect(addDataBtn).toBeVisible();
    await addDataBtn.focus();
    await addDataBtn.click();

    // Wait for dialog to appear
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();

    // Close via Escape
    await page.keyboard.press('Escape');
    await expect(dialog).not.toBeVisible();

    // Verify focus returned to trigger or at minimum is not inside the closed dialog
    const postCloseFocus = await page.evaluate(() => {
      const el = document.activeElement;
      if (!el || el === document.body) return { tag: 'body', insideDialog: false };
      const dialogAncestor = el.closest('[role="dialog"]');
      return {
        tag: el.tagName.toLowerCase(),
        insideDialog: !!dialogAncestor,
      };
    });
    expect(postCloseFocus.insideDialog).toBe(false);
  });

  test('popup_config success-path round-trip (FOLLOWUP-01)', async ({ page }) => {
    const token = getAuthToken();
    const headers = {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    };
    const authHeaders = { Authorization: `Bearer ${token}` };

    // Get the first layer from the test map
    const layers = await getMapLayers(mapId, authHeaders);
    const layer = layers[0];
    expect(layer).toBeTruthy();

    // Directly patch the layer with an invalid popup_config expression.
    // This puts the map in a "previously-blocked" state where the frontend
    // pre-check will surface the named error toast.
    const patchRes = await fetch(`${BASE_URL}/api/maps/${mapId}/layers/`, {
      method: 'PATCH',
      headers,
      body: JSON.stringify({
        updated: [{
          id: layer.id,
          popup_config: {
            enabled: true,
            expression: '{{__missing_column__}}',
            visible_fields: null,
          },
        }],
      }),
    });
    // Backend accepts the patch because it only validates shape, not placeholder correctness.
    expect(patchRes.ok).toBe(true);

    // Open builder — the layer now has an invalid popup expression in local state.
    await page.goto(`/maps/${mapId}`);
    await waitForBuilder(page);

    // Click Save. The frontend pre-check detects the invalid placeholder and shows
    // a named error toast (FOLLOWUP-01 surface).
    await page.getByRole('button', { name: /save/i }).first().click();

    // Assert: error toast with the popup-config-invalid dedupe id appears
    const popupErrorToast = page.locator('[data-sonner-toast][data-type="error"]');
    await expect(popupErrorToast).toBeVisible({ timeout: 5_000 });
    const toastText = await popupErrorToast.textContent();
    expect(toastText).toMatch(/popup expression|invalid popup|cannot save/i);

    // Fix: open the layer editor → Popup tab and clear the invalid expression.
    const layerRow = page.locator(`#stack-row-${layer.id}`);
    await expect(layerRow).toBeVisible();
    await layerRow.click();

    const editor = page.getByTestId('builder-layer-editor');
    await expect(editor).toBeVisible({ timeout: 5_000 });

    // Navigate to Popup tab
    const popupTab = page.getByRole('tab', { name: /popup/i });
    await expect(popupTab).toBeVisible({ timeout: 5_000 });
    await popupTab.click();

    // Clear the invalid expression (empty expression = no placeholder validation needed)
    const exprInput = page.locator('#popup-expression');
    await expect(exprInput).toBeVisible({ timeout: 5_000 });
    await exprInput.clear();

    // Save again — no popup-config-invalid toast, success toast appears
    const saveResponsePromise = page.waitForResponse(
      (resp) =>
        (resp.url().includes(`/api/maps/${mapId}`) && resp.request().method() === 'PUT') ||
        (resp.url().includes(`/api/maps/${mapId}/layers`) && resp.request().method() === 'PATCH'),
    );
    await page.getByRole('button', { name: /save/i }).first().click();
    const saveResp = await saveResponsePromise;
    expect(saveResp.status()).toBe(200);

    // No popup-config-invalid error toast (may have the old one still from before — check
    // that a new one is not opened by verifying success toast appears instead)
    const successToast = page.locator('[data-sonner-toast][data-type="success"]');
    await expect(successToast).toBeVisible({ timeout: 8_000 });

    // Reload and verify the layer is still present (PUT round-trip persisted)
    await page.reload();
    await waitForBuilder(page);
    const reloadedLayers = await getMapLayers(mapId, authHeaders);
    expect(reloadedLayers.some((l) => l.id === layer.id)).toBe(true);

    // Restore layer to clean state (remove popup_config) so other tests are unaffected
    await fetch(`${BASE_URL}/api/maps/${mapId}/layers/`, {
      method: 'PATCH',
      headers,
      body: JSON.stringify({
        updated: [{ id: layer.id, popup_config: null }],
      }),
    });
  });

  test('no error toasts from raster tile 404s', async ({ page }) => {
    const consoleErrors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') consoleErrors.push(msg.text());
    });

    await page.goto(`/maps/${mapId}`);
    await waitForBuilder(page);

    // Wait for any tile loading to settle — networkidle resolves once outbound
    // requests are quiet for 500ms, deterministically replacing a 3s sleep.
    // Tolerate non-settling streams (websocket / SSE) by falling through.
    await page.waitForLoadState('networkidle', { timeout: 10_000 }).catch(() => {
      /* fall through to toast assertion below */
    });

    // No error toasts should be visible to the user — toHaveCount auto-retries.
    await expect(page.locator('[data-sonner-toast][data-type="error"]')).toHaveCount(0, { timeout: 5_000 });

    // Console-level MapLibre tile errors are expected and acceptable;
    // the test only verifies they don't surface as UI error toasts
  });
});
