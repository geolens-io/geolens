import type { APIRequestContext, Page } from '@playwright/test';
import { test, expect } from './helpers/session';
import { seedCategoryDataset, deleteDataset } from './helpers/catalog';
import { authHeaders, createMap, deleteMap } from './helpers/maps';

const BASE_URL = process.env.E2E_BASE_URL ?? 'http://localhost:8080';

// The fixture's six points span about 0.05 degrees around New York; the map
// opens on the westernmost one, with all six in view.
const FIRST_POINT = { lng: -73.99, lat: 40.74 };

async function updateMap(request: APIRequestContext, mapId: string, data: Record<string, unknown>) {
  const response = await request.put(`${BASE_URL}/api/maps/${mapId}`, { headers: authHeaders(), data });
  expect(response.ok(), `Update map failed: ${response.status()}`).toBe(true);
}

/** Opens the map as a reader sees it and waits until the Map data button can open the panel. */
async function openViewer(page: Page, mapId: string) {
  await page.goto(`/maps/${mapId}?preview=viewer`);
  const launcher = page.getByRole('button', { name: 'Map data', exact: true });
  await expect(launcher).toBeEnabled({ timeout: 30_000 });
  return launcher;
}

function scaleText(page: Page) {
  return page.locator('.maplibregl-ctrl-scale').textContent();
}

test.describe('Viewer Map data panel', () => {
  let datasetId = '';
  let datasetTitle = '';
  let mapId = '';

  test.beforeAll(async ({ request }) => {
    // seedCategoryDataset can poll for up to 60 s.
    test.setTimeout(120_000);
    const seeded = await seedCategoryDataset('Reader Table E2E Points');
    datasetId = seeded.id;
    datasetTitle = seeded.title;
    mapId = await createMap(request, `Reader Table E2E ${Date.now()}`);
    const layer = await request.post(`${BASE_URL}/api/maps/${mapId}/layers/`, {
      headers: authHeaders(),
      data: { dataset_id: datasetId },
    });
    expect(layer.ok()).toBe(true);
    await updateMap(request, mapId, { center_lng: FIRST_POINT.lng, center_lat: FIRST_POINT.lat, zoom: 12 });
  });

  test.afterAll(async ({ request }) => {
    if (mapId) await deleteMap(request, mapId);
    if (datasetId) await deleteDataset(datasetId, datasetTitle);
  });

  test('a reader pages the layer, fits the map to a row and narrows the rows to the view', async ({ page }) => {
    const launcher = await openViewer(page, mapId);
    await launcher.click();

    const panel = page.getByRole('region', { name: 'Map data' });
    await expect(panel.getByRole('radio', { name: 'Table' })).toBeChecked();
    const rows = panel.getByRole('row', { name: /^Show row \d+ on the map$/ });
    await expect(rows).toHaveCount(6, { timeout: 15_000 });
    // Unfiltered, the total is the table's estimate.
    await expect(panel.locator('header').getByText(/^Showing 1-6 of ~?6 rows$/)).toBeVisible();

    const scaleBefore = await scaleText(page);
    const first = rows.first();
    await first.click();
    await expect(first).toHaveAttribute('aria-selected', 'true');
    // The fit zooms to the point, so the scale bar reads a shorter distance.
    await expect.poll(() => scaleText(page), { timeout: 10_000 }).not.toBe(scaleBefore);

    // Back at the opening view, In view keeps all six; zoomed in on the first
    // point it keeps fewer.
    await page.goto(`/maps/${mapId}?preview=viewer`);
    await expect(launcher).toBeEnabled({ timeout: 30_000 });
    await launcher.click();
    await panel.getByRole('switch', { name: 'In view' }).click();
    await expect(panel.locator('header').getByText('Showing 1-6 of 6 rows')).toBeVisible({ timeout: 15_000 });

    const canvas = page.locator('canvas.maplibregl-canvas');
    await canvas.focus();
    for (let step = 0; step < 3; step += 1) {
      await page.keyboard.press('=');
      // Each step eases; a key pressed mid-ease is dropped.
      await page.waitForTimeout(400);
    }
    await expect(panel.locator('header').getByText(/^Showing 1-[1-5] of [1-5] rows$/)).toBeVisible({ timeout: 15_000 });
    expect(await rows.count()).toBeLessThan(6);
  });

  test('the List view lists what the map renders', async ({ page }) => {
    const launcher = await openViewer(page, mapId);
    await launcher.click();

    const panel = page.getByRole('region', { name: 'Map data' });
    await panel.getByRole('radio', { name: 'List' }).click();
    await expect(panel.getByRole('radio', { name: 'List' })).toBeFocused();
    await expect(panel.getByRole('region', { name: 'Map layer and feature data' })).toBeVisible();
    await expect(panel.getByRole('heading', { name: 'Features in this view' })).toBeVisible();
  });

  test('with the reader table off, the panel offers only the List view', async ({ page, request }) => {
    await updateMap(request, mapId, { show_attribute_table: false });
    try {
      const launcher = await openViewer(page, mapId);
      await launcher.click();

      const panel = page.getByRole('region', { name: 'Map data' });
      await expect(panel.getByRole('region', { name: 'Map layer and feature data' })).toBeVisible();
      await expect(panel.getByRole('radio', { name: 'Table' })).toHaveCount(0);
      await expect(panel.getByRole('row', { name: /^Show row / })).toHaveCount(0);
    } finally {
      await updateMap(request, mapId, { show_attribute_table: true });
    }
  });

  test('on a phone the panel docks in the map pane and Expand opens it full screen', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    const launcher = await openViewer(page, mapId);
    await launcher.click();

    const panel = page.getByRole('region', { name: 'Map data' });
    await expect(panel.getByRole('row', { name: /^Show row / }).first()).toBeVisible({ timeout: 15_000 });
    expect((await panel.boundingBox())!.height).toBeGreaterThanOrEqual(240);

    const expand = panel.getByRole('button', { name: 'Expand map data' });
    await expand.click();
    const dialog = page.getByRole('dialog', { name: 'Map data' });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByRole('row', { name: /^Show row / })).toHaveCount(6);

    await page.keyboard.press('Escape');
    await expect(dialog).toHaveCount(0);
    await expect(expand).toBeFocused();
  });
});
