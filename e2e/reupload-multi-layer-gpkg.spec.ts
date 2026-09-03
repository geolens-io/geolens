/**
 * GPKG-01 Phase 1058: Multi-layer GPKG reupload headless Playwright spec.
 *
 * Encodes the acceptance behavior for GPKG-01 (silent-data-swap fix):
 *   Scenario A — happy path: previous source_layer pre-selected from prior IngestJob
 *   Scenario B — missing-layer warning: user must explicitly pick a replacement
 *
 * NOTE: These tests require a running local stack (localhost:8080) with the Phase 1058
 * backend deployed. They are NOT run against the live stack in CI by default.
 * Phase 1060 live MCP re-verify will exercise these paths interactively.
 *
 * To run headless against local stack:
 *   npx playwright test e2e/reupload-multi-layer-gpkg.spec.ts --reporter=list
 */

import { test, expect } from '@playwright/test';
import path from 'path';
import { getAuthToken } from './helpers/catalog';

const FIXTURE_PATH = path.join(__dirname, 'fixtures/multi-layer-gpkg.gpkg');
const BASE_URL = process.env.E2E_BASE_URL ?? 'http://localhost:8080';
const API_URL = `${BASE_URL}/api`;

/**
 * Upload a GeoJSON file via the API and return {datasetId, jobId} after ingest completes.
 * Uses direct API calls to avoid depending on the full import UI flow.
 */
async function seedDatasetViaAPI(
  request: import('@playwright/test').APIRequestContext,
  geojsonContent: string,
  filename: string,
): Promise<{ datasetId: string; jobId: string }> {
  const token = getAuthToken();
  const headers = { Authorization: `Bearer ${token}` };

  // 1. Upload file
  const uploadResp = await request.post(`${API_URL}/import/upload/`, {
    headers,
    multipart: {
      file: {
        name: filename,
        mimeType: 'application/geo+json',
        buffer: Buffer.from(geojsonContent),
      },
    },
  });
  expect(uploadResp.ok(), `Upload failed: ${await uploadResp.text()}`).toBeTruthy();
  const { job_id: jobId } = await uploadResp.json() as { job_id: string };

  // 2. Preview (get layer name)
  const previewResp = await request.post(`${API_URL}/import/upload/${jobId}/preview/`, {
    headers,
    data: {},
  });
  expect(previewResp.ok(), `Preview failed: ${await previewResp.text()}`).toBeTruthy();
  const previewData = await previewResp.json() as { layer_name?: string };
  const layerName = previewData.layer_name ?? '';

  // 3. Commit (with minimal metadata)
  const commitResp = await request.post(`${API_URL}/import/upload/${jobId}/commit/`, {
    headers,
    data: {
      title: `GPKG-01 test dataset (${filename})`,
      summary: 'Automated test dataset for GPKG-01 phase 1058',
      visibility: 'private',
      layer_name: layerName,
    },
  });
  expect(commitResp.ok(), `Commit failed: ${await commitResp.text()}`).toBeTruthy();
  const commitData = await commitResp.json() as { dataset_id?: string; job_id?: string };

  // 4. Poll for completion (max 30s)
  const datasetId = commitData.dataset_id ?? '';
  const commitJobId = commitData.job_id ?? jobId;

  for (let i = 0; i < 30; i++) {
    await new Promise((r) => setTimeout(r, 1000));
    const statusResp = await request.get(`${API_URL}/jobs/${commitJobId}`, { headers });
    if (statusResp.ok()) {
      const { status } = await statusResp.json() as { status: string };
      if (status === 'complete') break;
      if (status === 'failed') throw new Error(`Ingest job ${commitJobId} failed`);
    }
  }

  return { datasetId, jobId: commitJobId };
}

/**
 * Delete a dataset via API (cleanup helper).
 */
async function deleteDataset(
  request: import('@playwright/test').APIRequestContext,
  datasetId: string,
) {
  const token = getAuthToken();
  await request.delete(`${API_URL}/datasets/${datasetId}`, {
    headers: { Authorization: `Bearer ${token}` },
  }).catch(() => {/* best-effort cleanup */});
}

const BUILDINGS_GEOJSON = JSON.stringify({
  type: 'FeatureCollection',
  features: [
    { type: 'Feature', geometry: { type: 'Point', coordinates: [-73.99, 40.75] }, properties: { name: 'Building A', floors: 5 } },
    { type: 'Feature', geometry: { type: 'Point', coordinates: [-73.98, 40.76] }, properties: { name: 'Building B', floors: 12 } },
  ],
});

const SOMETHING_ELSE_GEOJSON = JSON.stringify({
  type: 'FeatureCollection',
  features: [
    { type: 'Feature', geometry: { type: 'Point', coordinates: [-73.99, 40.75] }, properties: { id: 1, label: 'Alpha' } },
  ],
});

test.describe('GPKG-01: Multi-layer GPKG reupload', () => {
  test.setTimeout(120_000);

  // fix(#1778): Scenario A ("happy path: default-selects previous source_layer")
  // used to assert on two `.catch(() => {})`-swallowed expects against
  // selectors ('[data-testid="bulk-review-list"]', '[data-testid="layer-select-table"]')
  // that exist only in this file's own vitest mocks, never in app source — the
  // test could only fail if /import had no file input at all. The behavior it
  // was named for (multi-layer fan-out commit, per-layer results) is covered
  // for real by frontend/src/components/import/__tests__/UploadForm.multiLayerFanOut.test.tsx,
  // which asserts against actual component output rather than a soft-swallowed
  // e2e selector guess. Scenario B below covers the reupload-dialog layer-select
  // path with hard assertions instead.

  test('Scenario B — ReuploadDialog file path: layer-select + missing-layer warning', async ({ page, request }) => {
    test.slow();

    // Navigate to the search page and find any vector dataset.
    // We use getAuthToken() from helpers (reads playwright/.auth/user.json directly).
    let datasetId: string | null = null;
    try {
      const token = getAuthToken();
      const resp = await request.get(`${API_URL}/datasets/?limit=50`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (resp.ok()) {
        // fix(#1778): DatasetListResponse's field is `datasets`, not `results`
        // (backend/openapi.json has no `results` key on this schema) — the
        // old read always produced an empty array here, so datasetId always
        // came from the DOM-scrape fallback below regardless of dataset type.
        const body = await resp.json() as { datasets?: Array<{ id: string; record_type?: string }> };
        const all = body.datasets ?? [];
        // Pick the first dataset, preferring vector datasets
        const vector = all.find((d) => d.record_type === 'vector_dataset');
        datasetId = (vector ?? all[0])?.id ?? null;
      }
    } catch {
      // getAuthToken() throws if auth file not found; treat as skip
    }

    if (!datasetId) {
      // Fallback: try navigating to the search page and extracting a dataset link
      await page.goto('/');
      await page.waitForLoadState('networkidle', { timeout: 20_000 }).catch(() => { /* ok */ });
      const firstDatasetLink = page.locator('a[href*="/datasets/"]').first();
      if (await firstDatasetLink.isVisible({ timeout: 5_000 }).catch(() => false)) {
        const href = await firstDatasetLink.getAttribute('href') ?? '';
        const match = href.match(/\/datasets\/([a-f0-9-]+)/);
        datasetId = match?.[1] ?? null;
      }
    }

    // fix(#1778): this used to be a test.skip(true, ...) — with the `results`
    // → `datasets` fix above, the CI catalog is always seeded
    // (e2e/auth.setup.ts's seedDataset, plus the demo seed script's own
    // vector datasets), so a missing datasetId is a real failure, not a
    // legitimate empty-catalog outcome.
    expect(datasetId, 'reupload flow needs a seeded vector dataset to target').toBeTruthy();

    const dataset = { id: datasetId };
    await page.goto(`/datasets/${dataset.id}`);
    await page.waitForLoadState('networkidle', { timeout: 15_000 }).catch(() => { /* ok */ });

    // Open "More" menu and click "Re-Upload"
    const moreBtn = page.getByRole('button', { name: /more|actions/i }).first();
    // fix(#1778): the Re-Upload affordance disappearing is exactly the
    // regression e2e/dataset-detail.spec.ts (IMPORT-04) exists to catch —
    // skipping here instead of failing let that regression turn this test
    // green-as-skipped.
    await expect(moreBtn).toBeVisible({ timeout: 5_000 });
    await moreBtn.click();
    const reuploadMenuItem = page.getByRole('menuitem', { name: /re-?upload/i }).first();
    await expect(reuploadMenuItem).toBeVisible({ timeout: 3_000 });
    await reuploadMenuItem.click();

    // Source selector should appear
    const sourceSelector = page.getByTestId('reupload-source-selector');
    await expect(sourceSelector).toBeVisible({ timeout: 10_000 });

    // Click "File"
    await page.getByRole('button', { name: 'File' }).click();

    // Upload the multi-layer GPKG
    const fileInput = page.locator('input[type="file"]').first();
    await expect(fileInput).toBeAttached({ timeout: 10_000 });
    await fileInput.setInputFiles(FIXTURE_PATH);

    // Wait for response: either the layer-select step or straight to preview
    const layerSelectOrPreview = page.locator(
      '[data-testid="reupload-file-layer-select"], [role="button"][name*="Confirm"]',
    );
    await expect(layerSelectOrPreview.first()).toBeVisible({ timeout: 30_000 });

    // fix(#1778): FIXTURE_PATH (multi-layer-gpkg.gpkg) is a known multi-layer
    // file, so the layer-select step is not an optional branch — it is
    // exactly the silent-data-swap symptom GPKG-01 exists to catch. Asserting
    // it unconditionally means a regression that skips straight to preview
    // (the old "acceptable, not a failure" branch) now fails this test.
    await expect(page.getByTestId('reupload-file-layer-select')).toBeVisible({ timeout: 5_000 });

    // Multi-layer path: verify both layer rows are present
    await expect(page.getByText('buildings')).toBeVisible({ timeout: 5_000 });
    await expect(page.getByText('addresses')).toBeVisible({ timeout: 5_000 });

    // Preview button should be visible
    const previewBtn = page.getByRole('button', { name: 'Preview Layer' });
    await expect(previewBtn).toBeVisible({ timeout: 5_000 });

    // If a row is already selected (previous_source_layer pre-selection), preview is enabled;
    // otherwise click a row to select
    if (await previewBtn.isDisabled({ timeout: 1_000 }).catch(() => false)) {
      await page.getByText('buildings').first().click();
      await expect(previewBtn).toBeEnabled({ timeout: 3_000 });
    }

    // Click Preview Layer
    await previewBtn.click();

    // Should transition to preview step
    await expect(page.getByRole('button', { name: 'Confirm Re-Upload' })).toBeVisible({
      timeout: 30_000,
    });
  });
});
