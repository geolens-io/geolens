import { test, expect } from '@playwright/test';

// REL-02: lightweight keyboard-nav smoke for the public front door.
// Scoped to /login and / only — no MapLibre/builder routes which flake headless.
// Phase 1248 GLUX vitest component tests already guard the map/builder flows.
test.describe('Keyboard navigation — public routes', () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test('/login: Tab reaches username → password → submit in order', async ({ page }) => {
    await page.goto('/login');
    await page.waitForLoadState('networkidle');

    const usernameField = page.getByLabel('Username');
    const passwordField = page.locator('#password');
    const submitButton = page.getByRole('button', { name: 'Sign In' });

    // Tab through the page (may skip over skip-to-content links or nav items)
    // until the username field receives focus, then assert the form sequence.
    for (let i = 0; i < 15; i++) {
      await page.keyboard.press('Tab');
      if (await usernameField.evaluate((el) => el === document.activeElement)) break;
    }
    await expect(usernameField).toBeFocused();
    await page.keyboard.type('keyboard-nav-smoke');

    // Password is next in tab order — proves no focus trap between them.
    await page.keyboard.press('Tab');
    await expect(passwordField).toBeFocused();
    await page.keyboard.type('keyboard-nav-smoke');

    // With the form filled the submit button is enabled and reachable. A disabled
    // submit (empty form) is correctly skipped in the tab order, so we fill first,
    // then Tab forward until it receives focus (tolerates an intervening control).
    for (let i = 0; i < 4; i++) {
      await page.keyboard.press('Tab');
      if (await submitButton.evaluate((el) => el === document.activeElement)) break;
    }
    await expect(submitButton).toBeFocused();
  });

  test('/ home: search input is keyboard-reachable and stays interactive after Enter', async ({
    page,
  }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    const searchInput = page.getByRole('combobox', { name: 'Search geospatial data...' });
    await expect(searchInput).toBeVisible();

    // Tab through the page until the catalog search combobox receives focus.
    for (let i = 0; i < 20; i++) {
      await page.keyboard.press('Tab');
      if (await searchInput.evaluate((el) => el === document.activeElement)) break;
    }
    await expect(searchInput).toBeFocused();

    // Type a query and press Enter — page must remain interactive with no focus stranding.
    await page.keyboard.type('parks');
    await page.keyboard.press('Enter');

    // The page is still alive and the search input is still accessible.
    await expect(page.locator('body')).toBeVisible();
    await expect(searchInput).toBeVisible();
  });
});
