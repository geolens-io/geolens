import { expect, type APIRequestContext, type Page } from '@playwright/test';

const DEMO_MAP_NAMES = [
  'Earth as Seen from Space',
  'Global Bathymetry',
  'Population at a Glance',
  'GDP per Capita PPP 2023',
  "The World's Disputed Places",
  'One Territory, Multiple Official Maps',
  'Conflict Events 2024 (UCDP GED)',
  'Refugees by Country of Origin 2023',
];

const OPTIONAL_DEMO_MAPS = [
  'Where the Ice Is',
  'Life Expectancy & Income',
];

const CONSOLE_NOISE_PATTERNS = [
  /ResizeObserver loop/i,
  /favicon/i,
  /Failed to load resource:.*sprite/i,
  /circle-11/i,
  /styleimagemissing/i,
  /React DevTools/i,
];

const isDemoSeeded = process.env.E2E_DEMO_SEEDED === '1';
const isConsoleNoise = (text: string) =>
  CONSOLE_NOISE_PATTERNS.some((re) => re.test(text));

type PlaywrightTest = typeof import('@playwright/test').test;

async function discoverDemoMapIds(request: APIRequestContext): Promise<Record<string, string>> {
  const resp = await request.get('/api/maps/?limit=100');
  expect(
    resp.ok(),
    `/api/maps/ returned HTTP ${resp.status()} — API is not reachable or the list endpoint is broken`,
  ).toBeTruthy();

  const body = await resp.json();
  const items: Array<{ id: string; name: string }> =
    body.maps || body.items || body.results || [];
  const mapIdByName: Record<string, string> = {};

  for (const item of items) {
    mapIdByName[item.name] = item.id;
  }

  expect(
    Object.keys(mapIdByName).length,
    `No demo maps parsed from /api/maps/ (HTTP ${resp.status()}, ${items.length} items in body). ` +
      'Either the seeder has not run OR the response shape has changed (expected items[] with {id,name}).',
  ).toBeGreaterThan(0);

  return mapIdByName;
}

async function expectDemoMapRenders(page: Page, name: string, id: string) {
  const consoleErrors: string[] = [];
  const failedRequests: Array<{ url: string; status: number }> = [];

  page.on('console', (msg) => {
    if (msg.type() === 'error' && !isConsoleNoise(msg.text())) {
      consoleErrors.push(msg.text());
    }
  });
  page.on('response', (resp) => {
    const url = resp.url();
    if (
      /\/api\/tiles\/|\.pbf(\?|$)|titiler/.test(url) &&
      resp.status() >= 400
    ) {
      failedRequests.push({ url, status: resp.status() });
    }
  });

  await page.goto(`/maps/${id}`);
  await expect(page.locator('.maplibregl-canvas').first()).toBeVisible({
    timeout: 30_000,
  });

  await page
    .locator('[data-tiles-loaded]')
    .first()
    .waitFor({ state: 'attached', timeout: 30_000 });
  await expect
    .poll(
      async () =>
        page
          .locator('[data-tiles-loaded]')
          .first()
          .getAttribute('data-tiles-loaded'),
      {
        message: `Map ${name} never reached idle state within 30 s`,
        timeout: 30_000,
      },
    )
    .toBe('true');

  expect(
    consoleErrors,
    `Console errors on ${name}:\n${consoleErrors.join('\n')}`,
  ).toEqual([]);

  expect(
    failedRequests,
    `Failed tile requests on ${name}:\n${failedRequests
      .map((r) => `  ${r.status} ${r.url}`)
      .join('\n')}`,
  ).toEqual([]);
}

export function registerDemoSmokeSuite(test: PlaywrightTest, title: string) {
  const mapIdByName: Record<string, string> = {};

  test.describe(title, () => {
    test.skip(
      !isDemoSeeded,
      'Demo data not seeded — set E2E_DEMO_SEEDED=1 to enable',
    );

    test.beforeAll(async ({ request }) => {
      Object.assign(mapIdByName, await discoverDemoMapIds(request));
    });

    for (const name of DEMO_MAP_NAMES) {
      test(`required map renders: ${name}`, async ({ page }) => {
        const id = mapIdByName[name];
        expect(
          id,
          `Map "${name}" not found in /api/maps/ — seeder may have failed`,
        ).toBeTruthy();
        if (!id) throw new Error(`unreachable: id for ${name} is undefined`);

        await expectDemoMapRenders(page, name, id);
      });
    }

    for (const name of OPTIONAL_DEMO_MAPS) {
      test(`optional map renders: ${name}`, async ({ page }) => {
        const id = mapIdByName[name];
        test.skip(
          !id,
          `Optional map "${name}" not present in this snapshot — skipping`,
        );
        if (!id) return;

        await page.goto(`/maps/${id}`);
        await expect(page.locator('.maplibregl-canvas').first()).toBeVisible({
          timeout: 30_000,
        });
      });
    }
  });
}
