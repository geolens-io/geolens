import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import fs from 'fs';
import path from 'path';

const AUTH_FILE = path.join(__dirname, '../playwright/.auth/user.json');
const BASE_URL = process.env.E2E_BASE_URL ?? 'http://localhost:8080';

interface DatasetListItem {
  id: string;
  record_type?: string | null;
  is_dem?: boolean | null;
}

interface MapLayerListItem {
  id: string;
  dataset_id: string;
  sort_order?: number | null;
  style_config?: Record<string, unknown> | null;
}

interface MapDetails {
  id: string;
  name: string;
  visibility?: string | null;
  layers?: MapLayerListItem[];
}

interface ConsoleGate {
  errors: string[];
  warnings: string[];
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

function getAuthToken(): string {
  const parsed = JSON.parse(getAuthEntry()) as { state?: { token?: string } };
  const token = parsed.state?.token;
  if (!token) throw new Error('Could not extract auth token from storage state');
  return token;
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

function attachConsoleGate(page: Page): ConsoleGate {
  const errors: string[] = [];
  const warnings: string[] = [];
  page.on('console', (msg) => {
    if (msg.type() === 'error') errors.push(msg.text());
    if (msg.type() === 'warning') warnings.push(msg.text());
  });
  return { errors, warnings };
}

function assertConsoleClean(gate: ConsoleGate) {
  expect(gate.errors, `Console errors:\n${gate.errors.join('\n')}`).toHaveLength(0);
  const filtered = gate.warnings.filter(
    (warning) =>
      !warning.includes('MapLibre') &&
      !warning.includes('GL Driver') &&
      !warning.includes('GPU stall') &&
      !warning.includes('Unable to load glyph range') &&
      !warning.includes('Rendering codepoint'),
  );
  expect(filtered, `Console warnings:\n${filtered.join('\n')}`).toHaveLength(0);
}

async function getDatasets(request: APIRequestContext): Promise<DatasetListItem[]> {
  const response = await request.get(`${BASE_URL}/api/datasets/?limit=100`, {
    headers: authHeaders(),
  });
  expect(response.ok(), `GET /api/datasets failed: ${response.status()}`).toBe(true);
  const payload = await response.json() as {
    datasets?: DatasetListItem[];
    items?: DatasetListItem[];
  };
  return payload.datasets ?? payload.items ?? [];
}

async function createMap(request: APIRequestContext, name: string): Promise<string> {
  const response = await request.post(`${BASE_URL}/api/maps/`, {
    headers: authHeaders(),
    data: { name, description: 'Temporary map for builder hardening coverage' },
  });
  expect(response.ok(), `Create map failed: ${response.status()} ${await response.text()}`).toBe(true);
  return ((await response.json()) as { id: string }).id;
}

async function deleteMap(request: APIRequestContext, mapId: string) {
  await request.delete(`${BASE_URL}/api/maps/${mapId}`, {
    headers: { Authorization: `Bearer ${getAuthToken()}` },
  });
}

async function addLayer(request: APIRequestContext, mapId: string, datasetId: string) {
  const response = await request.post(`${BASE_URL}/api/maps/${mapId}/layers/`, {
    headers: authHeaders(),
    data: { dataset_id: datasetId },
  });
  expect(response.ok(), `Add layer failed: ${response.status()} ${await response.text()}`).toBe(true);
}

async function getMapDetails(request: APIRequestContext, mapId: string): Promise<MapDetails> {
  const response = await request.get(`${BASE_URL}/api/maps/${mapId}`, {
    headers: authHeaders(),
  });
  expect(response.ok(), `GET /api/maps/${mapId} failed: ${response.status()}`).toBe(true);
  return await response.json() as MapDetails;
}

function withFolderGroupMetadata(
  layer: MapLayerListItem,
  groupId: string,
  groupName: string,
) {
  const styleConfig = layer.style_config && typeof layer.style_config === 'object'
    ? layer.style_config
    : {};
  const builder = styleConfig.builder && typeof styleConfig.builder === 'object' && !Array.isArray(styleConfig.builder)
    ? styleConfig.builder as Record<string, unknown>
    : {};
  return {
    id: layer.id,
    sort_order: layer.sort_order ?? 0,
    style_config: {
      ...styleConfig,
      builder: {
        ...builder,
        folderGroupId: groupId,
        folderGroupName: groupName,
        folderGroupExpanded: true,
      },
    },
  };
}

async function seedFolderGroup(
  request: APIRequestContext,
  mapId: string,
  layers: MapLayerListItem[],
  groupId: string,
  groupName: string,
) {
  const response = await request.patch(`${BASE_URL}/api/maps/${mapId}/layers`, {
    headers: authHeaders(),
    data: {
      updated: layers.map((layer) => withFolderGroupMetadata(layer, groupId, groupName)),
    },
  });
  expect(response.ok(), `Seed folder group failed: ${response.status()} ${await response.text()}`).toBe(true);
}

async function createLayeredMap(
  request: APIRequestContext,
  name: string,
  layerCount: number,
) {
  const datasets = await getDatasets(request);
  const vector = datasets.find((dataset) => dataset.record_type === 'vector_dataset') ?? datasets[0];
  const raster = datasets.find((dataset) => dataset.record_type === 'raster_dataset');
  expect(vector?.id, 'At least one dataset is required for builder hardening E2E').toBeTruthy();

  const mapId = await createMap(request, name);
  for (let i = 0; i < layerCount; i++) {
    const dataset = raster && (i === 3 || i === 11) ? raster : vector;
    await addLayer(request, mapId, dataset.id);
  }
  return { mapId, hasRaster: Boolean(raster) };
}

async function createPublicSharedMap(request: APIRequestContext, name: string) {
  const mapId = await createMap(request, name);
  const update = await request.put(`${BASE_URL}/api/maps/${mapId}`, {
    headers: authHeaders(),
    data: { visibility: 'public' },
  });
  expect(update.ok(), `Publish map failed: ${update.status()}`).toBe(true);
  const share = await request.post(`${BASE_URL}/api/maps/${mapId}/share/`, {
    headers: authHeaders(),
    data: {},
  });
  expect(share.ok(), `Create share token failed: ${share.status()}`).toBe(true);
  return { mapId, shareToken: ((await share.json()) as { token: string }).token };
}

test.describe('Builder residual-risk hardening', () => {
  test.slow();

  test('builder shell loads cleanly on the current browser engine', async ({ page, request }) => {
    const gate = attachConsoleGate(page);
    const { mapId } = await createLayeredMap(request, `E2E Builder Browser Shell ${Date.now()}`, 1);
    try {
      await seedAuth(page);
      await page.goto(`/maps/${mapId}`);
      await waitForBuilder(page);
      await expect(page.locator('text=Something went wrong')).toHaveCount(0);
      assertConsoleClean(gate);
    } finally {
      await deleteMap(request, mapId);
    }
  });

  test('large mixed grouped stack supports duplicate, keyboard reorder, save, and reload', async ({ page, request, browserName }) => {
    test.skip(browserName !== 'chromium', 'large stack manipulation is covered in Chromium; cross-browser shell has a separate smoke');

    const gate = attachConsoleGate(page);
    const { mapId, hasRaster } = await createLayeredMap(request, `E2E Builder Hardening Large ${Date.now()}`, 18);
    try {
      const initial = await getMapDetails(request, mapId);
      const initialLayers = initial.layers ?? [];
      expect(initialLayers.length).toBeGreaterThanOrEqual(18);
      const groupedChildren = initialLayers.slice(0, 8);
      const groupId = `group-${Date.now()}`;
      const groupName = 'Large mixed group';
      await seedFolderGroup(request, mapId, groupedChildren, groupId, groupName);

      await seedAuth(page);
      await page.setViewportSize({ width: 1440, height: 900 });
      await page.goto(`/maps/${mapId}`);
      await waitForBuilder(page);

      await expect(page.getByText(groupName).first()).toBeVisible({ timeout: 10_000 });
      await expect(page.locator('[data-testid^="folder-group-children-"]').first()).toBeVisible();
      const stackRows = page.locator('[id^="stack-row-"]');
      await expect(stackRows).toHaveCount(initialLayers.length + 2, { timeout: 10_000 });
      if (hasRaster) {
        await expect(page.locator(`#stack-row-${initialLayers[3].id}`)).toBeVisible();
        await expect(page.locator(`#stack-row-${initialLayers[11].id}`)).toBeVisible();
      }

      const duplicateTarget = initialLayers[8] ?? initialLayers[0];
      const duplicateResponse = page.waitForResponse(
        (response) => response.url().includes(`/api/maps/${mapId}/layers`) && response.request().method() === 'POST',
      );
      const duplicateRow = page.locator(`#stack-row-${duplicateTarget.id}`);
      await duplicateRow.hover();
      await duplicateRow.locator('[data-kebab-trigger]').click();
      await page.getByRole('menuitem', { name: /^Duplicate$/i }).click();
      expect([200, 201]).toContain((await duplicateResponse).status());

      await expect.poll(async () => (await getMapDetails(request, mapId)).layers?.length ?? 0)
        .toBe(initialLayers.length + 1);

      const looseA = initialLayers[8];
      const looseB = initialLayers[9];
      expect(looseA?.id).toBeTruthy();
      expect(looseB?.id).toBeTruthy();

      const dragHandle = page
        .locator(`#stack-row-${looseB.id}`)
        .getByRole('button', { name: /drag to reorder/i });
      await dragHandle.focus();
      await page.keyboard.press('Space');
      await page.keyboard.press('ArrowUp');
      await page.keyboard.press('Space');

      await expect.poll(async () => {
        const ids = await stackRows.evaluateAll((elements) => elements.map((element) => element.id));
        return ids.indexOf(`stack-row-${looseB.id}`) < ids.indexOf(`stack-row-${looseA.id}`);
      }).toBe(true);

      const patchResponse = page.waitForResponse(
        (response) => response.url().includes(`/api/maps/${mapId}/layers`) && response.request().method() === 'PATCH',
      );
      const metadataResponse = page.waitForResponse(
        (response) => response.url().includes(`/api/maps/${mapId}`) && response.request().method() === 'PUT',
      );
      await page.getByRole('button', { name: /save/i }).first().click();
      expect((await patchResponse).status()).toBe(200);
      expect((await metadataResponse).status()).toBe(200);
      await expect(page.locator('[data-sonner-toast][data-type="error"]')).toHaveCount(0);

      await page.reload();
      await waitForBuilder(page);
      await expect(page.getByText(groupName).first()).toBeVisible({ timeout: 10_000 });
      await expect.poll(async () => {
        const ids = await stackRows.evaluateAll((elements) => elements.map((element) => element.id));
        return ids.indexOf(`stack-row-${looseB.id}`) < ids.indexOf(`stack-row-${looseA.id}`);
      }).toBe(true);
      assertConsoleClean(gate);
    } finally {
      await deleteMap(request, mapId);
    }
  });

  test('tile failures and a failed metadata save leave the builder recoverable', async ({ page, request, browserName }) => {
    test.skip(browserName !== 'chromium', 'network failure recovery is covered in the primary browser project');

    const { mapId } = await createLayeredMap(request, `E2E Builder Network ${Date.now()}`, 1);
    try {
      await seedAuth(page);
      await page.route('**/tiles/**', async (route) => {
        await new Promise((resolve) => setTimeout(resolve, 150));
        await route.fulfill({ status: 503, body: '' });
      });

      await page.goto(`/maps/${mapId}`);
      await waitForBuilder(page);
      await expect(page.locator('text=Something went wrong')).toHaveCount(0);

      await page.unroute('**/tiles/**');
      let failedOnce = false;
      await page.route(`**/api/maps/${mapId}`, async (route) => {
        if (route.request().method() === 'PUT' && !failedOnce) {
          failedOnce = true;
          await new Promise((resolve) => setTimeout(resolve, 250));
          await route.fulfill({
            status: 500,
            contentType: 'application/json',
            body: JSON.stringify({ detail: 'injected save failure' }),
          });
          return;
        }
        await route.continue();
      });

      await page.getByRole('button', { name: /notes/i }).click();
      await page.getByPlaceholder(/add notes/i).fill('Network recovery smoke note');
      await page.getByRole('button', { name: /save/i }).first().click();
      await expect(page.getByTestId('builder-save-status')).toHaveAttribute('data-save-status', 'failed');

      const retryResponse = page.waitForResponse(
        (response) => response.url().includes(`/api/maps/${mapId}`) && response.request().method() === 'PUT' && response.status() === 200,
      );
      await page.getByTestId('builder-save-status').click();
      await retryResponse;
      await expect(page.getByTestId('builder-save-status')).not.toHaveAttribute('data-save-status', 'failed');

      await page.getByRole('button', { name: /history/i }).click();
      await expect(page.getByRole('list', { name: /map edit history/i })).toContainText(/Updated map settings/i, { timeout: 10_000 });
    } finally {
      await deleteMap(request, mapId);
    }
  });

  test('public share, embed, and read-only map viewers work while unauthenticated editing stays protected', async ({ browser, request, browserName }) => {
    test.skip(browserName !== 'chromium', 'permission/share variants are covered in the primary browser project');

    const { mapId, shareToken } = await createPublicSharedMap(request, `E2E Public Share ${Date.now()}`);
    const context = await browser.newContext({ storageState: { cookies: [], origins: [] } });
    const viewer = await context.newPage();
    try {
      await viewer.goto(`${BASE_URL}/m/${shareToken}`);
      await expect(viewer.locator('text=Something went wrong')).toHaveCount(0);
      await expect(viewer.locator('canvas.maplibregl-canvas')).toBeVisible({ timeout: 20_000 });

      await viewer.goto(`${BASE_URL}/m/${shareToken}?embed=true`);
      await expect(viewer.locator('text=Something went wrong')).toHaveCount(0);
      await expect(viewer.locator('canvas.maplibregl-canvas')).toBeVisible({ timeout: 20_000 });

      await viewer.goto(`${BASE_URL}/maps/${mapId}`);
      await expect(viewer.locator('canvas.maplibregl-canvas')).toBeVisible({ timeout: 20_000 });
      await expect(viewer.getByText(/^Sign In$/)).toBeVisible();
      await expect(viewer.getByTestId('builder-sidebar')).toHaveCount(0);
    } finally {
      await context.close();
      await deleteMap(request, mapId);
    }
  });

  test('mobile builder sheets expose notes, history, and AI without horizontal overflow', async ({ page, request, browserName }) => {
    test.skip(browserName !== 'chromium', 'mobile ergonomics are covered in the primary browser project');

    const { mapId } = await createLayeredMap(request, `E2E Builder Mobile ${Date.now()}`, 2);
    try {
      await seedAuth(page);
      await page.setViewportSize({ width: 390, height: 844 });
      await page.goto(`/maps/${mapId}`);
      await waitForBuilder(page);

      await page.getByRole('button', { name: /notes/i }).click();
      await expect(page.getByRole('dialog')).toBeVisible();
      await page.getByPlaceholder(/add notes/i).fill('Mobile notes smoke');
      await page.getByRole('button', { name: /close panel/i }).click();

      await page.getByRole('button', { name: /history/i }).click();
      await expect(page.getByRole('dialog')).toBeVisible();
      await page.getByRole('button', { name: /close panel/i }).click();

      await page.getByRole('button', { name: /ask ai|ai unavailable/i }).click();
      await expect(page.getByRole('dialog')).toBeVisible();
      await expect(
        page.getByRole('status').or(page.getByPlaceholder(/describe a map change/i)).first(),
      ).toBeVisible({ timeout: 10_000 });

      const hasHorizontalOverflow = await page.evaluate(
        () => document.documentElement.scrollWidth > window.innerWidth + 1,
      );
      expect(hasHorizontalOverflow).toBe(false);
    } finally {
      await deleteMap(request, mapId);
    }
  });
});

test.describe('Builder hardening cross-browser config smoke', () => {
  test('can create and delete maps through authenticated API in any project', async ({ request }) => {
    const mapId = await createMap(request, `E2E Builder API Cross Browser ${Date.now()}`);
    await deleteMap(request, mapId);
  });
});
