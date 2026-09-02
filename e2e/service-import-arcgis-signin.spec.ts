import { test, expect, type Page } from '@playwright/test';

/**
 * Lane A2 (service-auth wave): the ArcGIS sign-in method on the import
 * wizard's Service URL tab. The sign-in endpoint (lane A1,
 * POST /api/services/arcgis/signin/) is mocked here with page.route — it
 * mints a request-only token from a username and password, so this spec
 * never touches a real ArcGIS portal.
 *
 * Opens the panel the way the other import-adjacent specs do (the Create
 * menu, not a hard page.goto to a protected route): a hard goto on the
 * worktree Vite recipe (:5174) logs the session out mid-test.
 */

const ARCGIS_URL =
  'https://services6.arcgis.com/demoOrgId/arcgis/rest/services/Wildfire/FeatureServer/0';
const SERVICE_URL_PLACEHOLDER =
  'https://example.com/wfs, ArcGIS FeatureServer, or OGC API endpoint';

async function openArcGisSignin(page: Page) {
  await page.goto('/');
  await page.getByRole('button', { name: 'Create' }).click();
  await page.getByRole('menuitem', { name: 'Import Data' }).click();
  await page.getByRole('button', { name: 'Service URL' }).click();

  await page.getByPlaceholder(SERVICE_URL_PLACEHOLDER).fill(ARCGIS_URL);

  await page.getByRole('combobox', { name: 'Authentication' }).click();
  await page.getByRole('option', { name: 'Sign in with username and password' }).click();
}

test.describe('ArcGIS sign-in on the import wizard', () => {
  test('choosing sign in reveals the portal, username, and password fields', async ({ page }) => {
    await openArcGisSignin(page);

    await expect(page.getByLabel('Portal URL')).toBeVisible();
    await expect(page.getByLabel('Username', { exact: true })).toBeVisible();
    await expect(page.getByLabel('Password', { exact: true })).toBeVisible();

    // codex review #1757: services6.arcgis.com is an ArcGIS Online
    // feature-service host, not a portal, so the prefill is
    // www.arcgis.com (the backend's own D8 referer default), not the
    // service URL's own origin. Still editable.
    await expect(page.getByLabel('Portal URL')).toHaveValue('https://www.arcgis.com');
  });

  test('a rejected sign-in leaves the wizard on the same step with the message anchored to the credential block', async ({
    page,
  }) => {
    await page.route('**/api/services/arcgis/signin/', (route) =>
      route.fulfill({
        status: 400,
        json: {
          detail: {
            code: 'arcgis_signin_rejected',
            message: 'invalid credentials',
            field: 'credential',
          },
        },
      }),
    );

    await openArcGisSignin(page);
    await page.getByLabel('Username', { exact: true }).fill('e2e-user');
    await page.getByLabel('Password', { exact: true }).fill('wrong-password');
    await page.getByRole('button', { name: 'Sign in' }).click();

    const credentialBlock = page.getByTestId('arcgis-auth-block');
    await expect(credentialBlock.getByText(/ArcGIS did not accept that sign-in/)).toBeVisible();

    // Still on the same step: the URL probe input and its Probe button are
    // still here, unmoved to layer selection or anywhere else.
    await expect(page.getByPlaceholder(SERVICE_URL_PLACEHOLDER)).toHaveValue(ARCGIS_URL);
    await expect(page.getByRole('button', { name: 'Probe →' })).toBeVisible();
  });

  test('a successful mint clears the password and fills the token field', async ({ page }) => {
    await page.route('**/api/services/arcgis/signin/', (route) =>
      route.fulfill({
        json: {
          token: 'e2e-minted-token',
          expires_at: new Date(Date.now() + 60 * 60 * 1000).toISOString(),
        },
      }),
    );

    await openArcGisSignin(page);
    await page.getByLabel('Username', { exact: true }).fill('e2e-user');
    await page.getByLabel('Password', { exact: true }).fill('correct-password');
    await page.getByRole('button', { name: 'Sign in' }).click();

    await expect(page.getByLabel('Token or API key')).toHaveValue('e2e-minted-token');
    await expect(page.getByLabel('Password', { exact: true })).toHaveValue('');

    // codex review #1757 P1: a minted token must not survive the service
    // URL being pointed at a different origin.
    await page
      .getByPlaceholder(SERVICE_URL_PLACEHOLDER)
      .fill('https://services7.arcgis.com/other-org/arcgis/rest/services/Bar/FeatureServer');
    await expect(page.getByRole('combobox', { name: 'Authentication' })).toHaveText(
      'No authentication',
    );
  });

  // codex review #1757 round 2 P2: the credential fields sit inside the
  // outer form whose submit button is Probe, so pressing Enter used to
  // Probe the protected service instead of signing in.
  test('pressing Enter in the password field routes to sign-in, not Probe', async ({ page }) => {
    let probeCalled = false;
    await page.route('**/api/services/probe/', (route) => {
      probeCalled = true;
      return route.fulfill({ status: 500, json: { detail: 'Probe should not have been called' } });
    });
    await page.route('**/api/services/arcgis/signin/', (route) =>
      route.fulfill({
        json: {
          token: 'e2e-enter-token',
          expires_at: new Date(Date.now() + 60 * 60 * 1000).toISOString(),
        },
      }),
    );

    await openArcGisSignin(page);
    await page.getByLabel('Username', { exact: true }).fill('e2e-user');
    await page.getByLabel('Password', { exact: true }).fill('correct-password');
    await page.getByLabel('Password', { exact: true }).press('Enter');

    // getByLabel is flaky here specifically after an Enter-triggered
    // submit (unlike the button-click path in the test above); the id
    // selector is unambiguous.
    await expect(page.locator('#arcgis-minted-token')).toHaveValue('e2e-enter-token');
    expect(probeCalled).toBe(false);
  });
});
