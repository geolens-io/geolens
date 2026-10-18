import { test, expect, type Page, getAuthToken } from './helpers/session';
import path from 'path';

const BASE_URL = process.env.E2E_BASE_URL ?? 'http://localhost:8080';

// Discover the first visible vector dataset at runtime instead of hardcoding a UUID.
// The seed script creates "Admin 0 Countries (10m)" and "Reefs (10m)".
let datasetTitle: string;
let datasetId: string;
let multiPageId: string | undefined;

async function openAdminCountriesDataset(page: Page) {
  await page.goto(`/datasets/${datasetId}`);
  await page.waitForURL(new RegExp(`/datasets/${datasetId}$`));
}

test.describe('Dataset Detail', () => {
  test.beforeAll(async () => {
    const token = getAuthToken();
    const headers = { Authorization: `Bearer ${token}` };
    const res = await fetch(`${BASE_URL}/api/datasets/?limit=100`, { headers });
    expect(res.ok).toBe(true);
    const data = await res.json();
    const all = data.datasets ?? data.items ?? data;
    multiPageId = all.find(
      (ds: any) => ds.record_type === 'vector_dataset' && (ds.feature_count ?? 0) > 50,
    )?.id;
    const datasets = all.slice(0, 10);
    // Prefer a seeded dataset with many features (not a tiny upload test artifact)
    const vector = datasets
      .filter((ds: any) => ds.record_type === 'vector_dataset')
      .sort((a: any, b: any) => (b.feature_count ?? 0) - (a.feature_count ?? 0));
    const ds = vector[0] ?? datasets[0];
    expect(ds).toBeTruthy();
    datasetId = ds.id;
    datasetTitle = ds.title;
  });

  // The table scrolls in one box on both axes. A nested scroll container used
  // to clip the bottom rows, carry the sticky header away, and push the
  // horizontal scrollbar below the fold.
  test('attribute table keeps its header and last row in view when scrolled to the bottom', async ({
    page,
  }) => {
    test.skip(!multiPageId, 'needs a vector dataset with more than one 50-row page');

    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`/datasets/${multiPageId}`);
    await page.getByRole('tab', { name: 'Data', exact: true }).click();

    const region = page.getByRole('region', { name: 'Feature attributes' });
    await expect(region.locator('tbody tr[data-index="0"]')).toBeVisible({ timeout: 15_000 });
    // The box and its pagination fit the viewport without scrolling the page.
    await expect(page.getByRole('button', { name: 'Next', exact: true })).toBeInViewport({ ratio: 1 });
    expect(await page.evaluate(() => window.scrollY)).toBe(0);

    await region.evaluate((el) => {
      el.scrollTop = el.scrollHeight;
    });

    const lastRow = region.locator('tbody tr[data-index="49"]');
    await expect(lastRow).toBeVisible();
    const box = await region.boundingBox();
    const rowBox = await lastRow.boundingBox();
    const headerBox = await region.getByRole('row').first().boundingBox();
    expect(box && rowBox && headerBox).toBeTruthy();
    const bottom = box!.y + box!.height;
    expect(rowBox!.y).toBeGreaterThanOrEqual(box!.y);
    expect(rowBox!.y + rowBox!.height).toBeLessThanOrEqual(bottom + 1);
    expect(headerBox!.y).toBeGreaterThanOrEqual(box!.y - 1);
    expect(headerBox!.y + headerBox!.height).toBeLessThanOrEqual(rowBox!.y);
  });

  test('map renders, attribute table loads, export triggers download', async ({
    page,
  }) => {
    await openAdminCountriesDataset(page);

    // Regression: dataset detail should expose exactly one canonical title heading
    const datasetHeading = page.getByRole('heading', {
      level: 1,
      name: datasetTitle,
    });
    await expect(datasetHeading).toHaveCount(1);
    await expect(datasetHeading).toBeVisible();

    // Primary action (highest priority) is a visible button; others overflow.
    await expect(page.getByRole('button', { name: /^(Publish|Unpublish)$/ })).toBeVisible();

    // Re-Upload and Delete are in the overflow menu
    await page.getByRole('button', { name: 'More actions' }).click();
    await expect(page.getByRole('menuitem', { name: 'Re-Upload' })).toBeVisible();
    await expect(page.getByRole('menuitem', { name: 'Delete' })).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(page.getByRole('menuitem', { name: 'Delete' })).toHaveCount(0);

    // Verify map canvas renders
    await expect(page.locator('canvas.maplibregl-canvas')).toBeVisible({
      timeout: 15_000,
    });

    // Hierarchy regression: heading appears before map in DOM
    const headingBeforeMap = await page.evaluate(() => {
      const heading = document.querySelector('h1');
      const mapCanvas = document.querySelector('canvas.maplibregl-canvas');
      if (!heading || !mapCanvas) return null;
      return Boolean(
        heading.compareDocumentPosition(mapCanvas) & Node.DOCUMENT_POSITION_FOLLOWING,
      );
    });
    expect(headingBeforeMap).toBe(true);

    // Verify dataset detail content renders with metadata tabs
    await expect(page.locator('[role="tab"]').filter({ hasText: 'Overview' })).toBeVisible();
    // The DatasetStatsBar StatCell label renders the i18n string "Features"
    // visually upper-cased via Tailwind's `uppercase` class — Playwright's
    // getByText matches the underlying text-node content, not the CSS-rendered
    // form, so we match "Features" (not "FEATURES"). { exact: true } prevents
    // RelatedDatasets card text like "248 features" from substring-matching.
    await expect(page.getByText('Features', { exact: true })).toBeVisible();

    // Verify export triggers download
    await page.getByRole('tab', { name: 'Access' }).click();
    const downloadButton = page.getByRole('tabpanel').getByRole('button', { name: 'Download' }).first();
    await expect(downloadButton).toBeVisible();
    const downloadPromise = page.waitForEvent('download');
    await downloadButton.click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toBeTruthy();
  });

  test('IMPORT-04: M001 audit replay — reupload affordance is reachable via accessible name', async ({
    page,
  }) => {
    await openAdminCountriesDataset(page);

    // Mirror M001 audit method: scan the page for any affordance whose accessible name
    // mentions Replace / Re-Upload / Reupload / More. If reupload is hidden behind
    // an unlabeled kebab again, this locator will resolve to the affordance OR fail.
    const reuploadAffordance = page.getByRole('button', {
      name: /Re-Upload|Replace|Reupload|More/i,
    });
    // First() because there may be both a "More" trigger and a "Re-Upload" item
    // visible (when overflow is expanded by a previous step).
    await expect(reuploadAffordance.first()).toBeVisible({ timeout: 5_000 });
    await reuploadAffordance.first().click();

    // If the click opened the overflow menu, click the Re-Upload menuitem inside it.
    const reuploadMenuItem = page.getByRole('menuitem', { name: /Re-Upload/i });
    if (await reuploadMenuItem.isVisible().catch(() => false)) {
      await reuploadMenuItem.click();
    }

    // Either path leads to the reupload dialog.
    await expect(page.getByRole('dialog', { name: /Re-Upload Dataset/i })).toBeVisible({
      timeout: 5_000,
    });

    // Close dialog and confirm it's gone (regression for SF-style snapshot leakage).
    await page.keyboard.press('Escape');
    await expect(page.getByRole('dialog', { name: /Re-Upload Dataset/i })).toHaveCount(0);
  });

  // Two tests were removed here; coverage moved to vitest
  // (DatasetPage.edit-affordances, PendingEditsBar, EditableFieldShell,
  // ValidationStatus, QualityScoreCard).
});
