import type { TileConfig } from '@/api/settings';

// Mirrors _LOCALHOST_HOSTS in backend/app/modules/embed_tokens/service.py.
// `new URL('http://[::1]:8080').hostname` keeps the brackets that Python's
// urlparse strips, so both spellings are listed.
const LOOPBACK_HOSTS = new Set(['localhost', '127.0.0.1', '::1', '[::1]']);

function isLoopbackOrigin(url: string): boolean {
  try {
    return LOOPBACK_HOSTS.has(new URL(url).hostname.toLowerCase());
  } catch {
    return false;
  }
}

/**
 * The deployment's public origin, but only when it is one this deployment can
 * actually be reached at. Null otherwise — including when it is *set to the
 * wrong thing*, which is the case a null check cannot see.
 *
 * fix(#1548 review r4): "configured" is not a boolean. `PUBLIC_APP_URL` has a
 * third state — present, non-null, and wrong — because both compose files
 * inject `${PUBLIC_APP_URL:-http://localhost:8080}` and `/settings/tile-config/`
 * hands that back as a perfectly good-looking string. An operator who never set
 * the variable, which is the default install, gets `http://localhost:8080` while
 * being reached at https://maps.example.com.
 *
 * So the test is not "is it set" but "is it somewhere a viewer could open".
 * The one origin this browser knows is reachable is its own, and that gives the
 * discriminator: a loopback configured origin is untrustworthy exactly when the
 * browser is NOT itself on loopback. That is the same predicate
 * `assert_domain_lock_is_enforceable` applies server-side (a real, non-loopback
 * request origin against an all-loopback set of self-origins), so the two agree
 * about which deployments are misconfigured — deliberately, since a UI that
 * withheld a snippet the API would have accepted, or the reverse, is the
 * two-readers-of-one-policy bug this PR started as.
 *
 * A genuine localhost install is not caught: there the browser is on loopback
 * too, the value is right, and it is returned.
 *
 * CALLERS MUST SPLIT ON WHAT FAILURE COSTS, and the split is why this returns
 * null rather than falling back for you:
 *
 * - An ordinary share link or unrestricted embed should fall back to the
 *   current origin. It is a serving origin even when it is not the canonical
 *   public one, so the link still opens; a localhost URL opens for nobody.
 *   These worked before any of this and must not start failing now.
 * - A DOMAIN-LOCKED embed must not fall back. There a wrong origin does not
 *   degrade: the shell loads, its own API calls carry an origin the backend
 *   does not recognize as first-party, and the map stays empty with nothing
 *   said. Withhold the snippet and name PUBLIC_APP_URL instead.
 *
 * `public_app_url` comes from `/settings/tile-config/`, whose own description
 * calls it "the browser-facing app URL used for share links". A configured
 * sub-path (`https://example.com/geolens`) is preserved — only a trailing slash
 * is trimmed — because it is part of where the app lives. The backend compares
 * origins with the path already dropped, so the two still agree.
 */
export function getPublicAppBaseUrl(
  tileConfig: Pick<TileConfig, 'public_app_url'> | null | undefined,
  currentOrigin: string,
): string | null {
  const base = tileConfig?.public_app_url?.trim().replace(/\/+$/, '');
  if (!base) return null;
  if (isLoopbackOrigin(base) && !isLoopbackOrigin(currentOrigin)) return null;
  return base;
}

/**
 * The origin to build an ordinary share link or unrestricted embed from.
 *
 * Prefers the configured public origin, because a URL someone else opens should
 * name the address people use to reach GeoLens rather than whatever hostname
 * this admin happens to be on. Falls back to the current origin when there is
 * no trustworthy configured value, since a link that opens beats a correct-
 * looking one that does not.
 */
export function getShareableBaseUrl(
  tileConfig: Pick<TileConfig, 'public_app_url'> | null | undefined,
  currentOrigin: string,
): string {
  return getPublicAppBaseUrl(tileConfig, currentOrigin) ?? currentOrigin;
}
