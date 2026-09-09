import { test, expect, type Page, type Route } from '@playwright/test';
import { getAuthToken, getSearchSeed, type SearchSeed } from './helpers/catalog';

const BASE_URL = process.env.E2E_BASE_URL ?? 'http://localhost:8080';

/**
 * Request-only authentication for STAC sources (feat(#1764)), from the two
 * places a person types the credential: the import wizard's STAC tab and a
 * STAC dataset's refresh dialog.
 *
 * Everything network-side is mocked with `page.route`, so nothing here needs
 * a live protected catalog: `POST /api/services/stac/{connect,collections}`
 * are fulfilled with a landing page and one collection, and the refresh door
 * answers 422 `service_token_required` the way a marked STAC origin does.
 *
 * Navigation to the dataset goes through the search typeahead, not a direct
 * `page.goto('/datasets/{id}')` — a hard goto of a protected route drops the
 * session under the worktree Vite recipe (`AGENTS.md`).
 */

const SERVICE_TOKEN_MESSAGE =
  "This dataset's source needed a credential the last time it was imported or refreshed, and this request carries none.";

const STAC_ESCAPE_HATCH =
  'If the catalog is public now, import the item again from the STAC catalog with no credential to clear this requirement.';

let seed: SearchSeed;
let baseDataset: Record<string, unknown>;

test.beforeAll(async () => {
  seed = await getSearchSeed();
  const res = await fetch(`${BASE_URL}/api/datasets/${seed.id}`, {
    headers: { Authorization: `Bearer ${getAuthToken()}` },
  });
  expect(res.ok).toBe(true);
  baseDataset = await res.json();
});

test.describe('STAC import wizard credential block', () => {
  test('a header-key credential reaches connect and collections as one auth object', async ({
    page,
  }) => {
    const connectBodies: unknown[] = [];
    const collectionBodies: unknown[] = [];

    await page.route('**/api/services/stac/connect', (route: Route) => {
      connectBodies.push(route.request().postDataJSON());
      return route.fulfill({
        json: {
          url: 'https://catalog.example/v1',
          catalog_id: 'e2e',
          title: 'E2E Catalog',
          description: '',
          stac_version: '1.0.0',
        },
      });
    });
    await page.route('**/api/services/stac/collections', (route: Route) => {
      collectionBodies.push(route.request().postDataJSON());
      return route.fulfill({
        json: { url: 'https://catalog.example/v1', collections: [] },
      });
    });

    await page.goto('/import');
    await page.getByRole('button', { name: 'STAC Catalog' }).click();

    await expect(page.getByTestId('stac-credential-block')).toBeVisible();
    await page
      .getByPlaceholder('https://earth-search.aws.element84.com/v1')
      .fill('https://catalog.example/v1');

    // Radix Select: open by its accessible name, then pick the option.
    await page.getByRole('combobox', { name: 'Authentication' }).click();
    await page.getByRole('option', { name: 'API key in a header' }).click();
    await page.getByLabel('Header name').fill('Ocp-Apim-Subscription-Key');
    await page.getByLabel('Header value').fill('e2e-catalog-key');

    await page.getByRole('button', { name: 'Connect' }).click();

    await expect.poll(() => connectBodies.length).toBeGreaterThan(0);
    const expected = {
      auth: {
        method: 'header',
        header_name: 'Ocp-Apim-Subscription-Key',
        header_value: 'e2e-catalog-key',
      },
    };
    expect(connectBodies[0]).toMatchObject(expected);
    expect(collectionBodies[0]).toMatchObject(expected);
    // The deprecated flat field is not sent alongside the auth object; the
    // door refuses a body that describes its credential twice.
    expect((connectBodies[0] as { token?: unknown }).token).toBeUndefined();
  });

  test('no credential is sent when the method is left at none', async ({ page }) => {
    const connectBodies: unknown[] = [];
    await page.route('**/api/services/stac/connect', (route: Route) => {
      connectBodies.push(route.request().postDataJSON());
      return route.fulfill({
        json: {
          url: 'https://catalog.example/v1',
          catalog_id: 'e2e',
          title: 'E2E Catalog',
          description: '',
          stac_version: '1.0.0',
        },
      });
    });
    await page.route('**/api/services/stac/collections', (route: Route) =>
      route.fulfill({ json: { url: 'https://catalog.example/v1', collections: [] } }),
    );

    await page.goto('/import');
    await page.getByRole('button', { name: 'STAC Catalog' }).click();
    await page
      .getByPlaceholder('https://earth-search.aws.element84.com/v1')
      .fill('https://catalog.example/v1');
    await page.getByRole('button', { name: 'Connect' }).click();

    await expect.poll(() => connectBodies.length).toBeGreaterThan(0);
    expect((connectBodies[0] as { auth?: unknown }).auth).toBeUndefined();
  });
});

function mockStacDataset(page: Page) {
  return page.route(`**/api/datasets/${seed.id}`, (route: Route) => {
    if (route.request().method() !== 'GET') return route.continue();
    return route.fulfill({
      json: { ...baseDataset, source_format: 'stac', origin: 'stac' },
    });
  });
}

async function openRefreshDialogAndSubmit(page: Page) {
  await page.goto('/');
  await page.waitForLoadState('networkidle');

  const searchInput = page.getByRole('combobox', { name: 'Search the catalog...' });
  await searchInput.click();
  await searchInput.fill(seed.query);
  await expect(page.getByRole('option', { name: seed.title, exact: true })).toBeVisible({
    timeout: 15_000,
  });
  await searchInput.press('ArrowDown');
  await searchInput.press('Enter');
  await expect(page).toHaveURL(new RegExp(`/datasets/${seed.id}$`));

  await page.getByRole('tab', { name: 'Source' }).click();
  await page.getByRole('button', { name: 'Refresh from source' }).click();
  await page.getByRole('button', { name: 'Start refresh' }).click();
}

test.describe('STAC refresh dialog credential prompt', () => {
  test('a marked STAC origin shows its own escape hatch and never the raw response text', async ({
    page,
  }) => {
    await mockStacDataset(page);
    await page.route(`**/api/datasets/${seed.id}/refresh`, (route: Route) => {
      if (route.request().method() !== 'POST') return route.continue();
      return route.fulfill({
        status: 422,
        json: {
          detail: { code: 'service_token_required', message: SERVICE_TOKEN_MESSAGE },
        },
      });
    });

    await openRefreshDialogAndSubmit(page);

    await expect(page.getByRole('dialog')).toBeVisible();
    await expect(page.getByText(STAC_ESCAPE_HATCH)).toBeVisible();
    // The re-upload dialog is the WFS escape hatch and does not exist for a
    // STAC dataset, so its copy must not be what the reader is shown.
    await expect(page.getByText(/Re-Upload dialog/i)).toHaveCount(0);
    await expect(page.locator('body')).not.toContainText(SERVICE_TOKEN_MESSAGE);
  });

  test('a bearer retry sends the structured auth object', async ({ page }) => {
    await mockStacDataset(page);

    let refreshCalls = 0;
    let secondCallBody: unknown;
    await page.route(`**/api/datasets/${seed.id}/refresh`, async (route: Route) => {
      if (route.request().method() !== 'POST') return route.continue();
      refreshCalls += 1;
      if (refreshCalls === 1) {
        return route.fulfill({
          status: 422,
          json: {
            detail: { code: 'service_token_required', message: SERVICE_TOKEN_MESSAGE },
          },
        });
      }
      secondCallBody = route.request().postDataJSON();
      return route.fulfill({
        json: {
          run_id: 'e2e-stac-run',
          job_id: 'e2e-stac-job',
          dataset_id: seed.id,
          origin_kind: 'stac',
          trigger: 'api',
          status: 'pending',
          message: 'Refresh queued from the stored STAC item',
        },
      });
    });

    await openRefreshDialogAndSubmit(page);

    await page.getByLabel('Authentication', { exact: true }).selectOption('bearer');
    await page.getByLabel('Bearer token', { exact: true }).fill('e2e-stac-token');
    await page.getByRole('button', { name: 'Start refresh' }).click();

    await expect(page.getByRole('dialog')).toHaveCount(0);
    expect(refreshCalls).toBe(2);
    expect(secondCallBody).toMatchObject({
      auth: { method: 'bearer', token: 'e2e-stac-token' },
    });
    expect((secondCallBody as { token?: unknown }).token).toBeFalsy();
  });
});
