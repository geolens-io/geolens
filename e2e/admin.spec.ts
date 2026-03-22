import { test, expect } from '@playwright/test';

test.describe('Admin Panel', () => {
  test('overview page loads with stats', async ({ page }) => {
    await page.goto('/admin/overview');

    // Verify overview heading
    await expect(
      page.getByRole('heading', { name: 'Overview' }),
    ).toBeVisible();

    // Verify stats cards are present
    await expect(page.getByText('Total Datasets')).toBeVisible({
      timeout: 10_000,
    });
  });

  test('user management: view user list and table columns', async ({
    page,
  }) => {
    await page.goto('/admin/users');

    // Verify page heading
    await expect(
      page.getByRole('heading', { name: 'Users' }),
    ).toBeVisible();

    // Verify user table headers are visible
    await expect(page.getByText('Username')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText('Email')).toBeVisible();
    await expect(page.getByText('Roles')).toBeVisible();
    await expect(page.getByText('Status')).toBeVisible();

    // Verify the admin user appears in the table
    await expect(
      page.getByRole('cell', { name: 'admin' }),
    ).toBeVisible();

    // Verify the "Add User" button is present
    await expect(
      page.getByRole('button', { name: 'Add User' }),
    ).toBeVisible();
  });

  test('job monitoring: view job list page', async ({ page }) => {
    await page.goto('/admin/jobs');

    // Verify page heading
    await expect(
      page.getByRole('heading', { name: 'Jobs' }),
    ).toBeVisible();

    // Verify job table headers or empty state
    const jobsCard = page.locator('[class*="card"]').first();
    await expect(jobsCard).toBeVisible({ timeout: 10_000 });

    // Verify filter controls are present
    await expect(page.getByText('Status')).toBeVisible();
    await expect(page.getByText('User')).toBeVisible();

    // Verify table headers appear (jobs may exist from upload tests)
    await expect(page.getByText('Created At')).toBeVisible();
    await expect(page.getByText('Filename')).toBeVisible();
  });

  test('audit log: view entries and table structure', async ({ page }) => {
    await page.goto('/admin/audit');

    // Verify page heading
    await expect(
      page.getByRole('heading', { name: 'Audit Logs' }),
    ).toBeVisible();

    // Verify audit log card loads
    await expect(page.getByText('Audit Logs').first()).toBeVisible({
      timeout: 10_000,
    });

    // Verify filter controls
    await expect(page.getByText('Action')).toBeVisible();
    await expect(page.getByText('From')).toBeVisible();
    await expect(page.getByText('To')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Clear' })).toBeVisible();

    // Verify table headers
    await expect(page.getByText('Timestamp')).toBeVisible();
    await expect(page.getByText('IP Address')).toBeVisible();
  });

  test('settings: general page loads with feature toggles', async ({
    page,
  }) => {
    await page.goto('/admin/settings/general');

    // Verify page heading
    await expect(
      page.getByRole('heading', { name: 'General' }),
    ).toBeVisible();

    // Verify feature toggle card
    await expect(page.getByText('Feature Toggles')).toBeVisible({
      timeout: 10_000,
    });

    // Verify toggle labels
    await expect(page.getByText('Self-Registration')).toBeVisible();
    await expect(page.getByText('AI Chat')).toBeVisible();

    // Verify save button is present
    await expect(page.getByRole('button', { name: 'Save' })).toBeVisible();
  });

  test('settings: basemaps page loads', async ({ page }) => {
    await page.goto('/admin/settings/basemaps');

    // Verify page heading
    await expect(
      page.getByRole('heading', { name: 'Basemaps' }),
    ).toBeVisible();

    // Verify basemap presets section
    await expect(page.getByText('Basemap Presets')).toBeVisible({
      timeout: 10_000,
    });
  });

  test('settings: map defaults page loads', async ({ page }) => {
    await page.goto('/admin/settings/map-defaults');

    // Verify page heading
    await expect(
      page.getByRole('heading', { name: 'Map Defaults' }),
    ).toBeVisible();

    // Verify form fields
    await expect(page.getByText('Default Map View')).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.getByText('Latitude')).toBeVisible();
    await expect(page.getByText('Longitude')).toBeVisible();
    await expect(page.getByText('Zoom Level')).toBeVisible();
  });

  test('settings: security page loads', async ({ page }) => {
    await page.goto('/admin/settings/security');

    // Verify page heading
    await expect(
      page.getByRole('heading', { name: 'Security' }),
    ).toBeVisible();

    // Verify rate limit settings
    await expect(page.getByText('Login Rate Limiting')).toBeVisible({
      timeout: 10_000,
    });
    await expect(
      page.getByText('Login attempts per minute'),
    ).toBeVisible();
  });

  test('settings: uploads page loads', async ({ page }) => {
    await page.goto('/admin/settings/uploads');

    // Verify page heading
    await expect(
      page.getByRole('heading', { name: 'Upload Settings' }),
    ).toBeVisible();

    // Verify upload limits card
    await expect(page.getByText('Upload Limits')).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.getByText('Maximum file size (MB)')).toBeVisible();
    await expect(page.getByText('Allowed extensions')).toBeVisible();
  });

  test('sidebar navigation works across admin sections', async ({ page }) => {
    await page.goto('/admin/overview');

    // Verify overview loaded
    await expect(
      page.getByRole('heading', { name: 'Overview' }),
    ).toBeVisible();

    // Navigate to Users via sidebar
    await page.getByRole('link', { name: 'Users' }).click();
    await page.waitForURL('/admin/users');
    await expect(
      page.getByRole('heading', { name: 'Users' }),
    ).toBeVisible();

    // Navigate to Jobs via sidebar
    await page.getByRole('link', { name: 'Jobs' }).click();
    await page.waitForURL('/admin/jobs');
    await expect(
      page.getByRole('heading', { name: 'Jobs' }),
    ).toBeVisible();

    // Navigate to Audit Log via sidebar
    await page.getByRole('link', { name: 'Audit Log' }).click();
    await page.waitForURL('/admin/audit');
    await expect(
      page.getByRole('heading', { name: 'Audit Logs' }),
    ).toBeVisible();

    // Navigate to Infrastructure via sidebar
    await page.getByRole('link', { name: 'Infrastructure' }).click();
    await page.waitForURL('/admin/infrastructure');
    await expect(
      page.getByRole('heading', { name: 'Infrastructure' }),
    ).toBeVisible();
  });
});
