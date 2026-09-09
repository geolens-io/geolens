import { test, expect, type Page } from '@playwright/test';

/**
 * feat(#1710): the URL import's download is a background job, so the tab has a
 * step between submit and preview that did not exist before.
 *
 * Every API call is mocked with page.route: the point is the client's own
 * state machine (submit, poll, preview), and a real download would need a
 * worker plus a reachable origin. Opens the panel through the Create menu
 * rather than a hard page.goto, which logs the session out on the worktree
 * Vite recipe.
 */

const FILE_URL = 'https://files.example.test/roads.geojson';
const JOB_ID = '11111111-2222-3333-4444-555555555555';

async function openUrlTab(page: Page) {
  await page.goto('/');
  await page.getByRole('button', { name: 'Create' }).click();
  await page.getByRole('menuitem', { name: 'Import Data' }).click();
  await page.getByRole('button', { name: 'File URL' }).click();
}

/** Answer the status poll from a queue, repeating the last entry forever. */
async function routeJobStatus(page: Page, statuses: Record<string, unknown>[]) {
  let index = 0;
  await page.route(`**/api/jobs/${JOB_ID}`, (route) => {
    const body = statuses[Math.min(index, statuses.length - 1)];
    index += 1;
    return route.fulfill({ status: 200, json: { id: JOB_ID, ...body } });
  });
}

test.describe('URL import download step', () => {
  test.beforeEach(async ({ page }) => {
    await page.route('**/api/ingest/upload/url', (route) =>
      route.fulfill({
        status: 201,
        json: { job_id: JOB_ID, status: 'running', message: 'Downloading the file' },
      }),
    );
  });

  test('a queued download shows job progress and only previews once staged', async ({
    page,
  }) => {
    await routeJobStatus(page, [
      { status: 'running', current_step: 'downloading', progress: 0 },
      { status: 'running', current_step: 'downloading', progress: 0 },
      { status: 'pending', current_step: null, progress: null },
    ]);

    let previewed = 0;
    await page.route(`**/api/ingest/preview/${JOB_ID}`, (route) => {
      previewed += 1;
      return route.fulfill({
        status: 200,
        json: {
          job_id: JOB_ID,
          source_filename: 'roads.geojson',
          columns: [{ name: 'id', type: 'Integer' }],
          crs: 4326,
          geometry_type: 'LineString',
          feature_count: 2,
          sample_rows: [],
          layer_name: 'roads',
          layers: null,
        },
      });
    });

    await openUrlTab(page);
    await page.getByLabel('File URL; fetched server-side').fill(FILE_URL);
    await page.getByRole('button', { name: 'Fetch →' }).click();

    // The download is an ordinary job-progress view, with the step label the
    // worker stamps and the hint that leaving the page is safe.
    await expect(
      page.getByText('The server is fetching the file.', { exact: false }),
    ).toBeVisible();
    await expect(page.getByText('Downloading', { exact: false }).first()).toBeVisible();
    expect(previewed).toBe(0);

    // Once the poll reports `pending` the staged file is previewable: the
    // review branch is the only one that renders Start Over.
    await expect(page.getByRole('button', { name: 'Start Over' })).toBeVisible({
      timeout: 20_000,
    });
    expect(previewed).toBeGreaterThan(0);
  });

  test('a failed download returns the tab to a usable form with the reason', async ({
    page,
  }) => {
    await routeJobStatus(page, [
      { status: 'running', current_step: 'downloading', progress: 0 },
      {
        status: 'failed',
        error_message: 'The server returned HTTP 404 for this URL.',
      },
    ]);

    await openUrlTab(page);
    await page.getByLabel('File URL; fetched server-side').fill(FILE_URL);
    await page.getByRole('button', { name: 'Fetch →' }).click();

    await expect(
      page.getByText('The server returned HTTP 404 for this URL.').first(),
    ).toBeVisible({ timeout: 20_000 });
    // The form is usable again rather than pinned to the dead job.
    await expect(page.getByLabel('File URL; fetched server-side')).toBeEnabled();
  });
});
