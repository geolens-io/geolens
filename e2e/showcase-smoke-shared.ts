import { expect, type APIRequestContext, type Page } from '@playwright/test';

const SHOWCASE_MAP_NAMES = [
  'Grand Canyon: Land in 3D',
  'NYC Zoning: Manhattan in 3D',
  'Density Bars: Los Angeles',
  'Global Earthquakes M5+ (Last 5 Years)',
  'Western US Wildfires 2020-2024',
];

const OPTIONAL_SHOWCASE_MAPS: string[] = [];

const CONSOLE_NOISE_PATTERNS = [
  /ResizeObserver loop/i,
  /favicon/i,
  /Failed to load resource:.*sprite/i,
  /circle-11/i,
  /styleimagemissing/i,
  /React DevTools/i,
];

const isShowcaseSeeded = process.env.E2E_SHOWCASE_SEEDED === '1';
const isConsoleNoise = (text: string) =>
  CONSOLE_NOISE_PATTERNS.some((re) => re.test(text));

type PlaywrightTest = typeof import('@playwright/test').test;

async function discoverShowcaseMapIds(request: APIRequestContext): Promise<Record<string, string>> {
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
    `No showcase maps parsed from /api/maps/ (HTTP ${resp.status()}, ${items.length} items in body). ` +
      'Either sample data has not been seeded OR the response shape has changed (expected items[] with {id,name}).',
  ).toBeGreaterThan(0);

  return mapIdByName;
}

async function expectShowcaseMapRenders(page: Page, name: string, id: string) {
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

export function registerShowcaseSmokeSuite(test: PlaywrightTest, title: string) {
  const mapIdByName: Record<string, string> = {};

  test.describe(title, () => {
    test.skip(
      !isShowcaseSeeded,
      'Showcase sample data not seeded — set E2E_SHOWCASE_SEEDED=1 to enable',
    );

    test.beforeAll(async ({ request }) => {
      Object.assign(mapIdByName, await discoverShowcaseMapIds(request));
    });

    for (const name of SHOWCASE_MAP_NAMES) {
      test(`required map renders: ${name}`, async ({ page }) => {
        const id = mapIdByName[name];
        expect(
          id,
          `Map "${name}" not found in /api/maps/ — sample-data seeding may have failed`,
        ).toBeTruthy();
        if (!id) throw new Error(`unreachable: id for ${name} is undefined`);

        await expectShowcaseMapRenders(page, name, id);
      });
    }

    for (const name of OPTIONAL_SHOWCASE_MAPS) {
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
