import { test } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { getAuthToken, seedDataset, deleteDataset, type SeededDataset } from './helpers/catalog';

const BASE_URL = process.env.E2E_BASE_URL ?? 'http://localhost:8080';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function formatViolations(violations: any[]): string {
  return violations
    .map(
      (v) =>
        `[${v.id}] ${v.description} (${v.impact})\n` +
        v.nodes.map((n) => `  - ${n.html}`).join('\n'),
    )
    .join('\n\n');
}

/**
 * fix(#1778): the gating suite's `wcagTags` (accessibility.spec.ts) omits
 * `wcag22aa`, the only tag that reaches axe-core's `target-size` rule, so
 * the map builder's 22px row controls (StackRow.tsx, FolderGroupRow.tsx,
 * BasemapGroupRow.tsx, UnifiedStackPanel.tsx, EmptyStackState.tsx,
 * BasemapGroupEditorScene.tsx) are structurally invisible to CI. Adding
 * `wcag22aa` to the gating tags would fail the suite on those controls
 * immediately, so this is a separate, non-gating scan: it always passes and
 * only surfaces violations (console + attachment) for the target-size work
 * to be scoped and scheduled later.
 *
 * Deliberately not listed in any package.json `e2e:smoke:*` script, so the
 * per-PR smoke gates never pick it up (same precedent as analysis.spec.ts).
 */
test.describe('Accessibility target-size scan (non-gating)', () => {
  let seed: SeededDataset;
  let mapId: string;

  test.beforeAll(async () => {
    seed = await seedDataset('A11y Target-Size Seed Dataset');
    const headers = {
      Authorization: `Bearer ${getAuthToken()}`,
      'Content-Type': 'application/json',
    };

    const mapRes = await fetch(`${BASE_URL}/api/maps/`, {
      method: 'POST',
      headers,
      body: JSON.stringify({
        name: `A11y Target-Size Map ${Date.now()}`,
        description: 'Fixture for the non-gating wcag22aa target-size scan',
      }),
    });
    if (!mapRes.ok) throw new Error(`map create failed: ${mapRes.status}`);
    mapId = ((await mapRes.json()) as { id: string }).id;

    const layerRes = await fetch(`${BASE_URL}/api/maps/${mapId}/layers/`, {
      method: 'POST',
      headers,
      body: JSON.stringify({ dataset_id: seed.id }),
    });
    if (!layerRes.ok) throw new Error(`layer create failed: ${layerRes.status}`);
  });

  test.afterAll(async () => {
    if (mapId) {
      await fetch(`${BASE_URL}/api/maps/${mapId}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${getAuthToken()}` },
      }).catch(() => {
        /* teardown is best-effort; the CI stack is torn down anyway */
      });
    }
    if (seed) await deleteDataset(seed.id, seed.title);
  });

  test('map builder page: wcag22aa target-size scan (reports only)', async ({ page }, testInfo) => {
    await page.goto(`/maps/${mapId}`);
    await page.waitForLoadState('networkidle');

    const results = await new AxeBuilder({ page }).withTags(['wcag22aa']).analyze();

    if (results.violations.length > 0) {
      const formatted = formatViolations(results.violations);
      // eslint-disable-next-line no-console
      console.warn(
        `[wcag22aa target-size, non-gating] ${results.violations.length} violation(s):\n${formatted}`,
      );
      await testInfo.attach('wcag22aa-violations.txt', {
        body: formatted,
        contentType: 'text/plain',
      });
    }
    // No assertion on results.violations by design (see module docstring):
    // this scan reports for later scoping, it does not gate CI.
  });
});
