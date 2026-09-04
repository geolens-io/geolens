import { test, expect, type Page, type Route } from '@playwright/test';
import { getAuthToken, getSearchSeed, type SearchSeed } from './helpers/catalog';

const BASE_URL = process.env.E2E_BASE_URL ?? 'http://localhost:8080';

/**
 * Refresh-door inline credential prompt (#1755 item 4, service-auth plan
 * section 3.7). Covers the 422 `service_token_required` refusal from
 * `POST /datasets/{id}/refresh`: the dialog must stay open and reveal a
 * credential prompt keyed to the token field, with different copy for an
 * ArcGIS origin (full sign-in taxonomy) than for a WFS/OGC API Features
 * origin (bearer token only, refused-outright copy).
 *
 * Everything network-side is mocked with `page.route`:
 *   - `GET /api/datasets/{id}` is rewritten to report whichever service
 *     `source_format` the test needs, on top of a real dataset's full
 *     payload (so every other field the page renders stays valid).
 *   - `POST /api/datasets/{id}/refresh` is fulfilled with the 422 this
 *     lane's frontend change reacts to; lane A1's sign-in endpoint has not
 *     merged yet, and the 422 itself does not depend on any dataset's real
 *     `auth_required` marker, so nothing here needs the live backend to
 *     agree the dataset is protected.
 *   - `POST /api/services/arcgis/signin/` is fulfilled per lane A1's
 *     contract (plan 3.2), which this lane builds against and mocks rather
 *     than calling for real.
 *
 * Navigation to the dataset goes through the search typeahead (client-side
 * routing), not a direct `page.goto('/datasets/{id}')` — a hard `goto` of a
 * protected route drops the session under the worktree Vite recipe used to
 * exercise this lane (`AGENTS.md`, "Working from a git worktree").
 */

const RAW_SERVICE_TOKEN_MESSAGE =
  "This dataset's source needed a service token the last time it was imported or refreshed, and this request carries none. Send the token again in the request body's `token` field; tokens are request-only and are never stored between runs. If the source is public now, re-import it through the re-upload dialog without a token to clear the requirement.";

// codex #1759 round 3: ArcgisCredentialBlock now schedules a clear for
// `expires_at` minus a 30s safety margin (round 2), so a mocked `expires_at`
// fixed to a literal date goes stale the moment that date is in the past --
// the credential clears itself right after sign-in and the spec can never
// observe "Signed in". Derived from the run's own clock instead, mirroring
// the `FAR_FUTURE_EXPIRY` fix applied to the vitest suite for the same
// reason.
const FAR_FUTURE_EXPIRY = new Date(Date.now() + 60 * 60 * 1000).toISOString();

let seed: SearchSeed;
let baseDataset: Record<string, unknown>;

test.beforeAll(async () => {
  seed = await getSearchSeed();
  // Node-side fetch with the bearer token pulled from the saved storage
  // state, matching `helpers/catalog.ts` and `dataset-detail.spec.ts` — the
  // auth token lives in localStorage, not a cookie, so the Playwright
  // `request` fixture (cookie-based) can't carry it.
  const res = await fetch(`${BASE_URL}/api/datasets/${seed.id}`, {
    headers: { Authorization: `Bearer ${getAuthToken()}` },
  });
  expect(res.ok).toBe(true);
  baseDataset = await res.json();
});

function mockDataset(page: Page, sourceFormat: 'wfs' | 'arcgis_featureserver') {
  return page.route(`**/api/datasets/${seed.id}`, (route: Route) => {
    if (route.request().method() !== 'GET') return route.continue();
    return route.fulfill({
      json: {
        ...baseDataset,
        source_format: sourceFormat,
        origin: 'service',
      },
    });
  });
}

/** Always answers the 422 this lane's frontend change reacts to. */
function mockRefreshRefused(page: Page) {
  return page.route(`**/api/datasets/${seed.id}/refresh`, (route: Route) => {
    if (route.request().method() !== 'POST') return route.continue();
    return route.fulfill({
      status: 422,
      json: {
        detail: { code: 'service_token_required', message: RAW_SERVICE_TOKEN_MESSAGE },
      },
    });
  });
}

async function openRefreshDialogAndSubmit(page: Page) {
  await page.goto('/');
  await page.waitForLoadState('networkidle');

  // SPA-navigate to the dataset via the search typeahead, not a hard goto —
  // see the file-level comment.
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

test.describe('Refresh-door credential prompt on service_token_required', () => {
  test('WFS origin: dialog stays open, shows the outright-refusal copy, never the raw response text', async ({
    page,
  }) => {
    await mockDataset(page, 'wfs');
    await mockRefreshRefused(page);

    await openRefreshDialogAndSubmit(page);

    await expect(
      page.getByText(
        'This source refused the refresh outright because it needs a credential. Send it again below.',
      ),
    ).toBeVisible();
    await expect(
      page.getByText(
        'If the source is public now, re-import it through the Re-Upload dialog with no credential to clear this requirement.',
      ),
    ).toBeVisible();
    await expect(page.getByRole('dialog')).toBeVisible();
    await expect(page.getByLabel('Authentication method')).toHaveCount(0);
    await expect(page.locator('body')).not.toContainText(RAW_SERVICE_TOKEN_MESSAGE);
  });

  // feat(#1746 B4): the WFS/OGC API Features credential prompt is the
  // four-way `ServiceCredentialBlock` select (none/bearer/basic/header), in
  // place of the bearer-only field this door offered before B2b (#1770,
  // merged to main before this lane started).
  test('WFS origin: a Basic-auth retry sends the structured auth object, not the deprecated token field', async ({
    page,
  }) => {
    await mockDataset(page, 'wfs');

    let refreshCalls = 0;
    let secondCallBody: unknown;
    await page.route(`**/api/datasets/${seed.id}/refresh`, async (route: Route) => {
      if (route.request().method() !== 'POST') return route.continue();
      refreshCalls += 1;
      if (refreshCalls === 1) {
        return route.fulfill({
          status: 422,
          json: {
            detail: { code: 'service_token_required', message: RAW_SERVICE_TOKEN_MESSAGE },
          },
        });
      }
      secondCallBody = route.request().postDataJSON();
      return route.fulfill({
        json: {
          run_id: 'e2e-run-2',
          job_id: 'e2e-job-2',
          dataset_id: seed.id,
          origin_kind: 'service',
          trigger: 'api',
          status: 'pending',
          message: 'Refresh queued from the stored source',
        },
      });
    });

    await openRefreshDialogAndSubmit(page);

    await page.getByLabel('Authentication', { exact: true }).selectOption('basic');
    await page.getByLabel('Username', { exact: true }).fill('e2e-user');
    await page.getByLabel('Password', { exact: true }).fill('e2e-password');
    await page.getByRole('button', { name: 'Start refresh' }).click();

    await expect(page.getByRole('dialog')).toHaveCount(0);
    expect(refreshCalls).toBe(2);
    expect(secondCallBody).toMatchObject({
      auth: { method: 'basic', username: 'e2e-user', password: 'e2e-password' },
    });
    expect((secondCallBody as { token?: unknown }).token).toBeFalsy();
  });

  test('ArcGIS origin: dialog stays open and offers the sign-in taxonomy, distinct from the WFS copy', async ({
    page,
  }) => {
    await mockDataset(page, 'arcgis_featureserver');
    await mockRefreshRefused(page);

    await openRefreshDialogAndSubmit(page);

    await expect(page.getByLabel('Authentication method')).toBeVisible();
    await expect(page.getByRole('dialog')).toBeVisible();
    await expect(page.getByText(/refused the refresh outright/i)).toHaveCount(0);
    await expect(page.locator('body')).not.toContainText(RAW_SERVICE_TOKEN_MESSAGE);
  });

  test('ArcGIS sign-in mints a token and the retry sends it in the refresh body', async ({ page }) => {
    await mockDataset(page, 'arcgis_featureserver');

    await page.route(`**/api/services/arcgis/signin/`, (route: Route) =>
      route.fulfill({
        json: { token: 'minted-e2e-token', expires_at: FAR_FUTURE_EXPIRY },
      }),
    );

    let refreshCalls = 0;
    let secondCallBody: unknown;
    await page.route(`**/api/datasets/${seed.id}/refresh`, async (route: Route) => {
      if (route.request().method() !== 'POST') return route.continue();
      refreshCalls += 1;
      if (refreshCalls === 1) {
        return route.fulfill({
          status: 422,
          json: {
            detail: { code: 'service_token_required', message: RAW_SERVICE_TOKEN_MESSAGE },
          },
        });
      }
      secondCallBody = route.request().postDataJSON();
      return route.fulfill({
        json: {
          run_id: 'e2e-run-1',
          job_id: 'e2e-job-1',
          dataset_id: seed.id,
          origin_kind: 'service',
          trigger: 'api',
          status: 'pending',
          message: 'Refresh queued from the stored source',
        },
      });
    });

    await openRefreshDialogAndSubmit(page);

    await page.getByLabel('Authentication method').selectOption('signin');
    await page.getByLabel('Portal URL').fill('https://myorg.maps.arcgis.com');
    await page.getByLabel('Username').fill('alice');
    await page.getByLabel('Password').fill('hunter2');
    await page.getByRole('button', { name: 'Sign in' }).click();

    await expect(page.getByText('Signed in. The refresh will use this token.')).toBeVisible();
    await expect(page.getByLabel('Password')).toHaveValue('');

    await page.getByRole('button', { name: 'Start refresh' }).click();

    await expect(page.getByRole('dialog')).toHaveCount(0);
    expect(refreshCalls).toBe(2);
    expect((secondCallBody as { token?: string } | undefined)?.token).toBe('minted-e2e-token');
  });
});
