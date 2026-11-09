import { test, expect } from './helpers/session';
import { createMap, deleteMap } from './helpers/maps';

test('viewer: the expanded attribution sits clear of the Ask AI launcher', async ({ page, request }) => {
  const mapId = await createMap(request, `Ask AI Attribution E2E ${Date.now()}`);
  try {
    // The CI stack has no AI provider; the admin e2e user reads availability from this endpoint.
    await page.route('**/api/admin/ai-status/', (route) =>
      route.fulfill({
        json: {
          provider: 'anthropic',
          model: 'claude-sonnet-5-5',
          enabled: true,
          configured: true,
          semantic_search_enabled: false,
          has_embeddings: false,
        },
      }),
    );
    await page.goto(`/maps/${mapId}?preview=viewer`);
    const launcher = page.getByRole('button', { name: 'Ask AI' });
    await expect(launcher).toBeVisible({ timeout: 30_000 });

    // Three lines of credit, as a map with several data sources has.
    const attribution = page.locator('.maplibregl-ctrl-attrib');
    await attribution.evaluate((el) => {
      el.classList.add('maplibregl-compact-show');
      const inner = el.querySelector('.maplibregl-ctrl-attrib-inner');
      if (inner) inner.textContent = 'Credit line one. '.repeat(40);
    });

    const a = await attribution.boundingBox();
    const l = await launcher.boundingBox();
    expect(a && l).toBeTruthy();
    const intersects =
      a!.x < l!.x + l!.width && a!.x + a!.width > l!.x && a!.y < l!.y + l!.height && a!.y + a!.height > l!.y;
    expect(intersects, `attribution ${JSON.stringify(a)} vs launcher ${JSON.stringify(l)}`).toBe(false);
  } finally {
    await deleteMap(request, mapId);
  }
});
