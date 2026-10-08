import fs from 'fs';
import path from 'path';
import { test as base } from '@playwright/test';

export * from '@playwright/test';

/** The admin session auth.setup.ts saves for the authenticated projects. */
export const AUTH_FILE = path.join(__dirname, '../../playwright/.auth/user.json');

/** Where auth.setup.ts keeps the API access token for a saved session. */
export function tokenFileFor(authFile: string): string {
  return authFile.replace(/\.json$/, '.token.json');
}

/** Bearer token for API calls made outside the browser as the saved admin. */
export function getAuthToken(): string {
  const raw = fs.readFileSync(tokenFileFor(AUTH_FILE), 'utf-8');
  const token = (JSON.parse(raw) as { token?: unknown }).token;
  if (typeof token !== 'string' || !token) {
    throw new Error(`No API token in ${tokenFileFor(AUTH_FILE)}; run the setup project`);
  }
  return token;
}

/**
 * The app recovers its access token from the refresh cookie on every page
 * load, and each recovery rotates the cookie. Presenting a rotated cookie again
 * after the server's grace window revokes the whole session, so every test
 * starts from the cookie the previous test left: a context opened from the
 * saved session writes its cookies back when the test ends.
 */
export const test = base.extend({
  context: async ({ context, storageState }, use) => {
    await use(context);
    if (typeof storageState === 'string' && path.resolve(storageState) === AUTH_FILE) {
      await context.storageState({ path: AUTH_FILE });
    }
  },
});
