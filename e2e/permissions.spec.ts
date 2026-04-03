import { test, expect } from '@playwright/test';

test.describe('Permissions', () => {
  test('settings: permissions tab loads with matrix', async ({ page }) => {
    await page.goto('/admin/settings#permissions');

    // Verify settings page heading
    await expect(
      page.getByRole('heading', { name: 'Settings' }),
    ).toBeVisible();

    // Click the Permissions tab to ensure it's active
    await page.getByRole('tab', { name: 'Permissions' }).click();

    // Verify matrix card
    await expect(page.getByText('Role Permissions')).toBeVisible({
      timeout: 10_000,
    });

    // Verify all 8 capability labels render
    await expect(page.getByText('Upload Datasets')).toBeVisible();
    await expect(page.getByText('Create Layers')).toBeVisible();
    await expect(page.getByText('Export Data')).toBeVisible();
    await expect(page.getByText('Edit Metadata')).toBeVisible();
    await expect(page.getByText('Manage Collections')).toBeVisible();
    await expect(page.getByText('AI Chat')).toBeVisible();
    await expect(page.getByText('Manage Users')).toBeVisible();
    await expect(page.getByText('Manage Settings')).toBeVisible();

    // Verify role column headers
    await expect(page.getByRole('columnheader', { name: 'viewer' })).toBeVisible();
    await expect(page.getByRole('columnheader', { name: 'editor' })).toBeVisible();
    await expect(page.getByRole('columnheader', { name: 'admin' })).toBeVisible();

    // Verify Save and Reset buttons
    await expect(page.getByRole('button', { name: 'Save' })).toBeVisible();
    await expect(
      page.getByRole('button', { name: 'Reset to Defaults' }),
    ).toBeVisible();
  });

  test('admin lockout: manage_users and manage_settings checkboxes are disabled for admin', async ({
    page,
  }) => {
    await page.goto('/admin/settings#permissions');

    // Click the Permissions tab to ensure it's active
    await page.getByRole('tab', { name: 'Permissions' }).click();

    await expect(page.getByText('Role Permissions')).toBeVisible({
      timeout: 10_000,
    });

    // Admin manage_users checkbox should be checked and disabled
    const manageUsersAdmin = page.getByRole('checkbox', {
      name: 'Manage Users for admin',
    });
    await expect(manageUsersAdmin).toBeChecked();
    await expect(manageUsersAdmin).toBeDisabled();

    // Admin manage_settings checkbox should be checked and disabled
    const manageSettingsAdmin = page.getByRole('checkbox', {
      name: 'Manage Settings for admin',
    });
    await expect(manageSettingsAdmin).toBeChecked();
    await expect(manageSettingsAdmin).toBeDisabled();
  });

  test('permissions API: /auth/me/permissions returns capabilities', async ({
    request,
  }) => {
    // Login to get token
    const loginResp = await request.post('/api/auth/login', {
      form: {
        username: process.env.GEOLENS_ADMIN_USERNAME ?? 'admin',
        password: process.env.GEOLENS_ADMIN_PASSWORD ?? 'admin',
      },
    });
    expect(loginResp.ok()).toBeTruthy();
    const { access_token } = await loginResp.json();

    // Fetch permissions
    const permResp = await request.get('/api/auth/me/permissions', {
      headers: { Authorization: `Bearer ${access_token}` },
    });
    expect(permResp.ok()).toBeTruthy();
    const data = await permResp.json();

    // Admin should have all 8 capabilities set to true
    expect(data.permissions).toBeDefined();
    const perms = data.permissions;
    expect(Object.keys(perms)).toHaveLength(8);
    for (const [, val] of Object.entries(perms)) {
      expect(val).toBe(true);
    }
  });

  test('navbar: admin sees Maps, Import, and Admin links', async ({
    page,
  }) => {
    await page.goto('/search');
    await expect(
      page.getByRole('combobox', { name: 'Search geospatial data...' }),
    ).toBeVisible();

    // Admin should see all permission-gated nav links
    const nav = page.locator('header nav');
    await expect(nav.getByRole('link', { name: 'Maps' })).toBeVisible();
    await expect(nav.getByRole('link', { name: 'Import' })).toBeVisible();
    await expect(nav.getByRole('link', { name: 'Admin' })).toBeVisible();
  });
});
