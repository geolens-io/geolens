/**
 * Plugin lifecycle E2E — closes the live-verification gaps flagged by
 * /plugin-audit (docs-internal/audits/plugin-audit-20260531.md):
 *
 *   MED-1/round-trip — toggling a plugin in the builder Settings panel, saving,
 *   and reloading round-trips through the `catalog.maps.plugins` column.
 *
 *   MED-2 — the per-map Settings plugin toggles are filtered by the admin
 *   `enabled_plugins` allowlist (no dead toggles for admin-disabled plugins).
 *
 * Self-contained: each test creates its own throwaway map via the API and
 * deletes it in `finally`. The admin-allowlist test mutates the GLOBAL
 * `enabled_plugins` setting, captured in beforeAll and restored precisely in
 * afterAll (and in the test's own finally) so the suite leaves no global state
 * behind. Runs serially so the global mutation never overlaps another test.
 */

import { test, expect, type Page, type APIRequestContext } from '@playwright/test';
import fs from 'fs';
import path from 'path';

const AUTH_FILE = path.join(__dirname, '../playwright/.auth/user.json');
const BASE_URL = process.env.E2E_BASE_URL ?? 'http://localhost:8080';

// --- Auth (inlined per project convention — no shared helper file) ---
function getAuthToken(): string {
  const state = JSON.parse(fs.readFileSync(AUTH_FILE, 'utf-8'));
  for (const origin of (state.origins ?? []) as Array<{ localStorage?: Array<{ name: string; value: string }> }>) {
    for (const entry of origin.localStorage ?? []) {
      if (entry.name === 'geolens-auth') {
        return (JSON.parse(entry.value) as { state?: { token?: string } }).state?.token ?? '';
      }
    }
  }
  throw new Error('Could not extract auth token from storage state');
}
function authHeaders() {
  return { Authorization: `Bearer ${getAuthToken()}`, 'Content-Type': 'application/json' };
}

// --- API helpers ---
async function createMap(request: APIRequestContext, name: string): Promise<string> {
  const res = await request.post(`${BASE_URL}/api/maps/`, {
    headers: authHeaders(),
    data: { name, description: 'Temporary map for plugin-lifecycle E2E' },
  });
  expect(res.ok(), `Create map failed: ${res.status()} ${await res.text()}`).toBe(true);
  return ((await res.json()) as { id: string }).id;
}
async function deleteMap(request: APIRequestContext, mapId: string) {
  await request.delete(`${BASE_URL}/api/maps/${mapId}`, { headers: authHeaders() });
}
async function getMapPlugins(request: APIRequestContext, mapId: string): Promise<string[] | null> {
  const res = await request.get(`${BASE_URL}/api/maps/${mapId}`, { headers: authHeaders() });
  expect(res.ok(), `GET /api/maps/${mapId} failed: ${res.status()}`).toBe(true);
  return ((await res.json()) as { plugins: string[] | null }).plugins;
}
async function getEnabledPlugins(request: APIRequestContext): Promise<string[] | null> {
  const res = await request.get(`${BASE_URL}/api/settings/enabled-plugins/`, { headers: authHeaders() });
  expect(res.ok(), `GET enabled-plugins failed: ${res.status()}`).toBe(true);
  return (await res.json()) as string[] | null;
}
async function setEnabledPlugins(request: APIRequestContext, ids: string[]) {
  const res = await request.put(`${BASE_URL}/api/settings/`, {
    headers: authHeaders(),
    data: { settings: { enabled_plugins: ids } },
  });
  expect(res.ok(), `PUT enabled_plugins failed: ${res.status()} ${await res.text()}`).toBe(true);
}
async function restoreEnabledPlugins(request: APIRequestContext, original: string[] | null) {
  if (original == null) {
    await request.post(`${BASE_URL}/api/settings/reset/`, {
      headers: authHeaders(),
      data: { keys: ['enabled_plugins'] },
    });
  } else {
    await setEnabledPlugins(request, original);
  }
}

// --- UI helpers ---
async function waitForBuilder(page: Page) {
  await expect(page.locator('canvas.maplibregl-canvas')).toBeVisible({ timeout: 15_000 });
}
/** Open the builder Settings flyout via the sidebar cog and wait for the
 *  PLUGINS section to render. Returns the editor-panel locator. */
async function openSettings(page: Page) {
  await page.getByTestId('settings-cog-btn').click();
  const editor = page.getByTestId('builder-layer-editor');
  await expect(editor.getByText('PLUGINS', { exact: true })).toBeVisible();
  return editor;
}

// en plugin labels (frontend/src/i18n/locales/en/builder.json): measurement→"Measure", legend→"Legend".
test.describe.serial('Plugin lifecycle (audit MED-1 / MED-2)', () => {
  test.use({ viewport: { width: 1280, height: 800 } }); // desktop: flyout editor, not the <800px Sheet

  let originalEnabledPlugins: string[] | null = null;
  test.beforeAll(async ({ request }) => {
    originalEnabledPlugins = await getEnabledPlugins(request);
  });
  test.afterAll(async ({ request }) => {
    await restoreEnabledPlugins(request, originalEnabledPlugins);
  });

  test('toggling a plugin in Settings persists across reload (plugins column round-trip)', async ({ page, request }) => {
    const mapId = await createMap(request, 'plugin-lifecycle-roundtrip');
    try {
      await page.goto(`/maps/${mapId}`);
      await waitForBuilder(page);

      // Fresh map ⇒ plugins=null ⇒ legend default-visible (ON), measurement OFF.
      let editor = await openSettings(page);
      const measureOn = editor.getByRole('switch', { name: 'Enable Measure' });
      await expect(measureOn).toBeVisible();
      await expect(editor.getByRole('switch', { name: 'Disable Legend' })).toBeVisible();

      // Turn the Measure plugin ON and save (Cmd/Ctrl+S — canonical builder shortcut).
      await measureOn.click();
      await page.keyboard.press('ControlOrMeta+s');

      // Authoritative persistence check: the maps.plugins column now holds measurement.
      await expect
        .poll(async () => await getMapPlugins(request, mapId), { timeout: 15_000 })
        .toContain('measurement');

      // Reload and confirm the UI restores the saved state (toggle now reads "Disable Measure").
      await page.reload();
      await waitForBuilder(page);
      editor = await openSettings(page);
      await expect(editor.getByRole('switch', { name: 'Disable Measure' })).toBeVisible();
    } finally {
      await deleteMap(request, mapId);
    }
  });

  test('admin-disabled plugin is hidden from the builder Settings toggles (no dead toggle)', async ({ page, request }) => {
    const mapId = await createMap(request, 'plugin-lifecycle-adminfilter');
    try {
      // Admin restricts the allowlist to legend only — measurement is globally disabled.
      await setEnabledPlugins(request, ['legend']);

      await page.goto(`/maps/${mapId}`);
      await waitForBuilder(page);
      const editor = await openSettings(page);

      // Legend remains togglable; the admin-disabled Measure plugin has NO toggle at all
      // (the audit fix: per-map list filters by getEnabledPluginDefinitions, not getPlugins).
      await expect(editor.getByRole('switch', { name: 'Disable Legend' })).toBeVisible();
      await expect(editor.getByRole('switch', { name: /Measure/ })).toHaveCount(0);
    } finally {
      await restoreEnabledPlugins(request, originalEnabledPlugins);
      await deleteMap(request, mapId);
    }
  });
});
