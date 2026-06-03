import { test, expect } from '@playwright/test';
import { getSearchSeed } from './helpers/catalog';

test.describe('Search Flow', () => {
  test('search page renders at root with search input', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    // Search page should load at /
    await expect(page).toHaveURL('/');

    // Search input should be present
    await expect(
      page.getByRole('combobox', { name: 'Search geospatial data...' }),
    ).toHaveCount(1);

    const filterRail = page.getByTestId('search-filter-rail');
    const resultsRegion = page.getByRole('region', { name: 'Search results' });
    await expect(filterRail).toBeVisible();
    await expect(resultsRegion).toBeVisible();

    const [filterRailBox, resultsBox] = await Promise.all([
      filterRail.boundingBox(),
      resultsRegion.boundingBox(),
    ]);

    expect(filterRailBox).not.toBeNull();
    expect(resultsBox).not.toBeNull();
    expect(filterRailBox!.x).toBeLessThan(resultsBox!.x);
  });

  test('query params are respected at /?q=something', async ({ page }) => {
    await page.goto('/?q=Zoning');
    await page.waitForLoadState('networkidle');

    // Should stay on root with query param
    await expect(page).toHaveURL('/?q=Zoning');

    // Search input should reflect the query
    const searchInput = page.getByRole('combobox', { name: 'Search geospatial data...' });
    await expect(searchInput).toHaveCount(1);
    await expect(searchInput).toHaveValue('Zoning');
  });

  test('prefix search supports keyboard typeahead navigation', async ({ page }) => {
    const seed = await getSearchSeed();

    // Verify search page loaded
    await page.goto('/');
    await expect(
      page.getByRole('combobox', { name: 'Search geospatial data...' }),
    ).toBeVisible();

    // Navigate with query param to bypass hero→sticky transition race condition.
    // This puts us directly in browse mode with a single SearchBar.
    await page.goto(`/?q=${encodeURIComponent(seed.query)}`);
    const searchInput = page.getByRole('combobox', { name: 'Search geospatial data...' });
    await expect(searchInput).toHaveValue(seed.query);

    // Focus and re-fill to trigger typeahead (onFocus + onChange open the dropdown)
    await searchInput.click();
    await searchInput.fill(seed.query);
    await expect(page.getByRole('option', { name: seed.title, exact: true })).toBeVisible({
      timeout: 15_000,
    });
    await searchInput.press('ArrowDown');
    await searchInput.press('Enter');

    // Verify dataset detail page
    await expect(page).toHaveURL(new RegExp(`/datasets/${seed.id}$`));
    await expect(
      page.getByRole('heading', { name: seed.title, exact: true }),
    ).toBeVisible();
  });

  test('result cards stay readable on mobile widths', async ({ page }) => {
    const seed = await getSearchSeed();

    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`/?q=${encodeURIComponent(seed.query)}`);

    const card = page.getByTestId('search-result-card').first();
    await expect(card).toBeVisible();
    await expect(card).toContainText(seed.title);

    const overflow = await card.evaluate((element) => ({
      clientWidth: element.clientWidth,
      scrollWidth: element.scrollWidth,
    }));

    expect(overflow.scrollWidth).toBeLessThanOrEqual(overflow.clientWidth + 1);
  });
});
