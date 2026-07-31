import { test, expect, type Page } from '@playwright/test';
import { getAuthToken } from './helpers/catalog';

const collectionName = `E2E Test Collection ${Date.now()}`;
const collectionDescription = 'Automated test collection for E2E';
const updatedDescription = 'Updated description for E2E test';
const BASE_URL = process.env.E2E_BASE_URL ?? 'http://localhost:8080';
let createdCollectionId: string | null = null;
let createdDatasetId: string | null = null;
let createdDatasetTitle: string | null = null;
let createdJobId: string | null = null;

interface JobStatusPayload {
  status: string;
  dataset_id: string | null;
  error_message?: string | null;
}

async function openCollectionDetail(page: Page) {
  if (!createdCollectionId) {
    throw new Error('Collection was not created before opening the detail page');
  }

  await page.goto(`/collections/${createdCollectionId}`);
  await expect(page.getByRole('heading', { name: collectionName })).toBeVisible();
}

async function waitForDatasetJob(jobId: string, authHeaders: Record<string, string>): Promise<string> {
  for (let attempt = 0; attempt < 45; attempt++) {
    const statusRes = await fetch(`${BASE_URL}/api/jobs/${jobId}`, { headers: authHeaders });
    expect(statusRes.ok).toBe(true);
    const status = await statusRes.json() as JobStatusPayload;
    if (status.status === 'complete' && status.dataset_id) return status.dataset_id;
    if (status.status === 'failed') {
      throw new Error(`Collection fixture import failed: ${status.error_message ?? 'unknown error'}`);
    }
    await new Promise((resolve) => setTimeout(resolve, 1_000));
  }
  throw new Error('Collection fixture import did not complete in time');
}

async function createCollectionDataset(): Promise<{ datasetId: string; title: string }> {
  const token = getAuthToken();
  const authHeaders = { Authorization: `Bearer ${token}` };
  const title = `E2E Collection Dataset ${Date.now()}`;
  // fix(#1018): register the confirm title before the upload can create
  // anything. afterAll needs BOTH halves of the handle, so resolving the id
  // later is no use if the title was never recorded.
  createdDatasetTitle = title;
  const filename = `${title.toLowerCase().replace(/[^a-z0-9]+/g, '-')}.geojson`;
  const geojson = JSON.stringify({
    type: 'FeatureCollection',
    features: [
      {
        type: 'Feature',
        properties: { name: 'Collection fixture', category: 'smoke' },
        geometry: { type: 'Point', coordinates: [-73.9857, 40.7484] },
      },
    ],
  });
  const formData = new FormData();
  formData.append('file', new Blob([geojson], { type: 'application/geo+json' }), filename);

  const uploadRes = await fetch(`${BASE_URL}/api/ingest/upload`, {
    method: 'POST',
    headers: authHeaders,
    body: formData,
  });
  expect(uploadRes.ok).toBe(true);
  const upload = await uploadRes.json() as { job_id: string };

  const previewRes = await fetch(`${BASE_URL}/api/ingest/preview/${upload.job_id}`, {
    method: 'POST',
    headers: authHeaders,
  });
  expect(previewRes.ok).toBe(true);
  const preview = await previewRes.json() as { layer_name?: string; geometry_type?: string | null };
  expect(preview.geometry_type).toBeTruthy();

  const commitRes = await fetch(`${BASE_URL}/api/ingest/commit/${upload.job_id}`, {
    method: 'POST',
    headers: { ...authHeaders, 'Content-Type': 'application/json' },
    body: JSON.stringify({
      title,
      summary: 'Temporary dataset for collection E2E smoke coverage',
      visibility: 'private',
      layer_name: preview.layer_name,
    }),
  });
  // fix(#1018): the job id is the only handle that exists between the commit
  // and the dataset appearing. Record it so teardown can resolve the dataset
  // even when the poll below gives up first.
  createdJobId = upload.job_id;
  expect(commitRes.ok).toBe(true);

  const datasetId = await waitForDatasetJob(upload.job_id, authHeaders);
  createdDatasetId = datasetId;
  return { datasetId, title };
}

test.describe.serial('Collections', () => {
  test.afterAll(async () => {
    const token = getAuthToken();

    // fix(#1018 review): the backend sets dataset_id in the same atomic update
    // that flips the job to 'complete' (_finalize_ingest), so there is no
    // earlier moment to claim the id. If the 45-second poll gives up one
    // second before the ingest lands — or anything after it throws — the
    // dataset exists and nothing here knows its id, and each failed retry
    // leaks a row (analysis.spec.ts had the same shape in #895; its catalog
    // count climbed 3 → 4 → 5 across three retries). One last lookup closes
    // that window.
    if (!createdDatasetId && createdJobId) {
      const res = await fetch(`${BASE_URL}/api/jobs/${createdJobId}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        const status = await res.json() as JobStatusPayload;
        if (status.dataset_id) createdDatasetId = status.dataset_id;
      }
    }

    if (!createdDatasetId || !createdDatasetTitle) return;

    await fetch(`${BASE_URL}/api/datasets/bulk-delete/`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        datasets: [{ dataset_id: createdDatasetId, confirm_title: createdDatasetTitle }],
      }),
    });
  });

  test('browse collections page loads', async ({ page }) => {
    await page.goto('/collections');

    await expect(
      page.getByRole('heading', { name: 'Collections' }),
    ).toBeVisible();
    await expect(
      page.getByRole('button', {
        name: /^(New Collection|Create your first collection)$/,
      }),
    ).toBeVisible();
  });

  test('create a new collection from the global create menu', async ({ page }) => {
    await page.goto('/collections');

    await page.getByRole('button', { name: 'Create', exact: true }).click();
    await page.getByRole('menuitem', { name: 'Collection' }).click();

    await expect(
      page.getByRole('heading', { name: 'Create Collection' }),
    ).toBeVisible();

    await page.getByLabel('Name').fill(collectionName);
    await page.locator('#collection-description').fill(collectionDescription);

    const createResponsePromise = page.waitForResponse(
      (response) =>
        response.request().method() === 'POST' &&
        response.url().includes('/api/catalog/collections/'),
    );
    await page.getByRole('button', { name: 'Create', exact: true }).click();

    const createResponse = await createResponsePromise;
    const createdCollection = await createResponse.json();
    createdCollectionId = createdCollection.id;
    expect(createdCollectionId).toBeTruthy();

    await expect(page.getByText('Collection created')).toBeVisible({
      timeout: 10_000,
    });
    await openCollectionDetail(page);
  });

  test('view collection detail page', async ({ page }) => {
    await openCollectionDetail(page);

    const metadata = page.getByLabel('Collection metadata');
    await expect(metadata.getByText('Datasets')).toBeVisible();
    await expect(metadata.getByText('Created')).toBeVisible();
    await expect(metadata.getByText('Last Updated')).toBeVisible();
    await expect(page.getByText(collectionDescription)).toBeVisible();
    await expect(
      page.getByLabel('breadcrumb').getByRole('link', { name: 'Collections' }),
    ).toBeVisible();
  });

  test('edit collection metadata', async ({ page }) => {
    await openCollectionDetail(page);

    await page.getByRole('button', { name: 'Edit' }).click();
    await expect(
      page.getByRole('heading', { name: 'Edit Collection' }),
    ).toBeVisible();

    await page.locator('#edit-collection-description').clear();
    await page.locator('#edit-collection-description').fill(updatedDescription);
    await page.getByRole('button', { name: 'Save' }).click();

    await expect(page.getByText('Collection updated')).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.locator('#main-content').getByText(updatedDescription)).toBeVisible();
  });

  test('add dataset to collection', async ({ page }) => {
    test.slow();
    await openCollectionDetail(page);

    await expect(
      page.getByRole('heading', { name: 'Add Datasets' }),
    ).toBeVisible();

    // createdDatasetId / createdDatasetTitle are registered inside the helper,
    // as early as each value exists, so afterAll can clean up a run that dies
    // before this line (fix(#1018)).
    const dataset = await createCollectionDataset();

    await page.getByPlaceholder('Search datasets by name...').fill(dataset.title);
    await page.getByRole('button', { name: 'Search' }).click();

    const addButton = page.getByRole('button', { name: 'Add' }).first();
    await expect(addButton).toBeVisible({
      timeout: 15_000,
    });

    await addButton.click();

    await expect(page.getByText('Dataset added to collection')).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.getByText('No datasets in this collection')).toHaveCount(0);
    await expect(page.getByTitle('Remove from collection').first()).toBeVisible();
  });

  test('remove dataset from collection', async ({ page }) => {
    await openCollectionDetail(page);

    await expect(page.getByTitle('Remove from collection').first()).toBeVisible({
      timeout: 10_000,
    });

    await page.getByTitle('Remove from collection').first().click();

    await expect(
      page.getByText('Dataset removed from collection'),
    ).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText('No datasets in this collection')).toBeVisible();
  });

  test('delete collection', async ({ page }) => {
    await openCollectionDetail(page);

    // Delete is in the overflow menu (...)
    await page.getByRole('button', { name: 'More actions' }).click();
    await page.getByRole('menuitem', { name: 'Delete' }).click();
    await expect(
      page.getByRole('heading', { name: 'Delete Collection' }),
    ).toBeVisible();

    await page.getByPlaceholder(collectionName).fill(collectionName);
    await page.getByRole('button', { name: 'Delete Collection' }).click();

    await expect(page.getByText('Collection deleted')).toBeVisible({
      timeout: 10_000,
    });
    await page.waitForURL('/collections');
  });
});
