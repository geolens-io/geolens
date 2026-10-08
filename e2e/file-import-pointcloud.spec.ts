import { test, expect, type Page, type Request } from './helpers/session';

const JOB_ID = '22222222-3333-4444-5555-666666666666';
const DATASET_ID = '33333333-4444-5555-6666-777777777777';

async function openImport(page: Page) {
  await page.goto('/');
  await page.getByRole('button', { name: 'Create' }).click();
  await page.getByRole('menuitem', { name: 'Import Data' }).click();
}

async function uploadPointCloud(page: Page) {
  await openImport(page);
  await page.getByRole('radio', { name: 'COPC point cloud' }).check();
  await page.getByLabel('Upload files').setInputFiles({
    name: 'terrain.copc.laz',
    mimeType: 'application/octet-stream',
    buffer: Buffer.from('LASF'),
  });
}

test.describe('file import of a COPC point cloud', () => {
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
    await page.route('**/api/ingest/upload', (route) => {
      submitted = route.request();
      return route.fulfill({ status: 201, json: { job_id: JOB_ID, status: 'pending' } });
    });
  });

  test('uploads, previews and commits a point cloud', async ({ page }) => {
    let committed: Request | null = null;
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
    await page.route(`**/api/jobs/${JOB_ID}`, (route) =>
      route.fulfill({
        status: 200,
        json: committed
          ? { id: JOB_ID, status: 'complete', dataset_id: DATASET_ID }
          : { id: JOB_ID, status: 'pending', current_step: null, progress: null },
      }),
    );

    await uploadPointCloud(page);

    await expect(page.getByText(/1,200 points/).first()).toBeVisible({ timeout: 20_000 });
    expect(submitted).not.toBeNull();
    const body = submitted!.postDataBuffer()?.toString() ?? '';
    expect(body).toContain('name="file"; filename="terrain.copc.laz"');
    expect(body).toContain('name="kind"\r\n\r\npointcloud');
    await expect(page.getByLabel('CRS Override')).toHaveCount(0);

    await page.getByRole('button', { name: 'Import Dataset' }).click();
    await expect(page.getByRole('link', { name: 'Open dataset' }).first())
      .toHaveAttribute('href', `/datasets/${DATASET_ID}`, { timeout: 20_000 });
    expect(committed?.postDataJSON()).toMatchObject({ title: 'terrain.copc' });
  });

  test('shows a coded preview refusal in the active language', async ({ page }) => {
    await page.route(`**/api/ingest/preview/${JOB_ID}`, (route) =>
      route.fulfill({
        status: 422,
        json: {
          detail: {
            code: 'pointcloud_not_copc',
            message: 'The point cloud is not a COPC file.',
          },
        },
      }),
    );

    await uploadPointCloud(page);

    await expect(page.getByText(/This point cloud isn't a COPC file/).first()).toBeVisible({ timeout: 20_000 });
    expect(submitted).not.toBeNull();
    expect(submitted!.postDataBuffer()?.toString()).toContain('name="kind"\r\n\r\npointcloud');
  });

  test('does not offer the point cloud kind on the File URL tab', async ({ page }) => {
    await openImport(page);
    await page.getByRole('button', { name: 'File URL' }).click();

    await expect(page.getByRole('radio', { name: '3D Tiles tileset' })).toBeVisible();
    await expect(page.getByRole('radio', { name: 'COPC point cloud' })).toHaveCount(0);
  });
});
