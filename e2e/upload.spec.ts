import { test, expect } from '@playwright/test';
import path from 'path';

test.describe('Upload Flow', () => {
  test('upload file, see preview, commit ingestion', async ({ page }) => {
    test.slow();

    await page.goto('/import');

    // Verify import page
    await expect(
      page.getByRole('heading', { name: 'Import Data' }),
    ).toBeVisible();
    await expect(page.getByTestId('import-upload-sidebar')).toBeVisible();

    // Upload via hidden file input (react-dropzone renders a hidden input)
    const fileInput = page.locator('input[type="file"]');
    await fileInput.setInputFiles(
      path.join(__dirname, 'fixtures/sample.geojson'),
    );

    // Wait for upload + preview to appear (reviewing phase)
    await expect(page.getByText('sample')).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText('Using embedded geometry')).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText('Import as non-spatial')).toHaveCount(0);

    // Commit the import
    await page
      .getByRole('button', { name: /Import|Commit/i })
      .first()
      .click();

    // Verify tracking phase (import progress) and compact completion state
    await expect(page.getByText(/complete|tracking|success|Import Progress/i)).toBeVisible({
      timeout: 30_000,
    });
    await expect(page.getByRole('link', { name: 'Open dataset' })).toBeVisible({
      timeout: 30_000,
    });
    await expect(page.getByRole('link', { name: 'View Dataset' })).toHaveCount(0);
    await expect(page.getByTestId('import-tracking-sidebar')).toBeVisible();
  });
});
