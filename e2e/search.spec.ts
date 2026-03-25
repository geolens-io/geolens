import { test, expect } from '@playwright/test';

test.describe('Search Flow', () => {
  test('landing scroll keeps filter access and does not mount the spatial dialog until opened', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByText('sample-nonspatial')).toBeVisible();

    await expect(
      page.getByRole('dialog', { name: 'Search area' }),
    ).toHaveCount(0);

    await page.evaluate(() => window.scrollTo(0, 1200));
    await page.waitForTimeout(250);

    const stickyShell = page.getByTestId('search-sticky-shell');
    await expect(stickyShell).toBeVisible();
    await expect(
      stickyShell.getByRole('button', { name: 'Keywords' }),
    ).toBeVisible();
  });

  test('prefix search supports keyboard typeahead navigation', async ({ page }) => {
    // Verify search page loaded
    await page.goto('/');
    await expect(
      page.getByRole('heading', { name: 'Find Geospatial Data' }),
    ).toBeVisible();
    await expect(
      page.getByRole('combobox', { name: 'Search geospatial data...' }),
    ).toHaveCount(1);

    // Navigate with query param to bypass hero→sticky transition race condition.
    // This puts us directly in browse mode with a single SearchBar.
    await page.goto('/?q=Zoning');
    const searchInput = page.getByRole('combobox', { name: 'Search geospatial data...' });

    // Focus and re-fill to trigger typeahead (onFocus + onChange open the dropdown)
    await searchInput.click();
    await searchInput.fill('Zoning');
    await expect(page.getByRole('option', { name: /Composite Zoning 2024/ })).toBeVisible({
      timeout: 15_000,
    });
    await searchInput.press('ArrowDown');
    await searchInput.press('Enter');

    // Verify dataset detail page
    await expect(page).toHaveURL(/\/datasets\//);
    await expect(
      page.getByRole('heading', { name: /Composite Zoning 2024/ }),
    ).toBeVisible();
  });

  test('result cards stay readable on mobile widths', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto('/?q=Zoning');

    const card = page.getByTestId('search-result-card').first();
    await expect(card).toBeVisible();
    await expect(card.getByText('Composite Zoning 2024')).toBeVisible();
    await expect(card.getByTestId('dataset-card-specs')).toContainText('EPSG:4326');
    await expect(card.getByTestId('dataset-card-source')).toContainText('Neglia Engineering Associates');

    const overflow = await card.evaluate((element) => ({
      clientWidth: element.clientWidth,
      scrollWidth: element.scrollWidth,
    }));

    expect(overflow.scrollWidth).toBeLessThanOrEqual(overflow.clientWidth + 1);
  });
});
