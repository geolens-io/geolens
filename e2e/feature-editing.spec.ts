/**
 * fix(#458 E-07): feature-editing persistence round-trips.
 *
 * The old inline-edit e2e coverage was removed with a "moved to vitest" note,
 * but the vitest suites never covered persistence — no test anywhere walked
 * edit -> reload -> still there. These specs create a throwaway layer via the
 * API, edit through the real UI, and assert the edit survives a reload.
 * The numeric-column case is the live regression guard for E-03 (string
 * payloads into typed columns).
 */
import { test, expect } from '@playwright/test';
import fs from 'fs';
import path from 'path';

const AUTH_FILE = path.join(__dirname, '../playwright/.auth/user.json');
const BASE_URL = process.env.E2E_BASE_URL ?? 'http://localhost:8080';

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

let datasetId: string;
let datasetTitle: string;
let editingWasEnabled: boolean | undefined;
let headers: Record<string, string>;

async function createEditingDataset() {
  datasetTitle = `E2E Feature Editing ${Date.now()}`;
  const layer = await fetch(`${BASE_URL}/api/layers/`, {
    method: 'POST',
    headers,
    body: JSON.stringify({
      title: datasetTitle,
      geometry_type: 'Point',
      columns: [
        { name: 'name', type: 'text' },
        { name: 'population', type: 'integer' },
      ],
    }),
  });
  expect(layer.ok).toBe(true);
  datasetId = (await layer.json()).id;

  const feature = await fetch(`${BASE_URL}/api/datasets/${datasetId}/features/`, {
    method: 'POST',
    headers,
    body: JSON.stringify({
      geometry: { type: 'Point', coordinates: [-73.9857, 40.7484] },
      properties: { name: 'alpha', population: 100 },
    }),
  });
  expect(feature.ok).toBe(true);
}

async function waitForPersistedValue(column: string, expectedValue: string | number) {
  await expect.poll(async () => {
    const response = await fetch(`${BASE_URL}/api/datasets/${datasetId}/rows/?limit=1`, {
      headers,
    });
    if (!response.ok) return undefined;
    const body = await response.json() as { rows?: Array<Record<string, unknown>> };
    return body.rows?.[0]?.[column];
  }, {
    message: `wait for ${column} edit to persist before reloading`,
    timeout: 15_000,
  }).toBe(expectedValue);
}

test.beforeAll(async () => {
  const token = getAuthToken();
  headers = {
    Authorization: `Bearer ${token}`,
    'Content-Type': 'application/json',
  };

  const flags = await fetch(`${BASE_URL}/api/settings/feature-flags/`, { headers });
  expect(flags.ok).toBe(true);
  editingWasEnabled = (await flags.json()).enable_dataset_editing === true;
  if (!editingWasEnabled) {
    const response = await fetch(`${BASE_URL}/api/settings/`, {
      method: 'PUT',
      headers,
      body: JSON.stringify({ settings: { enable_dataset_editing: true } }),
    });
    expect(response.ok).toBe(true);
  }
});

test.beforeEach(async () => {
  await createEditingDataset();
});

test.afterEach(async () => {
  if (!datasetId) return;
  const response = await fetch(`${BASE_URL}/api/datasets/${datasetId}`, {
    method: 'DELETE',
    headers,
    body: JSON.stringify({ confirm_title: datasetTitle }),
  });
  expect(response.ok).toBe(true);
  datasetId = '';
});

test.afterAll(async () => {
  if (editingWasEnabled === false) {
    const response = await fetch(`${BASE_URL}/api/settings/`, {
      method: 'PUT',
      headers,
      body: JSON.stringify({ settings: { enable_dataset_editing: false } }),
    });
    expect(response.ok).toBe(true);
  }
});

test.describe('Feature editing round-trips', () => {

  async function openDataTab(page: import('@playwright/test').Page) {
    await page.goto(`/datasets/${datasetId}#data`);
  }

  async function editCell(
    page: import('@playwright/test').Page,
    currentValue: string,
    nextValue: string,
  ) {
    const cell = page.getByRole('button', { name: currentValue, exact: true });
    await expect(cell).toBeVisible({ timeout: 15_000 });
    await cell.click();
    const input = page.locator('tbody input');
    await expect(input).toBeVisible();
    await input.fill(nextValue);
    await input.press('Enter');
    await expect(page.getByText('Cell updated').first()).toBeVisible({
      timeout: 10_000,
    });
  }

  test('text cell edit persists across reload', async ({ page }) => {
    await openDataTab(page);
    await editCell(page, 'alpha', 'bravo');
    await waitForPersistedValue('name', 'bravo');

    await page.reload();
    await expect(
      page.getByRole('button', { name: 'bravo', exact: true }),
    ).toBeVisible({ timeout: 15_000 });
  });

  test('integer cell edit persists across reload (E-03 live)', async ({ page }) => {
    await openDataTab(page);
    await editCell(page, '100', '250');
    await waitForPersistedValue('population', 250);

    await page.reload();
    await expect(
      page.getByRole('button', { name: '250', exact: true }),
    ).toBeVisible({ timeout: 15_000 });
  });

  test('non-numeric input into an integer cell is rejected with a message', async ({
    page,
  }) => {
    await openDataTab(page);
    const cell = page.getByRole('button', { name: '100', exact: true });
    await expect(cell).toBeVisible({ timeout: 15_000 });
    await cell.click();
    const input = page.locator('tbody input');
    await input.fill('not-a-number');
    await input.press('Enter');
    await expect(page.getByText(/not a valid/i).first()).toBeVisible({
      timeout: 10_000,
    });
    // Value unchanged after reload.
    await page.reload();
    await expect(
      page.getByRole('button', { name: '100', exact: true }),
    ).toBeVisible({ timeout: 15_000 });
  });
});

test.describe('Feature editing affordances (anonymous)', () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test('anonymous viewer of a public dataset sees no editable cells', async ({
    page,
  }) => {
    // Publish the throwaway dataset so an anonymous user can view it.
    const res = await fetch(`${BASE_URL}/api/datasets/${datasetId}`, {
      method: 'PATCH',
      headers,
      body: JSON.stringify({ visibility: 'public', record_status: 'published' }),
    });
    expect(res.ok).toBe(true);

    await page.goto(`/datasets/${datasetId}#data`);
    // Value renders as plain text, not as an edit button.
    await expect(page.getByText('alpha', { exact: true })).toBeVisible({
      timeout: 15_000,
    });
    await expect(
      page.getByRole('button', { name: 'alpha', exact: true }),
    ).toHaveCount(0);
  });
});
