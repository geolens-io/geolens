import fs from 'fs';
import path from 'path';
import { test as base, type TestInfo } from '@playwright/test';

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

const REFRESH_WINDOW_MS = 60_000;
/** Refreshes a test may start with, leaving the rest of the endpoint's 30 per minute per IP to the test itself. */
const REFRESH_START_BUDGET = 12;
// On disk because a failed test restarts the worker while the API's bucket keeps counting.
const REFRESH_LOG = path.join(path.dirname(AUTH_FILE), 'refresh-times.json');

function readRefreshTimes(): number[] {
  try {
    const parsed: unknown = JSON.parse(fs.readFileSync(REFRESH_LOG, 'utf-8'));
    const cutoff = Date.now() - REFRESH_WINDOW_MS;
    return Array.isArray(parsed) ? parsed.filter((t): t is number => typeof t === 'number' && t > cutoff) : [];
  } catch {
    return [];
  }
}

function recordRefresh(): void {
  fs.writeFileSync(REFRESH_LOG, JSON.stringify([...readRefreshTimes(), Date.now()]));
}

async function waitForRefreshBudget(testInfo: TestInfo): Promise<void> {
  for (;;) {
    const refreshTimes = readRefreshTimes();
    if (refreshTimes.length < REFRESH_START_BUDGET) return;
    const waitMs = refreshTimes[0] + REFRESH_WINDOW_MS - Date.now() + 100;
    testInfo.setTimeout(testInfo.timeout + waitMs);
    await new Promise((resolve) => setTimeout(resolve, waitMs));
  }
}

/**
 * The app recovers its access token from the refresh cookie on every page
 * load, and each recovery rotates the cookie. Presenting a rotated cookie again
 * after the server's grace window revokes the whole session, so every test
 * starts from the cookie the previous test left: a context opened from the
 * saved session writes its cookies back when the test ends.
 */
export const test = base.extend({
  context: async ({ context, storageState }, use, testInfo) => {
    const shared = typeof storageState === 'string' && path.resolve(storageState) === AUTH_FILE;
    // The same refreshes renew the access token API calls from Node use, which
    // would otherwise expire partway through a long serial run.
    if (shared) {
      // Every page load spends one refresh. A 429 leaves the SPA holding a
      // stored user but no access token, so capability-gated UI such as the
      // Admin menu item never renders; staying under the limit is the only fix.
      await waitForRefreshBudget(testInfo);
      context.on('response', (response) => {
        if (!/\/auth\/refresh\/?$/.test(new URL(response.url()).pathname)) return;
        recordRefresh();
        if (!response.ok()) return;
        void response
          .json()
          .then((body: { access_token?: unknown }) => {
            if (typeof body.access_token !== 'string') return;
            fs.writeFileSync(tokenFileFor(AUTH_FILE), JSON.stringify({ token: body.access_token }), { mode: 0o600 });
          })
          .catch(() => {});
      });
    }
    await use(context);
    if (shared) await context.storageState({ path: AUTH_FILE });
  },
});
