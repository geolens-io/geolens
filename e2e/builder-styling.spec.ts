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

    // Phase 1034 retired the "Expand options" button — clicking the unified
    // stack row opens the LayerEditorPanel flyout directly. Phase 1035 inserted
    // a basemap-group row at the top of the stack, so the actual vector layer
    // row is at index 1 (or any row not matching the basemap-group ID).
    const dataRow = page
      .locator('[id^="stack-row-"]:not([id="stack-row-basemap-group"])')
      .first();
    await expect(dataRow).toBeVisible();
    await dataRow.click();
    await expect(page.getByTestId('builder-layer-editor')).toBeVisible({ timeout: 5_000 });

    // The Appearance section is open by default and surfaces the Data-Driven
    // Style controls when a column supports it.
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

  test('colors preserved after closing and reopening the layer editor', async ({ page }) => {
    await page.goto(`/maps/${mapId}`);
    await expect(page.locator('canvas.maplibregl-canvas')).toBeVisible({ timeout: 15_000 });

    const dataRow = page
      .locator('[id^="stack-row-"]:not([id="stack-row-basemap-group"])')
      .first();
    await expect(dataRow).toBeVisible();

    // Configure data-driven styling fresh — zustand layer state resets on each
    // page load, so don't rely on test 1's in-session state.
    await dataRow.click();
    const editor = page.getByTestId('builder-layer-editor');
    await expect(editor).toBeVisible({ timeout: 5_000 });
    await expect(editor.getByText('Data-Driven Style')).toBeVisible();

    await editor.getByText('Select column').click();
    const firstOption = page.getByRole('option').first();
    await expect(firstOption).toBeVisible({ timeout: 5_000 });
    await firstOption.click();

    await expect(editor.getByText('Colors', { exact: true })).toBeVisible({ timeout: 10_000 });
    const swatches = editor.locator('button.w-5.h-5.rounded-sm');
    await expect(swatches.first()).toBeVisible({ timeout: 5_000 });
    const initialCount = await swatches.count();
    const firstColor = await swatches.first().getAttribute('title');
    expect(initialCount).toBeGreaterThanOrEqual(1);
    expect(firstColor).toBeTruthy();

    // Close the flyout. Layer state lives in the builder's zustand store, so
    // re-opening the same row must rehydrate the configured swatches.
    await editor.getByRole('button', { name: /close layer editor/i }).click();
    await expect(editor).not.toBeVisible();

    await dataRow.click();
    await expect(editor).toBeVisible({ timeout: 5_000 });
    const afterSwatches = editor.locator('button.w-5.h-5.rounded-sm');
    await expect(afterSwatches.first()).toBeVisible({ timeout: 5_000 });
    expect(await afterSwatches.count()).toBe(initialCount);
    expect(await afterSwatches.first().getAttribute('title')).toBe(firstColor);
  });

  test('filter editor remains reachable after returning to the map stack', async ({ page }) => {
    await page.goto(`/maps/${mapId}`);
    await expect(page.locator('canvas.maplibregl-canvas')).toBeVisible({ timeout: 15_000 });

    const dataRow = page
      .locator('[id^="stack-row-"]:not([id="stack-row-basemap-group"])')
      .first();
    await expect(dataRow).toBeVisible();
    await dataRow.click();

    const editor = page.getByTestId('builder-layer-editor');
    await expect(editor).toBeVisible({ timeout: 5_000 });

    // Phase 1034 replaced the per-tab editor with collapsible sections; the
    // Filter section is collapsed by default and exposes a section trigger
    // button whose accessible name starts with "Filter".
    await editor.getByRole('button', { name: /^Filter/i }).click();
    await expect(editor.getByRole('button', { name: 'Add filter' })).toBeVisible();

    await editor.getByRole('button', { name: /close layer editor/i }).click();
    await expect(editor).not.toBeVisible();

    await dataRow.click();
    await expect(editor).toBeVisible({ timeout: 5_000 });
    await editor.getByRole('button', { name: /^Filter/i }).click();
    await expect(editor.getByRole('button', { name: 'Add filter' })).toBeVisible();
  });

  test('label toggle persists after returning to the map stack', async ({ page }) => {
    await page.goto(`/maps/${mapId}`);
    await expect(page.locator('canvas.maplibregl-canvas')).toBeVisible({ timeout: 15_000 });

    const dataRow = page
      .locator('[id^="stack-row-"]:not([id="stack-row-basemap-group"])')
      .first();
    await expect(dataRow).toBeVisible();
    await dataRow.click();

    const editor = page.getByTestId('builder-layer-editor');
    await expect(editor).toBeVisible({ timeout: 5_000 });

    await editor.getByRole('button', { name: /^Labels/i }).click();
    const labelsSwitch = editor.getByRole('switch', { name: 'Enable labels' });
    await expect(labelsSwitch).toBeVisible();
    await labelsSwitch.click();
    await expect(labelsSwitch).toBeChecked();

    await editor.getByRole('button', { name: /close layer editor/i }).click();
    await expect(editor).not.toBeVisible();

    await dataRow.click();
    await expect(editor).toBeVisible({ timeout: 5_000 });
    await editor.getByRole('button', { name: /^Labels/i }).click();
    await expect(editor.getByRole('switch', { name: 'Enable labels' })).toBeChecked();
  });
});
