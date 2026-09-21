import { test, expect, type Page, type Route } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { getAuthToken, getSearchSeed, type SearchSeed } from './helpers/catalog';

const BASE_URL = process.env.E2E_BASE_URL ?? 'http://localhost:8080';

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

async function openSources(page: Page) {
  await page.goto(`/datasets/${seed.id}`);
  await page.getByRole('tab', { name: 'Source' }).click();
}

function sourceDataset() {
  return {
    ...baseDataset,
    origin: 'service',
    source_format: 'arcgis_featureserver',
    origin_uri: 'https://maps.example.test/arcgis/rest/services/Parks/FeatureServer',
    origin_ref: {
      kind: 'service', service_type: 'arcgis_featureserver',
      url: 'https://maps.example.test/arcgis/rest/services/Parks/FeatureServer', layer_id: '0',
    },
  };
}

async function routeDataset(page: Page) {
  await page.route(`**/api/datasets/${seed.id}`, (route: Route) => {
    if (route.request().method() !== 'GET') return route.continue();
    return route.fulfill({ json: sourceDataset() });
  });
  await page.route('**/api/settings/edition/**', (route: Route) => route.fulfill({
    json: { edition: 'enterprise', features: ['scheduled_sync'] },
  }));
  await page.route('**/api/sync/credentials**', (route: Route) => route.fulfill({ json: { items: [] } }));
}

test.describe('scheduled dataset sync', () => {
  test('creates a draft, verifies it, explicitly enables it, and detaches it', async ({ page }) => {
    await routeDataset(page);
    let automation: Record<string, unknown> | null = null;
    let verified = false;

    await page.route(`**/api/datasets/${seed.id}/sync`, async (route: Route) => {
      const request = route.request();
      if (request.method() === 'GET') return route.fulfill(automation ? { json: automation } : { status: 404, json: { detail: 'not configured' } });
      if (request.method() === 'POST') {
        expect(request.postDataJSON()).toMatchObject({
          source: { connector: 'arcgis_feature_server', layer_id: 0 }, cadence: { kind: 'daily', hour: 2, minute: 0 },
        });
        automation = {
          id: 'sync-1', dataset_id: seed.id, revision: 1, status: 'draft', pause_reason: null,
          source: { connector: 'arcgis_feature_server', service_url: 'https://maps.example.test/arcgis/rest/services/Parks/FeatureServer', layer_id: 0 }, credential: null,
          cadence: { kind: 'daily', hour: 2, minute: 0 }, next_due_at: null,
          eligibility: { eligible: false, reasons: ['qualifying_run_required'], policy_version: 'arcgis_id_set_v1' }, last_occurrence: null,
          created_at: '2026-09-19T00:00:00Z', updated_at: '2026-09-19T00:00:00Z',
        };
        return route.fulfill({ status: 201, json: automation });
      }
      if (request.method() === 'DELETE') {
        automation = null;
        return route.fulfill({ status: 204 });
      }
      return route.continue();
    });
    await page.route(`**/api/datasets/${seed.id}/sync/run`, (route: Route) => {
      expect(route.request().headers()['idempotency-key']).toBeTruthy();
      expect(route.request().postDataJSON()).toEqual({ revision: 1 });
      verified = true;
      automation = { ...automation!, eligibility: { eligible: true, reasons: [], policy_version: 'arcgis_id_set_v1' } };
      return route.fulfill({ status: 202, json: { occurrence_id: 'occ-1', run_id: 'run-1', job_id: 'job-1', state: 'planned' } });
    });
    await page.route(`**/api/datasets/${seed.id}/sync/resume`, (route: Route) => {
      expect(verified).toBe(true);
      automation = { ...automation!, status: 'enabled', next_due_at: '2026-09-20T02:00:00Z' };
      return route.fulfill({ json: automation });
    });

    await openSources(page);
    await page.getByRole('button', { name: 'Set up schedule' }).click();
    await expect(page.getByRole('dialog', { name: 'Set up scheduled sync' })).toBeVisible();
    await page.getByRole('button', { name: 'Create draft' }).click();
    await expect(page.getByRole('button', { name: 'Run verification' })).toBeVisible();
    await page.getByRole('button', { name: 'Run verification' }).click();
    await expect(page.getByRole('button', { name: 'Enable schedule' })).toBeVisible();
    await page.getByRole('button', { name: 'Enable schedule' }).click();
    await page.getByRole('alertdialog', { name: 'Enable scheduled sync?' }).getByRole('button', { name: 'Enable schedule' }).click();
    await expect(page.getByText('Enabled', { exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Detach' }).click();
    await page.getByRole('alertdialog').getByRole('button', { name: 'Detach' }).click();
    await expect(page.getByText('No schedule is configured.')).toBeVisible();
  });

  test('keeps paid controls unavailable when the capability is absent', async ({ page }) => {
    await page.route(`**/api/datasets/${seed.id}`, (route: Route) => route.request().method() === 'GET'
      ? route.fulfill({ json: sourceDataset() }) : route.continue());
    await page.route('**/api/settings/edition/**', (route: Route) => route.fulfill({ json: { edition: 'community', features: [] } }));
    await openSources(page);
    await expect(page.getByText(/Enterprise scheduling capability/)).toBeVisible();
    await expect(page.getByRole('button', { name: 'Set up schedule' })).toHaveCount(0);
  });

  test('has no WCAG 2 AA violations in the schedule setup dialog', async ({ page }) => {
    await routeDataset(page);
    await page.route(`**/api/datasets/${seed.id}/sync`, (route: Route) => route.request().method() === 'GET'
      ? route.fulfill({ status: 404, json: { detail: 'not configured' } })
      : route.continue());
    await openSources(page);
    await page.getByRole('button', { name: 'Set up schedule' }).click();
    await expect(page.getByRole('dialog', { name: 'Set up scheduled sync' })).toBeVisible();

    const results = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
      .include('[role="dialog"]')
      .analyze();
    expect(results.violations).toEqual([]);
  });
});
