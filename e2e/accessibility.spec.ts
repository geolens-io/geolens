import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { getAuthToken, getSearchSeed } from './helpers/catalog';

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

  test.beforeAll(async () => {
    const response = await fetch(`${BASE_URL}/api/maps/`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${getAuthToken()}`,
      },
      body: JSON.stringify({
        name: `A11y Builder Test ${Date.now()}`,
        description: 'Temporary map for builder accessibility coverage',
      }),
    });

    expect(response.ok).toBe(true);
    const payload = await response.json();
    builderMapId = payload.id;
    expect(builderMapId).toBeTruthy();
  });

  test.afterAll(async () => {
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
  });

  test('dataset detail page has no accessibility violations', async ({ page }) => {
    const seed = await getSearchSeed();

    await page.goto(`/datasets/${seed.id}`);
    await page.waitForLoadState('networkidle');

    // Wait for dataset detail to load
    await expect(
      page.getByRole('heading', { name: seed.title, exact: true }),
    ).toBeVisible();
    await page.waitForLoadState('networkidle');

    // Exclude MapLibre canvas -- WebGL canvases cannot be inspected by axe
    const results = await new AxeBuilder({ page })
      .withTags(wcagTags)
      .exclude('.maplibregl-map')
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
});
