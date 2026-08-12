import { API_BASE } from '@/lib/constants';

/**
 * GH-1302: how this browser talks to /auth/login and /auth/refresh/.
 *
 * The refresh token moves into an httpOnly cookie, which the browser will only
 * replay to the origin that set it. Both shipped deployments put the API on the
 * app's own origin — the dev Vite proxy (`/api` -> API, `rewrite` strips the
 * prefix) and the production nginx `location /api/` block — and `API_BASE`
 * defaults to the relative `/api`, so cookie mode is the normal path.
 *
 * A deployment that repoints `API_BASE_URL` at a different origin cannot use
 * the cookie (its refresh POST is cross-site, and `SameSite=Lax` withholds it),
 * so those installs stay on the pre-GH-1302 body-token flow rather than being
 * handed a credential the browser would never send back.
 */
export const AUTH_MODE_HEADER = 'X-GeoLens-Auth-Mode';
export const CSRF_HEADER = 'X-CSRF-Token';
export const CSRF_COOKIE_NAME = 'geolens_csrf';

export function cookieAuthAvailable(): boolean {
  if (typeof window === 'undefined') return false;
  // Relative base (the default) is same-origin by construction.
  if (!/^https?:\/\//i.test(API_BASE)) return true;
  try {
    return new URL(API_BASE, window.location.href).origin === window.location.origin;
  } catch {
    return false;
  }
}

export function readCsrfCookie(): string | null {
  if (typeof document === 'undefined') return null;
  for (const entry of document.cookie.split(';')) {
    const [name, ...rest] = entry.trim().split('=');
    if (name === CSRF_COOKIE_NAME) return decodeURIComponent(rest.join('='));
  }
  return null;
}

/**
 * Headers that opt this request into the cookie flow. Empty when cookie mode is
 * unavailable, which leaves the request byte-identical to the legacy call.
 */
export function cookieAuthHeaders(): Record<string, string> {
  if (!cookieAuthAvailable()) return {};
  const headers: Record<string, string> = { [AUTH_MODE_HEADER]: 'cookie' };
  const csrf = readCsrfCookie();
  // Absent on the very first login and on the one migrating refresh, where the
  // backend has no cookie to compare against and so does not require it.
  if (csrf) headers[CSRF_HEADER] = csrf;
  return headers;
}
