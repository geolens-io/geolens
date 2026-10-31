/**
 * Belt-and-braces client-side scheme guard for an operator-configured URL
 * rendered as a raw `<a href>` (privacy_url).
 *
 * The backend validates the same shape at admin write, at boot and at read time
 * (GET /settings/branding/ drops an unsafe stored value). This guard is not the
 * source of truth; it covers the rolling-upgrade window where an old API pod can
 * still serve a value written before those checks existed.
 */
const HTTP_URL_PATTERN = /^https?:\/\//i;
// A browser silently strips or re-encodes these, so the string it opens is not the one checked.
// eslint-disable-next-line no-control-regex -- control characters are the point
const WHITESPACE_OR_CONTROL = /[\s\u0000-\u001f\u007f]/;

export function isSafeHttpUrl(value: string | null | undefined): value is string {
  if (typeof value !== 'string' || !HTTP_URL_PATTERN.test(value) || WHITESPACE_OR_CONTROL.test(value)) return false;
  try {
    return new URL(value).hostname !== '';
  } catch {
    return false;
  }
}
