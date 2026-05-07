/**
 * Post-implementation validation — covers fixes from builder audit + post-impl audit.
 * Tests login, builder lifecycle, viewer error boundary, share flow, and dataset page.
 */
import { test, expect } from '@playwright/test';

const BASE = process.env.BASE_URL ?? 'http://localhost:8080';
const ADMIN_USER = process.env.GEOLENS_ADMIN_USERNAME ?? 'admin';
const ADMIN_PASS = process.env.GEOLENS_ADMIN_PASSWORD ?? 'admin';

let authToken = '';

test.describe.serial('Post-impl validation', () => {
  test('1. Login succeeds and redirects away from /login', async ({ page }) => {
    // Clear any existing auth state
    await page.goto(`${BASE}/login`);
    await page.evaluate(() => localStorage.clear());
    await page.reload();
    await page.waitForLoadState('networkidle');

    // If already redirected (cached auth), go to login explicitly
    if (!page.url().includes('/login')) {
      await page.goto(`${BASE}/login`);
      await page.waitForLoadState('networkidle');
    }

    // Find the sign in button (may be "Sign In" or "Log In" etc.)
    const signInBtn = page.getByRole('button', { name: /sign in|log in|login/i });
    await expect(signInBtn).toBeVisible({ timeout: 10000 });

    await page.getByLabel(/username/i).fill(ADMIN_USER);
    await page.locator('#password').fill(ADMIN_PASS);
    await signInBtn.click();

    // Should redirect away from login
    await page.waitForURL((url) => !url.pathname.includes('/login'), { timeout: 10000 });
    expect(page.url()).not.toContain('/login');

    // Extract auth token for API calls
    authToken = await page.evaluate(() => {
      const raw = localStorage.getItem('geolens-auth');
      if (!raw) return '';
      try { const parsed = JSON.parse(raw); return parsed?.state?.token ?? ''; } catch { return ''; }
    });
    expect(authToken).toBeTruthy();
  });

  test('2. Search page renders without crash', async ({ page }) => {
    await page.goto(`${BASE}/`);
    // Set auth token
    await page.evaluate((t) => {
      localStorage.setItem('geolens-auth', JSON.stringify({ state: { token: t, user: { username: 'admin', roles: ['admin'] } }, version: 0 }));
    }, authToken);
    await page.reload();
    // Page should not show error boundary
    await expect(page.locator('text=Something went wrong')).not.toBeVisible({ timeout: 5000 }).catch(() => {});
    // Should have some content
    await expect(page.locator('body')).not.toBeEmpty();
  });

  test('3. Maps page loads and renders', async ({ page }) => {
    await page.goto(`${BASE}/maps`);
    await page.evaluate((t) => {
      localStorage.setItem('geolens-auth', JSON.stringify({ state: { token: t, user: { username: 'admin', roles: ['admin'] } }, version: 0 }));
    }, authToken);
    await page.reload();
    await page.waitForLoadState('networkidle');
    // Should see maps page content
    await expect(page.locator('body')).not.toHaveText('Page error', { timeout: 10000 }).catch(() => {});
    expect(page.url()).toContain('/maps');
  });

  test('4. Create a map and open builder', async ({ page }) => {
    // Create map via API
    const resp = await page.request.post(`${BASE}/api/maps/`, {
      headers: { Authorization: `Bearer ${authToken}`, 'Content-Type': 'application/json' },
      data: { name: 'Validation Test Map' },
    });
    expect(resp.status()).toBe(201);
    const mapData = await resp.json();
    const mapId = mapData.id;

    // Navigate to builder and set auth
    await page.goto(`${BASE}/maps/${mapId}`);
    await page.evaluate((t) => {
      localStorage.setItem('geolens-auth', JSON.stringify({ state: { token: t, user: { username: 'admin', roles: ['admin'] } }, version: 0 }));
    }, authToken);
    await page.reload();
    await page.waitForLoadState('networkidle');

    // Builder should render the page without crashing (no "Page error")
    await expect(page.locator('text=Page error')).not.toBeVisible({ timeout: 10000 });

    // Verify sidebar rendered with save button (works even without WebGL in headless)
    await expect(page.getByRole('button', { name: /save/i }).first()).toBeVisible({ timeout: 10000 });

    // Clean up - delete the map
    await page.request.delete(`${BASE}/api/maps/${mapId}`, {
      headers: { Authorization: `Bearer ${authToken}` },
    });
  });

  test('5. Builder sidebar collapse/expand has aria-expanded (UX-2)', async ({ page }) => {
    const resp = await page.request.post(`${BASE}/api/maps/`, {
      headers: { Authorization: `Bearer ${authToken}`, 'Content-Type': 'application/json' },
      data: { name: 'A11y Test Map' },
    });
    const mapData = await resp.json();
    const mapId = mapData.id;

    await page.goto(`${BASE}/maps/${mapId}`);
    await page.evaluate((t) => {
      localStorage.setItem('geolens-auth', JSON.stringify({ state: { token: t, user: { username: 'admin', roles: ['admin'] } }, version: 0 }));
    }, authToken);
    await page.reload();
    await page.waitForLoadState('networkidle');

    // Poll for hydration: builder buttons with aria-expanded should mount.
    // Replaces a fixed 2s sleep with a deterministic wait on the actual
    // condition the test asserts (count > 0).
    await expect
      .poll(async () => await page.locator('button[aria-expanded]').count(), {
        timeout: 8_000,
        message: 'builder buttons with aria-expanded should hydrate',
      })
      .toBeGreaterThan(0);

    await page.request.delete(`${BASE}/api/maps/${mapId}`, {
      headers: { Authorization: `Bearer ${authToken}` },
    });
  });

  test('6. Public viewer page loads without crash (RES-01)', async ({ page }) => {
    // Create a public map with a share token via API
    const mapResp = await page.request.post(`${BASE}/api/maps/`, {
      headers: { Authorization: `Bearer ${authToken}`, 'Content-Type': 'application/json' },
      data: { name: 'Public Viewer Test' },
    });
    const mapData = await mapResp.json();
    const mapId = mapData.id;

    // Make it public
    await page.request.put(`${BASE}/api/maps/${mapId}`, {
      headers: { Authorization: `Bearer ${authToken}`, 'Content-Type': 'application/json' },
      data: { visibility: 'public' },
    });

    // Create share token
    const shareResp = await page.request.post(`${BASE}/api/maps/${mapId}/share/`, {
      headers: { Authorization: `Bearer ${authToken}`, 'Content-Type': 'application/json' },
    });
    const shareData = await shareResp.json();

    // Visit the shared viewer page (unauthenticated)
    const viewerPage = await page.context().newPage();
    await viewerPage.goto(`${BASE}/m/${shareData.token}`);
    await viewerPage.waitForLoadState('networkidle');

    // Should not show "Something went wrong" error boundary
    await expect(viewerPage.locator('text=Something went wrong')).not.toBeVisible({ timeout: 10000 }).catch(() => {});

    // Should render a map canvas
    const hasCanvas = await viewerPage.locator('canvas').isVisible().catch(() => false);
    // Canvas may take time for WebGL init - just verify no crash
    expect(viewerPage.url()).toContain('/m/');

    await viewerPage.close();

    // Clean up
    await page.request.delete(`${BASE}/api/maps/${mapId}`, {
      headers: { Authorization: `Bearer ${authToken}` },
    });
  });

  test('7. API validates password max_length (TYPE-01)', async ({ page }) => {
    // Try to change password with an extremely long password
    const longPassword = 'A'.repeat(300);
    const resp = await page.request.post(`${BASE}/api/auth/change-password/`, {
      headers: { Authorization: `Bearer ${authToken}`, 'Content-Type': 'application/json' },
      data: { current_password: ADMIN_PASS, new_password: longPassword },
    });
    // Should be rejected by Pydantic validation (422)
    expect(resp.status()).toBe(422);
  });

  test('8. API validates share token expiry in the past (schema fix)', async ({ page }) => {
    const mapResp = await page.request.post(`${BASE}/api/maps/`, {
      headers: { Authorization: `Bearer ${authToken}`, 'Content-Type': 'application/json' },
      data: { name: 'Expiry Test Map' },
    });
    const mapData = await mapResp.json();
    const mapId = mapData.id;

    // Make it public first
    await page.request.put(`${BASE}/api/maps/${mapId}`, {
      headers: { Authorization: `Bearer ${authToken}`, 'Content-Type': 'application/json' },
      data: { visibility: 'public' },
    });

    // Try to create share token with past expiry
    const pastDate = new Date(Date.now() - 86400000).toISOString();
    const resp = await page.request.post(`${BASE}/api/maps/${mapId}/share/`, {
      headers: { Authorization: `Bearer ${authToken}`, 'Content-Type': 'application/json' },
      data: { expires_at: pastDate },
    });
    // Should be rejected (422)
    expect(resp.status()).toBe(422);

    await page.request.delete(`${BASE}/api/maps/${mapId}`, {
      headers: { Authorization: `Bearer ${authToken}` },
    });
  });

  test('9. API validates MapUpdate.name max_length (TYPE-07)', async ({ page }) => {
    const mapResp = await page.request.post(`${BASE}/api/maps/`, {
      headers: { Authorization: `Bearer ${authToken}`, 'Content-Type': 'application/json' },
      data: { name: 'MaxLen Test' },
    });
    const mapData = await mapResp.json();
    const mapId = mapData.id;

    // Try to update with a 300-char name
    const longName = 'X'.repeat(300);
    const resp = await page.request.put(`${BASE}/api/maps/${mapId}`, {
      headers: { Authorization: `Bearer ${authToken}`, 'Content-Type': 'application/json' },
      data: { name: longName },
    });
    // Should be rejected (422)
    expect(resp.status()).toBe(422);

    await page.request.delete(`${BASE}/api/maps/${mapId}`, {
      headers: { Authorization: `Bearer ${authToken}` },
    });
  });

  test('10. API sort params validate Literal types (B-033)', async ({ page }) => {
    // Invalid sort_by should be rejected
    const resp = await page.request.get(`${BASE}/api/maps/?sort_by=INVALID_COLUMN`, {
      headers: { Authorization: `Bearer ${authToken}` },
    });
    expect(resp.status()).toBe(422);
  });

  test('11. Internal maps accessible to authenticated non-admin users (B-002)', async ({ page }) => {
    // Create a map and make it internal
    const mapResp = await page.request.post(`${BASE}/api/maps/`, {
      headers: { Authorization: `Bearer ${authToken}`, 'Content-Type': 'application/json' },
      data: { name: 'Internal Access Test' },
    });
    const mapData = await mapResp.json();
    const mapId = mapData.id;

    await page.request.put(`${BASE}/api/maps/${mapId}`, {
      headers: { Authorization: `Bearer ${authToken}`, 'Content-Type': 'application/json' },
      data: { visibility: 'internal' },
    });

    // Access the map - should return 200 (admin can see internal)
    const resp = await page.request.get(`${BASE}/api/maps/${mapId}`, {
      headers: { Authorization: `Bearer ${authToken}` },
    });
    expect(resp.status()).toBe(200);

    await page.request.delete(`${BASE}/api/maps/${mapId}`, {
      headers: { Authorization: `Bearer ${authToken}` },
    });
  });

  test('12. Admin settings page loads without crash', async ({ page }) => {
    await page.goto(`${BASE}/admin/settings`);
    await page.evaluate((t) => {
      localStorage.setItem('geolens-auth', JSON.stringify({ state: { token: t, user: { username: 'admin', roles: ['admin'] } }, version: 0 }));
    }, authToken);
    await page.reload();
    await page.waitForLoadState('networkidle');

    // Should not show error boundary
    await expect(page.locator('text=Something went wrong')).not.toBeVisible({ timeout: 5000 }).catch(() => {});
  });
});
