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

// One hostname label as the server's STD3 check allows it, after the parser
// has lower-cased the host and turned an IDN into punycode.
const HOST_LABEL = /^(?!-)[a-z0-9-]{1,63}(?<!-)$/;

/**
 * Whether `value` is an absolute http(s) URL the server's privacy-link shape
 * check also accepts: no credentials, a DNS host or IP literal written in the
 * form a browser keeps.
 */
export function isSafeHttpUrl(value: string | null | undefined): value is string {
  // A browser reads a backslash as a slash, so `host\@other` would open `host`.
  if (typeof value !== 'string' || !HTTP_URL_PATTERN.test(value) || WHITESPACE_OR_CONTROL.test(value) || value.includes('\\')) {
    return false;
  }
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    return false;
  }
  const host = url.hostname;
  if (host === '' || url.username || url.password) return false;
  if (host.startsWith('[')) return true;
  // A trailing dot names the DNS root; the server accepts it too.
  const labels = host.replace(/\.$/, '').split('.');
  // The parser decodes `%6d` and rewrites `0x7f.1`; the server refuses both,
  // so the host must appear in the address as written. An international host
  // is rewritten to punycode, which the server accepts too.
  const international = labels.some((label) => label.startsWith('xn--'));
  if (!international && !value.toLowerCase().startsWith(`${url.protocol}//${host}`)) return false;
  return labels.every((label) => HOST_LABEL.test(label));
}
