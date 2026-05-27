/**
 * Canonical-form origin normalization for SharePanel chip input (Plan 04).
 *
 * Mirrors backend `_normalize_origin` in
 * `backend/app/modules/embed_tokens/schemas.py:14-31` so the chip the user
 * sees after pressing Enter equals the string the backend persists after PATCH.
 * Eliminates Pitfall #8 (flash-of-non-canonical-text between optimistic render
 * and PATCH response).
 *
 * CSP invariant (ROADMAP SC #1, locked decision in 1137-CONTEXT.md):
 * `*` is NEVER a valid origin. `normalizeOrigin('*')` throws `WildcardOriginError`.
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
 * Normalizes an origin string to canonical form.
 *
 * Rules (matching backend `_normalize_origin`):
 * 1. Trim whitespace.
 * 2. Reject `*` with `WildcardOriginError`.
 * 3. Reject empty/whitespace with `InvalidOriginError`.
 * 4. Prepend `https://` if no scheme present.
 * 5. Parse with WHATWG `new URL()` — rethrow parse failures as `InvalidOriginError`.
 * 6. Lowercase scheme + host.
 * 7. Strip default ports (80 for http, 443 for https).
 * 8. Discard path, query, and fragment — return origin only.
 *
 * @throws {WildcardOriginError} if input is `*` or starts with `*`
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

  const scheme = parsed.protocol.replace(/:$/, '').toLowerCase(); // drop trailing ':'
  const host = parsed.hostname.toLowerCase();

  // WHATWG URL parser already strips default ports (port === '' for http:80, https:443).
  // We apply an explicit guard to defend against future parser changes (plan directive).
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

/**
 * Deduplicates an array of origin strings by canonical form.
 *
 * - Wildcard entries (`*`) are silently filtered out (not thrown).
 * - Invalid entries are silently filtered out.
 * - First-seen order is preserved for valid, non-duplicate entries.
 *
 * @param inputs Raw origin strings (may be unnormalized or include wildcards)
 * @returns Array of unique canonical origin strings
 */
export function dedupeOrigins(inputs: string[]): string[] {
  const seen = new Set<string>();
  const result: string[] = [];

  for (const input of inputs) {
    let canonical: string;
    try {
      canonical = normalizeOrigin(input);
    } catch (err) {
      if (err instanceof WildcardOriginError || err instanceof InvalidOriginError) {
        // Silently skip wildcards and invalid entries.
        continue;
      }
      throw err;
    }

    if (!seen.has(canonical)) {
      seen.add(canonical);
      result.push(canonical);
    }
  }

  return result;
}
