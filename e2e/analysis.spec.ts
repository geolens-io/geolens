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

    // fix(#894): resolve the id BEFORE asserting on the toast, so an assertion
    // failure still cleans up. Previously each failed attempt leaked one output
    // dataset (visible as the catalog count climbing across retries).
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

    // Leave the builder: tracking is global (AnalysisJobWatcher in RootLayout),
    // so the completion toast must still be standing on a different page.
    //
    // fix(#894): navigate CLIENT-SIDE rather than page.goto('/'). A materialize
    // job here finishes in ~80 ms, so the toast is normally raised while the
    // builder is still mounted; a hard reload then destroys it and rehydrates
    // the store with job: null, leaving nothing to re-poll. That made the old
    // assertion a coin flip on how fast the UI steps ran. The comment above the
    // watcher claims a reloaded tab still reports, and it does — but only for a
    // job still running at reload time, which an 80 ms job never is. Nothing to
    // fix in the product: it toasted at completion, on the page the user was on.
    await page.getByRole('button', { name: 'Close panel' }).click();
    await page.locator('header nav').getByRole('link', { name: 'Maps' }).click();
    await expect(page).toHaveURL(/\/maps$/);
    // Scope to the toast: the finished dataset also lands in the catalog list
    // behind it (which is the query invalidation doing its job).
    const completionToast = page
      .locator('[data-sonner-toast]')
      .filter({ hasText: OUTPUT_TITLE });
    await expect(completionToast).toBeVisible({ timeout: 60_000 });
    // fix(#894): the action label is decided once, when the toast is raised —
    // canAddToMap depends on MapBuilderPage being mounted at that instant. With
    // a job this fast it is "Add to map"; a genuinely slow job gets
    // "View dataset". Assert the actionable affordance, not which branch won.
    await expect(
      completionToast.getByRole('button', { name: /Add to map|View dataset/ }),
    ).toBeVisible();
  });
});
