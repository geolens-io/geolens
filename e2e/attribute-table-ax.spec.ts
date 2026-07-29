import { test, expect } from '@playwright/test';
import { getAuthToken } from './helpers/catalog';

const BASE_URL = process.env.E2E_BASE_URL ?? 'http://localhost:8080';

// fix(#820): with the Chrome CDP Accessibility domain enabled (a real screen
// reader, or any AX-attached automation), clicking the Data tab on a vector
// dataset locked React in an infinite synchronous re-render loop — the
// measureElement dynamic-measurement ref in AttributeTable fed back
// measure→layout→re-render on every AX-tree pass. This spec replays that exact
// trigger and asserts the page stays responsive.
test.describe('AttributeTable with an accessibility client attached (#820)', () => {
  let datasetId: string;

  test.beforeAll(async () => {
    const headers = { Authorization: `Bearer ${getAuthToken()}` };
    const res = await fetch(`${BASE_URL}/api/datasets/?limit=10`, { headers });
    expect(res.ok).toBe(true);
    const data = await res.json();
    const datasets = data.datasets ?? data.items ?? data;
    const vector = datasets.filter(
      (ds: { record_type?: string }) => ds.record_type === 'vector_dataset',
    );
    const ds = vector[0] ?? datasets[0];
    expect(ds).toBeTruthy();
    datasetId = ds.id;
  });

  test('Data tab stays responsive with the CDP Accessibility domain enabled', async ({
    page,
    context,
  }) => {
    await page.goto(`/datasets/${datasetId}`);
    const dataTab = page.getByRole('tab', { name: 'Data', exact: true });
    await dataTab.waitFor();

    // The trigger: attach the AX tree, exactly like a screen reader or
    // aria-snapshot tooling does. Without this the bug never fires.
    const cdp = await context.newCDPSession(page);
    await cdp.send('Accessibility.enable');

    // noWaitAfter: if the renderer freezes, a normal click would hang the
    // test inside the actionability wait instead of reaching the assertion.
    await dataTab.click({ noWaitAfter: true, timeout: 5_000 });

    // A frozen renderer never answers this CDP roundtrip; race it against a
    // timeout so the failure mode is an assertion, not a test timeout.
    const alive = await Promise.race([
      page.title().then(() => true),
      new Promise<boolean>((resolve) => setTimeout(() => resolve(false), 10_000)),
    ]);
    expect(alive, 'page froze after clicking the Data tab with AX attached').toBe(true);

    // The table actually rendered — attribute rows are inside the virtualized
    // body, and the table itself carries an accessible name.
    await expect(page.getByRole('table').first()).toBeVisible({ timeout: 15_000 });
  });
});
