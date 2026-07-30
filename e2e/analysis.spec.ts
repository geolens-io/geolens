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

    // fix(#894): hold the browser's view of the job at "running" until the
    // builder is gone. This spec exists for #682 — a job that OUTLIVES the
    // builder must still report — but a materialize job here finishes in ~80 ms
    // and useJobStatus fetches immediately on mount, so in practice the toast
    // was raised while the builder was still up. The old spec then did
    // page.goto('/'), a hard reload, which destroyed that toast and rehydrated
    // the store with job: null, leaving nothing to re-poll; whether it passed
    // was a coin flip on how fast the UI steps ran (1 failed / 2 flaky on
    // 07-29, 2 failed on 07-30, ~1-in-4 locally). Waiting for completion before
    // navigating would be stable but vacuous: it would only prove a Sonner
    // toast survives client-side navigation, and would still pass if the
    // watcher stopped tracking on unmount. Masking the poll makes "mid-job"
    // true by construction, so the assertion pins the real invariant.
    // Node-side cleanup polling below uses fetch(), not the browser, so it is
    // unaffected by this route.
    let holdJobRunning = true;
    await page.route('**/api/jobs/*', async (route) => {
      const response = await route.fetch();
      if (!holdJobRunning) {
        await route.fulfill({ response });
        return;
      }
      const body = (await response.json()) as Record<string, unknown>;
      await route.fulfill({
        response,
        json: { ...body, status: 'running', dataset_id: null },
      });
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

    // Leave the builder while the browser still believes the job is running.
    // Tracking is global (AnalysisJobWatcher in RootLayout), so completion has
    // to surface here. Client-side navigation, not page.goto: a hard reload is
    // a different scenario (the store rehydrates) and is not what #682 covers.
    await page.getByRole('button', { name: 'Close panel' }).click();
    await page.locator('header nav').getByRole('link', { name: 'Maps' }).click();
    await expect(page).toHaveURL(/\/maps$/);
    await expect(page.getByTestId('analysis-panel')).toBeHidden();

    // Resolve the id for cleanup BEFORE any assertion that can fail — a failed
    // attempt used to leak one output dataset (the catalog count climbed
    // 3 → 4 → 5 across the three retries). This runs Node-side, so it sees the
    // true terminal status while the browser is still masked and has therefore
    // not toasted yet.
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

    // Scope to the toast: the finished dataset also lands in the catalog list
    // behind it (which is the query invalidation doing its job).
    const completionToast = page
      .locator('[data-sonner-toast]')
      .filter({ hasText: OUTPUT_TITLE });
    // The job is already complete server-side, yet nothing has toasted. This
    // asserts the mask held, which is what makes the next assertion mean
    // something: the toast below can only have been raised after the builder
    // was gone. Without this the test would still pass if AnalysisJobWatcher
    // stopped tracking on unmount, since a Sonner toast raised back on the
    // builder survives client-side navigation on its own.
    await expect(completionToast).toBeHidden();

    // Now let the real terminal status reach the browser. useJobStatus polls
    // every 2s, so the watcher picks it up with no builder mounted anywhere.
    holdJobRunning = false;

    await expect(completionToast).toBeVisible({ timeout: 60_000 });
    // "View dataset" rather than "Add to map" is deterministic now: the action
    // label is chosen when the toast is raised, from canAddToMap, which needs
    // MapBuilderPage mounted — and it provably is not, per the assertions above.
    await expect(
      completionToast.getByRole('button', { name: 'View dataset' }),
    ).toBeVisible();
  });
});
