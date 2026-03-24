import { test, expect } from '@playwright/test';
import path from 'path';

test.describe.serial('Non-spatial CSV', () => {
  let datasetUrl = '';

  test('upload non-spatial CSV and complete ingestion', async ({ page }) => {
    test.slow();

    await page.goto('/import');

    await expect(
      page.getByRole('heading', { name: 'Import Data' }),
    ).toBeVisible();

    const fileInput = page.locator('input[type="file"]');
    await fileInput.setInputFiles(
      path.join(__dirname, 'fixtures/sample-nonspatial.csv'),
    );

    // Wait for preview
    await expect(page.getByText('sample-nonspatial')).toBeVisible({
      timeout: 30_000,
    });

    // Commit the import
    await page
      .getByRole('button', { name: /Import|Commit/i })
      .first()
      .click();

    // Wait for ingestion to complete
    await expect(
      page.getByText(/complete|tracking|success|Import Progress/i),
    ).toBeVisible({ timeout: 30_000 });

    // Store the URL for subsequent tests
    datasetUrl = page.url();
  });

  test('dataset page shows graceful non-spatial state', async ({ page }) => {
    // Navigate via search to find the uploaded dataset
    await page.goto('/?q=sample-nonspatial');
    const link = page
      .getByRole('link', { name: /sample-nonspatial/i })
      .first();
    await expect(link).toBeVisible({ timeout: 15_000 });
    await link.click();
    await page.waitForURL(/\/datasets\//);

    // Verify page loads with heading
    await expect(
      page.getByRole('heading', { level: 1 }),
    ).toBeVisible({ timeout: 10_000 });

    // No error toasts visible
    const errorToast = page.locator('[data-sonner-toast][data-type="error"]');
    await expect(errorToast).toHaveCount(0);

    // Store URL for next test
    datasetUrl = page.url();
  });

  test('attribute table shows rows for non-spatial dataset', async ({
    page,
  }) => {
    // Navigate to the dataset page
    await page.goto(datasetUrl || '/?q=sample-nonspatial');
    if (!datasetUrl) {
      const link = page
        .getByRole('link', { name: /sample-nonspatial/i })
        .first();
      await expect(link).toBeVisible({ timeout: 15_000 });
      await link.click();
      await page.waitForURL(/\/datasets\//);
    }

    // Wait for the page to load
    await expect(
      page.getByRole('heading', { level: 1 }),
    ).toBeVisible({ timeout: 10_000 });

    // Look for attribute table content — the table should show the CSV rows
    // Check for at least one of the expected values in the page
    await expect(page.getByText('Alice')).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText('Bob')).toBeVisible();
    await expect(page.getByText('Charlie')).toBeVisible();
  });
});
