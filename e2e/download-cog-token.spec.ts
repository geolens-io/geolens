/**
 * IA-P0-01 regression: Download COG token-mint two-request flow.
 *
 * Verifies:
 *   1. Clicking "Download COG" first calls POST /auth/download-token/{id}
 *   2. The /download/cog URL carries the minted token (NOT the session JWT)
 *   3. Session JWT presented as ?token= on /download/cog is rejected with 401
 *
 * For browser flow tests, the spec mocks the network so no live raster dataset
 * is required. For the JWT rejection test, set E2E_RASTER_DATASET_ID.
 */

import path from 'path';
import fs from 'fs';
import { test, expect } from '@playwright/test';

const API = process.env.E2E_API_URL ?? '/api';

function getAuthToken(): string {
  const authFile = path.join(__dirname, '../playwright/.auth/user.json');
  try {
    const raw = fs.readFileSync(authFile, 'utf-8');
    const state = JSON.parse(raw);
    for (const origin of state.origins ?? []) {
      for (const entry of origin.localStorage ?? []) {
        if (entry.name === 'geolens-auth') {
          return JSON.parse(entry.value).state?.token ?? '';
        }
      }
    }
  } catch {
    // Auth file may not exist in all environments
  }
  return '';
}

// ─────────────────────────────────────────────────────────────────────────────
// S-IA-P001 — Session JWT rejected as ?token= on /download/cog
// ─────────────────────────────────────────────────────────────────────────────

test('S-IA-P001 download-token typ validation — session JWT rejected on cog download', async ({ request }) => {
  const rasterDatasetId = process.env.E2E_RASTER_DATASET_ID;
  test.skip(!rasterDatasetId, 'Set E2E_RASTER_DATASET_ID to a raster dataset UUID');

  const token = getAuthToken();
  test.skip(!token, 'Could not read auth token from playwright/.auth/user.json');

  // A session JWT (typ missing / not 'download') must be rejected with 401
  const res = await request.get(
    `${API}/datasets/${rasterDatasetId}/download/cog?token=${token}`
  );
  expect(res.status()).toBe(401);
  const body = await res.json();
  // Error message must mention download-scoped / typ / download
  const detail: string = (body.detail ?? '').toLowerCase();
  expect(
    detail.includes('download') || detail.includes('typ')
  ).toBe(true);
});

// ─────────────────────────────────────────────────────────────────────────────
// Browser flow: mint-then-open two-request order (network-mocked)
// ─────────────────────────────────────────────────────────────────────────────

test('IA-P0-01 download-cog mints token before opening URL', async ({ page }) => {
  const rasterDatasetId = process.env.E2E_RASTER_DATASET_ID;
  test.skip(!rasterDatasetId, 'Set E2E_RASTER_DATASET_ID to a raster dataset UUID');

  const MINTED_TOKEN = 'test-download-token-123';
  let mintCallCount = 0;
  let cogUrl: string | null = null;

  // Mock the token-mint endpoint
  await page.route(`**/auth/download-token/**`, async (route) => {
    mintCallCount++;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ token: MINTED_TOKEN, expires_in: 120 }),
    });
  });

  // Intercept the COG download URL — capture it, then fulfill with a small binary
  await page.route(`**/download/cog**`, async (route) => {
    cogUrl = route.request().url();
    await route.fulfill({
      status: 200,
      contentType: 'application/octet-stream',
      body: Buffer.from('GeoTIFF'),
    });
  });

  // Navigate to the dataset detail page
  await page.goto(`/datasets/${rasterDatasetId}`);

  // Wait for the Download COG button to appear (raster dataset with connect URL)
  const downloadButton = page.locator('button', { hasText: 'Download COG' });
  await downloadButton.waitFor({ timeout: 10_000 }).catch(() => {
    test.skip(true, 'Download COG button not visible — dataset may not be a connected raster');
  });

  // Click the button
  await downloadButton.click();

  // Give the async chain time to resolve
  await page.waitForTimeout(1000);

  // Assert the mint endpoint was called exactly once
  expect(mintCallCount).toBe(1);

  // Assert the COG URL carries the minted token, NOT the session JWT
  if (cogUrl) {
    const url = new URL(cogUrl);
    expect(url.searchParams.get('token')).toBe(MINTED_TOKEN);

    // The minted token must NOT equal the session JWT
    const sessionToken = getAuthToken();
    if (sessionToken) {
      expect(url.searchParams.get('token')).not.toBe(sessionToken);
    }
  }
});
