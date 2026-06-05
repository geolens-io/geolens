// Capture-time redaction for the in-app problem reporter.
//
// Everything that enters the report ring buffer passes through redact() FIRST,
// so a leaked credential never reaches the buffer, the on-screen technical
// details, the clipboard, or a (public) GitHub issue body. Redacting at capture
// time — not at send time — means there is no live, un-redacted copy a user
// could accidentally copy out of the panel.
//
// This is defense-in-depth scrubbing of the common credential/PII shapes that
// show up in console/network/maplibre noise. It is intentionally conservative
// (over-redact rather than leak); it is NOT a guarantee that no sensitive value
// can ever appear, so the review step still tells the user what is attached.

interface RedactionRule {
  pattern: RegExp;
  replacement: string;
}

// Keys whose values are credentials / session secrets. Matched case-insensitively
// as either `key=value` (query strings, log lines) or `key: value` (JSON / object
// literals), with the value optionally quoted. `sig` covers signed-tile URLs;
// the session names cover server-set cookies that surface in error bodies.
const SENSITIVE_KEYS = [
  'password',
  'passwd',
  'pwd',
  'api_key',
  'apikey',
  'access_token',
  'refresh_token',
  'token',
  'secret',
  'sig',
  'signature',
  'sessionid',
  'session_id',
  'jsessionid',
  'phpsessid',
  'sid',
  'cookie',
].join('|');

const RULES: RedactionRule[] = [
  // JWTs (header.payload.signature, base64url). Auth tokens are this shape.
  { pattern: /\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}/g, replacement: '[redacted-token]' },
  // Authorization headers: `Bearer <token>` / `Basic <base64>`. Handled before
  // the key=value rule because the scheme + space-separated credential shape
  // would otherwise leak the part after the space.
  { pattern: /Bearer\s+[A-Za-z0-9._~+/=-]+/gi, replacement: 'Bearer [redacted]' },
  { pattern: /Basic\s+[A-Za-z0-9+/=]+/gi, replacement: 'Basic [redacted]' },
  // <sensitive-key>=value or <sensitive-key>: value (value optionally quoted).
  // The \b before the key keeps `token=` from matching the tail of unrelated
  // keys like csrf_token=; alternation order lets access_token/signature win
  // over their token/sig prefixes.
  {
    pattern: new RegExp(`\\b(${SENSITIVE_KEYS})(["']?\\s*[:=]\\s*["']?)[^\\s"'\`&,}\\])]+`, 'gi'),
    replacement: '$1$2[redacted]',
  },
  // Share / embed tokens that live in the URL PATH, not a query param:
  // /m/<token>, /embed/<token>, /share/<token>. These are bearer-equivalent
  // access secrets for public/shared maps.
  { pattern: /\/(m|embed|share)\/[A-Za-z0-9._~-]+/gi, replacement: '/$1/[redacted]' },
  // Email addresses.
  { pattern: /[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/g, replacement: '[redacted-email]' },
];

/**
 * Strip credentials and PII from an arbitrary string. Safe on any input —
 * non-string values are coerced, and a throwing regex never propagates.
 */
export function redact(value: unknown): string {
  let text = typeof value === 'string' ? value : String(value ?? '');
  try {
    for (const rule of RULES) {
      text = text.replace(rule.pattern, rule.replacement);
    }
  } catch {
    // A malformed input should never break capture — fall back to the raw text.
  }
  return text;
}
