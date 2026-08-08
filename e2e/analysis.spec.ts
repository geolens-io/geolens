import { test, expect } from '@playwright/test';
import { getAuthToken, seedDataset, deleteDataset, type SeededDataset } from './helpers/catalog';

const BASE_URL = process.env.E2E_BASE_URL ?? 'http://localhost:8080';
const OUTPUT_TITLE = `E2E Analysis Buffer ${Date.now()}`;
const DISSOLVE_TITLE = `E2E Analysis Dissolve ${Date.now()}`;

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
  let dissolveDatasetId: string | null = null;

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
    if (dissolveDatasetId) {
      await deleteDataset(dissolveDatasetId, DISSOLVE_TITLE);
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

    // fix(#1253): preview is clipped to the current viewport, so fit the map
    // to the seeded New York layer after the panel opens and finalizes layout.
    await page.getByRole('button', { name: `Layer options for ${seed.title}` }).click();
    await page.getByTestId('kebab-zoom-to-layer').click();
    await page.waitForTimeout(1500); // the fly-to animation

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
  /** Poll Node-side for the job's terminal status and return the new dataset id. */
  async function awaitJobDataset(jobId: string): Promise<string> {
    for (let attempt = 0; attempt < 30; attempt++) {
      const res = await fetch(`${BASE_URL}/api/jobs/${jobId}`, { headers });
      if (res.ok) {
        const body = (await res.json()) as { status: string; dataset_id: string | null };
        if (body.status === 'complete' && body.dataset_id) return body.dataset_id;
        if (body.status === 'failed') throw new Error('analysis job failed');
      }
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }
    throw new Error(`job ${jobId} did not complete in time`);
  }

  /**
   * fix(#945): materializing is the ONLY way a user validates dissolve — it has
   * no preview by design (#779) — and the pipeline behind it is never wired
   * together anywhere else: the `col:` sentinel, the collision guard, and
   * `enable_hashagg=off` are each unit-tested in isolation and never end to end.
   */
  test('dissolve materializes without a preview', async ({ page }) => {
    await page.goto(`/maps/${mapId}`);
    await expect(page.locator('canvas.maplibregl-canvas')).toBeVisible({ timeout: 15_000 });

    await page.getByRole('button', { name: 'Analysis', exact: true }).click();
    await expect(page.getByTestId('analysis-panel')).toBeVisible();

    await page.getByLabel('Operation').click();
    await page.getByRole('option', { name: 'Dissolve' }).click();

    // The hint that names the only way to run it, and the absence of the
    // preview affordance every other operation has.
    await expect(page.getByText('Run it with Create dataset')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Preview', exact: true })).toBeHidden();

    // Group by the fixture's own column, which exercises the `col:` sentinel
    // rather than the no-grouping path.
    await page.getByLabel('Group by field (optional)').click();
    await page.getByRole('option', { name: 'name', exact: true }).click();

    await page.getByLabel('New dataset name').fill(DISSOLVE_TITLE);
    const materializeResponse = page.waitForResponse(
      (r) => r.url().includes('/analysis/materialize/') && r.request().method() === 'POST',
    );
    await page.getByRole('button', { name: 'Create dataset' }).click();

    const response = await materializeResponse;
    const { job_id: jobId } = (await response.json()) as { job_id: string };
    expect(jobId).toBeTruthy();

    // Resolve for cleanup before ANY assertion that can fail — including the
    // request-body one below. A dropped by_field still runs as an ungrouped
    // dissolve and still creates a dataset, so asserting first would leak one
    // output per Playwright retry into the shared catalog.
    dissolveDatasetId = await awaitJobDataset(jobId);
    expect(dissolveDatasetId).toBeTruthy();

    expect(JSON.parse(response.request().postData() ?? '{}')).toMatchObject({
      operation: 'dissolve',
      by_field: 'name',
    });

    await expect(
      page.locator('[data-sonner-toast]').filter({ hasText: DISSOLVE_TITLE }),
    ).toBeVisible({ timeout: 60_000 });
  });

  /**
   * fix(#945): the pointer path that regressed twice, in #726 and again in
   * #729. The draw-guard unit test covers the flag; nothing covered a real
   * drawn geometry reaching the clip operation. Preview rather than
   * materialize: the mask travels in the request either way, and preview
   * leaves no dataset to clean up.
   */
  test('a drawn clip mask reaches the clip operation', async ({ page }) => {
    await page.goto(`/maps/${mapId}`);
    const canvas = page.locator('canvas.maplibregl-canvas');
    await expect(canvas).toBeVisible({ timeout: 15_000 });

    await page.getByRole('button', { name: 'Analysis', exact: true }).click();
    await expect(page.getByTestId('analysis-panel')).toBeVisible();

    await page.getByLabel('Operation').click();
    await page.getByRole('option', { name: 'Clip', exact: true }).click();

    // Put the data under the cursor, with the panel already open so the fit
    // runs against the final layout. Without this the map sits at its default
    // view and a box drawn at the center lands in the Atlantic, so the clip
    // matches nothing — which is what makes the preview assertion below
    // meaningful: it passes only if the drawn screen coordinates unproject to
    // the lng/lat the feature is actually at.
    // Scoped by layer name: the basemap row's kebab shares the same prefix.
    await page.getByRole('button', { name: `Layer options for ${seed.title}` }).click();
    await page.getByTestId('kebab-zoom-to-layer').click();
    await page.waitForTimeout(1500); // the fly-to animation

    await page.getByRole('button', { name: 'Draw clip area' }).click();
    await expect(page.getByText('Draw on the map — double-click to finish')).toBeVisible();

    // Draw a box around the map center, which is now the seeded feature.
    const box = await canvas.boundingBox();
    if (!box) throw new Error('map canvas has no bounding box');
    const cx = box.x + box.width / 2;
    const cy = box.y + box.height / 2;
    const r = Math.min(box.width, box.height) / 4;
    for (const [dx, dy] of [[-r, -r], [r, -r], [r, r]] as const) {
      await page.mouse.click(cx + dx, cy + dy);
    }
    await page.mouse.dblclick(cx - r, cy + r);

    await expect(page.getByText('Clip area set')).toBeVisible();

    const previewResponse = page.waitForResponse(
      (r) => r.url().includes('/analysis/preview/') && r.request().method() === 'POST',
    );
    await page.getByRole('button', { name: 'Preview', exact: true }).click();

    // The drawn geometry, not just the operation, has to reach the server —
    // that is the half the unit-level draw guard cannot see.
    const body = JSON.parse((await previewResponse).request().postData() ?? '{}') as {
      operation?: string;
      mask?: { type?: string; coordinates?: unknown[] };
    };
    expect(body.operation).toBe('clip');
    expect(body.mask?.type).toBe('Polygon');
    expect(Array.isArray(body.mask?.coordinates)).toBe(true);

    await expect(page.getByRole('button', { name: 'Clear preview' })).toBeVisible({
      timeout: 15_000,
    });
  });
});
