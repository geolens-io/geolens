import { test, expect, type Page } from '@playwright/test';

/**
 * Lane B4 (service-auth wave): the four-way credential method select for a
 * non-ArcGIS-shaped service URL (WFS, OGC API Features) on the import
 * wizard's Service URL tab. Backend B2b (#1770, merged to main before this
 * lane started) is what makes Basic and header-key methods actually reach
 * the service; the probe/preview endpoints are mocked here with page.route,
 * so this spec never touches a real WFS server, but does exercise the real
 * `auth` object the frontend now builds and sends.
 *
 * Opens the panel the way the other import-adjacent specs do (the Create
 * menu, not a hard page.goto to a protected route): a hard goto on the
 * worktree Vite recipe (:5174) logs the session out mid-test.
 */

const WFS_URL = 'https://example.test/wfs';
const SERVICE_URL_PLACEHOLDER =
  'https://example.com/wfs, ArcGIS FeatureServer, or OGC API endpoint';

async function openServiceTab(page: Page) {
  await page.goto('/');
  await page.getByRole('button', { name: 'Create' }).click();
  await page.getByRole('menuitem', { name: 'Import Data' }).click();
  await page.getByRole('button', { name: 'Service URL' }).click();
  await page.getByPlaceholder(SERVICE_URL_PLACEHOLDER).fill(WFS_URL);
}

const PROBE_RESPONSE = {
  service_type: 'WFS 2.0',
  url: WFS_URL,
  selected_layer_id: null,
  layers: [
    {
      name: 'roads',
      title: 'Roads',
      geometry_type: 'LineString',
      feature_count: 12,
      layer_type: 'layer',
      layer_id: null,
      object_id_field: null,
      kind: 'vector',
    },
  ],
};

const PREVIEW_RESPONSE = {
  job_id: '11111111-1111-1111-1111-111111111111',
  source_filename: null,
  columns: [{ name: 'id', type: 'Integer' }],
  crs: 4326,
  geometry_type: 'LineString',
  feature_count: 12,
  sample_rows: [],
  layer_name: 'roads',
};

test.describe('Service tab credential method select', () => {
  test('switching method clears the other branch\'s fields', async ({ page }) => {
    await openServiceTab(page);

    await page.getByRole('combobox', { name: 'Authentication' }).click();
    await page.getByRole('option', { name: 'API key in a header' }).click();
    await page.getByLabel('Header name').fill('X-API-Key');
    await page.getByLabel('Header value').fill('secret-key-value');

    await page.getByRole('combobox', { name: 'Authentication' }).click();
    await page.getByRole('option', { name: 'Username and password' }).click();
    await expect(page.getByLabel('Header name')).not.toBeVisible();
    await page.getByLabel('Username', { exact: true }).fill('alice');
    await page.getByLabel('Password', { exact: true }).fill('hunter2');

    // Back to header: the username/password typed above must not still be
    // reachable, and the header fields must be blank, not carrying the
    // earlier values across the round trip.
    await page.getByRole('combobox', { name: 'Authentication' }).click();
    await page.getByRole('option', { name: 'API key in a header' }).click();
    await expect(page.getByLabel('Header name')).toHaveValue('');
    await expect(page.getByLabel('Header value')).toHaveValue('');

    await page.getByRole('combobox', { name: 'Authentication' }).click();
    await page.getByRole('option', { name: 'Username and password' }).click();
    await expect(page.getByLabel('Username', { exact: true })).toHaveValue('');
    await expect(page.getByLabel('Password', { exact: true })).toHaveValue('');
  });

  test('a Basic-auth import reaches the preview step', async ({ page }) => {
    let probeBody: unknown;
    await page.route('**/api/services/probe/', (route) => {
      probeBody = route.request().postDataJSON();
      return route.fulfill({ json: PROBE_RESPONSE });
    });
    let previewBody: unknown;
    await page.route('**/api/services/preview/', (route) => {
      previewBody = route.request().postDataJSON();
      return route.fulfill({ json: PREVIEW_RESPONSE });
    });

    await openServiceTab(page);

    await page.getByRole('combobox', { name: 'Authentication' }).click();
    await page.getByRole('option', { name: 'Username and password' }).click();
    await page.getByLabel('Username', { exact: true }).fill('e2e-user');
    await page.getByLabel('Password', { exact: true }).fill('e2e-password');

    await page.getByRole('button', { name: 'Probe →' }).click();
    await expect(page.getByRole('button', { name: /Roads/i })).toBeVisible();

    expect(probeBody).toMatchObject({
      url: WFS_URL,
      auth: { method: 'basic', username: 'e2e-user', password: 'e2e-password' },
    });

    await page.getByRole('button', { name: /Roads/i }).click();

    // Reaches the review step: the metadata form (title field) renders,
    // proving the preview call succeeded with the Basic credential.
    await expect(page.getByRole('button', { name: 'Start Over' })).toBeVisible();

    expect(previewBody).toMatchObject({
      auth: { method: 'basic', username: 'e2e-user', password: 'e2e-password' },
    });
    // Never the deprecated bearer spelling alongside the structured object.
    expect((previewBody as { token?: unknown }).token).toBeFalsy();
  });

  test('a header-key import sends the caller-named header, not a hardcoded one', async ({ page }) => {
    let probeBody: unknown;
    await page.route('**/api/services/probe/', (route) => {
      probeBody = route.request().postDataJSON();
      return route.fulfill({ json: PROBE_RESPONSE });
    });

    await openServiceTab(page);

    await page.getByRole('combobox', { name: 'Authentication' }).click();
    await page.getByRole('option', { name: 'API key in a header' }).click();
    await page.getByLabel('Header name').fill('Ocp-Apim-Subscription-Key');
    await page.getByLabel('Header value').fill('e2e-header-secret');

    await page.getByRole('button', { name: 'Probe →' }).click();
    await expect(page.getByRole('button', { name: /Roads/i })).toBeVisible();

    expect(probeBody).toMatchObject({
      url: WFS_URL,
      auth: {
        method: 'header',
        header_name: 'Ocp-Apim-Subscription-Key',
        header_value: 'e2e-header-secret',
      },
    });
  });
});
