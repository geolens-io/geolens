import { test, expect, type Locator, type Page } from '@playwright/test';

// fix(#1204): the sortable column headers are tabbable buttons sitting between
// the filter bar and the row toggles, so the first row control is a bounded
// number of Tabs away from "Clear" rather than exactly one. Tab until the
// target gains focus; the final assertion still fails loudly if it never does.
async function tabUntilFocused(page: Page, target: Locator, maxTabs = 12) {
  for (let i = 0; i < maxTabs; i += 1) {
    await page.keyboard.press('Tab');
    if (await target.evaluate((el) => el === document.activeElement).catch(() => false)) {
      break;
    }
  }
  await expect(target).toBeFocused();
}

test.describe('Admin Panel', () => {
  test('overview page loads with stats', async ({ page }) => {
    await page.goto('/admin/overview');

    await expect(
      page.getByRole('heading', { level: 1, name: 'Overview' }),
    ).toBeVisible();
    await expect(page.getByText('Total Datasets')).toBeVisible({
      timeout: 10_000,
    });
  });

  test('user management: view user list and table columns', async ({ page }) => {
    await page.goto('/admin/users');

    await expect(
      page.getByRole('heading', { level: 1, name: 'Users' }),
    ).toBeVisible();
    // Column headers asserted by role: plain getByText('Email') strict-collides
    // with the "Export emails (CSV)" toolbar button (substring match).
    await expect(page.getByRole('columnheader', { name: 'Username' })).toBeVisible({ timeout: 10_000 });
    await expect(page.getByRole('columnheader', { name: 'Email' })).toBeVisible();
    await expect(page.getByRole('columnheader', { name: 'Roles' })).toBeVisible();
    await expect(page.getByRole('columnheader', { name: 'Status' })).toBeVisible();
    await expect(
      page.getByRole('cell', { name: 'admin', exact: true }).first(),
    ).toBeVisible();
    await expect(
      page.getByRole('button', { name: 'Add User' }),
    ).toBeVisible();
  });

  test('job monitoring: view job list page', async ({ page }) => {
    await page.goto('/admin/jobs');

    await expect(
      page.getByRole('heading', { level: 1, name: 'Jobs' }),
    ).toBeVisible();
    await expect(page.locator('label').filter({ hasText: 'Status' })).toBeVisible();
    await expect(page.locator('label').filter({ hasText: 'User' })).toBeVisible();
    await expect(page.getByRole('columnheader', { name: 'Created At' })).toBeVisible();
    await expect(page.getByRole('columnheader', { name: 'Filename' })).toBeVisible();
    const detailsToggles = page.getByTestId('job-details-toggle');
    const detailsToggle = detailsToggles.first();
    await expect(detailsToggle).toBeVisible();

    await page.getByRole('button', { name: 'Clear' }).focus();
    await tabUntilFocused(page, detailsToggle);

    const jobToggleCount = await detailsToggles.count();
    if (jobToggleCount > 1) {
      await page.keyboard.press('ArrowDown');
      await expect(detailsToggles.nth(1)).toBeFocused();
    }

    await page.keyboard.press('Tab');
    await expect(detailsToggle).not.toBeFocused();
    if (jobToggleCount > 1) {
      await expect(detailsToggles.nth(1)).not.toBeFocused();
    }

    await detailsToggle.click();
    await expect(detailsToggle).toHaveAttribute('aria-expanded', 'true');
  });

  test('audit log: view entries and table structure', async ({ page }) => {
    await page.goto('/admin/audit');

    await expect(
      page.getByRole('heading', { level: 1, name: 'Audit Logs' }),
    ).toBeVisible();
    await expect(page.locator('label').filter({ hasText: 'Action' })).toBeVisible();
    await expect(page.locator('label').filter({ hasText: 'From' })).toBeVisible();
    await expect(page.locator('label').filter({ hasText: 'To' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Clear' })).toBeVisible();

    const emptyState = page.getByText('No audit logs found');
    const detailsToggles = page.getByTestId('audit-details-toggle');
    const firstToggle = detailsToggles.first();

    // Wait for loading to finish before deciding whether the clean installation
    // needs a seed row. Exporting an empty result records its own audit.export event.
    await expect
      .poll(
        async () =>
          (await emptyState.isVisible()) || (await firstToggle.isVisible()),
        { message: 'audit table did not reach an empty or populated state' },
      )
      .toBe(true);

    if (await emptyState.isVisible()) {
      const downloadPromise = page.waitForEvent('download');
      await page.getByRole('button', { name: 'Export CSV' }).click();
      const download = await downloadPromise;
      await download.path();
      await page.reload();
    }

    await expect(page.getByRole('columnheader', { name: 'Timestamp' })).toBeVisible();
    await expect(page.getByRole('columnheader', { name: 'IP Address' })).toBeVisible();
    await expect(firstToggle).toBeVisible();

    await page.getByRole('button', { name: 'Clear' }).focus();
    await tabUntilFocused(page, firstToggle);

    const auditToggleCount = await detailsToggles.count();
    if (auditToggleCount > 1) {
      await page.keyboard.press('ArrowDown');
      await expect(detailsToggles.nth(1)).toBeFocused();
    }

    await page.keyboard.press('Tab');
    await expect(firstToggle).not.toBeFocused();
    if (auditToggleCount > 1) {
      await expect(detailsToggles.nth(1)).not.toBeFocused();
    }

    await firstToggle.click();
    await expect(page.getByText('Expanded log details')).toBeVisible();
  });

  test('settings: general page loads with feature toggles', async ({ page }) => {
    await page.goto('/admin/settings/general');

    await expect(
      page.getByRole('heading', { level: 1, name: 'General' }),
    ).toBeVisible();
    await expect(page.getByText('Require Metadata for Publishing')).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.getByText('Public App URL')).toBeVisible();
    await expect(page.getByText('Public API URL')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Save' })).toBeVisible();
  });

  test('settings: auth page loads', async ({ page }) => {
    await page.goto('/admin/settings/auth');

    await expect(
      page.getByRole('heading', { level: 1, name: 'Auth', exact: true }),
    ).toBeVisible();
    await expect(page.getByRole('heading', { name: 'OAuth Providers' })).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.getByText('Access Token Lifetime (minutes)')).toBeVisible();
    await expect(page.getByText('Refresh Token Lifetime (days)')).toBeVisible();
  });

  test('settings: network page loads', async ({ page }) => {
    await page.goto('/admin/settings/network');

    await expect(
      page.getByRole('heading', { level: 1, name: 'Network' }),
    ).toBeVisible();
    await expect(page.getByText('CORS Allowed Origins')).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.getByText('Global Rate Limit (per second)')).toBeVisible();
  });

  test('settings: storage page loads', async ({ page }) => {
    await page.goto('/admin/settings/storage');

    await expect(
      page.getByRole('heading', { level: 1, name: 'Storage' }),
    ).toBeVisible();
    await expect(page.getByText('Maximum file size (MB)')).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.getByText('Allowed extensions')).toBeVisible();
    await expect(page.getByText('Tile Cache TTL (seconds)')).toBeVisible();
  });

  test('settings: map page loads', async ({ page }) => {
    await page.goto('/admin/settings/map');

    await expect(
      page.getByRole('heading', { level: 1, name: 'Map', exact: true }),
    ).toBeVisible();
    await expect(page.getByText('Basemap Presets')).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.getByText('Default Map View')).toBeVisible();
    await expect(page.getByText('Map Plugins')).toBeVisible();
  });

  // test(#828): the AI and appearance settings pages were never visited by the
  // admin e2e — their gating (edition, capability, env-key notice) was pinned
  // only by unit tests.
  test('settings: ai page loads with provider config and env-key notice', async ({ page }) => {
    await page.goto('/admin/settings/ai');

    await expect(
      page.getByRole('heading', { level: 1, name: 'AI', exact: true }),
    ).toBeVisible();

    // The env-key notice copy is the point: keys are env-only and cannot be
    // edited from this page.
    await expect(
      page.getByText('API keys can only be set via environment variables'),
    ).toBeVisible({ timeout: 10_000 });

    // Key status rows render for both providers regardless of configured
    // state, and either status is valid — CI runs keyless while a dev stack
    // may have real keys. Fully anchored "<KEY> <status>" regexes scope the
    // match to the status-row span alone: a start-only anchor also matched
    // the keyless-stack warning ("OPENAI_API_KEY is not set. Embedding…")
    // and strict-mode-failed in CI.
    await expect(page.getByText(/^ANTHROPIC_API_KEY (configured|not set)$/)).toBeVisible();
    await expect(page.getByText(/^OPENAI_API_KEY (configured|not set)$/)).toBeVisible();

    // Provider config controls are present.
    await expect(page.locator('#ai-toggle')).toBeVisible();
    await expect(page.locator('#llm-provider')).toBeVisible();
    await expect(page.locator('#semantic-toggle')).toBeVisible();

    // The admin (manage_users, single-tenant) passes useAIStatusReader, so the
    // probe button is offered. Deliberately NOT clicked — it spends live
    // provider tokens.
    await expect(page.getByRole('button', { name: 'Test Connection' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Save' })).toBeVisible();
  });

  test('settings: appearance URL never renders the appearance tab on community', async ({ page }) => {
    await page.goto('/admin/settings/appearance');

    // fix(#871): AdminSettingsPage's edition gate owns this URL now, so a
    // community stack lands on /general (it used to be dragged to /map by a
    // static legacy redirect that outranked `admin/settings/:tab`). The
    // enterprise direction — same URL renders the branding tab — is pinned at
    // the unit level in AdminSettingsPage.test.tsx, since the stack under
    // test only ever has one edition.
    await page.waitForURL('/admin/settings/general');
    await expect(
      page.getByRole('heading', { level: 1, name: 'General', exact: true }),
    ).toBeVisible({ timeout: 10_000 });
    // The appearance tab's branding toggle must never render for community.
    await expect(page.locator('#show-badge')).toHaveCount(0);

    // Community edition gating that IS observable here: the sidebar offers no
    // Appearance entry (AdminSidebar hides enterprise-only tabs).
    await expect(page.locator('a[href="/admin/settings/appearance"]')).toHaveCount(0);
  });

  test('published maps page loads', async ({ page }) => {
    await page.goto('/admin/shared-maps');

    await expect(
      page.getByRole('heading', { level: 1, name: 'Published Maps' }),
    ).toBeVisible();
    await expect(page.getByPlaceholder('Search by map name...')).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.getByRole('columnheader', { name: 'Map' })).toBeVisible();
    await expect(page.getByRole('columnheader', { name: 'Status' })).toBeVisible();
  });

  test('sidebar navigation works across current admin sections', async ({ page }) => {
    await page.goto('/admin/overview');

    await expect(
      page.getByRole('heading', { level: 1, name: 'Overview' }),
    ).toBeVisible();

    await page.getByRole('link', { name: 'Users' }).click();
    await page.waitForURL('/admin/users');
    await expect(
      page.getByRole('heading', { level: 1, name: 'Users' }),
    ).toBeVisible();

    await page.getByRole('link', { name: 'Jobs' }).click();
    await page.waitForURL((url) => url.pathname === '/admin/jobs');
    await expect(
      page.getByRole('heading', { level: 1, name: 'Jobs' }),
    ).toBeVisible();

    await page.getByRole('link', { name: 'Audit Log' }).click();
    await page.waitForURL('/admin/audit');
    await expect(
      page.getByRole('heading', { level: 1, name: 'Audit Logs' }),
    ).toBeVisible();

    await page.getByRole('link', { name: 'Published Maps' }).click();
    await page.waitForURL('/admin/shared-maps');
    await expect(
      page.getByRole('heading', { level: 1, name: 'Published Maps' }),
    ).toBeVisible();

    await page.locator('a[href="/admin/settings/map"]').click();
    await page.waitForURL('/admin/settings/map');
    await expect(
      page.getByRole('heading', { level: 1, name: 'Map', exact: true }),
    ).toBeVisible();
  });
});
