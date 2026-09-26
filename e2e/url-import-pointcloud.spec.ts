import { test, expect, type Page, type Request } from '@playwright/test';

const FILE_URL = 'https://files.example.test/terrain.copc.laz';
const JOB_ID = '22222222-3333-4444-5555-666666666666';
const DATASET_ID = '33333333-4444-5555-6666-777777777777';

async function openUrlTab(page: Page) {
  await page.goto('/');
  await page.getByRole('button', { name: 'Create' }).click();
  await page.getByRole('menuitem', { name: 'Import Data' }).click();
  await page.getByRole('button', { name: 'File URL' }).click();
}

async function openUploadTab(page: Page) {
  await page.goto('/');
  await page.getByRole('button', { name: 'Create' }).click();
  await page.getByRole('menuitem', { name: 'Import Data' }).click();
}

async function submitPointCloud(page: Page) {
  await page.getByRole('radio', { name: 'COPC point cloud' }).check();
  await page.getByLabel('File URL; fetched server-side').fill(FILE_URL);
  await page.getByRole('button', { name: 'Fetch →' }).click();
}

test.describe('URL import of a COPC point cloud', () => {
  let submitted: Request | null;

  test.beforeEach(async ({ page }) => {
    submitted = null;
    await page.route('**/api/ingest/upload/config', (route) =>
      route.fulfill({
        status: 200,
        json: {
          max_file_size_bytes: 1024 * 1024 * 1024,
          allowed_extensions: '.geojson,.laz',
          presigned_uploads: false,
          remaining_dataset_quota: null,
        },
      }),
    );
    await page.route('**/api/ingest/upload/url', (route) => {
      submitted = route.request();
      return route.fulfill({
        status: 201,
        json: { job_id: JOB_ID, status: 'running', message: 'Downloading the file' },
      });
    });
  });

  test('previews and commits a point cloud', async ({ page }) => {
    let committed: Request | null = null;
    await page.route(`**/api/jobs/${JOB_ID}`, (route) =>
      route.fulfill({
        status: 200,
        json: committed
          ? { id: JOB_ID, status: 'complete', dataset_id: DATASET_ID }
          : { id: JOB_ID, status: 'pending', current_step: null, progress: null },
      }),
    );
    await page.route(`**/api/ingest/preview/${JOB_ID}`, (route) =>
      route.fulfill({
        status: 200,
        json: {
          job_id: JOB_ID,
          source_filename: 'terrain.copc.laz',
          point_count: 1200,
          point_format: 7,
          srid: 26912,
          vertical_crs: null,
          extent_bbox: [-111, 40, -110, 41],
          z_min: 100,
          z_max: 200,
          size_bytes: 4096,
        },
      }),
    );
    await page.route(`**/api/ingest/commit/${JOB_ID}`, (route) => {
      committed = route.request();
      return route.fulfill({ status: 202, json: { job_id: JOB_ID, status: 'queued' } });
    });

    await openUrlTab(page);
    await submitPointCloud(page);

    await expect(page.getByText(/1,200/)).toBeVisible({ timeout: 20_000 });
    expect(submitted?.postDataJSON()).toEqual({ url: FILE_URL, kind: 'pointcloud' });
    await expect(page.getByText('terrain.copc.laz')).toBeVisible();
    await expect(page.getByLabel('CRS Override')).toHaveCount(0);

    await page.getByRole('button', { name: 'Import Dataset' }).click();
    await expect(page.getByRole('link', { name: 'View Dataset' })).toBeVisible({ timeout: 20_000 });
    expect(committed?.postDataJSON()).toMatchObject({ title: 'terrain.copc' });
  });

  test('shows a coded refusal in the active language', async ({ page }) => {
    await page.route(`**/api/jobs/${JOB_ID}`, (route) =>
      route.fulfill({
        status: 200,
        json: {
          id: JOB_ID,
          status: 'failed',
          error_code: 'pointcloud_not_copc',
          error_message: 'The point cloud is not a COPC file.',
        },
      }),
    );

    await openUrlTab(page);
    await submitPointCloud(page);

    await expect(page.getByText(/This point cloud isn't a COPC file/).first()).toBeVisible({ timeout: 20_000 });
    await expect(page.getByRole('radio', { name: 'COPC point cloud' })).toBeChecked();
    await expect(page.getByLabel('File URL; fetched server-side')).toBeEnabled();
  });
});

test('file upload sends a .laz as a point cloud and shows its preview', async ({ page }) => {
  let submitted: Request | null = null;
  await page.route('**/api/ingest/upload/config', (route) =>
    route.fulfill({
      status: 200,
      json: {
        max_file_size_bytes: 1024 * 1024 * 1024,
        allowed_extensions: '.geojson,.laz',
        presigned_uploads: false,
        remaining_dataset_quota: null,
      },
    }),
  );
  await page.route('**/api/ingest/upload', (route) => {
    submitted = route.request();
    return route.fulfill({ status: 201, json: { job_id: JOB_ID, status: 'pending' } });
  });
  await page.route(`**/api/ingest/preview/${JOB_ID}`, (route) =>
    route.fulfill({
      status: 200,
      json: {
        job_id: JOB_ID,
        source_filename: 'terrain.copc.laz',
        point_count: 1200,
        point_format: 7,
        srid: 26912,
        vertical_crs: null,
        extent_bbox: [-111, 40, -110, 41],
        z_min: 100,
        z_max: 200,
        size_bytes: 4096,
      },
    }),
  );

  await openUploadTab(page);
  await page.getByRole('radio', { name: 'COPC point cloud' }).check();
  await page.getByLabel('Upload files').setInputFiles({
    name: 'terrain.copc.laz',
    mimeType: 'application/octet-stream',
    buffer: Buffer.from('LASF'),
  });

  await expect(page.getByText(/1,200 points/).first()).toBeVisible({ timeout: 20_000 });
  expect(submitted).not.toBeNull();
  const body = submitted!.postDataBuffer()?.toString() ?? '';
  expect(body).toContain('name="file"; filename="terrain.copc.laz"');
  expect(body).toContain('name="kind"\r\n\r\npointcloud');
});
