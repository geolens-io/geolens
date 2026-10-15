import { test, expect, type Page, type Route } from './helpers/session';
import { getAuthToken, getSearchSeed, type SearchSeed } from './helpers/catalog';

const BASE_URL = process.env.E2E_BASE_URL ?? 'http://localhost:8080';

const LONG_LABEL =
  'Parks and Recreation production ArcGIS service token with an unreasonably long display name ' +
  'that would push the credential select wider than the dialog panel if it were allowed to';

let seed: SearchSeed;
let baseDataset: Record<string, unknown>;

test.beforeAll(async () => {
  seed = await getSearchSeed();
  const response = await fetch(`${BASE_URL}/api/datasets/${seed.id}`, {
    headers: { Authorization: `Bearer ${getAuthToken()}` },
  });
  expect(response.ok).toBe(true);
  baseDataset = await response.json();
});

async function openSyncDialog(page: Page) {
  const url = 'https://maps.example.test/arcgis/rest/services/Parks/FeatureServer';
  await page.route(`**/api/datasets/${seed.id}`, (route: Route) => route.request().method() !== 'GET'
    ? route.continue()
    : route.fulfill({
      json: {
        ...baseDataset,
        origin: 'service',
        source_format: 'arcgis_featureserver',
        origin_uri: url,
        origin_ref: { kind: 'service', service_type: 'arcgis_featureserver', url, layer_id: '0' },
      },
    }));
  await page.route('**/api/settings/edition/**', (route: Route) => route.fulfill({
    json: { edition: 'enterprise', features: ['scheduled_sync'] },
  }));
  await page.route('**/api/sync/credentials**', (route: Route) => route.fulfill({
    json: {
      items: [{
        id: 'cred-1',
        connector_name: 'arcgis_feature_server',
        allowed_origin: 'https://maps.example.test',
        display_name: LONG_LABEL,
        current_version: 1,
        current_expires_at: null,
        revoked_at: null,
        created_at: '2026-09-19T00:00:00Z',
        updated_at: '2026-09-19T00:00:00Z',
      }],
    },
  }));
  await page.route(`**/api/datasets/${seed.id}/sync`, (route: Route) => route.request().method() === 'GET'
    ? route.fulfill({ status: 404, json: { detail: 'not configured' } })
    : route.continue());

  await page.goto(`/datasets/${seed.id}`);
  await page.getByRole('tab', { name: 'Source' }).click();
  await page.getByRole('button', { name: 'Set up schedule' }).click();
  const dialog = page.getByRole('dialog', { name: 'Set up scheduled sync' });
  await expect(dialog).toBeVisible();
  return dialog;
}

// A 200% browser zoom on a 1280x720 window leaves a 640x360 CSS-pixel viewport.
test.describe('scheduled sync dialog at 200% zoom', () => {
  test.use({ viewport: { width: 640, height: 360 }, deviceScaleFactor: 2 });

  test('keeps a long credential label inside the panel', async ({ page }) => {
    const dialog = await openSyncDialog(page);
    await dialog.getByRole('combobox', { name: 'Credential' }).click();
    await page.getByRole('option', { name: LONG_LABEL }).click();

    const trigger = dialog.getByRole('combobox', { name: 'Credential' });
    await expect(trigger).toContainText('Parks and Recreation');
    const panel = await dialog.boundingBox();
    const control = await trigger.boundingBox();
    expect(panel).not.toBeNull();
    expect(control).not.toBeNull();
    expect(control!.x + control!.width).toBeLessThanOrEqual(panel!.x + panel!.width);
    const overflow = await dialog.evaluate((el) => el.scrollWidth - el.clientWidth);
    expect(overflow).toBeLessThanOrEqual(0);
  });

  test('scrolls the dialog body instead of growing past the viewport', async ({ page }) => {
    const dialog = await openSyncDialog(page);

    const box = await dialog.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.y).toBeGreaterThanOrEqual(0);
    expect(box!.y + box!.height).toBeLessThanOrEqual(360);
    const scrolls = await dialog.evaluate((el) => el.scrollHeight > el.clientHeight);
    expect(scrolls).toBe(true);

    const submit = dialog.getByRole('button', { name: 'Create draft' });
    await submit.scrollIntoViewIfNeeded();
    await expect(submit).toBeInViewport();
  });
});
