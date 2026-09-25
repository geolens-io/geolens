import { test, expect, type Page, type Request } from '@playwright/test';

/**
 * The File URL form imports a 3D Tiles archive: it sends kind=tiles3d, previews
 * the tileset, commits it in tileset mode and shows a refused archive's reason.
 *
 * Every ingest call is mocked with page.route, as in url-import-download.spec.ts:
 * the URL fetch refuses private addresses, so no local archive server can stand
 * in for a real download.
 */

const FILE_URL = 'https://files.example.test/campus.3tz';
const JOB_ID = '22222222-3333-4444-5555-666666666666';
const DATASET_ID = '33333333-4444-5555-6666-777777777777';
// The upload door's wording for this refusal, which the download task stores as the job's reason.
const REFUSAL =
  "An entry in the archive has an absolute path, or an empty, '.' or '..' path segment. " +
  'Every entry must sit below the archive root.';

async function openUrlTab(page: Page) {
  await page.goto('/');
  await page.getByRole('button', { name: 'Create' }).click();
  await page.getByRole('menuitem', { name: 'Import Data' }).click();
  await page.getByRole('button', { name: 'File URL' }).click();
}

async function submitTileset(page: Page) {
  await page.getByRole('radio', { name: '3D Tiles tileset' }).check();
  await page.getByLabel('File URL; fetched server-side').fill(FILE_URL);
  await page.getByRole('button', { name: 'Fetch →' }).click();
}

test.describe('URL import of a 3D Tiles archive', () => {
  let submitted: Request | null;

  test.beforeEach(async ({ page }) => {
    submitted = null;
    await page.route('**/api/ingest/upload/url', (route) => {
      submitted = route.request();
      return route.fulfill({
        status: 201,
        json: { job_id: JOB_ID, status: 'running', message: 'Downloading the file' },
      });
    });
  });

  test('a tileset archive previews, commits in tileset mode and completes', async ({ page }) => {
    let committed: Request | null = null;
    await page.route(`**/api/jobs/${JOB_ID}`, (route) =>
      route.fulfill({
        status: 200,
        json: committed
          ? {
              id: JOB_ID,
              status: 'complete',
              dataset_id: DATASET_ID,
              created_at: '2026-09-25T10:00:00Z',
              completed_at: '2026-09-25T10:01:00Z',
            }
          : { id: JOB_ID, status: 'pending', current_step: null, progress: null },
      }),
    );
    await page.route(`**/api/ingest/preview/${JOB_ID}`, (route) =>
      route.fulfill({
        status: 200,
        json: {
          job_id: JOB_ID,
          source_filename: 'campus.3tz',
          version: '1.1',
          geometric_error: 500,
          bounding_volume: 'region',
          extent_bbox: [-75.61, 40.04, -75.6, 40.05],
          unpacked_bytes: 2048,
          entry_count: 3,
        },
      }),
    );
    await page.route(`**/api/ingest/commit/${JOB_ID}`, (route) => {
      committed = route.request();
      return route.fulfill({
        status: 202,
        json: { job_id: JOB_ID, status: 'queued', message: 'Import started' },
      });
    });

    await openUrlTab(page);
    await submitTileset(page);

    await expect(page.getByText('Tileset', { exact: true })).toBeVisible({ timeout: 20_000 });
    expect(submitted?.postDataJSON()).toEqual({ url: FILE_URL, kind: 'tiles3d' });
    await expect(page.getByText('campus.3tz', { exact: true })).toBeVisible();
    // Tileset mode takes no CRS override, since a tileset keeps its own coordinates.
    await expect(page.getByLabel('CRS Override')).toHaveCount(0);

    await page.getByRole('button', { name: 'Import Dataset' }).click();

    await expect(page.getByRole('link', { name: 'View Dataset' })).toBeVisible({ timeout: 20_000 });
    expect(committed).not.toBeNull();
    expect(committed!.postDataJSON()).toMatchObject({ title: 'campus' });
  });

  test('a refused archive returns the form with the refusal reason', async ({ page }) => {
    await page.route(`**/api/jobs/${JOB_ID}`, (route) =>
      route.fulfill({
        status: 200,
        json: { id: JOB_ID, status: 'failed', error_message: REFUSAL },
      }),
    );

    await openUrlTab(page);
    await submitTileset(page);

    await expect(page.getByText(REFUSAL).first()).toBeVisible({ timeout: 20_000 });
    await expect(page.getByLabel('File URL; fetched server-side')).toBeEnabled();
    await expect(page.getByRole('radio', { name: '3D Tiles tileset' })).toBeChecked();
  });
});
