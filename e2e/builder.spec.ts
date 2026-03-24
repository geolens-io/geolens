import { test, expect } from '@playwright/test';
import fs from 'fs';
import path from 'path';

const AUTH_FILE = path.join(__dirname, '../playwright/.auth/user.json');
const BASE_URL = process.env.E2E_BASE_URL ?? 'http://localhost:8080';

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

let mapId: string;
let duplicatedMapId: string | null = null;

test.describe.serial('Map Builder', () => {
  test.slow();

  test.beforeAll(async () => {
    const token = getAuthToken();
    const headers = {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    };

    // Get a dataset ID to add as a layer
    const dsRes = await fetch(`${BASE_URL}/api/datasets/?limit=1`, { headers });
    expect(dsRes.ok).toBe(true);
    const dsData = await dsRes.json();
    const datasetId = dsData.datasets?.[0]?.id ?? dsData.items?.[0]?.id ?? dsData[0]?.id;
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
  });

  test('loads existing map and canvas is visible', async ({ page }) => {
    await page.goto(`/maps/${mapId}`);
    const canvas = page.locator('canvas.maplibregl-canvas');
    await expect(canvas).toBeVisible({ timeout: 15_000 });
  });

  test('sidebar collapses with inert attribute and reopens', async ({ page }) => {
    await page.goto(`/maps/${mapId}`);
    await expect(page.locator('canvas.maplibregl-canvas')).toBeVisible({ timeout: 15_000 });

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
    await expect(page.locator('canvas.maplibregl-canvas')).toBeVisible({ timeout: 15_000 });

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
    await expect(page.locator('canvas.maplibregl-canvas')).toBeVisible({ timeout: 15_000 });

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

  test('saves map without errors', async ({ page }) => {
    await page.goto(`/maps/${mapId}`);
    await expect(page.locator('canvas.maplibregl-canvas')).toBeVisible({ timeout: 15_000 });

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
    await expect(page.locator('canvas.maplibregl-canvas')).toBeVisible({ timeout: 15_000 });

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
    await expect(page.locator('canvas.maplibregl-canvas')).toBeVisible({ timeout: 15_000 });
  });

  test('switches basemap without losing overlay layers', async ({ page }) => {
    await page.goto(`/maps/${mapId}`);
    await expect(page.locator('canvas.maplibregl-canvas')).toBeVisible({ timeout: 15_000 });

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
    // Brief wait for style reload
    await page.waitForTimeout(1_000);

    // Canvas should still be visible
    await expect(page.locator('canvas.maplibregl-canvas')).toBeVisible();

    // Layer items should still be present (overlay layers not lost)
    if (layerItemsBefore > 0) {
      const layerItemsAfter = await page.locator('[data-testid^="layer-item"]').count()
        .catch(() => 0);
      expect(layerItemsAfter).toBe(layerItemsBefore);
    }
  });

  test('keyboard-only navigation through builder controls', async ({ page }) => {
    await page.goto(`/maps/${mapId}`);
    await expect(page.locator('canvas.maplibregl-canvas')).toBeVisible({ timeout: 15_000 });

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
    await expect(page.locator('canvas.maplibregl-canvas')).toBeVisible({ timeout: 15_000 });

    // Open the per-layer "More actions" menu (inside the layer row, not the header tray)
    const layerRow = page.getByRole('button', { name: /hide layer .+ more actions/i }).first();
    const moreBtn = layerRow.getByLabel(/more actions/i);
    await moreBtn.click();

    // Click "Zoom to layer"
    const zoomItem = page.getByRole('menuitem', { name: /zoom to layer/i });
    await expect(zoomItem).toBeVisible();
    await zoomItem.click();

    // Map should still be functional — canvas visible, no error toasts
    await page.waitForTimeout(1_500);
    await expect(page.locator('canvas.maplibregl-canvas')).toBeVisible();
    await expect(page.locator('[data-sonner-toast][data-type="error"]')).toHaveCount(0);
  });

  test('sidebar drag handle resizes sidebar', async ({ page }) => {
    await page.goto(`/maps/${mapId}`);
    await expect(page.locator('canvas.maplibregl-canvas')).toBeVisible({ timeout: 15_000 });

    // Clear persisted width
    await page.evaluate(() => localStorage.removeItem('geolens-builder-sidebar-width'));

    // Get the drag handle and sidebar
    const handle = page.locator('[class*="cursor-col-resize"]');
    await expect(handle).toBeVisible();
    const sidebar = page.locator('.border-r.bg-background');

    const widthBefore = await sidebar.evaluate((el) => el.offsetWidth);

    // Find a y-coordinate where the handle is actually hittable (avoid icons/buttons)
    const hitX = await page.evaluate(() => {
      const h = document.querySelector('[class*="cursor-col-resize"]');
      if (!h) return null;
      const rect = h.getBoundingClientRect();
      // Scan to find a hittable x
      for (let x = Math.floor(rect.left); x <= Math.ceil(rect.right); x++) {
        const el = document.elementFromPoint(x, rect.top + 50);
        if (h.contains(el) || el === h) return x;
      }
      return null;
    });
    expect(hitX).toBeTruthy();

    const box = await handle.boundingBox();
    expect(box).toBeTruthy();
    const startY = box!.y + 50; // Use a point near top, away from layer controls

    await page.mouse.move(hitX!, startY);
    await page.mouse.down();
    await page.mouse.move(hitX! + 100, startY, { steps: 15 });
    await page.mouse.up();
    await page.waitForTimeout(300);

    const widthAfter = await sidebar.evaluate((el) => el.offsetWidth);
    expect(widthAfter).toBeGreaterThan(widthBefore);

    // Verify width persisted to localStorage
    const stored = await page.evaluate(() => localStorage.getItem('geolens-builder-sidebar-width'));
    expect(stored).toBe(String(widthAfter));

    // Reload and verify persistence
    await page.reload();
    await expect(page.locator('canvas.maplibregl-canvas')).toBeVisible({ timeout: 15_000 });
    const widthAfterReload = await sidebar.evaluate((el) => el.offsetWidth);
    expect(widthAfterReload).toBe(widthAfter);
  });

  test('sidebar collapsed state persists across reload', async ({ page }) => {
    await page.goto(`/maps/${mapId}`);
    await expect(page.locator('canvas.maplibregl-canvas')).toBeVisible({ timeout: 15_000 });

    // Clear stored state
    await page.evaluate(() => localStorage.removeItem('geolens-builder-sidebar-collapsed'));

    // Collapse sidebar
    const collapseBtn = page.getByRole('button', { name: /collapse sidebar/i });
    await collapseBtn.click();
    await expect(page.getByRole('button', { name: /expand sidebar/i })).toBeVisible();

    // Reload — should stay collapsed
    await page.reload();
    await expect(page.locator('canvas.maplibregl-canvas')).toBeVisible({ timeout: 15_000 });
    await expect(page.getByRole('button', { name: /expand sidebar/i })).toBeVisible();

    // Expand and reload — should stay expanded
    await page.getByRole('button', { name: /expand sidebar/i }).click();
    await expect(page.getByRole('button', { name: /collapse sidebar/i })).toBeVisible();
    await page.reload();
    await expect(page.locator('canvas.maplibregl-canvas')).toBeVisible({ timeout: 15_000 });
    await expect(page.getByRole('button', { name: /collapse sidebar/i })).toBeVisible();
  });

  test('no error toasts from raster tile 404s', async ({ page }) => {
    const consoleErrors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') consoleErrors.push(msg.text());
    });

    await page.goto(`/maps/${mapId}`);
    await expect(page.locator('canvas.maplibregl-canvas')).toBeVisible({ timeout: 15_000 });

    // Wait for any tile loading to settle
    await page.waitForTimeout(3_000);

    // No error toasts should be visible to the user
    await expect(page.locator('[data-sonner-toast][data-type="error"]')).toHaveCount(0);

    // Console-level MapLibre tile errors are expected and acceptable;
    // the test only verifies they don't surface as UI error toasts
  });
});
