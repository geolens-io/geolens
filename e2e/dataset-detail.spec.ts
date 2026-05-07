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

function deriveDistinctDraft(currentSummary: string, marker: string): string {
  const suffix = ` [${marker}]`;
  const trimmedSummary = currentSummary.trimEnd();

  if (trimmedSummary.endsWith(suffix)) {
    const withoutSuffix = trimmedSummary.slice(0, -suffix.length).trimEnd();
    return withoutSuffix.length > 0 ? withoutSuffix : `${marker} draft`;
  }

  return trimmedSummary.length > 0 ? `${trimmedSummary}${suffix}` : `${marker} draft`;
}

async function openAdminCountriesDataset(page: Page) {
  await page.goto(`/datasets/${datasetId}`);
  await page.waitForURL(new RegExp(`/datasets/${datasetId}$`));
}

async function setStoredUserRoles(page: Page, roles: string[]) {
  await page.evaluate((nextRoles) => {
    const raw = localStorage.getItem('geolens-auth');
    if (!raw) return;

    const parsed = JSON.parse(raw) as {
      state?: {
        user?: {
          roles?: string[];
        };
      };
    };

    if (!parsed.state?.user) return;
    parsed.state.user.roles = nextRoles;
    localStorage.setItem('geolens-auth', JSON.stringify(parsed));
  }, roles);
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

  // Re-enabled 2026-05-07 (Phase 278, TEST-10) — replaces the racy
  // UI-driven fill-prelude with a deterministic API-seeded fixture so the
  // pending-edits state machine starts from a known-good baseline. The
  // prior skipped test (commit 2dff66e1) cited "data-dependent timing
  // issue": the conditional `if summary == "" : fill : noop` prelude
  // raced against initial render on CI. Seeding via PATCH
  // `/api/datasets/{id}` removes the race entirely.
  test('editable markers, viewer hint-on-attempt, and pending lifecycle remain stable', async ({
    page,
  }) => {
    // Deterministic seed: PATCH the summary to a known value BEFORE the UI
    // test runs. Bypasses the editable-field state-machine race fixed in
    // Phase 278 (TEST-10, H-33). The seeded summary is unique per run so
    // re-runs against the same dataset don't rely on prior state.
    const token = getAuthToken();
    const seedSummary = `E2E baseline summary (run ${Date.now()})`;
    const seedResp = await page.request.patch(
      `${BASE_URL}/api/datasets/${datasetId}`,
      {
        headers: {
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        data: { summary: seedSummary },
      },
    );
    expect(seedResp.ok()).toBe(true);

    await openAdminCountriesDataset(page);

    // Ensure Overview tab is active and loaded
    await expect(page.getByRole('tab', { name: 'Overview' })).toBeVisible();

    const summaryShell = page.getByTestId('editable-field-shell-summary');
    await expect(summaryShell).toHaveAttribute('data-editable', 'true');

    // Open the InlineEdit textarea by clicking the role=button trigger; the
    // shell renders the editor inline once summaryValue is non-empty (which
    // the API seed guarantees).
    const summaryTextarea = summaryShell.locator('textarea');
    await summaryShell.locator('[role="button"]').click();
    await expect(summaryTextarea).toBeVisible();
    await expect(summaryTextarea).toHaveValue(seedSummary);

    // Pending bar appears after draft changes and disappears after cancel.
    const cancelBaseline = await summaryTextarea.inputValue();
    const cancelDraft = deriveDistinctDraft(cancelBaseline, 'pending-cancel');
    await summaryTextarea.fill(cancelDraft);
    expect(cancelDraft).not.toBe(cancelBaseline);
    await expect(summaryTextarea).not.toHaveValue(cancelBaseline);
    await page.getByRole('tab', { name: 'Overview' }).click();

    await expect(page.getByTestId('pending-edits-bar')).toBeVisible();
    await expect(page.getByTestId('pending-edits-count')).toContainText('unsaved change');

    await page.getByTestId('pending-edits-cancel').click();
    await expect(page.getByTestId('pending-edits-bar')).toHaveCount(0);

    // Pending bar also clears after save.
    await summaryShell.locator('[role="button"]').click();
    await expect(summaryTextarea).toBeVisible();
    const saveBaseline = await summaryTextarea.inputValue();
    const saveDraft = deriveDistinctDraft(saveBaseline, 'pending-save');
    await summaryTextarea.fill(saveDraft);
    expect(saveDraft).not.toBe(saveBaseline);
    await expect(summaryTextarea).not.toHaveValue(saveBaseline);
    await page.getByRole('tab', { name: 'Overview' }).click();

    await expect(page.getByTestId('pending-edits-bar')).toBeVisible();
    await page.getByTestId('pending-edits-save').click();
    await expect(page.getByTestId('pending-edits-bar')).toHaveCount(0);

    // Simulate viewer capability state to verify neutral read-only defaults and hint-on-attempt.
    await setStoredUserRoles(page, ['viewer']);
    await page.reload();

    const viewerSummaryShell = page.getByTestId('editable-field-shell-summary');
    await expect(viewerSummaryShell).toHaveAttribute('data-editable', 'false');
    await expect(viewerSummaryShell).toHaveClass(/bg-transparent/);
    await expect(viewerSummaryShell.getByTestId('editable-field-shell-icon')).toHaveCount(0);

    const denyHintText = 'You can view this field. Editors can make changes.';
    await expect(page.getByText(denyHintText)).toHaveCount(0);
    await viewerSummaryShell.click();
    await expect(page.getByText(denyHintText)).toBeVisible();
  });

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
