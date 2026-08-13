import { test, expect } from '@playwright/test';
import { getAuthToken } from './helpers/catalog';

const BASE_URL = process.env.E2E_BASE_URL ?? 'http://localhost:8080';

// fix(#1446): logout is now a real server-side security event —
// revoke_all_tokens bumps token_version and revokes every refresh row for the
// user. Running this flow as the shared admin therefore destroyed the saved
// storageState session that every parallel spec depends on, minutes into the
// run (the pre-#1446 SPA never called /auth/logout/, which is what made a
// shared session survivable). The flow gets its own throwaway user so the
// revocation lands on nobody else.
const LOGOUT_USER = 'e2e-logout-probe';
const LOGOUT_PASS = 'E2e-Logout-Probe-42';

async function adminHeaders(): Promise<Record<string, string>> {
  return {
    Authorization: `Bearer ${getAuthToken()}`,
    'Content-Type': 'application/json',
  };
}

async function deleteProbeUser(): Promise<void> {
  const headers = await adminHeaders();
  const list = await fetch(
    `${BASE_URL}/api/admin/users/?search=${LOGOUT_USER}`,
    { headers },
  );
  if (!list.ok) return;
  const data = await list.json();
  const users: { id: string; username: string }[] = data.users ?? data.items ?? [];
  const probe = users.find((u) => u.username === LOGOUT_USER);
  if (!probe) return;
  await fetch(`${BASE_URL}/api/admin/users/${probe.id}`, {
    method: 'DELETE',
    headers,
  });
}

test.describe('Authentication Flow', () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeAll(async () => {
    const res = await fetch(`${BASE_URL}/api/admin/users/`, {
      method: 'POST',
      headers: await adminHeaders(),
      body: JSON.stringify({
        username: LOGOUT_USER,
        password: LOGOUT_PASS,
        role: 'viewer',
      }),
    });
    // 409 "Username already taken" = leftover from an interrupted run. The
    // password is deterministic, so the login below still proves it usable.
    if (!res.ok && res.status !== 409) {
      throw new Error(
        `Could not create logout probe user: ${res.status} ${await res.text()}`,
      );
    }
  });

  test.afterAll(async () => {
    // Best effort — a leftover probe user is tolerated by beforeAll anyway.
    await deleteProbeUser().catch(() => {});
  });

  test('login, see dashboard, logout', async ({ page }) => {
    await page.goto('/login');

    // Verify login page
    await expect(
      page.getByRole('button', { name: 'Sign In' }),
    ).toBeVisible();

    // Fill credentials
    await page.getByLabel('Username').fill(LOGOUT_USER);
    await page.locator('#password').fill(LOGOUT_PASS);

    // Submit
    await page.getByRole('button', { name: 'Sign In' }).click();

    // Current auth flow lands on the root workspace.
    await page.waitForURL((url) => url.pathname === '/');

    // Verify workspace loaded
    await expect(
      page.getByRole('combobox', { name: 'Search the catalog...' }),
    ).toBeVisible();

    // Verify username displayed in navbar user menu button
    await expect(page.getByRole('button', { name: 'User menu' })).toBeVisible();

    // Logout
    await page.getByRole('button', { name: 'User menu' }).click();
    await page.getByRole('menuitem', { name: 'Logout' }).click();

    // Verify redirected to login
    await page.waitForURL('/login');

    // Verify login heading visible again
    await expect(
      page.getByRole('button', { name: 'Sign In' }),
    ).toBeVisible();
  });
});
