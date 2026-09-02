import { test, expect } from '@playwright/test';
import path from 'path';

test.describe('Upload Flow', () => {
  test('upload file, see preview, commit ingestion', async ({ page }) => {
    test.slow();

    await page.goto('/import');

    // Verify import page renders (heading uses i18n, check for the Upload tab)
    await expect(
      page.getByRole('heading', { level: 1 }),
    ).toBeVisible();

    // Upload tab should be active by default
    const uploadTab = page.locator('button').filter({ hasText: /Upload/i }).first();
    await expect(uploadTab).toBeVisible();

    // Upload via hidden file input (react-dropzone renders a hidden input).
    // fix(#432): files staged during the upload-config boot fetch are queued
    // and flushed once the config settles, so a single set must stage the row
    // — no reload-retry. This test failing here means the queue regressed.
    const fileInput = page.locator('input[type="file"]');
    await fileInput.setInputFiles(
      path.join(__dirname, 'fixtures/sample.geojson'),
    );
    await expect(page.getByText('sample')).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText('Using embedded geometry')).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText('Import as non-spatial')).toHaveCount(0);

    // Commit the import
    await page
      .getByRole('button', { name: /Import|Commit/i })
      .first()
      .click();

    // Verify tracking phase (import progress) and compact completion state
    await expect(page.getByText(/Importing \d+ files/i)).toBeVisible({
      timeout: 30_000,
    });
    await expect(page.getByRole('link', { name: 'Open dataset' })).toBeVisible({
      timeout: 30_000,
    });
  });

  // fix(#1712): a tab switch used to unmount UploadForm entirely, dropping
  // whatever the in-flight upload+preview had produced. The module-scoped
  // upload-session (api/upload-session.ts) keeps that work reachable, so
  // switching away and back shows the same batch instead of a job-less
  // dropzone.
  test('a tab switch mid-upload does not strand the batch', async ({ page }) => {
    test.slow();

    await page.goto('/import');

    const fileInput = page.locator('input[type="file"]');
    await fileInput.setInputFiles(
      path.join(__dirname, 'fixtures/sample.geojson'),
    );

    // Switch away, then back, before asserting anything about the upload —
    // exercising a switch that can land mid-upload or mid-preview rather
    // than waiting for either to settle first.
    await page.locator('button').filter({ hasText: /STAC/i }).first().click();
    await page.locator('button').filter({ hasText: /Upload/i }).first().click();

    // The upload and preview kept running server-side while the tab was
    // hidden; the Upload tab shows the resumed batch's progress rather than
    // an empty dropzone with no memory of the drop.
    //
    // Scoped to the file row's accessible name rather than a bare
    // getByText('sample') — by this point the preview panel's derived
    // layer name (e.g. "<uuid>_sample") also contains "sample" as a
    // substring, and a bare text match against both is ambiguous.
    await expect(
      page.getByRole('button', { name: /sample\.geojson/i }),
    ).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText('Using embedded geometry')).toBeVisible({ timeout: 30_000 });
  });
});
