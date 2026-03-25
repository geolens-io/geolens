import { test, expect } from '@playwright/test';
import path from 'path';

test.describe.serial('Non-spatial CSV', () => {
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

    // Wait for job tracking UI to appear (Import Progress heading or View Dataset link)
    await expect(
      page.getByText(/Import Progress|View Dataset/),
    ).toBeVisible({ timeout: 30_000 });
  });

  test('dataset page shows graceful non-spatial state', async ({ page }) => {
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
  });

  test('attribute table shows rows for non-spatial dataset', async ({
    page,
  }) => {
    await page.goto('/?q=sample-nonspatial');
    const link = page
      .getByRole('link', { name: /sample-nonspatial/i })
      .first();
    await expect(link).toBeVisible({ timeout: 15_000 });
    await link.click();
    await page.waitForURL(/\/datasets\//);

    // Wait for the page to load
    await expect(
      page.getByRole('heading', { level: 1 }),
    ).toBeVisible({ timeout: 10_000 });

    // Check for expected CSV row values in the attribute table
    await expect(page.getByText('Alice')).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText('Bob')).toBeVisible();
    await expect(page.getByText('Charlie')).toBeVisible();
  });
});
