import { test, expect, type Page } from './helpers/session';

const GUEST_BROWSE_KEY = 'gl-guest-browse';

async function allowGuestCatalog(page: Page) {
  await page.addInitScript((key) => {
    window.sessionStorage.setItem(key, 'true');
  }, GUEST_BROWSE_KEY);
}

// Lightweight keyboard-nav smoke for the public front door.
// Scoped to /login and / only — no MapLibre/builder routes which flake headless.
// Vitest component tests already guard the map/builder flows.
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

    // Tab forward until the submit button has focus, which tolerates an
    // intervening control such as the show-password toggle.
    for (let i = 0; i < 4; i++) {
      await page.keyboard.press('Tab');
      if (await submitButton.evaluate((el) => el === document.activeElement)) break;
    }
    await expect(submitButton).toBeFocused();
  });

  test('/ home: search input is keyboard-reachable and stays interactive after Enter', async ({
    page,
  }) => {
    // Matches the LoginPage "Browse the catalog" escape path when landing_first
    // is enabled in demo/cloud configs.
    await allowGuestCatalog(page);
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    const searchInput = page.getByRole('combobox', { name: 'Search the catalog...' });
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
