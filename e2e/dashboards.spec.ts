import type { APIRequestContext, Browser, Page } from '@playwright/test';
import { test, expect } from './helpers/session';
import { seedDataset, deleteDataset } from './helpers/catalog';
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

test.describe('Map dashboards', () => {
  let datasetId = '';
  let datasetTitle = '';

  test.beforeAll(async () => {
    // seedDataset can poll for up to 60 s.
    test.setTimeout(120_000);
    const seeded = await seedDataset('Dashboard E2E Dataset');
    datasetId = seeded.id;
    datasetTitle = seeded.title;

    // Public maps show anonymous readers only public datasets.
    const publish = await fetch(`${BASE_URL}/api/datasets/${datasetId}`, {
      method: 'PATCH',
      headers: authHeaders(),
      body: JSON.stringify({ visibility: 'public', record_status: 'published' }),
    });
    expect(publish.ok).toBe(true);
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
      await page.locator('[data-rail-button="dashboard"]').click();
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
