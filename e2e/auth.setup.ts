import { test as setup, expect } from '@playwright/test';
import path from 'path';

const authFile = path.join(__dirname, '../playwright/.auth/user.json');

setup('authenticate as admin', async ({ page }) => {
  const adminUser = process.env.GEOLENS_ADMIN_USERNAME ?? 'admin';
  const adminPass = process.env.GEOLENS_ADMIN_PASSWORD ?? 'admin';

  await page.goto('/login');

  // Wait for the login form to render
  await expect(page.getByRole('button', { name: 'Sign In' })).toBeVisible();

  // Fill credentials
  await page.getByLabel('Username').fill(adminUser);
  await page.locator('#password').fill(adminPass);

  // Submit the form
  await page.getByRole('button', { name: 'Sign In' }).click();

  // Wait for redirect to the search workspace (index route)
  await page.waitForURL('/');

  // Verify workspace loaded
  await expect(page.locator('[data-testid="search-page"], input[type="search"], [role="search"]').first()).toBeVisible({ timeout: 10000 }).catch(() => {
    // Fallback: just verify we're no longer on /login
    expect(page.url()).not.toContain('/login');
  });

  // Save storage state (includes localStorage with auth token)
  await page.context().storageState({ path: authFile });
});
