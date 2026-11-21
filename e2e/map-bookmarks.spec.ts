import type { Browser, Page } from '@playwright/test';
import { test, expect } from './helpers/session';
import { authHeaders, createMap, deleteMap, isMapUpdateResponse, waitForBuilder } from './helpers/maps';
import { readMapCamera } from './helpers/stories';

const BASE_URL = process.env.E2E_BASE_URL ?? 'http://localhost:8080';

async function anonymousPage(browser: Browser): Promise<Page> {
  const context = await browser.newContext({ storageState: { cookies: [], origins: [] } });
  return context.newPage();
}

/** Moves the map with its own keyboard handler: arrows pan, plus zooms in. */
async function moveMap(page: Page, keys: string[]) {
  await page.locator('canvas.maplibregl-canvas').focus();
  for (const key of keys) await page.keyboard.press(key);
  // Keyboard moves ease for a moment.
  await page.waitForTimeout(1200);
}

test.describe('Map bookmarks', () => {
  test('an author saves bookmarks by keyboard and readers jump to them', async ({ page, browser, request }) => {
    const mapId = await createMap(request, `Bookmarks E2E ${Date.now()}`);
    try {
      const made = await request.put(`${BASE_URL}/api/maps/${mapId}`, {
        headers: authHeaders(),
        data: { visibility: 'public' },
      });
      expect(made.ok()).toBe(true);
      const share = await request.post(`${BASE_URL}/api/maps/${mapId}/share/`, { headers: authHeaders() });
      expect(share.ok()).toBe(true);
      const shareToken = ((await share.json()) as { token: string }).token;

      await page.goto(`/maps/${mapId}`);
      await waitForBuilder(page);

      const rail = page.locator('[data-rail-button="bookmarks"]');
      await rail.focus();
      await page.keyboard.press('Enter');
      await expect(page.getByText(/save a map view/i)).toBeVisible();

      const add = page.getByRole('button', { name: 'Add current view' });
      await add.focus();
      await page.keyboard.press('Enter');
      const first = await readMapCamera(page);
      await expect(page.getByLabel('Name of bookmark 1')).toBeFocused();
      await page.keyboard.type('Overview');
      await page.keyboard.press('Tab');

      await moveMap(page, ['ArrowRight', 'ArrowRight', 'ArrowRight', 'Equal', 'Equal']);
      await add.focus();
      await page.keyboard.press('Enter');
      await expect(page.getByLabel('Name of bookmark 2')).toHaveValue('Bookmark 2');

      // Put the second ahead of the first.
      await page.getByRole('button', { name: 'Move Bookmark 2 up' }).focus();
      await page.keyboard.press('Enter');
      await expect(page.getByLabel('Name of bookmark 1')).toHaveValue('Bookmark 2');

      const saved = page.waitForResponse((response) => isMapUpdateResponse(response, mapId));
      await page.getByRole('button', { name: /save/i }).first().click();
      expect((await saved).status()).toBe(200);

      await page.reload();
      await waitForBuilder(page);
      await page.locator('[data-rail-button="bookmarks"]').click();
      await expect(page.getByLabel('Name of bookmark 1')).toHaveValue('Bookmark 2');
      await expect(page.getByLabel('Name of bookmark 2')).toHaveValue('Overview');

      for (const path of [`/maps/${mapId}`, `/m/${shareToken}`, `/m/${shareToken}?embed=true`]) {
        const reader = await anonymousPage(browser);
        try {
          await reader.goto(path);
          await expect(reader.locator('canvas.maplibregl-canvas')).toBeVisible({ timeout: 20_000 });
          const control = reader.getByRole('button', { name: 'Bookmarks' });
          await expect(control).toBeVisible();
          const before = await readMapCamera(reader);
          await control.click();
          await reader.getByRole('menuitem', { name: 'Overview' }).click();
          await expect
            .poll(async () => Math.abs((await readMapCamera(reader)).zoom - first.zoom), { timeout: 10_000 })
            .toBeLessThan(0.2);
          const after = await readMapCamera(reader);
          expect(Math.abs(after.zoom - before.zoom) + Math.abs(after.lng - before.lng)).toBeGreaterThan(0);
        } finally {
          await reader.context().close();
        }
      }
    } finally {
      await deleteMap(request, mapId);
    }
  });
});
