import { test, expect } from '@playwright/test';

test.describe('Collections', () => {
  const collectionName = `E2E Test Collection ${Date.now()}`;
  const collectionDescription = 'Automated test collection for E2E';
  const updatedDescription = 'Updated description for E2E test';

  test('browse collections page loads', async ({ page }) => {
    await page.goto('/collections');

    // Verify page heading
    await expect(
      page.getByRole('heading', { name: 'Collections' }),
    ).toBeVisible();
  });

  test('create a new collection', async ({ page }) => {
    await page.goto('/collections');

    // Click "New Collection" button
    await page.getByRole('button', { name: 'New Collection' }).click();

    // Verify create dialog opens
    await expect(
      page.getByRole('heading', { name: 'Create Collection' }),
    ).toBeVisible();

    // Fill in collection details
    await page.getByLabel('Name').fill(collectionName);
    await page.locator('#collection-description').fill(collectionDescription);

    // Submit the form
    await page.getByRole('button', { name: 'Create' }).click();

    // Verify success toast
    await expect(page.getByText('Collection created')).toBeVisible({
      timeout: 10_000,
    });

    // Verify collection appears in the list
    await expect(page.getByText(collectionName)).toBeVisible({
      timeout: 10_000,
    });
  });

  test('view collection detail page', async ({ page }) => {
    await page.goto('/collections');

    // Wait for the collection to appear
    await expect(page.getByText(collectionName)).toBeVisible({
      timeout: 10_000,
    });

    // Click on the collection to navigate to detail
    await page.getByText(collectionName).first().click();

    // Verify detail page loaded with collection name as heading
    await expect(
      page.getByRole('heading', { name: collectionName }),
    ).toBeVisible();

    // Verify metadata section is present
    await expect(page.getByText('Datasets')).toBeVisible();
    await expect(page.getByText('Created')).toBeVisible();
    await expect(page.getByText('Last Updated')).toBeVisible();

    // Verify the description is shown
    await expect(page.getByText(collectionDescription)).toBeVisible();

    // Verify breadcrumb back to collections
    await expect(
      page.getByRole('link', { name: 'Collections' }),
    ).toBeVisible();
  });

  test('edit collection metadata', async ({ page }) => {
    await page.goto('/collections');

    // Navigate to collection detail
    await expect(page.getByText(collectionName)).toBeVisible({
      timeout: 10_000,
    });
    await page.getByText(collectionName).first().click();
    await expect(
      page.getByRole('heading', { name: collectionName }),
    ).toBeVisible();

    // Click Edit button
    await page.getByRole('button', { name: 'Edit' }).click();

    // Verify edit dialog opens
    await expect(
      page.getByRole('heading', { name: 'Edit Collection' }),
    ).toBeVisible();

    // Update the description
    await page.locator('#edit-collection-description').clear();
    await page.locator('#edit-collection-description').fill(updatedDescription);

    // Save changes
    await page.getByRole('button', { name: 'Save' }).click();

    // Verify success toast
    await expect(page.getByText('Collection updated')).toBeVisible({
      timeout: 10_000,
    });

    // Verify updated description is shown on the page
    await expect(page.getByText(updatedDescription)).toBeVisible();
  });

  test('add dataset to collection', async ({ page }) => {
    await page.goto('/collections');

    // Navigate to collection detail
    await expect(page.getByText(collectionName)).toBeVisible({
      timeout: 10_000,
    });
    await page.getByText(collectionName).first().click();
    await expect(
      page.getByRole('heading', { name: collectionName }),
    ).toBeVisible();

    // Verify the "Add Datasets" section is visible (editor-only)
    await expect(
      page.getByRole('heading', { name: 'Add Datasets' }),
    ).toBeVisible();

    // Search for a dataset to add
    await page
      .getByPlaceholder('Search datasets by name...')
      .fill('countries');
    await page.getByRole('button', { name: 'Search' }).click();

    // Wait for search results to appear
    await expect(page.getByText('World Countries')).toBeVisible({
      timeout: 15_000,
    });

    // Click Add button on the first result
    await page.getByRole('button', { name: 'Add' }).first().click();

    // Verify success toast
    await expect(page.getByText('Dataset added to collection')).toBeVisible({
      timeout: 10_000,
    });
  });

  test('remove dataset from collection', async ({ page }) => {
    await page.goto('/collections');

    // Navigate to collection detail
    await expect(page.getByText(collectionName)).toBeVisible({
      timeout: 10_000,
    });
    await page.getByText(collectionName).first().click();
    await expect(
      page.getByRole('heading', { name: collectionName }),
    ).toBeVisible();

    // Verify the dataset is listed in the collection
    await expect(page.getByText('World Countries')).toBeVisible({
      timeout: 10_000,
    });

    // Click the remove button (X icon) for the dataset
    await page
      .getByTitle('Remove from collection')
      .first()
      .click();

    // Verify success toast
    await expect(
      page.getByText('Dataset removed from collection'),
    ).toBeVisible({ timeout: 10_000 });
  });

  test('delete collection', async ({ page }) => {
    await page.goto('/collections');

    // Navigate to collection detail
    await expect(page.getByText(collectionName)).toBeVisible({
      timeout: 10_000,
    });
    await page.getByText(collectionName).first().click();
    await expect(
      page.getByRole('heading', { name: collectionName }),
    ).toBeVisible();

    // Click Delete button
    await page.getByRole('button', { name: 'Delete' }).click();

    // Verify delete dialog opens
    await expect(
      page.getByRole('heading', { name: 'Delete Collection' }),
    ).toBeVisible();

    // Type collection name to confirm
    await page.getByPlaceholder(collectionName).fill(collectionName);

    // Click the delete confirmation button
    await page.getByRole('button', { name: 'Delete Collection' }).click();

    // Verify success toast
    await expect(page.getByText('Collection deleted')).toBeVisible({
      timeout: 10_000,
    });

    // Verify redirected back to collections list
    await page.waitForURL('/collections');
  });
});
