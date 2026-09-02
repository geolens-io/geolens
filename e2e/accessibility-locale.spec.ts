import { test } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { getAuthToken, seedDataset, deleteDataset, type SeededDataset } from './helpers/catalog';

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

/**
 * fix(#1778): playwright.config.ts pins `locale: 'en-US'` for every project,
 * so es/fr/de bundles never render under the gating axe suite in
 * accessibility.spec.ts — only the dark-mode half of that finding (#1782)
 * has been closed so far. A full 4-locale x N-route x 2-color-scheme sweep
 * folded into the gating suite would multiply its wall-clock well past the
 * "stays under 2 minutes" budget, so this mirrors the wcag22aa precedent
 * (#1790, accessibility-target-size.spec.ts): a separate, non-gating scan
 * that only reports (console + attachment), scoped to `de` (German strings
 * run longest of the three non-English locales, so it is the locale most
 * likely to break layouts sized for English) over the densest few routes:
 * the map builder sidebar, the dataset detail page, and the admin settings
 * forms.
 *
 * Deliberately not listed in any package.json `e2e:smoke:*` script, so the
 * per-PR smoke gates never pick it up (same precedent as
 * accessibility-target-size.spec.ts and analysis.spec.ts).
 */
test.describe('Accessibility locale scan — de (non-gating)', () => {
  test.use({ locale: 'de' });

  let seed: SeededDataset;
  let mapId: string;

  test.beforeAll(async () => {
    seed = await seedDataset('A11y Locale Seed Dataset');
    const headers = {
      Authorization: `Bearer ${getAuthToken()}`,
      'Content-Type': 'application/json',
    };

    const mapRes = await fetch(`${BASE_URL}/api/maps/`, {
      method: 'POST',
      headers,
      body: JSON.stringify({
        name: `A11y Locale Map ${Date.now()}`,
        description: 'Fixture for the non-gating de locale scan',
      }),
    });
    if (!mapRes.ok) throw new Error(`map create failed: ${mapRes.status}`);
    mapId = ((await mapRes.json()) as { id: string }).id;

    const layerRes = await fetch(`${BASE_URL}/api/maps/${mapId}/layers/`, {
      method: 'POST',
      headers,
      body: JSON.stringify({ dataset_id: seed.id }),
    });
    if (!layerRes.ok) throw new Error(`layer create failed: ${layerRes.status}`);
  });

  test.afterAll(async () => {
    if (mapId) {
      await fetch(`${BASE_URL}/api/maps/${mapId}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${getAuthToken()}` },
      }).catch(() => {
        /* teardown is best-effort; the CI stack is torn down anyway */
      });
    }
    if (seed) await deleteDataset(seed.id, seed.title);
  });

  async function scanAndReport(page: import('@playwright/test').Page, testInfo: import('@playwright/test').TestInfo, label: string) {
    const results = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
      .analyze();

    if (results.violations.length > 0) {
      const formatted = formatViolations(results.violations);
      // eslint-disable-next-line no-console
      console.warn(`[de locale scan, non-gating] ${label}: ${results.violations.length} violation(s):\n${formatted}`);
      await testInfo.attach(`de-locale-violations-${label}.txt`, {
        body: formatted,
        contentType: 'text/plain',
      });
    }
    // No assertion on results.violations by design (see module docstring):
    // this scan reports for later scoping, it does not gate CI.
  }

  test('map builder page: de locale scan (reports only)', async ({ page }, testInfo) => {
    await page.goto(`/maps/${mapId}`);
    await page.waitForLoadState('networkidle');
    await scanAndReport(page, testInfo, 'map-builder');
  });

  test('dataset detail page: de locale scan (reports only)', async ({ page }, testInfo) => {
    await page.goto(`/datasets/${seed.id}`);
    await page.waitForLoadState('networkidle');
    await scanAndReport(page, testInfo, 'dataset-detail');
  });

  test('admin settings page: de locale scan (reports only)', async ({ page }, testInfo) => {
    await page.goto('/admin/settings');
    await page.waitForLoadState('networkidle');
    await scanAndReport(page, testInfo, 'admin-settings');
  });
});
