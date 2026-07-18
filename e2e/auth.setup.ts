import { test as setup, expect } from '@playwright/test';
import fs from 'fs';
import path from 'path';
import {
  deleteDataset,
  seedDataset,
  type SeededDataset,
} from './helpers/catalog';

const authFile = path.join(__dirname, '../playwright/.auth/user.json');
const catalogFixtureFile = path.join(__dirname, '../playwright/.auth/catalog-fixture.json');

setup('authenticate as admin', async ({ page }) => {
  setup.slow();
  const adminUser = process.env.GEOLENS_ADMIN_USERNAME ?? 'admin';
  const adminPass = process.env.GEOLENS_ADMIN_PASSWORD ?? 'admin';

  await page.goto('/login');

  // Wait for the login form to render
  await expect(page.getByRole('button', { name: 'Sign In' })).toBeVisible();

  // Fill credentials
  await page.getByLabel('Username').fill(adminUser);
  await page.locator('#password').fill(adminPass);

  // Submit the form
  await page.getByRole('button', { name: 'Sign In' }).click();

  // Wait for redirect to the search workspace (index route). On a credential
  // rejection the SPA stays on /login and renders a role="alert" instead of
  // navigating; surface that message immediately rather than letting waitForURL
  // run out the full test timeout — an auth failure otherwise masquerades as a
  // slow-redirect flake (e.g. the seeded admin not matching the test creds).
  try {
    await page.waitForURL('/', { timeout: 30_000 });
  } catch (err) {
    const alert = page.getByRole('alert');
    if (await alert.isVisible().catch(() => false)) {
      const message = (await alert.textContent())?.trim();
      throw new Error(
        `Login failed — credentials rejected ("${message}"). ` +
          'Confirm GEOLENS_ADMIN_USERNAME/PASSWORD match the seeded admin.',
      );
    }
    throw err;
  }

  // Verify workspace loaded
  await expect(page.locator('[data-testid="search-page"], input[type="search"], [role="search"]').first()).toBeVisible({ timeout: 10000 }).catch(() => {
    // Fallback: just verify we're no longer on /login
    expect(page.url()).not.toContain('/login');
  });

  // Save storage state (includes localStorage with auth token)
  await page.context().storageState({ path: authFile });

  // fix(#547): host-backend stacks (uvicorn on the host + docker Postgres)
  // cannot run the real ingest that seedDataset needs, so E2E_SKIP_SEED=1
  // stops here — auth state is saved, no shared fixture is created, and
  // catalog.teardown already no-ops when the manifest is absent.
  if (process.env.E2E_SKIP_SEED === '1') return;

  // An interrupted local run may leave its manifest behind. Remove that
  // fixture before recording a replacement so repeated runs cannot orphan it.
  if (fs.existsSync(catalogFixtureFile)) {
    const staleFixture = JSON.parse(
      fs.readFileSync(catalogFixtureFile, 'utf-8'),
    ) as SeededDataset;
    expect(
      await deleteDataset(staleFixture.id, staleFixture.title),
      'stale shared catalog fixture should be removable',
    ).toBe(true);
    fs.rmSync(catalogFixtureFile);
  }

  // Several browser flows need a real vector dataset. Seed one here so a
  // clean CI database exercises those flows without depending on demo data.
  const catalogFixture = await seedDataset('Shared E2E Catalog Fixture');
  fs.writeFileSync(catalogFixtureFile, JSON.stringify(catalogFixture));
});
