import { test, expect, type Page } from '@playwright/test';
import fs from 'fs';
import path from 'path';

const AUTH_FILE = path.join(__dirname, '../playwright/.auth/user.json');
const BASE_URL = process.env.E2E_BASE_URL ?? 'http://localhost:8080';

function getAuthToken(): string {
  const raw = fs.readFileSync(AUTH_FILE, 'utf-8');
  const state = JSON.parse(raw);
  for (const origin of state.origins ?? []) {
    for (const entry of origin.localStorage ?? []) {
      if (entry.name === 'geolens-auth') {
        return JSON.parse(entry.value).state?.token ?? '';
      }
    }
  }
  throw new Error('Could not extract auth token from storage state');
}

// Discover the first visible vector dataset at runtime instead of hardcoding a UUID.
// The seed script creates "Admin 0 Countries (10m)" and "Reefs (10m)".
let datasetTitle: string;
let datasetId: string;

async function openAdminCountriesDataset(page: Page) {
  await page.goto(`/datasets/${datasetId}`);
  await page.waitForURL(new RegExp(`/datasets/${datasetId}$`));
}

test.describe('Dataset Detail', () => {
  test.beforeAll(async () => {
    const token = getAuthToken();
    const headers = { Authorization: `Bearer ${token}` };
    const res = await fetch(`${BASE_URL}/api/datasets/?limit=10`, { headers });
    expect(res.ok).toBe(true);
    const data = await res.json();
    const datasets = data.datasets ?? data.items ?? data;
    // Prefer a seeded dataset with many features (not a tiny upload test artifact)
    const vector = datasets
      .filter((ds: any) => ds.record_type === 'vector_dataset')
      .sort((a: any, b: any) => (b.feature_count ?? 0) - (a.feature_count ?? 0));
    const ds = vector[0] ?? datasets[0];
    expect(ds).toBeTruthy();
    datasetId = ds.id;
    datasetTitle = ds.title;
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
    await expect(page.getByRole('button', { name: 'Export' })).toBeVisible();
    const downloadPromise = page.waitForEvent('download');
    await page.getByRole('button', { name: 'Export' }).click();
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

  // Two tests removed in v13.12 H-33 / v13.13 Phase 278-06 TEST-10 Path B.
  // Coverage moved to vitest (DatasetPage.edit-affordances, PendingEditsBar,
  // EditableFieldShell, ValidationStatus, QualityScoreCard). See
  // .planning/milestones/v13.13-MILESTONE-AUDIT.md (TEST-10) for rationale.
});
