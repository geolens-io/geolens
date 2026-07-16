import { test, expect, type Page } from '@playwright/test';
import fs from 'fs';
import path from 'path';

/**
 * Dataset-scoped AI chat (dataset-chat v1, #531).
 *
 * The CI stack has no AI provider configured, so the AI surface is mocked at
 * the network layer: `/api/admin/ai-status/` is routed to report AI as
 * available (the e2e user is admin, so availability rides the admin
 * endpoint), and the SSE stream endpoint is fulfilled with canned frames.
 * Everything else — auth, dataset resolution, map creation on
 * "Open in builder" — runs against the real backend.
 */

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

let datasetId: string;
let datasetTitle: string;
// Set when a test creates a real map; deleted in afterEach so the fixture
// doesn't leak when an assertion fails mid-test (#535 review).
let createdMapId: string | null = null;

async function mockAIAvailable(page: Page, available: boolean) {
  await page.route('**/api/admin/ai-status/', (route) =>
    route.fulfill({
      json: {
        provider: available ? 'anthropic' : null,
        model: available ? 'claude-sonnet-5' : null,
        enabled: available,
        configured: available,
        semantic_search_enabled: false,
        has_embeddings: false,
      },
    }),
  );
}

const SSE_FRAMES = [
  'event: token',
  'data: {"text": "The largest park is Central Park (843 acres)."}',
  '',
  'event: actions',
  'data: {"actions": [{"type": "show_query_result", "rows": [["Central Park", 843]], "columns": ["name", "acres"], "row_count": 1}]}',
  '',
  'event: done',
  'data: {"explanation": "The largest park is Central Park (843 acres)."}',
  '',
  '',
].join('\n');

// Spatial result for the builder-carryover test (#533/#542). The bbox centers
// at exactly (40.75, -73.95) — values chosen to round cleanly in the builder's
// coordinate readout so the camera-fit assertion is deterministic.
const CARRYOVER_BBOX = [-74.0, 40.7, -73.9, 40.8];
const CARRYOVER_GEOJSON = {
  type: 'FeatureCollection',
  features: [
    { type: 'Feature', geometry: { type: 'Point', coordinates: [-73.98, 40.72] }, properties: { name: 'Alpha' } },
    { type: 'Feature', geometry: { type: 'Point', coordinates: [-73.92, 40.78] }, properties: { name: 'Beta' } },
  ],
};
const CARRYOVER_SSE_FRAMES = [
  'event: token',
  'data: {"text": "Found 2 stations."}',
  '',
  'event: actions',
  `data: ${JSON.stringify({
    actions: [
      {
        type: 'show_query_result',
        rows: [['Alpha'], ['Beta']],
        columns: ['name'],
        row_count: 2,
        geojson: CARRYOVER_GEOJSON,
        bbox: CARRYOVER_BBOX,
      },
    ],
  })}`,
  '',
  'event: done',
  'data: {"explanation": "Found 2 stations."}',
  '',
  '',
].join('\n');

test.describe('Dataset AI chat', () => {
  test.beforeAll(async () => {
    const token = getAuthToken();
    const headers = { Authorization: `Bearer ${token}` };
    const res = await fetch(`${BASE_URL}/api/datasets/?limit=10`, { headers });
    expect(res.ok).toBe(true);
    const data = await res.json();
    const datasets = data.datasets ?? data.items ?? data;
    const vector = datasets
      .filter((ds: { record_type: string }) => ds.record_type === 'vector_dataset')
      .sort(
        (a: { feature_count?: number }, b: { feature_count?: number }) =>
          (b.feature_count ?? 0) - (a.feature_count ?? 0),
      );
    const ds = vector[0] ?? datasets[0];
    expect(ds).toBeTruthy();
    datasetId = ds.id;
    datasetTitle = ds.title;
  });

  test.afterEach(async () => {
    if (!createdMapId) return;
    const token = getAuthToken();
    // Best-effort teardown — runs even when the test body failed.
    await fetch(`${BASE_URL}/api/maps/${createdMapId}`, {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${token}` },
    }).catch(() => {});
    createdMapId = null;
  });

  test('Ask AI is hidden when AI is not configured', async ({ page }) => {
    await mockAIAvailable(page, false);
    // Synchronize on the mocked status actually being delivered — the panel
    // renders nothing while availability is still loading, so asserting
    // absence before the response lands would pass vacuously (#535 review).
    const statusSeen = page.waitForResponse('**/api/admin/ai-status/');
    await page.goto(`/datasets/${datasetId}`);
    await expect(page.getByRole('heading', { level: 1, name: datasetTitle })).toBeVisible();
    await statusSeen;
    // One settle frame for React Query to apply the response before the
    // negative assertion.
    await page.waitForTimeout(250);
    await expect(page.getByRole('button', { name: 'Ask AI' })).toHaveCount(0);
  });

  test('asks a question, streams the answer, and opens the result in the builder', async ({
    page,
  }) => {
    await mockAIAvailable(page, true);
    await page.route('**/api/ai/chat/dataset/stream/', (route) =>
      route.fulfill({
        contentType: 'text/event-stream',
        body: SSE_FRAMES,
      }),
    );

    await page.goto(`/datasets/${datasetId}`);
    await page.getByRole('button', { name: 'Ask AI' }).click();

    const composer = page.getByPlaceholder('Ask about this data...');
    await expect(composer).toBeVisible();
    await composer.fill('what is the largest park?');
    await page.getByRole('button', { name: 'Send' }).click();

    // Streamed answer + result table render in the panel.
    await expect(
      page.getByText('The largest park is Central Park (843 acres).'),
    ).toBeVisible();
    await expect(page.getByText('Central Park', { exact: true })).toBeVisible();

    // "Open in builder" creates a REAL map and stages this dataset. The
    // ?add_dataset param is consumed (deleted) by the builder on load, so
    // assert the map route rather than the transient query string.
    await page.getByRole('button', { name: 'Open in builder' }).click();
    await page.waitForURL(/\/maps\/[0-9a-f-]{36}/);

    createdMapId = page.url().match(/\/maps\/([0-9a-f-]{36})/)?.[1] ?? null;
    expect(createdMapId).toBeTruthy();

    // The staged layer for this dataset appears in the builder stack. Scope
    // to a stack row — the map itself is named "<datasetTitle> Map", so a
    // bare text match could pass on the header alone (#535 review).
    await expect(page.locator('canvas.maplibregl-canvas')).toBeVisible({ timeout: 15_000 });
    await expect(
      page
        .locator('[id^="stack-row-"]')
        .filter({ hasText: datasetTitle })
        .first(),
    ).toBeVisible({ timeout: 15_000 });
  });

  test('carries a spatial result into the builder as an ephemeral overlay (#533/#542)', async ({
    page,
  }) => {
    await mockAIAvailable(page, true);
    await page.route('**/api/ai/chat/dataset/stream/', (route) =>
      route.fulfill({
        contentType: 'text/event-stream',
        body: CARRYOVER_SSE_FRAMES,
      }),
    );

    await page.goto(`/datasets/${datasetId}`);
    await page.getByRole('button', { name: 'Ask AI' }).click();

    const composer = page.getByPlaceholder('Ask about this data...');
    await composer.fill('show me the stations');
    await page.getByRole('button', { name: 'Send' }).click();
    await expect(page.getByText('Found 2 stations.')).toBeVisible();

    await page.getByRole('button', { name: 'Open in builder' }).click();
    await page.waitForURL(/\/maps\/[0-9a-f-]{36}/);
    createdMapId = page.url().match(/\/maps\/([0-9a-f-]{36})/)?.[1] ?? null;
    expect(createdMapId).toBeTruthy();

    await expect(page.locator('canvas.maplibregl-canvas')).toBeVisible({ timeout: 15_000 });
    // Two independent assertions on purpose: the badge is React state, the
    // camera fit is map state. The fix(#542) race kept the badge visible while
    // the overlay and fitBounds silently never applied. The race itself is
    // timing-dependent (it needs the style transiently unloaded at pickup, so
    // a fast local run may not reproduce it — the deterministic regression
    // test lives in use-ephemeral-layers.test.ts); what this spec pins down is
    // the full stash → pickup → overlay integration, which jsdom cannot.
    await expect(page.getByText(/Query result · 2 features/)).toBeVisible({ timeout: 15_000 });
    await expect(page.locator('[data-coord-readout="true"]')).toContainText(
      '40.75° N · 73.95° W',
      { timeout: 15_000 },
    );
  });
});
