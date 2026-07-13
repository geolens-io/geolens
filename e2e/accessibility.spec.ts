import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { getAuthToken, seedDataset, deleteDataset } from './helpers/catalog';

const wcagTags = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'];
const BASE_URL = process.env.E2E_BASE_URL ?? 'http://localhost:8080';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function formatViolations(violations: any[]): string {
  return violations
    .map(
      (v) =>
        `[${v.id}] ${v.description} (${v.impact})\n` +
        v.nodes.map((n) => `  - ${n.html}`).join('\n'),
    )
    .join('\n\n');
}

test.describe('Accessibility - WCAG 2AA', () => {
  let builderMapId: string;
  let builderMapName: string;
  let shareToken: string;
  let datasetId: string;
  let datasetTitle: string;
  let collectionId: string;
  let collectionName: string;

  test.beforeAll(async () => {
    // Seed a real dataset so the dataset-detail test has something to render.
    // This spec runs standalone in the Accessibility CI job (empty stack), so
    // nothing else creates catalog data.
    const seeded = await seedDataset();
    datasetId = seeded.id;
    datasetTitle = seeded.title;

    collectionName = `A11y Collection Test ${Date.now()}`;
    const collectionResponse = await fetch(`${BASE_URL}/api/catalog/collections/`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${getAuthToken()}`,
      },
      body: JSON.stringify({
        name: collectionName,
        description: 'Temporary collection for detail-page accessibility coverage',
      }),
    });
    expect(collectionResponse.ok).toBe(true);
    collectionId = ((await collectionResponse.json()) as { id: string }).id;

    const membershipResponse = await fetch(
      `${BASE_URL}/api/catalog/collections/${collectionId}/datasets/`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${getAuthToken()}`,
        },
        body: JSON.stringify({ dataset_ids: [datasetId] }),
      },
    );
    expect(membershipResponse.ok).toBe(true);

    builderMapName = `A11y Builder Test ${Date.now()}`;
    const response = await fetch(`${BASE_URL}/api/maps/`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${getAuthToken()}`,
      },
      body: JSON.stringify({
        name: builderMapName,
        description: 'Temporary map for builder accessibility coverage',
      }),
    });

    expect(response.ok).toBe(true);
    const payload = await response.json();
    builderMapId = payload.id;
    expect(builderMapId).toBeTruthy();

    const layerResponse = await fetch(`${BASE_URL}/api/maps/${builderMapId}/layers/`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${getAuthToken()}`,
      },
      body: JSON.stringify({ dataset_id: datasetId }),
    });
    expect(layerResponse.ok).toBe(true);

    const publishResponse = await fetch(`${BASE_URL}/api/maps/${builderMapId}`, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${getAuthToken()}`,
      },
      body: JSON.stringify({
        visibility: 'public',
        center_lng: -73.9857,
        center_lat: 40.7484,
        zoom: 14,
      }),
    });
    expect(publishResponse.ok).toBe(true);

    const shareResponse = await fetch(`${BASE_URL}/api/maps/${builderMapId}/share/`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${getAuthToken()}`,
      },
    });
    expect(shareResponse.ok).toBe(true);
    const sharePayload = await shareResponse.json();
    shareToken = sharePayload.token;
    expect(shareToken).toBeTruthy();
  });

  test.afterAll(async () => {
    if (collectionId) {
      await fetch(`${BASE_URL}/api/catalog/collections/${collectionId}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${getAuthToken()}` },
      }).catch(() => {
        /* teardown is best-effort; the CI stack is torn down anyway */
      });
    }
    if (datasetId) await deleteDataset(datasetId, datasetTitle);
    if (!builderMapId) return;
    await fetch(`${BASE_URL}/api/maps/${builderMapId}`, {
      method: 'DELETE',
      headers: {
        Authorization: `Bearer ${getAuthToken()}`,
      },
    });
  });

  test('public search page has no accessibility violations', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    const results = await new AxeBuilder({ page })
      .withTags(wcagTags)
      .analyze();

    expect(results.violations, formatViolations(results.violations)).toEqual([]);
  });

  test.describe('logged-out routes', () => {
    test.use({ storageState: { cookies: [], origins: [] } });

    test('login page has no accessibility violations', async ({ page }) => {
      await page.goto('/login');
      await page.waitForLoadState('networkidle');

      const results = await new AxeBuilder({ page })
        .withTags(wcagTags)
        .analyze();

      expect(results.violations, formatViolations(results.violations)).toEqual([]);
    });

    test('public saved-map output has no accessibility violations', async ({ page }) => {
      await page.goto(`/m/${shareToken}`);
      await expect(page.getByText(builderMapName)).toBeVisible({ timeout: 15_000 });
      await page.getByRole('button', { name: 'Map data' }).click();
      const dataDialog = page.getByRole('dialog', { name: 'Map data' });
      await expect(dataDialog).toBeVisible();
      await expect(dataDialog.getByText(datasetTitle).first()).toBeVisible();
      await expect(
        dataDialog.getByRole('region', { name: 'Map layer and feature data' }),
      ).toBeVisible();
      await expect(dataDialog.getByText('E2E Test Point', { exact: true })).toBeVisible({
        timeout: 15_000,
      });
      await page.waitForLoadState('networkidle').catch(() => {
        /* MapLibre/background tile requests may keep the page active. */
      });

      const results = await new AxeBuilder({ page })
        .withTags(wcagTags)
        .exclude('.maplibregl-canvas')
        .exclude('.maplibregl-control-container')
        .exclude('.maplibregl-ctrl-attrib-inner')
        .analyze();

      expect(results.violations, formatViolations(results.violations)).toEqual([]);
    });
  });

  test('dataset detail page has no accessibility violations', async ({ page }) => {
    await page.goto(`/datasets/${datasetId}`);
    await page.waitForLoadState('networkidle');

    // Wait for dataset detail to load
    await expect(
      page.getByRole('heading', { name: datasetTitle, exact: true }),
    ).toBeVisible();
    await page.waitForLoadState('networkidle');

    // Exclude MapLibre canvas -- WebGL canvases cannot be inspected by axe
    const results = await new AxeBuilder({ page })
      .withTags(wcagTags)
      .exclude('.maplibregl-map')
      .analyze();

    expect(results.violations, formatViolations(results.violations)).toEqual([]);
  });

  test('collection detail page has no accessibility violations', async ({ page }) => {
    await page.goto(`/collections/${collectionId}`);
    await expect(
      page.getByRole('heading', { name: collectionName, exact: true }),
    ).toBeVisible();
    await page.waitForLoadState('networkidle');

    const results = await new AxeBuilder({ page })
      .withTags(wcagTags)
      .analyze();

    expect(results.violations, formatViolations(results.violations)).toEqual([]);
  });

  test('maps listing page has no accessibility violations', async ({ page }) => {
    await page.goto('/maps');
    await page.waitForLoadState('networkidle');

    const results = await new AxeBuilder({ page })
      .withTags(wcagTags)
      .analyze();

    expect(results.violations, formatViolations(results.violations)).toEqual([]);
  });

  test('map builder page has no accessibility violations', async ({ page }) => {
    await page.goto(`/maps/${builderMapId}`);
    await page.waitForLoadState('networkidle');

    // Wait for builder sidebar to be present
    await expect(
      page.locator('input[type="text"]').first(),
    ).toBeVisible({ timeout: 15_000 });

    const results = await new AxeBuilder({ page })
      .withTags(wcagTags)
      .exclude('.maplibregl-canvas')
      .exclude('.maplibregl-ctrl-attrib-inner')
      .analyze();

    expect(results.violations, formatViolations(results.violations)).toEqual([]);
  });

  test('Add Dataset dialog has no accessibility violations', async ({ page }) => {
    await page.goto(`/maps/${builderMapId}`);
    await page.waitForLoadState('networkidle');

    await expect(page.getByTestId('builder-sidebar')).toBeVisible({ timeout: 15_000 });
    await page.getByRole('button', { name: /add data/i }).first().click();

    const dialog = page.getByRole('dialog', { name: /add dataset/i });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByRole('radio', { name: 'All' })).toBeVisible();

    const results = await new AxeBuilder({ page })
      .withTags(wcagTags)
      .include('[role="dialog"]')
      .analyze();

    expect(results.violations, formatViolations(results.violations)).toEqual([]);
  });

  test('admin overview page has no accessibility violations', async ({ page }) => {
    await page.goto('/admin');
    await expect(
      page.getByRole('heading', { level: 1 }),
    ).toBeVisible();
    await page.waitForLoadState('networkidle');

    const results = await new AxeBuilder({ page })
      .withTags(wcagTags)
      .analyze();

    expect(results.violations, formatViolations(results.violations)).toEqual([]);
  });

  // fix(#438): A11Y-12 — the audit found Import, Settings, and Collections
  // uncovered. Same wcagTags contract as the routes above.
  for (const { name, path } of [
    { name: 'import', path: '/import' },
    { name: 'settings', path: '/settings' },
    { name: 'collections', path: '/collections' },
  ]) {
    test(`${name} page has no accessibility violations`, async ({ page }) => {
      await page.goto(path);
      await page.waitForLoadState('networkidle');

      const results = await new AxeBuilder({ page })
        .withTags(wcagTags)
        .analyze();

      expect(results.violations, formatViolations(results.violations)).toEqual([]);
    });
  }

  test.describe('register (logged out)', () => {
    test.use({ storageState: { cookies: [], origins: [] } });

    test('register page has no accessibility violations', async ({ page }) => {
      await page.goto('/register');
      await page.waitForLoadState('networkidle');

      const results = await new AxeBuilder({ page })
        .withTags(wcagTags)
        .analyze();

      expect(results.violations, formatViolations(results.violations)).toEqual([]);
    });
  });
});
