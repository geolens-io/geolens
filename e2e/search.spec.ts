import { test, expect } from '@playwright/test';

test.describe('Search Flow', () => {
  test('landing page hands off to the search workspace and keeps the spatial dialog lazy', async ({ page }) => {
    await page.goto('/');
    await expect(
      page.getByRole('heading', { name: /your team's spatial data, searchable in one place/i }),
    ).toBeVisible();

    await expect(
      page.getByRole('dialog', { name: 'Search area' }),
    ).toHaveCount(0);

    await page.getByRole('button', { name: 'Explore catalog' }).click();
    await expect(page).toHaveURL(/\/search$/);
    await expect(
      page.getByRole('combobox', { name: 'Search geospatial data...' }),
    ).toBeVisible();
    await expect(
      page.getByRole('button', { name: 'Keywords' }),
    ).toBeVisible();
  });

  test('legacy root query URLs redirect into the search workspace', async ({ page }) => {
    await page.goto('/?q=Zoning');
    await expect(page).toHaveURL(/\/search\?q=Zoning/);
    await expect(
      page.getByRole('combobox', { name: 'Search geospatial data...' }),
    ).toBeVisible();
  });

  test('tablet browse keeps the desktop filter tray and spatial sheet semantics', async ({ page }) => {
    await page.setViewportSize({ width: 1024, height: 900 });
    await page.goto('/search?q=Zoning');

    await expect(
      page.getByRole('button', { name: 'Keywords' }),
    ).toBeVisible();
    await expect(page.getByRole('button', { name: 'Filters' })).toHaveCount(0);

    await page.getByRole('button', { name: 'Location' }).click();
    const spatialDialog = page.getByRole('dialog', { name: 'Search area' });
    await expect(spatialDialog).toBeVisible();
    await expect(
      spatialDialog.getByText('Draw a rectangle or polygon to limit search results to a specific area.'),
    ).toBeVisible();

    await spatialDialog.getByRole('button', { name: 'Close' }).click();
    await expect(spatialDialog).toHaveCount(0);
  });

  test('prefix search supports keyboard typeahead navigation', async ({ page }) => {
    await page.goto('/search?q=Zoning');
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
    await page.goto('/search?q=Zoning');

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
