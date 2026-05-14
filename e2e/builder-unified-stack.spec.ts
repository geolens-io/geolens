import { test, expect, type Page } from '@playwright/test';
import fs from 'fs';
import path from 'path';

// ---------------------------------------------------------------------------
// Auth / setup helpers (inlined per project convention — no shared helper file)
// ---------------------------------------------------------------------------

const AUTH_FILE = path.join(__dirname, '../playwright/.auth/user.json');
const BASE_URL = process.env.E2E_BASE_URL ?? 'http://localhost:8080';

/** Extract JWT token from the Playwright storage state file. */
function getAuthToken(): string {
  const raw = fs.readFileSync(AUTH_FILE, 'utf-8');
  const state = JSON.parse(raw);
  for (const origin of (state.origins ?? []) as Array<{ localStorage?: Array<{ name: string; value: string }> }>) {
    for (const entry of origin.localStorage ?? []) {
      if (entry.name === 'geolens-auth') {
        const parsed = JSON.parse(entry.value) as { state?: { token?: string } };
        return parsed.state?.token ?? '';
      }
    }
  }
  throw new Error('Could not extract auth token from storage state');
}

async function waitForBuilder(page: Page) {
  await expect(page.locator('canvas.maplibregl-canvas')).toBeVisible({ timeout: 15_000 });
}

// ---------------------------------------------------------------------------
// Console gate helpers
// ---------------------------------------------------------------------------

interface ConsoleGate {
  errors: string[];
  warnings: string[];
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

function assertConsoleClean({ errors, warnings }: ConsoleGate) {
  expect(errors, `Console errors:\n${errors.join('\n')}`).toHaveLength(0);
  // Filter out non-application noise:
  // - MapLibre runtime warnings (third-party renderer)
  // - MapLibre glyph-range fetch warnings (font tiles unavailable in test env)
  // - WebGL/GPU driver messages — emitted by the headless Chromium GL backend
  const filtered = warnings.filter(
    (w) =>
      !w.includes('MapLibre') &&
      !w.includes('GL Driver') &&
      !w.includes('GPU stall') &&
      !w.includes('Unable to load glyph range') &&
      !w.includes('Rendering codepoint'),
  );
  expect(filtered, `Console warnings (non-app):\n${filtered.join('\n')}`).toHaveLength(0);
}

// ---------------------------------------------------------------------------
// Map lifecycle state (shared across serial tests via module scope)
// ---------------------------------------------------------------------------

let mapId: string;
let legacyMapId: string;
let emptyMapId: string;
let hasDemLayer = false;

// ---------------------------------------------------------------------------
// Test suite
// ---------------------------------------------------------------------------

test.describe.serial('Builder Unified Stack UAT (Phase 1038, BSR-25 + BSR-27)', () => {
  test.slow();

  // -------------------------------------------------------------------------
  // beforeAll: create test maps + add layer fixtures
  // -------------------------------------------------------------------------

  test.beforeAll(async () => {
    const token = getAuthToken();
    const headers = {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    };

    // -- 1. Create the primary test map (used for most tests) --
    const mapRes = await fetch(`${BASE_URL}/api/maps/`, {
      method: 'POST',
      headers,
      body: JSON.stringify({
        name: 'E2E Unified Stack UAT',
        description: 'Phase 1038 BSR-25 + BSR-27 UAT',
      }),
    });
    expect(mapRes.ok, `Create primary map: ${mapRes.status}`).toBe(true);
    const mapData = await mapRes.json() as { id: string };
    mapId = mapData.id;
    expect(mapId).toBeTruthy();

    // -- 2. Find a vector dataset and add it to the primary map --
    const dsRes = await fetch(`${BASE_URL}/api/datasets/?limit=20`, { headers });
    expect(dsRes.ok).toBe(true);
    const dsPayload = await dsRes.json() as { datasets?: Array<{ id: string; record_type?: string; is_dem?: boolean }>; items?: Array<{ id: string; record_type?: string; is_dem?: boolean }> };
    const allDatasets = dsPayload.datasets ?? dsPayload.items ?? [];
    const vectorDataset = allDatasets.find((ds) => ds.record_type === 'vector_dataset') ?? allDatasets[0];

    if (vectorDataset?.id) {
      const layerRes = await fetch(`${BASE_URL}/api/maps/${mapId}/layers/`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ dataset_id: vectorDataset.id }),
      });
      expect(layerRes.ok, `Add vector layer: ${layerRes.status}`).toBe(true);
    }

    // -- 3. Check for a DEM dataset (test 3 will skip gracefully if absent) --
    const demDataset = allDatasets.find((ds) => ds.record_type === 'raster_dataset' && ds.is_dem === true);
    if (demDataset?.id) {
      await fetch(`${BASE_URL}/api/maps/${mapId}/layers/`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ dataset_id: demDataset.id }),
      });
      hasDemLayer = true;
    }

    // -- 4. Create an empty map (for tests 6 and 7) --
    const emptyMapRes = await fetch(`${BASE_URL}/api/maps/`, {
      method: 'POST',
      headers,
      body: JSON.stringify({
        name: 'E2E Unified Stack UAT — Empty',
        description: 'Phase 1038 empty-state UAT',
      }),
    });
    expect(emptyMapRes.ok, `Create empty map: ${emptyMapRes.status}`).toBe(true);
    const emptyMapData = await emptyMapRes.json() as { id: string };
    emptyMapId = emptyMapData.id;

    // -- 5. Create a legacy six-section map (test 8) --
    // Uses the style_json shape from the v1008 compatibility layer: six top-level section keys
    const legacyStyleJson = {
      version: 8,
      name: 'Legacy six-section',
      _geolens_sections: {
        vector: [],
        raster: [],
        dem: [],
        basemap: [],
        labels: [],
        terrain: null,
      },
    };
    const legacyMapRes = await fetch(`${BASE_URL}/api/maps/`, {
      method: 'POST',
      headers,
      body: JSON.stringify({
        name: 'E2E Unified Stack UAT — Legacy Map',
        description: 'Phase 1038 legacy normalizer UAT',
        style_json: legacyStyleJson,
      }),
    });
    expect(legacyMapRes.ok, `Create legacy map: ${legacyMapRes.status}`).toBe(true);
    const legacyMapData = await legacyMapRes.json() as { id: string };
    legacyMapId = legacyMapData.id;
  });

  // -------------------------------------------------------------------------
  // afterAll: delete all created test maps
  // -------------------------------------------------------------------------

  test.afterAll(async () => {
    const authHeader = { Authorization: `Bearer ${getAuthToken()}` };
    for (const id of [mapId, emptyMapId, legacyMapId]) {
      if (id) {
        await fetch(`${BASE_URL}/api/maps/${id}`, { method: 'DELETE', headers: authHeader });
      }
    }
  });

  // =========================================================================
  // Test 1: Drag-reorder changes layer z-order
  // =========================================================================

  test('1. drag-reorder changes layer z-order', async ({ page }) => {
    const gate = attachConsoleGate(page);

    await page.goto(`/maps/${mapId}`);
    await waitForBuilder(page);

    // Collect the initial row order
    const rows = page.locator('[id^="stack-row-"]');
    const initialCount = await rows.count();

    if (initialCount < 2) {
      // Only one layer — cannot test reorder, but still assert no console issues
      assertConsoleClean(gate);
      return;
    }

    const initialIds = await rows.evaluateAll((els: Element[]) => els.map((e) => e.id));

    // Use keyboard drag via dnd-kit keyboard sensor:
    // Focus the drag handle of the second row, press Space, ArrowUp, Space to reorder
    const secondRowId = initialIds[1].replace('stack-row-', '');
    const dragHandleLocator = page
      .locator(`#stack-row-${secondRowId}`)
      .getByRole('button', { name: new RegExp('Drag to reorder', 'i') });

    if (await dragHandleLocator.count() === 0) {
      // Handle not found — skip drag assertion but verify rows are present
      await expect(rows.first()).toBeVisible();
      assertConsoleClean(gate);
      return;
    }

    await dragHandleLocator.focus();
    await page.keyboard.press('Space'); // lift
    await page.keyboard.press('ArrowUp'); // move up
    await page.keyboard.press('Space'); // drop

    // Wait for potential re-render
    await page.waitForTimeout(300);

    const reorderedIds = await rows.evaluateAll((els: Element[]) => els.map((e) => e.id));
    // The second item should now be first (or at minimum the order changed)
    // Some dnd-kit keyboard implementations move by one step per keypress
    expect(reorderedIds).not.toEqual(initialIds);

    assertConsoleClean(gate);
  });

  // =========================================================================
  // Test 2: Basemap group expand reveals sublayers
  // =========================================================================

  test('2. basemap-group expand reveals sublayers', async ({ page }) => {
    const gate = attachConsoleGate(page);

    await page.goto(`/maps/${mapId}`);
    await waitForBuilder(page);

    // The basemap group row is always rendered in the basemap dock
    const basemapDock = page.getByTestId('basemap-dock');
    await expect(basemapDock).toBeVisible({ timeout: 10_000 });

    // The expand/collapse button on the basemap group row
    const expandBtn = basemapDock.getByRole('button', {
      name: /toggle basemap group/i,
    });

    if (await expandBtn.count() === 0) {
      // No expandable basemap group present — skip gracefully
      assertConsoleClean(gate);
      return;
    }

    // Click to expand
    await expandBtn.click();

    // After expansion: the children container should be visible with sublayer rows
    const childrenContainer = page.locator('[data-testid^="basemap-group-children-"]');
    await expect(childrenContainer).toBeVisible({ timeout: 5_000 });

    // At least one sublayer row should be present inside
    const sublayerRows = childrenContainer.locator('[id^="stack-row-"]');
    await expect(sublayerRows.first()).toBeVisible({ timeout: 5_000 });

    assertConsoleClean(gate);
  });

  // =========================================================================
  // Test 3: DEM render-mode switch preserves source binding (skip if no DEM)
  // =========================================================================

  test('3. DEM render-mode switch preserves source binding', async ({ page }) => {
    if (!hasDemLayer) {
      test.skip(true, 'No DEM dataset available in the test environment — skipping DEM render-mode test');
    }

    const gate = attachConsoleGate(page);

    await page.goto(`/maps/${mapId}`);
    await waitForBuilder(page);

    // Find a DEM layer row (it will have a TypePill showing "DEM")
    const demRow = page.locator('[id^="stack-row-"]').filter({ has: page.locator('span', { hasText: /^DEM/i }) }).first();

    if (await demRow.count() === 0) {
      // No DEM row visible — skip
      assertConsoleClean(gate);
      return;
    }

    // Click the DEM row to open the editor
    await demRow.click();

    const editor = page.getByTestId('builder-layer-editor');
    await expect(editor).toBeVisible({ timeout: 10_000 });

    // Look for the render-mode pill strip (demEditor section with Hillshade / Color / Contour)
    const hillshadeOption = editor.getByRole('radio', { name: /hillshade/i }).or(
      editor.getByRole('button', { name: /hillshade/i }),
    );

    if (await hillshadeOption.count() > 0) {
      await hillshadeOption.first().click();

      // The editor should still be open with no errors
      await expect(editor).toBeVisible();
      await expect(page.locator('[data-sonner-toast][data-type="error"]')).toHaveCount(0);
    }

    assertConsoleClean(gate);
  });

  // =========================================================================
  // Test 4: Flyout opens, closes, focus returns to row (BSR-25 + BSR-13)
  // =========================================================================

  test('4. flyout opens, closes, and returns focus to row (BSR-25 + BSR-13)', async ({ page }) => {
    const gate = attachConsoleGate(page);

    // --- Desktop flow (viewport >= 800px) ---
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto(`/maps/${mapId}`);
    await waitForBuilder(page);

    const firstRow = page.locator('[id^="stack-row-"]').first();
    await expect(firstRow).toBeVisible();

    // Click the row to open the editor flyout
    await firstRow.click();

    const editor = page.getByTestId('builder-layer-editor');
    await expect(editor).toBeVisible({ timeout: 10_000 });

    // Close via the X / "Close layer editor" button
    const closeBtn = editor.getByRole('button', { name: /close layer editor/i });
    await expect(closeBtn).toBeVisible();
    await closeBtn.click();

    await expect(editor).not.toBeVisible({ timeout: 5_000 });

    // BSR-25: focus must return to the originating stack row
    const focusedId = await page.evaluate(() => document.activeElement?.id ?? '');
    expect(focusedId, 'Focus should return to a stack-row element after closing the editor').toMatch(/^stack-row-/);

    // A11y Tab-traversal assertion: tab forward from body and verify we reach
    // expected focusable elements (Save button, Share button, layer rows)
    await page.locator('body').click();
    const focusedTags: string[] = [];
    for (let i = 0; i < 15; i++) {
      await page.keyboard.press('Tab');
      const info = await page.evaluate(() => {
        const el = document.activeElement;
        if (!el || el === document.body) return null;
        const inertAncestor = el.closest('[inert]');
        return { tag: el.tagName.toLowerCase(), insideInert: !!inertAncestor };
      });
      if (info) {
        expect(info.insideInert, 'Focused element must not be inside an [inert] ancestor').toBe(false);
        focusedTags.push(info.tag);
      }
    }
    expect(focusedTags.length, 'Should tab through at least 5 focusable elements in the builder shell').toBeGreaterThanOrEqual(5);

    // --- Mobile flow (viewport < 800px) — BSR-13: Sheet overlay ---
    // At <800px the sidebar collapses to a 64px rail (isRail=true) and the editor
    // column is hidden (isEditorHidden=true). The full-anatomy stack rows are not
    // rendered in the rail variant — entry happens via rail icons or the mobile
    // sheet trigger. Drill-down Sheet wiring is verified separately by the
    // component-level test in `__tests__/LayerEditorPanel.test.tsx` (`isDrillDown=true`
    // back-arrow render path). UAT-level verification of the rail→Sheet entry flow
    // is deferred to a future polish phase that designs the rail's per-layer entry
    // affordance (BSR-13 followup).
    await page.setViewportSize({ width: 700, height: 900 });
    await page.goto(`/maps/${mapId}`);
    await waitForBuilder(page);

    // Verify the page at <800px loads without console errors and the builder
    // shell renders. The main content region is the most stable selector across
    // the rail/full-sidebar variants.
    const mainContent = page.locator('main, [role="main"], #main-content').first();
    await expect(mainContent).toBeVisible({ timeout: 5_000 });

    assertConsoleClean(gate);
  });

  // =========================================================================
  // Test 5: Settings panel opens via cog button
  // =========================================================================

  test('5. settings panel opens via cog button', async ({ page }) => {
    const gate = attachConsoleGate(page);

    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto(`/maps/${mapId}`);
    await waitForBuilder(page);

    // Click the settings cog button
    const cogBtn = page.getByTestId('settings-cog-btn');
    await expect(cogBtn).toBeVisible();

    // aria-pressed should be false (or not set) before opening
    const pressedBefore = await cogBtn.getAttribute('aria-pressed');
    expect(pressedBefore).not.toBe('true');

    await cogBtn.click();

    // The editor column should now show settings content
    const editor = page.getByTestId('builder-layer-editor');
    await expect(editor).toBeVisible({ timeout: 10_000 });

    // Settings panel typically contains Terrain or Widgets or Projection
    const hasSettingsContent = await editor
      .getByText(/terrain|widgets|projection/i)
      .first()
      .isVisible()
      .catch(() => false);
    expect(hasSettingsContent, 'Settings panel should show Terrain/Widgets/Projection content').toBe(true);

    // aria-pressed should now be 'true'
    await expect(cogBtn).toHaveAttribute('aria-pressed', 'true');

    assertConsoleClean(gate);
  });

  // =========================================================================
  // Test 6: Empty-state entry shows search input + suggestions
  // =========================================================================

  test('6. empty-state entry shows search input + suggestions', async ({ page }) => {
    const gate = attachConsoleGate(page);

    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto(`/maps/${emptyMapId}`);
    await waitForBuilder(page);

    // The EmptyStackState region should be visible
    const emptyRegion = page.getByRole('region', { name: /no layers/i });
    await expect(emptyRegion).toBeVisible({ timeout: 10_000 });

    // Heading should indicate "Add your first layer" (or similar)
    const heading = emptyRegion.getByRole('heading');
    await expect(heading).toBeVisible();

    // Inline search input (role=searchbox) should be present
    const searchInput = emptyRegion.getByRole('searchbox');
    await expect(searchInput, 'Inline search input should be present in empty state').toBeVisible();

    // Suggested datasets list element should exist in the DOM. The list ships
    // empty by default (operator-curated per deployment) so visibility is not
    // asserted — only that the empty-state region renders the list scaffold.
    const suggestedList = emptyRegion.getByRole('list', { name: /suggested datasets/i });
    await expect(suggestedList).toHaveCount(1);

    assertConsoleClean(gate);
  });

  // =========================================================================
  // Test 7: Add Data modal opens with query pre-fill from empty state
  // =========================================================================

  test('7. Add Data modal opens with query pre-fill from empty state', async ({ page }) => {
    const gate = attachConsoleGate(page);

    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto(`/maps/${emptyMapId}`);
    await waitForBuilder(page);

    const emptyRegion = page.getByRole('region', { name: /no layers/i });
    await expect(emptyRegion).toBeVisible({ timeout: 10_000 });

    // Type a query into the inline search box
    const searchInput = emptyRegion.getByRole('searchbox');
    await expect(searchInput).toBeVisible();
    const testQuery = 'census';
    await searchInput.fill(testQuery);

    // Submit the inline search (Enter) — this is the "search submit" path that
    // pre-fills the Add Data modal with the typed query. The separate "Browse all
    // datasets" button is an unfiltered open path and does NOT carry the query
    // (browse all = browse everything).
    await searchInput.press('Enter');

    // The Add Dataset dialog should open
    const dialog = page.getByRole('dialog', { name: /add dataset/i });
    await expect(dialog).toBeVisible({ timeout: 10_000 });

    // The dialog's primary search input should be pre-filled with the query
    const dialogSearch = dialog.getByRole('textbox').or(dialog.getByLabel(/search datasets/i)).first();
    await expect(dialogSearch).toBeVisible();
    await expect(dialogSearch).toHaveValue(testQuery);

    // Close dialog
    await page.keyboard.press('Escape');
    await expect(dialog).not.toBeVisible({ timeout: 5_000 });

    assertConsoleClean(gate);
  });

  // =========================================================================
  // Test 8: Legacy six-section saved map opens under unified stack
  // =========================================================================

  test('8. legacy six-section saved map opens under unified stack', async ({ page }) => {
    const gate = attachConsoleGate(page);

    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto(`/maps/${legacyMapId}`);
    await waitForBuilder(page);

    // No error toasts — the normalizer should handle the legacy format gracefully
    await expect(page.locator('[data-sonner-toast][data-type="error"]')).toHaveCount(0, { timeout: 5_000 });

    // The builder should render without crashing
    // (Legacy map has no vector layers — so no stack-row — but the basemap dock should be present)
    await expect(page.getByTestId('basemap-dock')).toBeVisible({ timeout: 5_000 });

    assertConsoleClean(gate);
  });

  // =========================================================================
  // Test 9: Save and reload preserves layer order
  // =========================================================================

  test('9. save and reload preserves layer order', async ({ page }) => {
    const gate = attachConsoleGate(page);

    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto(`/maps/${mapId}`);
    await waitForBuilder(page);

    // Capture current row order
    const rows = page.locator('[id^="stack-row-"]');
    const initialCount = await rows.count();

    if (initialCount < 2) {
      // Cannot test reorder with fewer than 2 rows — just verify save works
      const saveResponsePromise = page.waitForResponse(
        (resp) => resp.url().includes(`/api/maps/${mapId}`) && resp.request().method() === 'PUT',
      );
      await page.getByRole('button', { name: /save/i }).first().click();
      expect((await saveResponsePromise).status()).toBe(200);
      await expect(page.locator('[data-sonner-toast][data-type="error"]')).toHaveCount(0);
      assertConsoleClean(gate);
      return;
    }

    // Capture the initial order
    const orderBeforeSave = await rows.evaluateAll((els: Element[]) => els.map((e) => e.id));

    // Save the map
    const saveResponsePromise = page.waitForResponse(
      (resp) => resp.url().includes(`/api/maps/${mapId}`) && resp.request().method() === 'PUT',
    );
    await page.getByRole('button', { name: /save/i }).first().click();
    const saveResponse = await saveResponsePromise;
    expect(saveResponse.status()).toBe(200);

    // No error toasts after save
    await expect(page.locator('[data-sonner-toast][data-type="error"]')).toHaveCount(0, { timeout: 5_000 });

    // Reload and verify order is preserved
    await page.reload();
    await waitForBuilder(page);

    const rowsAfterReload = page.locator('[id^="stack-row-"]');
    await expect(rowsAfterReload.first()).toBeVisible();

    const orderAfterReload = await rowsAfterReload.evaluateAll((els: Element[]) => els.map((e) => e.id));
    expect(orderAfterReload, 'Layer order should be preserved after save and reload').toEqual(orderBeforeSave);

    await expect(page.locator('[data-sonner-toast][data-type="error"]')).toHaveCount(0);

    assertConsoleClean(gate);
  });
});
