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
 *  - `malformed`         present but not a usable HTTP(S) URL — wrong scheme,
 *                        no host, or carrying a query or fragment that every
 *                        caller here would append a path after. Reachable from
 *                        the environment, which the backend `Settings` field
 *                        accepts as a raw string without parsing it. See
 *                        `parseUsablePublicUrl` for the full rule.
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

/**
 * Is this a value a browser could actually be sent to?
 *
 * fix(#1548 review r8): ONE shape rule for `PUBLIC_APP_URL` — an absolute
 * HTTP(S) URL, with a host, and no query or fragment. The backend states the
 * same rule in `is_usable_public_origin` (backend/app/core/public_urls.py), and
 * `__tests__/public-app-url-shape.cases.json` is the single case table both are
 * tested against, because two independent validators for one setting is exactly
 * the arrangement that let each side learn about a different invalid shape.
 *
 * Each clause earns its place:
 *
 *  - SCHEME, checked explicitly rather than inferred from a parse success:
 *    `new URL('mailto:x')` and `new URL('javascript:alert(1)')` both parse
 *    happily. On the backend the same values are worse than useless — its
 *    normalizer prepends `https://` and turns `ftp://maps.example.com` into the
 *    plausible non-loopback origin `https://ftp:`.
 *  - HOST, because `https://?x` parses with an empty hostname.
 *  - NO QUERY OR FRAGMENT, because every caller here APPENDS to this value:
 *    `${base}/m/${token}` against `https://maps.example.com?tenant=a` puts the
 *    path inside the query string, and against `...#section` puts it after the
 *    fragment. Either way the copied link and the iframe src are unopenable.
 *
 * Returns the parsed URL so callers can compare origins without parsing twice.
 */
function parseUsablePublicUrl(url: string): URL | null {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return null;
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return null;
  if (!parsed.hostname) return null;
  if (parsed.search || parsed.hash) return null;
  // fix(#1548 review r9/r10): three refusals, all on the RAW string rather than
  // on `parsed`, because this parser has already decoded and punycoded by the
  // time we could look — the raw string is the only view Python can compare
  // against identically.
  //
  //  - PERCENT-ENCODING: this parser decodes `%6D` to `m`; Python's urlsplit
  //    leaves it literal.
  //  - BACKSLASH: `https://maps.example.com\@evil.com` is host `evil.com` here
  //    and host `maps.example.com\` in Python. An origin-confusion primitive,
  //    not a formatting nit.
  //  - NON-ASCII: this parser punycodes per WHATWG/UTS #46, while Python's
  //    built-in idna codec is IDNA2003 and maps `faß.de` to `fass.de` where a
  //    browser sends `xn--fa-hia.de`. Rather than approximate one from the
  //    other — a NEAR match denies every request while looking correct — an
  //    internationalized domain must be configured in its punycode form, which
  //    is what the browser sends anyway.
  if (url.includes('%') || url.includes('\\')) return null;
  // Code-point iteration, matching Python's str.isascii(); a character-class
  // regex here would need a no-control-regex suppression to say the same thing.
  if ([...url].some((c) => (c.codePointAt(0) ?? 0) > 127)) return null;
  return parsed;
}

/**
 * The browser's own spelling of a usable value, or null.
 *
 * fix(#1548 review r9/r10): the configured value and the origin a browser
 * presents have to be the same STRING, not merely the same place. Userinfo is
 * never sent, a default port is never sent, and the host is lowercased — so
 * storing the operator's spelling meant the domain lock was issued and then
 * missed on every request. `URL.origin` normalizes all of that, and the backend
 * does the same in `_normalize_origin`. An internationalized host is refused
 * upstream rather than converted, so no IDNA translation happens here.
 *
 * A configured sub-path is preserved, since it is part of where the app lives
 * and both sides drop it before comparing origins.
 */
function canonicalizePublicUrl(url: string): string | null {
  const parsed = parseUsablePublicUrl(url);
  if (parsed === null) return null;
  const path = parsed.pathname.replace(/\/+$/, '');
  return `${parsed.origin}${path}`;
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

  // Shape FIRST, and it must pass. A previous revision asked `isLoopbackOrigin()`
  // and read its parse failure as "not loopback, therefore fine" — a narrower
  // predicate standing in for trust, so `not-a-url` was handed out in card links
  // and iframe sources. Trust is earned here, never inherited from another
  // check's failure mode.
  const parsed = parseUsablePublicUrl(raw);
  if (parsed === null) return { kind: 'malformed', value: raw };
  const canonical = canonicalizePublicUrl(raw);
  if (canonical === null) return { kind: 'malformed', value: raw };

  const currentIsLoopback = (() => {
    const current = parseUsablePublicUrl(currentOrigin);
    return current !== null && LOOPBACK_HOSTS.has(current.hostname.toLowerCase());
  })();

  if (LOOPBACK_HOSTS.has(parsed.hostname.toLowerCase()) && !currentIsLoopback) {
    return { kind: 'loopback-default', value: canonical };
  }

  return { kind: 'trusted', baseUrl: canonical };
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
 *  - A DOMAIN-LOCKED preview → `getLockedPreviewBaseUrl`, which additionally
 *    requires the configured origin to BE the current one, because
 *    `frame-ancestors` judges the parent document. See its docstring.
 */
export function getPublicAppBaseUrl(
  tileConfig: Pick<TileConfig, 'public_app_url'> | null | undefined,
  currentOrigin: string,
): string | null {
  const state = resolvePublicAppUrl(tileConfig, currentOrigin);
  return state.kind === 'trusted' ? state.baseUrl : null;
}

/**
 * The base URL a DOMAIN-LOCKED preview may load from, or null if it cannot be
 * previewed here at all.
 *
 * fix(#1548 review r7): a locked preview has to satisfy TWO browser rules at
 * once, and for a split-horizon deployment nothing satisfies both.
 *
 *  1. Its API calls carry the SHELL's origin, and the backend accepts only the
 *     configured origin as first-party — so the shell must be loaded from the
 *     configured host.
 *  2. The shell is served with `frame-ancestors 'self' <customer origins>`
 *     (frontend/nginx.conf, built by `build_embed_frame_ancestors`), and CSP
 *     judges the PARENT document. Loaded from the public host but parented by a
 *     Share dialog on an internal hostname, the parent matches neither `'self'`
 *     — which resolves to the PUBLIC origin, not the admin's — nor the customer
 *     allowlist. The browser blocks the frame before a single API call runs.
 *
 * Earlier rounds each tried to find an origin satisfying both. There isn't one:
 * rule 1 fixes the child's origin and rule 2 then requires the parent to match
 * it. So the preview is offered only when the two are already the same origin,
 * and otherwise refused with an explanation. That is not a workaround — it is
 * the domain lock doing exactly what it was asked to do, to us.
 *
 * The comparison is by ORIGIN, so a configured sub-path
 * (`https://example.com/geolens` while the admin is at `https://example.com`)
 * still previews: CSP and the origin check both ignore the path.
 */
export function getLockedPreviewBaseUrl(
  tileConfig: Pick<TileConfig, 'public_app_url'> | null | undefined,
  currentOrigin: string,
): string | null {
  const baseUrl = getPublicAppBaseUrl(tileConfig, currentOrigin);
  if (baseUrl === null) return null;
  const configured = parseUsablePublicUrl(baseUrl);
  const current = parseUsablePublicUrl(currentOrigin);
  if (configured === null || current === null) return null;
  return configured.origin === current.origin ? baseUrl : null;
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
