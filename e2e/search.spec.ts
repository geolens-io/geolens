import { test, expect } from '@playwright/test';

test.describe('Search Flow', () => {
  test('prefix search supports keyboard typeahead navigation', async ({ page }) => {
    // Verify search page loaded
    await page.goto('/');
    await expect(
      page.getByRole('heading', { name: 'Find Geospatial Data' }),
    ).toBeVisible();

    // Navigate with query param to bypass hero→sticky transition race condition.
    // This puts us directly in browse mode with a single SearchBar.
    await page.goto('/?q=Reefs');
    const searchInput = page.getByRole('combobox', { name: 'Search geospatial data...' });

    // Focus and re-fill to trigger typeahead (onFocus + onChange open the dropdown)
    await searchInput.click();
    await searchInput.fill('Reefs');
    await expect(page.getByRole('option', { name: /Reefs/ })).toBeVisible({
      timeout: 15_000,
    });
    await searchInput.press('ArrowDown');
    await searchInput.press('Enter');

    // Verify dataset detail page
    await expect(page).toHaveURL(/\/datasets\//);
    await expect(
      page.getByRole('heading', { name: /Reefs/ }),
    ).toBeVisible();
  });
});
