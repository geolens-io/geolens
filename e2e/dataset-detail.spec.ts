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
    await expect(page.getByText('FEATURES')).toBeVisible();

    // Verify export triggers download
    await page.getByRole('tab', { name: 'Access' }).click();
    await expect(page.getByRole('button', { name: 'Export' })).toBeVisible();
    const downloadPromise = page.waitForEvent('download');
    await page.getByRole('button', { name: 'Export' }).click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toBeTruthy();
  });

  // Removed 2026-05-07 (v1.1.0 UAT, TEST-10 Path B). The test asserted that
  // typing into the multiline InlineEdit textarea then clicking the Overview
  // tab leaves the draft as a "pending edit". That contradicts the UX shipped
  // in commit a8c75e67 ("Fix multiline InlineEdit save-on-blur (cancel on
  // blur, Ctrl+Enter to save)") — multiline blur explicitly calls cancel(),
  // so a tab-click reverts the draft and pending-edits-bar never appears.
  //
  // Phase 278-06 (TEST-10) Path A unskipped this test with a PATCH-seed
  // fixture for the upstream empty-summary race, but Path A could not fix
  // the inherent blur-cancels-draft conflict. The 5-run flake check at the
  // v1.1.0 UAT exposed this; per Phase 278-06's own decision memo, the
  // documented fall-through is Path B with vitest alternative coverage:
  //
  //   | Behavior                                 | Vitest coverage                                   |
  //   |------------------------------------------|---------------------------------------------------|
  //   | Pending bar lifecycle (save + cancel)    | DatasetPage.edit-affordances.test.tsx:267-298,300-315 |
  //   | PendingEditsBar isolated lifecycle (4×)  | components/dataset/__tests__/PendingEditsBar.test.tsx |
  //   | EditableFieldShell role-gating + hint    | components/dataset/__tests__/EditableFieldShell.test.tsx |
  //
  // All 12 vitest cases pass. The lost coverage is the real-network
  // integration path (browser → frontend → backend → Postgres) for these
  // exact assertions, which the surviving test 1 (`map renders, attribute
  // table loads, export triggers download`) above still exercises against
  // the same dataset.

  // The previous "context guard choices, validation troubleshoot, and
  // freshness guidance are visible in-flow" test was deleted (test-audit
  // v13.12, H-33). It exercised an "edit-context" toggle UI
  // (`edit-context-option-attributes`, `edit-context-option-metadata`,
  // `context-switch-guard-dialog`, `Save & switch`, `Discard & switch`)
  // that was never shipped — no matching components or testIds exist in
  // `frontend/src/components/dataset/`. The validation-troubleshoot and
  // quality-freshness assertions live on inside `ValidationStatus.test.tsx`
  // and `QualityScoreCard.test.tsx` (vitest) which cover the same surface
  // without depending on the absent context-switch UI.
});
