import { test, expect } from '@playwright/test';

test.describe('Admin Panel', () => {
  test('overview page loads with stats', async ({ page }) => {
    await page.goto('/admin/overview');

    await expect(
      page.getByRole('heading', { name: 'Overview' }),
    ).toBeVisible();
    await expect(page.getByText('Total Datasets')).toBeVisible({
      timeout: 10_000,
    });
  });

  test('user management: view user list and table columns', async ({ page }) => {
    await page.goto('/admin/users');

    await expect(
      page.getByRole('heading', { name: 'Users' }),
    ).toBeVisible();
    await expect(page.getByText('Username')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText('Email')).toBeVisible();
    await expect(page.getByText('Roles')).toBeVisible();
    await expect(page.getByText('Status')).toBeVisible();
    await expect(
      page.getByRole('cell', { name: 'admin', exact: true }).first(),
    ).toBeVisible();
    await expect(
      page.getByRole('button', { name: 'Add User' }),
    ).toBeVisible();
  });

  test('job monitoring: view job list page', async ({ page }) => {
    await page.goto('/admin/jobs');

    await expect(
      page.getByRole('heading', { name: 'Jobs' }),
    ).toBeVisible();
    await expect(page.locator('label').filter({ hasText: 'Status' })).toBeVisible();
    await expect(page.locator('label').filter({ hasText: 'User' })).toBeVisible();
    await expect(page.getByRole('columnheader', { name: 'Created At' })).toBeVisible();
    await expect(page.getByRole('columnheader', { name: 'Filename' })).toBeVisible();
    const detailsToggle = page.getByTestId('job-details-toggle').first();
    await expect(detailsToggle).toBeVisible();
    await detailsToggle.click();
    await expect(detailsToggle).toHaveAttribute('aria-expanded', 'true');
  });

  test('audit log: view entries and table structure', async ({ page }) => {
    await page.goto('/admin/audit');

    await expect(
      page.getByRole('heading', { name: 'Audit Logs' }),
    ).toBeVisible();
    await expect(page.locator('label').filter({ hasText: 'Action' })).toBeVisible();
    await expect(page.locator('label').filter({ hasText: 'From' })).toBeVisible();
    await expect(page.locator('label').filter({ hasText: 'To' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Clear' })).toBeVisible();
    await expect(page.getByRole('columnheader', { name: 'Timestamp' })).toBeVisible();
    await expect(page.getByRole('columnheader', { name: 'IP Address' })).toBeVisible();
    await expect(page.getByTestId('audit-details-toggle').first()).toBeVisible();
    await page.getByTestId('audit-details-toggle').first().click();
    await expect(page.getByText('Expanded log details')).toBeVisible();
  });

  test('settings: general page loads with feature toggles', async ({ page }) => {
    await page.goto('/admin/settings/general');

    await expect(
      page.getByRole('heading', { name: 'General' }),
    ).toBeVisible();
    await expect(page.getByText('Require Metadata for Publishing')).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.getByText('Public App URL')).toBeVisible();
    await expect(page.getByText('Public API URL')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Save' })).toBeVisible();
  });

  test('settings: auth page loads', async ({ page }) => {
    await page.goto('/admin/settings/auth');

    await expect(
      page.getByRole('heading', { name: 'Auth', exact: true }),
    ).toBeVisible();
    await expect(page.getByRole('heading', { name: 'OAuth Providers' })).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.getByText('Access Token Lifetime (minutes)')).toBeVisible();
    await expect(page.getByText('Refresh Token Lifetime (days)')).toBeVisible();
  });

  test('settings: network page loads', async ({ page }) => {
    await page.goto('/admin/settings/network');

    await expect(
      page.getByRole('heading', { name: 'Network' }),
    ).toBeVisible();
    await expect(page.getByText('CORS Allowed Origins')).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.getByText('Global Rate Limit (per second)')).toBeVisible();
  });

  test('settings: storage page loads', async ({ page }) => {
    await page.goto('/admin/settings/storage');

    await expect(
      page.getByRole('heading', { name: 'Storage' }),
    ).toBeVisible();
    await expect(page.getByText('Maximum file size (MB)')).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.getByText('Allowed extensions')).toBeVisible();
    await expect(page.getByText('Tile Cache TTL (seconds)')).toBeVisible();
  });

  test('settings: map page loads', async ({ page }) => {
    await page.goto('/admin/settings/map');

    await expect(
      page.getByRole('heading', { name: 'Map', exact: true }),
    ).toBeVisible();
    await expect(page.getByText('Basemap Presets')).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.getByText('Default Map View')).toBeVisible();
    await expect(page.getByText('Map Widgets')).toBeVisible();
  });

  test('published maps page loads', async ({ page }) => {
    await page.goto('/admin/shared-maps');

    await expect(
      page.getByRole('heading', { name: 'Published Maps' }),
    ).toBeVisible();
    await expect(page.getByPlaceholder('Search by map name...')).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.getByRole('columnheader', { name: 'Map' })).toBeVisible();
    await expect(page.getByRole('columnheader', { name: 'Status' })).toBeVisible();
  });

  test('sidebar navigation works across current admin sections', async ({ page }) => {
    await page.goto('/admin/overview');

    await expect(
      page.getByRole('heading', { name: 'Overview' }),
    ).toBeVisible();

    await page.getByRole('link', { name: 'Users' }).click();
    await page.waitForURL('/admin/users');
    await expect(
      page.getByRole('heading', { name: 'Users' }),
    ).toBeVisible();

    await page.getByRole('link', { name: 'Jobs' }).click();
    await page.waitForURL('/admin/jobs');
    await expect(
      page.getByRole('heading', { name: 'Jobs' }),
    ).toBeVisible();

    await page.getByRole('link', { name: 'Audit Log' }).click();
    await page.waitForURL('/admin/audit');
    await expect(
      page.getByRole('heading', { name: 'Audit Logs' }),
    ).toBeVisible();

    await page.getByRole('link', { name: 'Published Maps' }).click();
    await page.waitForURL('/admin/shared-maps');
    await expect(
      page.getByRole('heading', { name: 'Published Maps' }),
    ).toBeVisible();

    await page.locator('a[href="/admin/settings/map"]').click();
    await page.waitForURL('/admin/settings/map');
    await expect(
      page.getByRole('heading', { name: 'Map', exact: true }),
    ).toBeVisible();
  });
});
