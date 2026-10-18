/**
 * Canonical-form origin normalization for SharePanel chip input.
 *
 * Mirrors backend `_normalize_origin` (`backend/app/modules/embed_tokens/schemas.py`)
 * so the chip shown after pressing Enter equals the string the backend persists
 * after PATCH, avoiding a flash of non-canonical text.
 *
 * CSP invariant: `*` is NEVER a valid origin. `normalizeOrigin('*')` throws
 * `WildcardOriginError`.
 */

/** Thrown when the input is the wildcard `*` — CSP `frame-ancestors` must never contain `*`. */
export class WildcardOriginError extends Error {
  constructor() {
    super('Wildcard origin not allowed');
    this.name = 'WildcardOriginError';
  }
}

/** Thrown when the input is empty, whitespace-only, or cannot be parsed as a URL. */
export class InvalidOriginError extends Error {
  constructor(input: string) {
    super(`Invalid origin: ${JSON.stringify(input)}`);
    this.name = 'InvalidOriginError';
  }
}

/**
 * Normalizes an origin string to canonical form, matching backend
 * `_normalize_origin`: trim, reject `*` and empty input, prepend `https://` when
 * no scheme is present, parse with WHATWG `new URL()`, lowercase scheme and
 * host, strip default ports, and discard path, query and fragment.
 *
 * @throws {WildcardOriginError} if input is `*`, starts with `*`, or the parsed hostname contains `*`
 * @throws {InvalidOriginError} if input is empty/whitespace or unparseable
 */
export function normalizeOrigin(input: string): string {
  const trimmed = input.trim();

  if (trimmed === '*' || trimmed.startsWith('*')) {
    throw new WildcardOriginError();
  }

  if (trimmed === '') {
    throw new InvalidOriginError(input);
  }

  // Add scheme so the WHATWG parser can resolve hostname.
  const withScheme = trimmed.includes('://') ? trimmed : `https://${trimmed}`;

  let parsed: URL;
  try {
    parsed = new URL(withScheme);
  } catch {
    throw new InvalidOriginError(input);
  }

  if (!parsed.hostname) {
    throw new InvalidOriginError(input);
  }

  // A wildcard in the parsed hostname catches `https://*.example.com`, which the
  // early startsWith('*') check misses.
  if (parsed.hostname.includes('*')) {
    throw new WildcardOriginError();
  }

  const scheme = parsed.protocol.replace(/:$/, '').toLowerCase(); // drop trailing ':'
  const host = parsed.hostname.toLowerCase();

  // The WHATWG parser already strips default ports; the explicit guard defends
  // against parser changes.
  let port = parsed.port; // '' when default for scheme
  if (
    (scheme === 'http' && port === '80') ||
    (scheme === 'https' && port === '443')
  ) {
    port = '';
  }

  if (port !== '') {
    return `${scheme}://${host}:${port}`;
  }
  return `${scheme}://${host}`;
}
