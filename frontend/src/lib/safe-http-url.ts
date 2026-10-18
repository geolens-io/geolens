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

export function isSafeHttpUrl(value: string | null | undefined): value is string {
  return typeof value === 'string' && HTTP_URL_PATTERN.test(value);
}
