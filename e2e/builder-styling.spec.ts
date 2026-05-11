import { test, expect } from '@playwright/test';
import fs from 'fs';
import path from 'path';

const AUTH_FILE = path.join(__dirname, '../playwright/.auth/user.json');
const BASE_URL = process.env.E2E_BASE_URL ?? 'http://localhost:8080';

const TEXT_TYPES = ['character', 'text', 'varchar', 'char'];

/** Extract JWT token from the Playwright storage state file. */
function getAuthToken(): string {
  const raw = fs.readFileSync(AUTH_FILE, 'utf-8');
  const state = JSON.parse(raw);
  for (const origin of state.origins ?? []) {
    for (const entry of origin.localStorage ?? []) {
      if (entry.name === 'geolens-auth') {
        return JSON.parse(entry.value).state?.token ?? '';
      }
    }
  }
  throw new Error('Could not extract auth token from storage state');
}

function hasTextColumn(columns: { name: string; type: string }[] | null): boolean {
  if (!columns) return false;
  return columns.some((c) => TEXT_TYPES.some((t) => c.type.toLowerCase().includes(t)));
}

let mapId: string;

test.describe.serial('Builder Data-Driven Styling', () => {
  test.slow();

  test.beforeAll(async () => {
    const token = getAuthToken();
    const headers = {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    };

    // Find a vector dataset with text columns for categorical styling
    const dsRes = await fetch(`${BASE_URL}/api/datasets/?limit=20`, { headers });
    expect(dsRes.ok).toBe(true);
    const dsData = await dsRes.json();
    const datasets = dsData.datasets ?? dsData.items ?? dsData;

    const suitable = datasets.find(
      (ds: any) => ds.record_type === 'vector_dataset' && hasTextColumn(ds.column_info),
    );
    const datasetId = suitable?.id ?? datasets[0]?.id;
    expect(datasetId).toBeTruthy();

    // Create a test map
    const mapRes = await fetch(`${BASE_URL}/api/maps/`, {
      method: 'POST',
      headers,
      body: JSON.stringify({
        name: 'E2E Builder Styling Test',
        description: 'Auto-created for data-driven styling E2E tests',
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
    if (!mapId) return;
    const token = getAuthToken();
    await fetch(`${BASE_URL}/api/maps/${mapId}`, {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${token}` },
    });
  });

  test('expands layer and configures categorical data-driven styling', async ({ page }) => {
    await page.goto(`/maps/${mapId}`);
    await expect(page.locator('canvas.maplibregl-canvas')).toBeVisible({ timeout: 15_000 });

    // Expand the layer panel
    const expandBtn = page.getByRole('button', { name: 'Expand options' });
    await expect(expandBtn).toBeVisible();
    await expandBtn.click();

    // Style tab is active by default — Data-Driven Style section should be visible.
    await expect(page.getByText('Data-Driven Style')).toBeVisible();

    // Select the first available column in the data-driven column dropdown
    const columnTrigger = page.getByText('Select column');
    await expect(columnTrigger).toBeVisible();
    await columnTrigger.click();

    // Wait for dropdown options and select the first one
    const firstOption = page.getByRole('option').first();
    await expect(firstOption).toBeVisible({ timeout: 5_000 });
    const selectedColumn = (await firstOption.textContent())?.trim();
    expect(selectedColumn).toBeTruthy();
    await firstOption.click();

    // Wait for category colors to load (API fetches distinct values for the column)
    await expect(page.getByText('Colors', { exact: true })).toBeVisible({ timeout: 10_000 });

    // Verify at least one category color swatch button appears
    const swatches = page.locator('button.w-5.h-5.rounded-sm');
    await expect(swatches.first()).toBeVisible({ timeout: 5_000 });
    const swatchCount = await swatches.count();
    expect(swatchCount).toBeGreaterThanOrEqual(1);

    // Verify the categorical style summary is applied to the active layer.
    await expect(page.getByText(`Styled by: ${selectedColumn}`)).toBeVisible();
  });

  test('colors preserved after collapse and re-expand', async ({ page }) => {
    await page.goto(`/maps/${mapId}`);
    await expect(page.locator('canvas.maplibregl-canvas')).toBeVisible({ timeout: 15_000 });

    // Expand and configure categorical styling
    await page.getByRole('button', { name: 'Expand options' }).click();
    await expect(page.getByText('Data-Driven Style')).toBeVisible();

    const columnTrigger = page.getByText('Select column');
    await expect(columnTrigger).toBeVisible();
    await columnTrigger.click();
    await page.getByRole('option').first().click();

    // Wait for colors to appear
    await expect(page.getByText('Colors', { exact: true })).toBeVisible({ timeout: 10_000 });
    const swatches = page.locator('button.w-5.h-5.rounded-sm');
    await expect(swatches.first()).toBeVisible({ timeout: 5_000 });
    const initialCount = await swatches.count();
    const firstColor = await swatches.first().getAttribute('title');
    expect(firstColor).toBeTruthy();

    // Return to the layer list through the current sidebar-local inspector control.
    await page.getByRole('button', { name: 'Back to layers' }).click();
    await expect(page.getByText('Data-Driven Style')).not.toBeVisible();

    // Re-expand
    await page.getByRole('button', { name: 'Expand options' }).click();

    // Colors should still be present with the same count and first color
    await expect(page.getByText('Colors', { exact: true })).toBeVisible({ timeout: 5_000 });
    const afterSwatches = page.locator('button.w-5.h-5.rounded-sm');
    await expect(afterSwatches.first()).toBeVisible({ timeout: 5_000 });
    expect(await afterSwatches.count()).toBe(initialCount);
    expect(await afterSwatches.first().getAttribute('title')).toBe(firstColor);
  });

  test('filter editor remains reachable after returning to the map stack', async ({ page }) => {
    await page.goto(`/maps/${mapId}`);
    await expect(page.locator('canvas.maplibregl-canvas')).toBeVisible({ timeout: 15_000 });

    // Expand the layer
    await page.getByRole('button', { name: 'Expand options' }).click();

    // Switch to Filter tab and add a filter condition
    await page.getByRole('tab', { name: 'Filter', exact: true }).click();
    await page.getByRole('button', { name: 'Add filter' }).click();
    await page.getByRole('textbox', { name: 'Value' }).fill('1');

    await page.getByRole('button', { name: 'Back to layers' }).click();
    const layerRow = page.locator('[data-testid^="layer-item"]').first();
    await expect(layerRow).toBeVisible();
    await layerRow.getByRole('button', { name: 'Expand options' }).click();
    await page.getByRole('tab', { name: 'Filter', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Add filter' })).toBeVisible();
  });

  test('label toggle persists after returning to the map stack', async ({ page }) => {
    await page.goto(`/maps/${mapId}`);
    await expect(page.locator('canvas.maplibregl-canvas')).toBeVisible({ timeout: 15_000 });

    // Expand the layer
    await page.getByRole('button', { name: 'Expand options' }).click();

    // Switch to Labels tab and toggle labels on
    await page.getByRole('tab', { name: 'Labels', exact: true }).click();
    const labelsSwitch = page
      .getByRole('tabpanel', { name: 'Labels' })
      .getByRole('switch');
    await expect(labelsSwitch).toBeVisible();
    await labelsSwitch.click();

    await page.getByRole('button', { name: 'Back to layers' }).click();
    const layerRow = page.locator('[data-testid^="layer-item"]').first();
    await expect(layerRow).toBeVisible();
    await layerRow.getByRole('button', { name: 'Expand options' }).click();
    await page.getByRole('tab', { name: 'Labels', exact: true }).click();
    await expect(
      page.getByRole('tabpanel', { name: 'Labels' }).getByRole('switch', { name: 'Enable labels' }),
    ).toBeChecked();
  });
});
