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
      await expect(page.getByRole('heading', { name: 'Map Stack' })).toBeVisible();
      await expect(page.getByRole('heading', { name: 'Data' })).toBeVisible();
      await expect(page.locator('[data-testid^="layer-item"]').first()).toBeVisible();
      await expect(page.getByRole('button', { name: 'Share' })).toBeVisible();
      await expect(page.getByRole('button', { name: /save/i })).toBeVisible();
      await expect(page.locator('[inert]')).toHaveCount(0);
    }
  });

  test('sidebar collapses with inert attribute and reopens', async ({ page }) => {
    await page.goto(`/maps/${mapId}`);
    await waitForBuilder(page);

    // Find and click collapse button
    const collapseBtn = page.getByRole('button', { name: /collapse sidebar/i });
    await expect(collapseBtn).toBeVisible();
    await collapseBtn.click();

    // Wait for expand button to appear (sidebar collapsed)
    const expandBtn = page.getByRole('button', { name: /expand sidebar/i });
    await expect(expandBtn).toBeVisible();

    // Verify inert attribute is set on the collapsed sidebar
    const inertElements = page.locator('[inert]');
    await expect(inertElements).toHaveCount(1, { timeout: 5_000 });

    // Reopen sidebar
    await expandBtn.click();

    // Collapse button should be visible again
    await expect(collapseBtn).toBeVisible();

    // inert attribute should be removed
    await expect(page.locator('[inert]')).toHaveCount(0);
  });

  test('opens Add Data dialog', async ({ page }) => {
    await page.goto(`/maps/${mapId}`);
    await waitForBuilder(page);

    // Click "Add Data" button in the layer panel
    const addDataBtn = page.getByRole('button', { name: /add data/i });
    await expect(addDataBtn).toBeVisible();
    await addDataBtn.click();

    // Dialog should be visible
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();

    // Close dialog via Escape
    await page.keyboard.press('Escape');
    await expect(dialog).not.toBeVisible();
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

    // Find basemap section heading
    const basemapHeading = page.getByText('Basemap');
    await expect(basemapHeading).toBeVisible();

    // Count current layer items in the sidebar before switching
    const layerItemsBefore = await page.locator('[data-testid^="layer-item"]').count()
      .catch(() => 0);

    // Expand the basemap picker (starts collapsed) by clicking the toggle
    const basemapToggle = page.locator('.px-2 > button').filter({ hasText: /basemap|positron|dark|voyager|osm/i }).first();
    await basemapToggle.click();

    // Select a different basemap option
    const basemapOptions = page.locator('[data-testid="basemap-option"]');
    await expect(basemapOptions.first()).toBeVisible({ timeout: 3_000 });
    // Click the second option (different from current)
    await basemapOptions.nth(1).click();

    // Canvas should still be visible — toBeVisible auto-retries until the
    // basemap style reload settles or the timeout fires (deterministic poll).
    await expect(page.locator('canvas.maplibregl-canvas')).toBeVisible({ timeout: 5_000 });

    // Layer items should still be present (overlay layers not lost)
    if (layerItemsBefore > 0) {
      const layerItemsAfter = await page.locator('[data-testid^="layer-item"]').count()
        .catch(() => 0);
      expect(layerItemsAfter).toBe(layerItemsBefore);
    }
  });

  test('keeps collapsed basemap options hidden from the DOM', async ({ page }) => {
    await page.goto(`/maps/${mapId}`);
    await waitForBuilder(page);

    const basemapToggle = page.getByRole('button', { name: /basemap:/i });
    await expect(basemapToggle).toHaveAttribute('aria-expanded', 'false');
    await expect(page.getByTestId('basemap-option')).toHaveCount(0);

    await basemapToggle.click();
    await expect(page.getByTestId('basemap-option').first()).toBeVisible();

    await basemapToggle.click();
    await expect(basemapToggle).toHaveAttribute('aria-expanded', 'false');
    await expect(page.getByTestId('basemap-option')).toHaveCount(0);
  });

  test('mobile sidebar can reach layer editor tabs and return to the layer list', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`/maps/${mapId}`);
    await waitForBuilder(page);

    await page.getByRole('button', { name: /expand sidebar/i }).click();
    const sheet = page.getByRole('dialog');
    await expect(sheet).toBeVisible();

    await sheet.getByRole('button', { name: /expand options/i }).first().click();
    await expect(sheet.getByRole('button', { name: /back to layers/i })).toBeVisible();

    for (const tab of ['Style', 'Filter', 'Labels', 'Popup']) {
      await expect(sheet.getByRole('tab', { name: tab })).toBeVisible();
    }

    await sheet.getByRole('tab', { name: 'Filter' }).click();
    await expect(sheet.getByRole('tab', { name: 'Filter' })).toHaveAttribute('aria-selected', 'true');

    await sheet.getByRole('button', { name: /back to layers/i }).click();
    await expect(sheet.getByRole('button', { name: /add data/i })).toBeVisible();
  });

  test('filter condition field remains readable in the default inspector width', async ({ page }) => {
    await page.goto(`/maps/${mapId}`);
    await waitForBuilder(page);

    await page.getByRole('button', { name: /expand options/i }).first().click();
    await page.getByRole('tab', { name: 'Filter' }).click();
    await page.getByRole('button', { name: /add filter/i }).click();

    const fieldTrigger = page.getByTestId('filter-field-row').locator('[role="combobox"]').first();
    const controlsRow = page.getByTestId('filter-value-row').first();
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

  test('zoom to layer changes map viewport', async ({ page }) => {
    await page.goto(`/maps/${mapId}`);
    await waitForBuilder(page);

    // Open the per-layer "More actions" menu. The first trigger belongs to the map header tray.
    const moreBtn = page.getByRole('button', { name: 'More actions' }).nth(1);
    await expect(moreBtn).toBeVisible();
    await moreBtn.click();

    // Click "Zoom to layer"
    const zoomItem = page.getByRole('menuitem', { name: /zoom to layer/i });
    await expect(zoomItem).toBeVisible();
    await zoomItem.click();

    // Map should still be functional — canvas visible, no error toasts.
    // Both toBeVisible and toHaveCount auto-retry up to their timeout, so they
    // implicitly poll for the post-zoom UI to settle (deterministic).
    await expect(page.locator('canvas.maplibregl-canvas')).toBeVisible({ timeout: 5_000 });
    await expect(page.locator('[data-sonner-toast][data-type="error"]')).toHaveCount(0, { timeout: 5_000 });
  });

  test('sidebar resize slider persists keyboard resizing', async ({ page }) => {
    await page.addInitScript(() => localStorage.removeItem('geolens-builder-sidebar-width'));
    await page.goto(`/maps/${mapId}`);
    await waitForBuilder(page);

    const handle = page.getByTestId('builder-sidebar-resize-handle');
    await expect(handle).toBeVisible();
    const sidebar = page.getByTestId('builder-sidebar');

    const widthBefore = await sidebar.evaluate((el) => el.offsetWidth);
    await expect(handle).toHaveAttribute('role', 'slider');
    await expect(handle).toHaveAttribute('aria-valuemin', '200');
    await expect(handle).toHaveAttribute('aria-valuemax', '600');

    await handle.focus();
    await expect(handle).toBeFocused();
    await page.keyboard.press('ArrowRight');
    await page.keyboard.press('ArrowRight');

    let storedNum: number | null = null;
    await expect
      .poll(async () => {
        const v = await page.evaluate(() => localStorage.getItem('geolens-builder-sidebar-width'));
        storedNum = v === null ? null : Number(v);
        return storedNum;
      }, {
        timeout: 3_000,
        message: 'keyboard resize should persist a wider sidebar to localStorage',
      })
      .toBeGreaterThan(widthBefore);

    if (storedNum === null) {
      throw new Error('localStorage was empty after keyboard resize resolved');
    }
    expect(Number.isFinite(storedNum)).toBe(true);
    expect(storedNum).toBeGreaterThanOrEqual(200); // SIDEBAR_MIN
    expect(storedNum).toBeLessThanOrEqual(600); // SIDEBAR_MAX
    await expect(handle).toHaveAttribute('aria-valuenow', String(storedNum));

    // Reload and verify the persisted value drives the rendered width.
    await page.reload();
    await waitForBuilder(page);
    const widthAfterReload = await sidebar.evaluate((el) => el.offsetWidth);
    expect(widthAfterReload).toBe(storedNum);
  });

  test('sidebar collapsed state persists across reload', async ({ page }) => {
    await page.goto(`/maps/${mapId}`);
    await waitForBuilder(page);

    // Clear stored state
    await page.evaluate(() => localStorage.removeItem('geolens-builder-sidebar-collapsed'));

    // Collapse sidebar
    const collapseBtn = page.getByRole('button', { name: /collapse sidebar/i });
    await collapseBtn.click();
    await expect(page.getByRole('button', { name: /expand sidebar/i })).toBeVisible();

    // Reload — should stay collapsed
    await page.reload();
    await waitForBuilder(page);
    await expect(page.getByRole('button', { name: /expand sidebar/i })).toBeVisible();

    // Expand and reload — should stay expanded
    await page.getByRole('button', { name: /expand sidebar/i }).click();
    await expect(page.getByRole('button', { name: /collapse sidebar/i })).toBeVisible();
    await page.reload();
    await waitForBuilder(page);
    await expect(page.getByRole('button', { name: /collapse sidebar/i })).toBeVisible();
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
