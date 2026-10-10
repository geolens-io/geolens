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

const RATE_WINDOW_MS = 60_000;

/**
 * Requests this run has sent to a per-IP rate-limited endpoint in the last
 * minute. The log is on disk because a failed test restarts the worker while
 * the API's bucket keeps counting.
 */
class RateBudget {
  private readonly file: string;

  /** `startBudget` is how many requests a test may start with; the rest of the endpoint's limit is left to the test itself. */
  constructor(name: string, private readonly startBudget: number) {
    this.file = path.join(path.dirname(AUTH_FILE), `${name}-times.json`);
  }

  private recent(): number[] {
    try {
      const parsed: unknown = JSON.parse(fs.readFileSync(this.file, 'utf-8'));
      const cutoff = Date.now() - RATE_WINDOW_MS;
      return Array.isArray(parsed) ? parsed.filter((t): t is number => typeof t === 'number' && t > cutoff) : [];
    } catch {
      return [];
    }
  }

  record(): void {
    fs.writeFileSync(this.file, JSON.stringify([...this.recent(), Date.now()]));
  }

  async waitForRoom(testInfo: TestInfo): Promise<void> {
    for (;;) {
      const times = this.recent();
      if (times.length < this.startBudget) return;
      const waitMs = times[0] + RATE_WINDOW_MS - Date.now() + 100;
      testInfo.setTimeout(testInfo.timeout + waitMs);
      await new Promise((resolve) => setTimeout(resolve, waitMs));
    }
  }
}

// Every page load spends one refresh (30 per minute per IP). A 429 leaves the SPA
// holding a stored user but no access token, so capability-gated UI such as the
// Admin menu item never renders.
const refreshBudget = new RateBudget('refresh', 12);

// Dataset and facet search share one 30 per minute bucket. A 429 renders as a
// failed catalog instead of the fixture the test expects.
const searchBudget = new RateBudget('search', 12);

/** Counts a search the test process sends outside the browser. */
export function recordSearchRequest(): void {
  searchBudget.record();
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
      await refreshBudget.waitForRoom(testInfo);
      await searchBudget.waitForRoom(testInfo);
      context.on('response', (response) => {
        const { pathname } = new URL(response.url());
        if (/^\/api\/search\/(datasets|facets)\/?$/.test(pathname)) searchBudget.record();
        if (!/\/auth\/refresh\/?$/.test(pathname)) return;
        refreshBudget.record();
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
