import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

const wcagTags = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'];

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
    // Navigate with query param to bypass hero→sticky SearchBar transition
    await page.goto('/?q=Reefs');
    await page.waitForLoadState('networkidle');
    const link = page.getByRole('link', { name: /Reefs \(10m\)/ }).first();
    await expect(link).toBeVisible({ timeout: 15_000 });
    await link.click();

    // Wait for dataset detail to load
    await expect(
      page.getByRole('heading', { name: /Reefs/ }),
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
    await page.goto('/maps/new');
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
