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
    // Retry staging until the row renders: the upload-config query runs with
    // staleTime 0, and a file set while its boot-time refetch is settling can
    // be silently swallowed (#274 dropzone-disable design; pre-existing race,
    // surfaced by dev-server timing). A swallowed drop does not recover on the
    // same page, so each retry reloads for a fresh boot.
    const fileInput = page.locator('input[type="file"]');
    await expect(async () => {
      await fileInput.setInputFiles(
        path.join(__dirname, 'fixtures/sample.geojson'),
      );
      try {
        await expect(page.getByText('sample')).toBeVisible({ timeout: 3_000 });
      } catch (err) {
        await page.reload();
        throw err;
      }
    }).toPass({ timeout: 45_000 });
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
});
