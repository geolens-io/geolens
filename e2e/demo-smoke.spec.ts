import { expect, test, type Page, type TestInfo } from '@playwright/test';

const SHOWCASE_MAP_NAMES = [
  'Restless Earth',
  'The Matterhorn in 3D',
  'Manhattan - A Century of Skyline',
  'Hurricane Alley - Major Atlantic Storms Since 1950',
  'Hurricane Exposure - Which Coasts the Major Storms Reach',
  'Everything That Fell From the Sky',
  'New York From Orbit - Sentinel-2',
] as const;

const CLOUDFLARE_BEACON =
  /^https:\/\/static\.cloudflareinsights\.com\/beacon\.min\.js(?:\/|$)/;
const ABORTED_REQUEST = /(?:ERR_ABORTED|NS_BINDING_ABORTED|cancelled)/i;
const ALLOW_LEGACY_READINESS = process.env.E2E_DEMO_LEGACY_READINESS === '1';

type BrowserDiagnostics = {
  assertClean: () => void;
  successfulDataRequests: string[];
};

function isMapDataRequest(url: string): boolean {
  const path = new URL(url).pathname;
  return (
    /^\/api\/tiles\/.+\.pbf$/.test(path) ||
    /^\/raster-tiles\//.test(path) ||
    /^\/api\/datasets\/[^/]+\/features\.geojson$/.test(path)
  );
}

function observeBrowser(page: Page): BrowserDiagnostics {
  const errors: string[] = [];
  const successfulDataRequests: string[] = [];

  page.on('pageerror', (error) => errors.push(`page error: ${error.message}`));
  page.on('console', (message) => {
    if (message.type() !== 'error') return;
    if (CLOUDFLARE_BEACON.test(message.location().url)) return;
    errors.push(`console error: ${message.text()}`);
  });
  page.on('response', (response) => {
    const url = response.url();
    if (response.status() >= 400 && !CLOUDFLARE_BEACON.test(url)) {
      errors.push(`HTTP ${response.status()}: ${url}`);
    }
  });
  page.on('requestfinished', async (request) => {
    if (!isMapDataRequest(request.url())) return;
    const response = await request.response();
    if (response?.ok()) successfulDataRequests.push(request.url());
  });
  page.on('requestfailed', (request) => {
    const url = request.url();
    const reason = request.failure()?.errorText ?? 'unknown failure';
    if (CLOUDFLARE_BEACON.test(url)) return;
    if (ABORTED_REQUEST.test(reason)) return;
    errors.push(`request failed (${reason}): ${url}`);
  });

  return {
    assertClean: () => expect(errors, errors.join('\n')).toEqual([]),
    successfulDataRequests,
  };
}

async function attachScreenshot(page: Page, testInfo: TestInfo, name: string) {
  const path = testInfo.outputPath(name);
  await page.screenshot({ fullPage: true, path });
  await testInfo.attach(name, {
    path,
    contentType: 'image/png',
  });
}

test.describe('live demo read-only smoke', () => {
  test('cold anonymous root remains the searchable catalog', async ({ page, request }, testInfo) => {
    const diagnostics = observeBrowser(page);

    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page).toHaveURL(/\/$/);
    await expect(page.getByRole('combobox', { name: 'Search the catalog...' })).toBeVisible();
    await expect(page.getByRole('region', { name: 'Search results' })).toBeVisible();
    await expect(page.getByTestId('search-result-card').first()).toBeVisible();

    const [authConfigResponse, healthResponse] = await Promise.all([
      request.get('/api/auth/config/'),
      request.get('/api/health'),
    ]);
    expect(authConfigResponse.ok(), `auth config returned HTTP ${authConfigResponse.status()}`).toBeTruthy();
    expect(healthResponse.ok(), `health returned HTTP ${healthResponse.status()}`).toBeTruthy();

    const authConfig = await authConfigResponse.json();
    expect(authConfig.landing_first).toBe(false);

    const health = await healthResponse.json();
    expect(health.status).toBe('healthy');
    if (process.env.E2E_EXPECT_VERSION) {
      expect(health.version).toBe(process.env.E2E_EXPECT_VERSION);
    }

    await attachScreenshot(page, testInfo, 'anonymous-catalog.png');
    diagnostics.assertClean();
  });

  test('catalog discovery, collections, and SSO entry points remain usable', async ({ page }) => {
    const diagnostics = observeBrowser(page);

    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const search = page.getByRole('combobox', { name: 'Search the catalog...' });
    await search.fill('earthquake');
    const earthquake = page
      .getByTestId('search-result-card')
      .filter({ hasText: 'Recent Earthquakes (M2.5+, last 30 days)' })
      .first();
    await expect(earthquake).toBeVisible();
    await earthquake.click();
    await expect(page).toHaveURL(/\/datasets\/[0-9a-f-]+$/);
    await expect(page.getByRole('heading', { name: 'Recent Earthquakes (M2.5+, last 30 days)' })).toBeVisible();

    await page.goto('/collections', { waitUntil: 'domcontentloaded' });
    await expect(page.getByRole('link', { name: 'Human World' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Restless Planet' })).toBeVisible();
    await page.getByRole('link', { name: 'Human World' }).click();
    await expect(page).toHaveURL(/\/collections\/[0-9a-f-]+$/);
    await expect(page.getByRole('heading', { name: 'Human World' })).toBeVisible();
    await expect(page.locator('a[href^="/datasets/"]').first()).toBeVisible();

    await page.goto('/login', { waitUntil: 'domcontentloaded' });
    await expect(page.getByRole('button', { name: 'Sign in with GitHub' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Sign in with Google' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Sign in with Microsoft' })).toBeVisible();
    await expect(page.getByText('Need access? Contact a GeoLens administrator.')).toBeVisible();
    await expect(page.locator('a[href*="register"]')).toHaveCount(0);

    diagnostics.assertClean();
  });

  test('seeded standards catalogs return public data', async ({ request }) => {
    const endpoints = ['/api/', '/api/conformance', '/api/stac/'];

    for (const endpoint of endpoints) {
      const response = await request.get(endpoint);
      expect(response.ok(), `${endpoint} returned HTTP ${response.status()}`).toBeTruthy();
      expect((await response.body()).length, `${endpoint} returned an empty body`).toBeGreaterThan(0);
    }

    const catalogs = [
      ['/api/collections', 'collections'],
      ['/api/stac/collections', 'collections'],
      ['/api/datasets/dcat/', 'dcat:dataset'],
      ['/api/datasets/dcat-us/3.0/', 'dataset'],
      ['/api/datasets/geodcat-ap/', 'dcat:dataset'],
    ] as const;

    for (const [endpoint, entriesKey] of catalogs) {
      const response = await request.get(endpoint);
      expect(response.ok(), `${endpoint} returned HTTP ${response.status()}`).toBeTruthy();
      const body = await response.json();
      expect(Array.isArray(body[entriesKey]), `${endpoint} omitted ${entriesKey}`).toBe(true);
      expect(body[entriesKey].length, `${endpoint} returned no public entries`).toBeGreaterThan(0);
    }
  });

  test('anonymous catalog and sign-in surfaces fit a mobile viewport', async ({ page }) => {
    const diagnostics = observeBrowser(page);
    await page.setViewportSize({ width: 390, height: 844 });

    const routes = [
      { path: '/', loaded: () => page.getByTestId('search-result-card').first() },
      { path: '/maps', loaded: () => page.getByRole('link', { name: SHOWCASE_MAP_NAMES[0], exact: true }) },
      { path: '/collections', loaded: () => page.getByRole('link', { name: 'Human World' }) },
      { path: '/login', loaded: () => page.getByRole('button', { name: 'Sign in with GitHub' }) },
    ];

    for (const { path, loaded } of routes) {
      await page.goto(path, { waitUntil: 'domcontentloaded' });
      await expect(loaded()).toBeVisible();
      await expect
        .poll(() => page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth), {
          message: `${path} overflows the mobile viewport`,
        })
        .toBeLessThanOrEqual(1);
    }

    diagnostics.assertClean();
  });

  for (const name of SHOWCASE_MAP_NAMES) {
    test(`catalog opens a data-ready map: ${name}`, async ({ page }, testInfo) => {
      const diagnostics = observeBrowser(page);

      await page.goto('/maps', { waitUntil: 'domcontentloaded' });
      const search = page.getByRole('textbox', { name: 'Search maps...' });
      await expect(search).toBeVisible();
      await search.fill(name);

      const mapLink = page.getByRole('link', { name, exact: true });
      await expect(mapLink).toBeVisible();
      await mapLink.click();
      await expect(page).toHaveURL(/\/maps\/[0-9a-f-]+$/);

      const viewer = page.getByRole('region', { name: 'Map viewer' });
      await expect(viewer).toBeVisible();
      await expect(page.locator('canvas.maplibregl-canvas')).toBeVisible();

      if (ALLOW_LEGACY_READINESS && (await viewer.getAttribute('data-map-ready')) === null) {
        testInfo.annotations.push({
          type: 'legacy readiness',
          description: 'Target lacks data-map-ready; using data-tiles-loaded plus completed data requests',
        });
        await expect(viewer).toHaveAttribute('data-tiles-loaded', 'true', { timeout: 60_000 });
      } else {
        await expect(viewer).toHaveAttribute('data-map-ready', 'true', { timeout: 60_000 });
      }
      if (name === 'The Matterhorn in 3D') {
        await expect(viewer).toHaveAttribute('data-terrain-ready', 'true', { timeout: 60_000 });
      }

      await expect
        .poll(() => diagnostics.successfulDataRequests.length, {
          message: `${name} reached the viewer without completing a dataset feature or tile request`,
          timeout: 60_000,
        })
        .toBeGreaterThan(0);
      await expect(page.locator('[data-sonner-toast][data-type="error"]')).toHaveCount(0);

      await attachScreenshot(
        page,
        testInfo,
        `${name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')}.png`,
      );
      diagnostics.assertClean();
    });
  }
});
