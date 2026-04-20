import { test, expect, type Page } from '@playwright/test';

const collectionName = `E2E Test Collection ${Date.now()}`;
const collectionDescription = 'Automated test collection for E2E';
const updatedDescription = 'Updated description for E2E test';
let createdCollectionId: string | null = null;

async function openCollectionDetail(page: Page) {
  if (!createdCollectionId) {
    throw new Error('Collection was not created before opening the detail page');
  }

  await page.goto(`/collections/${createdCollectionId}`);
  await expect(page.getByRole('heading', { name: collectionName })).toBeVisible();
}

test.describe.serial('Collections', () => {
  test('browse collections page loads', async ({ page }) => {
    await page.goto('/collections');

    await expect(
      page.getByRole('heading', { name: 'Collections' }),
    ).toBeVisible();
    await expect(
      page.getByRole('button', { name: 'New Collection' }),
    ).toBeVisible();
  });

  test('create a new collection from the global create menu', async ({ page }) => {
    await page.goto('/collections');

    await page.getByRole('button', { name: 'Create' }).click();
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
    await page.getByRole('button', { name: 'Create' }).click();

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
    await openCollectionDetail(page);

    await expect(
      page.getByRole('heading', { name: 'Add Datasets' }),
    ).toBeVisible();

    await page.getByPlaceholder('Search datasets by name...').fill('Reefs');
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
