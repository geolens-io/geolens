/**
 * PRIV-1: belt-and-braces client-side scheme guard for an operator-configured
 * URL rendered as a raw `<a href>` (privacy_url).
 *
 * The backend already validates this three times — at admin write (PUT
 * /settings/), at boot (an unsafe env value refuses to start), and again at
 * read time (GET /settings/branding/ drops an unsafe stored value instead of
 * serving it) — all through the same shape check. This is not the source of
 * truth for "safe"; it exists for the rolling-upgrade window where an old
 * API pod can still be serving a value written before any of those checks
 * existed, and a frontend build with this guard should not trust it blindly.
 */
const HTTP_URL_PATTERN = /^https?:\/\//i;

export function isSafeHttpUrl(value: string | null | undefined): value is string {
  return typeof value === 'string' && HTTP_URL_PATTERN.test(value);
}
