import { test, expect } from '@playwright/test';

test.describe('Authentication Flow', () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test('login, see dashboard, logout', async ({ page }) => {
    const adminUser = process.env.GEOLENS_ADMIN_USERNAME ?? 'admin';
    const adminPass = process.env.GEOLENS_ADMIN_PASSWORD ?? 'admin';

    await page.goto('/login');

    // Verify login page
    await expect(
      page.getByRole('button', { name: 'Sign In' }),
    ).toBeVisible();

    // Fill credentials
    await page.getByLabel('Username').fill(adminUser);
    await page.locator('#password').fill(adminPass);

    // Submit
    await page.getByRole('button', { name: 'Sign In' }).click();

    // Current auth flow lands on the root workspace.
    await page.waitForURL((url) => url.pathname === '/');

    // Verify workspace loaded
    await expect(
      page.getByRole('combobox', { name: 'Search geospatial data...' }),
    ).toBeVisible();

    // Verify username displayed in navbar user menu button
    await expect(page.getByRole('button', { name: 'User menu' })).toBeVisible();

    // Logout
    await page.getByRole('button', { name: 'User menu' }).click();
    await page.getByRole('menuitem', { name: 'Logout' }).click();

    // Verify redirected to login
    await page.waitForURL('/login');

    // Verify login heading visible again
    await expect(
      page.getByRole('button', { name: 'Sign In' }),
    ).toBeVisible();
  });
});
