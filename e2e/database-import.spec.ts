import { test, expect, type Page, type Route } from './helpers/session';

/**
 * The Database source on the import page. CI has no SQL Server, so the
 * capabilities, the table listing and the import POST are all fulfilled with
 * `page.route`; what this pins is the page wiring: the source appears only
 * for an account with a connection, a table can be picked and imported from
 * the keyboard-reachable form, and a table without an SRID asks for one.
 */

async function mockCapabilities(page: Page, connections: { name: string; database: string }[]) {
  await page.route('**/api/capabilities/', async (route: Route) => {
    const response = await route.fetch();
    const body = await response.json();
    body.me = { ...(body.me ?? {}), database_connections: connections };
    await route.fulfill({ response, json: body });
  });
}

const LISTING = {
  connection: 'warehouse',
  database: 'Warehouse',
  limit: 500,
  truncated: false,
  tables: [
    {
      schema_name: 'gis',
      table_name: 'parcels',
      object_type: 'table',
      geometry_column: 'shape',
      column_type: 'geometry',
      srid: 4326,
    },
    {
      schema_name: 'gis',
      table_name: 'v_zones',
      object_type: 'view',
      geometry_column: 'shape',
      column_type: 'geometry',
      srid: null,
    },
  ],
};

test.describe('Database import source', () => {
  test('is hidden when the account has no database connection', async ({ page }) => {
    await mockCapabilities(page, []);
    const capabilities = page.waitForResponse('**/api/capabilities/');
    await page.goto('/import');
    await capabilities;

    // The tab list renders before capabilities settle. Let the response reach
    // the query cache and React paint again before asserting absence.
    await expect(page.getByRole('button', { name: 'Upload File', exact: true })).toBeVisible();
    await page.evaluate(
      () => new Promise<void>((done) => requestAnimationFrame(() => requestAnimationFrame(() => done()))),
    );
    await expect(page.getByRole('button', { name: 'Database', exact: true })).toHaveCount(0);
  });

  test('imports a table from a connection', async ({ page }) => {
    await mockCapabilities(page, [{ name: 'warehouse', database: 'Warehouse' }]);
    await page.route('**/api/services/databases/warehouse/tables/', (route) =>
      route.fulfill({ json: LISTING }),
    );
    let posted: Record<string, unknown> | null = null;
    await page.route('**/api/services/databases/warehouse/imports/', async (route) => {
      posted = route.request().postDataJSON();
      await route.fulfill({
        status: 202,
        json: { job_id: '00000000-0000-4000-8000-000000000001', status: 'pending', message: 'queued' },
      });
    });
    await page.goto('/import');

    await page.getByRole('button', { name: 'Database', exact: true }).click();
    await page.getByRole('radio', { name: /gis\.parcels/ }).check();
    await page.getByRole('button', { name: 'Continue' }).click();
    await page.getByRole('button', { name: /^Import/ }).click();

    await expect.poll(() => posted).toMatchObject({
      schema_name: 'gis',
      table_name: 'parcels',
      srid_override: null,
    });
  });

  test('asks for a CRS when the table has no SRID', async ({ page }) => {
    await mockCapabilities(page, [{ name: 'warehouse', database: 'Warehouse' }]);
    await page.route('**/api/services/databases/warehouse/tables/', (route) =>
      route.fulfill({ json: LISTING }),
    );
    let posted: Record<string, unknown> | null = null;
    await page.route('**/api/services/databases/warehouse/imports/', async (route) => {
      posted = route.request().postDataJSON();
      await route.fulfill({
        status: 202,
        json: { job_id: '00000000-0000-4000-8000-000000000002', status: 'pending', message: 'queued' },
      });
    });
    await page.goto('/import');

    await page.getByRole('button', { name: 'Database', exact: true }).click();
    await page.getByRole('radio', { name: /gis\.v_zones/ }).check();
    await page.getByRole('button', { name: 'Continue' }).click();
    await page.getByLabel(/CRS/i).fill('3857');
    await page.getByRole('button', { name: /^Import/ }).click();

    await expect.poll(() => posted).toMatchObject({ table_name: 'v_zones', srid_override: 3857 });
  });
});
