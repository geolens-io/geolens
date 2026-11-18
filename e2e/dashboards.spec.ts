import type { APIRequestContext, Browser, Page } from '@playwright/test';
import { test, expect } from './helpers/session';
import { seedCategoryDataset, seedDataset, deleteDataset } from './helpers/catalog';
import { authHeaders, createMap, deleteMap, isMapUpdateResponse, waitForBuilder } from './helpers/maps';

const BASE_URL = process.env.E2E_BASE_URL ?? 'http://localhost:8080';

/** A page with no session, as an anonymous reader opens a public map or share link. */
async function anonymousPage(browser: Browser): Promise<Page> {
  const context = await browser.newContext({ storageState: { cookies: [], origins: [] } });
  return context.newPage();
}

/** A public map with the dataset as its one layer, and a share token for it. */
async function publicMapWithShareLink(request: APIRequestContext, datasetId: string) {
  const mapId = await createMap(request, `Dashboard E2E ${Date.now()}`);
  const layer = await request.post(`${BASE_URL}/api/maps/${mapId}/layers/`, {
    headers: authHeaders(),
    data: { dataset_id: datasetId },
  });
  expect(layer.ok()).toBe(true);
  const madePublic = await request.put(`${BASE_URL}/api/maps/${mapId}`, {
    headers: authHeaders(),
    data: { visibility: 'public' },
  });
  expect(madePublic.ok()).toBe(true);
  const share = await request.post(`${BASE_URL}/api/maps/${mapId}/share/`, { headers: authHeaders() });
  expect(share.ok()).toBe(true);
  return { mapId, shareToken: ((await share.json()) as { token: string }).token };
}

/** Public maps show anonymous readers only public datasets. */
async function publishDataset(datasetId: string) {
  const publish = await fetch(`${BASE_URL}/api/datasets/${datasetId}`, {
    method: 'PATCH',
    headers: authHeaders(),
    body: JSON.stringify({ visibility: 'public', record_status: 'published' }),
  });
  expect(publish.ok).toBe(true);
}

test.describe('Map dashboards', () => {
  let datasetId = '';
  let datasetTitle = '';

  test.beforeAll(async () => {
    // seedDataset can poll for up to 60 s.
    test.setTimeout(120_000);
    const seeded = await seedDataset('Dashboard E2E Dataset');
    datasetId = seeded.id;
    datasetTitle = seeded.title;
    await publishDataset(datasetId);
  });

  test.afterAll(async () => {
    if (datasetId) await deleteDataset(datasetId, datasetTitle);
  });

  test('an author builds a dashboard and anonymous readers see it', async ({ page, browser, request }) => {
    const { mapId, shareToken } = await publicMapWithShareLink(request, datasetId);
    try {
      await page.goto(`/maps/${mapId}`);
      await waitForBuilder(page);

      await page.locator('[data-rail-button="dashboard"]').click();
      await page.getByRole('button', { name: 'Add Indicator' }).click();
      await page.getByRole('button', { name: 'Add Bar chart' }).click();
      // Both preview against the layer: the fixture has one point.
      await expect(page.getByRole('region', { name: 'Preview' })).toHaveCount(2, { timeout: 15_000 });

      const saved = page.waitForResponse((response) => isMapUpdateResponse(response, mapId));
      await page.getByRole('button', { name: /save/i }).first().click();
      expect((await saved).status()).toBe(200);
      await expect(page.locator('[data-sonner-toast][data-type="error"]')).toHaveCount(0);

      await page.reload();
      await waitForBuilder(page);
      // A map with widgets opens its dashboard panel on load.
      await expect(page.locator('[data-rail-button="dashboard"]')).toHaveAttribute('aria-pressed', 'true');
      await expect(page.getByRole('button', { name: /^Remove / })).toHaveCount(2);

      const reader = await anonymousPage(browser);
      try {
        await reader.goto(`/maps/${mapId}`);
        const panel = reader.getByRole('region', { name: 'Dashboard' });
        await expect(panel).toBeVisible({ timeout: 20_000 });
        await expect(panel.getByRole('article')).toHaveCount(2);
        // The indicator counts the fixture's one point.
        await expect(panel.getByText('1', { exact: true }).first()).toBeVisible({ timeout: 15_000 });

        await panel.getByRole('button', { name: 'Hide dashboard' }).click();
        await expect(panel.getByRole('article')).toHaveCount(0);
        await panel.getByRole('button', { name: 'Open dashboard' }).click();
        await expect(panel.getByRole('article')).toHaveCount(2);

        await reader.goto(`/m/${shareToken}`);
        await expect(reader.getByRole('region', { name: 'Dashboard' }).getByRole('article')).toHaveCount(2, {
          timeout: 20_000,
        });

        // An embed can open with the dashboard collapsed.
        await reader.goto(`/m/${shareToken}?embed=true&dashboard=collapsed`);
        await expect(reader.getByRole('button', { name: 'Open dashboard' })).toBeVisible({ timeout: 20_000 });
      } finally {
        await reader.context().close();
      }
    } finally {
      await deleteMap(request, mapId);
    }
  });
});

test.describe('Map dashboard linking', () => {
  let datasetId = '';
  let datasetTitle = '';

  test.beforeAll(async () => {
    test.setTimeout(120_000);
    const seeded = await seedCategoryDataset('Dashboard Linking E2E');
    datasetId = seeded.id;
    datasetTitle = seeded.title;
    await publishDataset(datasetId);
  });

  test.afterAll(async () => {
    if (datasetId) await deleteDataset(datasetId, datasetTitle);
  });

  test('a reader clicks a bar and the other widgets on the layer follow until the chip clears it', async ({
    page,
    browser,
    request,
  }) => {
    const { mapId, shareToken } = await publicMapWithShareLink(request, datasetId);
    try {
      await page.goto(`/maps/${mapId}`);
      await waitForBuilder(page);
      await page.locator('[data-rail-button="dashboard"]').click();
      for (const type of ['Bar chart', 'Indicator', 'Histogram', 'Category selector']) {
        await page.getByRole('button', { name: `Add ${type}` }).click();
      }
      await expect(page.getByRole('region', { name: 'Preview' })).toHaveCount(4, { timeout: 15_000 });
      // New widgets start on the fixture's text and numeric columns.
      await expect(page.getByRole('combobox', { name: 'Group by' })).toHaveText('kind');
      await expect(page.getByRole('combobox', { name: 'Column' }).nth(0)).toHaveText('height');

      const saved = page.waitForResponse((response) => isMapUpdateResponse(response, mapId));
      await page.getByRole('button', { name: /save/i }).first().click();
      expect((await saved).status()).toBe(200);

      const reader = await anonymousPage(browser);
      try {
        for (const path of [`/maps/${mapId}`, `/m/${shareToken}`]) {
          await reader.goto(path);
          const panel = reader.getByRole('region', { name: 'Dashboard' });
          await expect(panel.getByRole('article')).toHaveCount(4, { timeout: 20_000 });
          const [chart, indicator, histogram, selector] = await panel.getByRole('article').all();
          await expect(indicator.getByText('6', { exact: true })).toBeVisible({ timeout: 15_000 });
          await expect(selector.getByRole('checkbox')).toHaveCount(3);

          await chart.locator('svg[aria-roledescription="bar chart"] g', { hasText: 'park' }).click();

          await expect(indicator.getByText('3', { exact: true })).toBeVisible({ timeout: 15_000 });
          await expect(selector.getByRole('checkbox')).toHaveCount(1);
          // The histogram re-bins the parks' whole-number heights, one bin per value.
          await histogram.getByText('Show data table').click();
          await expect(histogram.getByRole('rowheader')).toHaveText(['1', '2', '3']);
          // The chart keeps every bar and marks the pick.
          await expect(chart.locator('svg g[data-picked] text')).toHaveText(['✓', 'park', '3']);
          await expect(chart.locator('svg rect.fill-primary')).toHaveCount(3);

          // The chip names the column by its attribute title.
          const chip = panel.getByRole('button', { name: /^Remove filter Kind: park/ });
          await expect(chip).toBeVisible();
          await chip.click();
          await expect(chip).toHaveCount(0);
          await expect(indicator.getByText('6', { exact: true })).toBeVisible({ timeout: 15_000 });
          await expect(selector.getByRole('checkbox')).toHaveCount(3);
          await expect(histogram.getByRole('rowheader')).toHaveText(['1', '2', '3', '4', '5', '6']);
        }
      } finally {
        await reader.context().close();
      }
    } finally {
      await deleteMap(request, mapId);
    }
  });
});

test.describe('Dashboard widgets and layouts', () => {
  let datasetId = '';
  let datasetTitle = '';

  test.beforeAll(async () => {
    test.setTimeout(120_000);
    const seeded = await seedCategoryDataset('Dashboard Widgets E2E');
    datasetId = seeded.id;
    datasetTitle = seeded.title;
    await publishDataset(datasetId);
  });

  test.afterAll(async () => {
    if (datasetId) await deleteDataset(datasetId, datasetTitle);
  });

  async function openDashboardEditor(page: Page, mapId: string, widgets: string[]) {
    await page.goto(`/maps/${mapId}`);
    await waitForBuilder(page);
    await page.locator('[data-rail-button="dashboard"]').click();
    for (const type of widgets) await page.getByRole('button', { name: `Add ${type}` }).click();
    await expect(page.getByRole('region', { name: 'Preview' })).toHaveCount(widgets.length, { timeout: 15_000 });
  }

  async function save(page: Page, mapId: string) {
    const saved = page.waitForResponse((response) => isMapUpdateResponse(response, mapId));
    await page.getByRole('button', { name: /save/i }).first().click();
    expect((await saved).status()).toBe(200);
  }

  test('a reader sees a table and a feature list, and picking a feature moves the map', async ({
    page,
    browser,
    request,
  }) => {
    const { mapId } = await publicMapWithShareLink(request, datasetId);
    try {
      await openDashboardEditor(page, mapId, ['Table', 'Feature list']);
      await save(page, mapId);

      const reader = await anonymousPage(browser);
      try {
        await reader.goto(`/maps/${mapId}`);
        const panel = reader.getByRole('region', { name: 'Dashboard' });
        await expect(panel.getByRole('article')).toHaveCount(2, { timeout: 20_000 });
        const table = panel.getByRole('table');
        await expect(table).toBeVisible({ timeout: 15_000 });
        await expect(table.getByRole('columnheader').first()).toBeVisible();

        const items = panel.getByRole('button', { name: 'Zoom to feature on the map' });
        await expect(items.first()).toBeVisible({ timeout: 15_000 });
        const readout = reader.locator('[data-coord-readout="true"]');
        await expect(readout).toContainText(/z \d/, { timeout: 20_000 });
        const before = await readout.innerText();
        await items.first().click();
        await expect.poll(async () => readout.innerText(), { timeout: 15_000 }).not.toBe(before);
      } finally {
        await reader.context().close();
      }
    } finally {
      await deleteMap(request, mapId);
    }
  });

  test('an indicator with a reference value shows the reference and the difference', async ({
    page,
    browser,
    request,
  }) => {
    const { mapId } = await publicMapWithShareLink(request, datasetId);
    try {
      await openDashboardEditor(page, mapId, ['Indicator']);
      await page.getByLabel('Reference value').fill('3');
      await save(page, mapId);

      const reader = await anonymousPage(browser);
      try {
        await reader.goto(`/maps/${mapId}`);
        const indicator = reader.getByRole('region', { name: 'Dashboard' }).getByRole('article');
        await expect(indicator).toHaveCount(1, { timeout: 20_000 });
        await expect(indicator.getByText('Reference: 3')).toBeVisible({ timeout: 15_000 });
        await expect(indicator).toContainText(/[▲▼]/);
      } finally {
        await reader.context().close();
      }
    } finally {
      await deleteMap(request, mapId);
    }
  });

  test("an indicator's own filter narrows its count for the author and for readers", async ({
    page,
    browser,
    request,
  }) => {
    const { mapId } = await publicMapWithShareLink(request, datasetId);
    try {
      await openDashboardEditor(page, mapId, ['Indicator']);
      const preview = page.getByRole('region', { name: 'Preview' });
      // The fixture has six points, three of them parks.
      await expect(preview.getByText('6', { exact: true })).toBeVisible({ timeout: 15_000 });

      await expect(page.getByText('Only count features where…')).toBeVisible();
      await page.getByRole('button', { name: 'Add filter' }).click();
      await page.getByRole('combobox', { name: 'Field' }).click();
      await page.getByRole('option', { name: 'kind', exact: true }).click();
      await page.getByRole('textbox', { name: 'Value' }).fill('park');
      await expect(preview.getByText('3', { exact: true })).toBeVisible({ timeout: 15_000 });
      await save(page, mapId);

      const reader = await anonymousPage(browser);
      try {
        await reader.goto(`/maps/${mapId}`);
        const indicator = reader.getByRole('region', { name: 'Dashboard' }).getByRole('article');
        await expect(indicator).toHaveCount(1, { timeout: 20_000 });
        await expect(indicator.getByText('3', { exact: true })).toBeVisible({ timeout: 15_000 });
      } finally {
        await reader.context().close();
      }
    } finally {
      await deleteMap(request, mapId);
    }
  });

  test('a dashboard that hides its map shows the widgets without a map', async ({ page, browser, request }) => {
    const { mapId } = await publicMapWithShareLink(request, datasetId);
    try {
      await openDashboardEditor(page, mapId, ['Indicator', 'Feature list']);
      // The note appears on widgets that follow the map view.
      await page.getByRole('combobox', { name: 'Covers' }).first().click();
      await page.getByRole('option', { name: "What's in the map view" }).click();
      await page.getByRole('switch', { name: /hide the map/i }).click();
      await save(page, mapId);

      const reader = await anonymousPage(browser);
      try {
        await reader.goto(`/maps/${mapId}`);
        const panel = reader.getByRole('region', { name: 'Dashboard' });
        await expect(panel.getByRole('article')).toHaveCount(2, { timeout: 20_000 });
        await expect(reader.locator('canvas.maplibregl-canvas')).toHaveCount(0);
        await expect(panel.getByText('Showing the whole layer: this dashboard hides its map.').first()).toBeVisible();
        await expect(panel.getByRole('button', { name: 'Zoom to feature on the map' })).toHaveCount(0);
      } finally {
        await reader.context().close();
      }
    } finally {
      await deleteMap(request, mapId);
    }
  });

  test('a dashboard with a dark reader theme opens dark', async ({ page, browser, request }) => {
    const { mapId } = await publicMapWithShareLink(request, datasetId);
    try {
      await openDashboardEditor(page, mapId, ['Indicator']);
      await page.getByRole('combobox', { name: 'Reader theme' }).click();
      await page.getByRole('option', { name: 'Dark' }).click();
      await save(page, mapId);

      const reader = await anonymousPage(browser);
      try {
        await reader.goto(`/maps/${mapId}`);
        await expect(reader.getByRole('region', { name: 'Dashboard' })).toBeVisible({ timeout: 20_000 });
        await expect
          .poll(() => reader.evaluate(() => document.documentElement.classList.contains('dark')))
          .toBe(true);
      } finally {
        await reader.context().close();
      }
    } finally {
      await deleteMap(request, mapId);
    }
  });
});
