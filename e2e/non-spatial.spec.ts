import { test, expect } from '@playwright/test';
import fs from 'fs';
import os from 'os';
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

test.describe.serial('Non-spatial CSV', () => {
  const datasetSlug = `sample-nonspatial-${Date.now()}`;
  const tempCsvDir = fs.mkdtempSync(path.join(os.tmpdir(), 'geolens-nonspatial-'));
  const tempCsvPath = path.join(tempCsvDir, `${datasetSlug}.csv`);
  let datasetId: string | null = null;
  let datasetTitle: string | null = null;

  test.beforeAll(() => {
    fs.copyFileSync(
      path.join(__dirname, 'fixtures/sample-nonspatial.csv'),
      tempCsvPath,
    );
  });

  test.afterAll(async () => {
    try {
      if (datasetId && datasetTitle) {
        let payload: { deleted: number; errors: number; results?: unknown[] } | null = null;

        for (let attempt = 0; attempt < 5; attempt++) {
          const response = await fetch(`${BASE_URL}/api/datasets/bulk-delete/`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              Authorization: `Bearer ${getAuthToken()}`,
            },
            body: JSON.stringify({
              datasets: [{ dataset_id: datasetId, confirm_title: datasetTitle }],
            }),
          });
          expect(response.ok).toBe(true);
          payload = await response.json();
          if (payload.deleted === 1 && payload.errors === 0) break;
          await new Promise((resolve) => setTimeout(resolve, 1_000));
        }

        expect(payload?.deleted).toBe(1);
        expect(payload?.errors).toBe(0);
      }
    } finally {
      fs.rmSync(tempCsvDir, { recursive: true, force: true });
    }
  });

  test('upload non-spatial CSV and complete ingestion', async ({ page }) => {
    test.slow();

    await page.goto('/import');

    await expect(
      page.getByRole('heading', { name: 'Import Data' }),
    ).toBeVisible();

    const fileInput = page.locator('input[type="file"]');
    await fileInput.setInputFiles(tempCsvPath);

    // Wait for preview
    await expect(page.getByText(datasetSlug)).toBeVisible({
      timeout: 30_000,
    });

    // Commit the import
    await page
      .getByRole('button', { name: /Import|Commit/i })
      .first()
      .click();

    // Wait for job tracking UI to appear. The bulk-tracking list now
    // ships the completed row with an "Open dataset" link (import.json
    // `bulk.openDataset`); older builds used "View Dataset". Accept both
    // so the test survives either translation string.
    await expect(
      page.getByText(/Import Progress|Open dataset|View Dataset/),
    ).toBeVisible({ timeout: 30_000 });

    const datasetLink = page.getByRole('link', {
      name: /Open dataset|View Dataset/i,
    });
    await expect(datasetLink).toBeVisible({ timeout: 30_000 });
    await datasetLink.click();
    await page.waitForURL(/\/datasets\/([a-f0-9-]+)$/);

    const match = page.url().match(/\/datasets\/([a-f0-9-]+)$/);
    expect(match?.[1]).toBeTruthy();
    datasetId = match![1];
    datasetTitle = datasetSlug;
    expect(datasetTitle).toBeTruthy();
  });

  test('dataset page shows graceful non-spatial state', async ({ page }) => {
    expect(datasetId).toBeTruthy();
    await page.goto(`/datasets/${datasetId}`);

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
    expect(datasetId).toBeTruthy();
    await page.goto(`/datasets/${datasetId}`);

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
