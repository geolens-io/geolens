import { test, expect } from '@playwright/test';
import { getAuthToken, seedDataset, deleteDataset, type SeededDataset } from './helpers/catalog';

const BASE_URL = process.env.E2E_BASE_URL ?? 'http://localhost:8080';
const OUTPUT_TITLE = `E2E Analysis Buffer ${Date.now()}`;

/**
 * Builder analysis tools (M4): buffer preview + materialize to a new dataset.
 * The completion toast is page-owned, so it must appear even after the
 * Analysis panel is closed mid-job (fix #682).
 */
test.describe('builder analysis tools', () => {
  let seed: SeededDataset;
  let mapId: string;
  let headers: Record<string, string>;
  let createdDatasetId: string | null = null;

  test.beforeAll(async () => {
    headers = {
      Authorization: `Bearer ${getAuthToken()}`,
      'Content-Type': 'application/json',
    };
    // Title must not contain "Analysis" — layer-row button labels embed the
    // dataset title and would collide with the rail button's accessible name.
    seed = await seedDataset('E2E Buffer Source');

    const mapRes = await fetch(`${BASE_URL}/api/maps/`, {
      method: 'POST',
      headers,
      body: JSON.stringify({
        name: 'E2E Analysis Map',
        description: 'Auto-created for analysis e2e',
      }),
    });
    expect(mapRes.ok).toBe(true);
    mapId = (await mapRes.json()).id;

    const layerRes = await fetch(`${BASE_URL}/api/maps/${mapId}/layers/`, {
      method: 'POST',
      headers,
      body: JSON.stringify({ dataset_id: seed.id }),
    });
    expect(layerRes.ok).toBe(true);
  });

  test.afterAll(async () => {
    if (mapId) {
      await fetch(`${BASE_URL}/api/maps/${mapId}`, { method: 'DELETE', headers });
    }
    if (createdDatasetId) {
      await deleteDataset(createdDatasetId, OUTPUT_TITLE);
    }
    if (seed) {
      await deleteDataset(seed.id, seed.title);
    }
  });

  test('buffer preview, materialize, and page-level completion toast', async ({ page }) => {
    await page.goto(`/maps/${mapId}`);
    await expect(page.locator('canvas.maplibregl-canvas')).toBeVisible({ timeout: 15_000 });

    await page.getByRole('button', { name: 'Analysis', exact: true }).click();
    await expect(page.getByTestId('analysis-panel')).toBeVisible();

    // Default operation is buffer @ 500 m; the only dataset layer auto-selects.
    await page.getByRole('button', { name: 'Preview', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Clear preview' })).toBeVisible({
      timeout: 15_000,
    });

    await page.getByLabel('New dataset name').fill(OUTPUT_TITLE);
    const materializeResponse = page.waitForResponse(
      (r) => r.url().includes('/analysis/materialize/') && r.request().method() === 'POST',
    );
    await page.getByRole('button', { name: 'Create dataset' }).click();
    const { job_id: jobId } = (await (await materializeResponse).json()) as {
      job_id: string;
    };
    expect(jobId).toBeTruthy();

    // Abandon the builder mid-job: tracking is global (AnalysisJobWatcher in
    // RootLayout), so completion must still surface on a different page — with
    // "View dataset" rather than "Add to map", since no builder is mounted.
    await page.getByRole('button', { name: 'Close panel' }).click();
    await page.goto('/');
    // Scope to the toast: the finished dataset also lands in the catalog list
    // behind it (which is the query invalidation doing its job).
    const completionToast = page
      .locator('[data-sonner-toast]')
      .filter({ hasText: OUTPUT_TITLE });
    await expect(completionToast).toBeVisible({ timeout: 60_000 });
    await expect(
      completionToast.getByRole('button', { name: 'View dataset' }),
    ).toBeVisible();

    // Resolve the created dataset id for cleanup.
    for (let attempt = 0; attempt < 30; attempt++) {
      const res = await fetch(`${BASE_URL}/api/jobs/${jobId}`, { headers });
      if (res.ok) {
        const body = (await res.json()) as { status: string; dataset_id: string | null };
        if (body.status === 'complete' && body.dataset_id) {
          createdDatasetId = body.dataset_id;
          break;
        }
        if (body.status === 'failed') throw new Error('analysis job failed');
      }
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }
    expect(createdDatasetId).toBeTruthy();
  });
});
