import type { TileConfig } from '@/api/settings';

// Mirrors _LOCALHOST_HOSTS in backend/app/modules/embed_tokens/service.py.
// `new URL('http://[::1]:8080').hostname` keeps the brackets that Python's
// urlparse strips, so both spellings are listed.
const LOOPBACK_HOSTS = new Set(['localhost', '127.0.0.1', '::1', '[::1]']);

/**
 * Every state `PUBLIC_APP_URL` can be in, named.
 *
 * fix(#1548 review r6): this enumeration is the point. The setting has been
 * treated as a boolean three separate times on this PR — "is it set" — and each
 * time the case that was missed was a state nobody had written down. Listing
 * them here means the next reader sees all of them at once instead of
 * rediscovering one in review.
 *
 *  - `unset`             nothing configured, or blank.
 *  - `malformed`         present but not a usable HTTP(S) URL. Reachable from
 *                        the environment, which the backend `Settings` field
 *                        accepts as a raw string without parsing it.
 *  - `loopback-default`  a loopback URL while this browser is somewhere else.
 *                        Almost always the shipped compose default
 *                        `${PUBLIC_APP_URL:-http://localhost:8080}` left alone.
 *  - `trusted`           a real HTTP(S) origin we are willing to hand out.
 *
 * The fifth state — VALID BUT WRONG, a stale or mistyped public hostname — is
 * deliberately absent, because nothing here can detect it: it parses, it is not
 * loopback, and only DNS knows it no longer serves GeoLens. It is reported by
 * the backend at runtime instead (`embed_token_domain_lock_denied`), and a
 * share link built from it fails loudly rather than silently.
 */
export type PublicAppUrlState =
  | { kind: 'trusted'; baseUrl: string }
  | { kind: 'unset' }
  | { kind: 'malformed'; value: string }
  | { kind: 'loopback-default'; value: string };

function parseOrigin(url: string): URL | null {
  try {
    const parsed = new URL(url);
    // Scheme is checked explicitly rather than inferred from a parse success:
    // `new URL('mailto:x')` and `new URL('javascript:alert(1)')` both parse.
    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return null;
    return parsed;
  } catch {
    return null;
  }
}

/**
 * Classify the deployment's configured public app URL.
 *
 * The question is never "is it set" but "is it somewhere a viewer could open".
 * The one origin a browser knows is reachable is its own, and that gives the
 * discriminator for `loopback-default`: a loopback configured origin is
 * untrustworthy exactly when the browser is NOT itself on loopback. That is the
 * same predicate `assert_domain_lock_is_enforceable` applies server-side
 * (backend/app/modules/embed_tokens/service.py), so the UI and the API agree
 * about which deployments are misconfigured rather than each holding its own
 * opinion. A genuine localhost install is not caught: there the browser is on
 * loopback too, the value is right, and it is trusted.
 *
 * `public_app_url` comes from `/settings/tile-config/`, whose own description
 * calls it "the browser-facing app URL used for share links". A configured
 * sub-path (`https://example.com/geolens`) is preserved — only a trailing slash
 * is trimmed — because it is part of where the app lives. The backend compares
 * origins with the path already dropped, so the two still agree.
 */
export function resolvePublicAppUrl(
  tileConfig: Pick<TileConfig, 'public_app_url'> | null | undefined,
  currentOrigin: string,
): PublicAppUrlState {
  const raw = tileConfig?.public_app_url?.trim().replace(/\/+$/, '');
  if (!raw) return { kind: 'unset' };

  // Parse FIRST, and require the parse to succeed. A previous revision asked
  // `isLoopbackOrigin()` and read its parse failure as "not loopback, therefore
  // fine" — a narrower predicate standing in for trust, so `not-a-url` was
  // handed out in card links and iframe sources. Trust is earned here, never
  // inherited from another check's failure mode.
  const parsed = parseOrigin(raw);
  if (parsed === null) return { kind: 'malformed', value: raw };

  const currentIsLoopback = (() => {
    const current = parseOrigin(currentOrigin);
    return current !== null && LOOPBACK_HOSTS.has(current.hostname.toLowerCase());
  })();

  if (LOOPBACK_HOSTS.has(parsed.hostname.toLowerCase()) && !currentIsLoopback) {
    return { kind: 'loopback-default', value: raw };
  }

  return { kind: 'trusted', baseUrl: raw };
}

/**
 * The configured public origin when it can be trusted, else null.
 *
 * CALLERS MUST SPLIT ON WHO OPENS THE URL, and on what a wrong origin costs:
 *
 *  - Handed to someone else (copied link, /card twin, iframe snippet) → prefer
 *    this, falling back via `getShareableBaseUrl` where a wrong-but-serving
 *    origin still opens.
 *  - Opened by THIS browser (the "Open" button, an UNLOCKED preview) → use
 *    `window.location.origin` directly, not this. A public host routed only
 *    externally is a normal split-horizon deployment, and a local affordance
 *    pointed at it simply fails.
 *  - A DOMAIN-LOCKED preview → this, with no fallback. It is opened here AND
 *    must satisfy the lock, and only the configured origin does both. When this
 *    is null the preview cannot be shown at all, which is the feature working.
 */
export function getPublicAppBaseUrl(
  tileConfig: Pick<TileConfig, 'public_app_url'> | null | undefined,
  currentOrigin: string,
): string | null {
  const state = resolvePublicAppUrl(tileConfig, currentOrigin);
  return state.kind === 'trusted' ? state.baseUrl : null;
}

/**
 * The origin to build an ordinary share link or unrestricted embed from.
 *
 * Prefers the configured public origin, because a URL someone else opens should
 * name the address people use to reach GeoLens rather than whatever hostname
 * this admin happens to be on. Falls back to the current origin for every
 * untrusted state, since a link that opens beats a correct-looking one that
 * does not — and `loopback-default` is the DEFAULT install, where these links
 * worked before any of this.
 */
export function getShareableBaseUrl(
  tileConfig: Pick<TileConfig, 'public_app_url'> | null | undefined,
  currentOrigin: string,
): string {
  return getPublicAppBaseUrl(tileConfig, currentOrigin) ?? currentOrigin;
}
