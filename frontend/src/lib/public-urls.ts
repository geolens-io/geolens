import type { TileConfig } from '@/api/settings';

/**
 * Is a browser served from this hostname talking to its own machine?
 *
 * fix(#1555): this was a set of three exact spellings, mirroring a backend set
 * of three. Loopback is a RANGE — all of `127.0.0.0/8` — so `http://127.0.0.2`
 * was classified as a real public origin on both sides, and the deployment
 * offered a domain lock whose shell URL every recipient resolves to their own
 * machine. `is_loopback_host` in backend/app/core/public_urls.py states the
 * same rule for Python, and `public-app-url-shape.cases.json` holds the two to
 * the same answers.
 *
 * `*.localhost` counts: RFC 6761 §6.3 puts the whole zone on loopback and
 * browsers resolve it there, so `http://app.localhost` is the same mistake in
 * a subdomain.
 *
 * `URL.hostname` keeps the brackets on an IPv6 literal that Python's urlparse
 * strips, so they come off here before parsing.
 */
function isLoopbackHostname(hostname: string): boolean {
  const host = hostname.trim().toLowerCase().replace(/^\[|\]$/g, '');
  if (!host) return false;
  if (host === 'localhost' || host.endsWith('.localhost')) return true;
  // `::1` is compared exactly rather than expanded, because every caller has
  // already been through `parseUsablePublicUrl`, which requires the host to be
  // spelled the way this parser serializes it. `[0:0:0:0:0:0:0:1]` never
  // reaches here — it is refused as non-canonical, on both sides. An
  // IPv4-mapped literal cannot reach here either: that whole class is refused,
  // because Python spells `::ffff:7f00:1` as `::ffff:127.0.0.1` and this parser
  // spells `::ffff:127.0.0.1` as `::ffff:7f00:1`, so neither side can call the
  // other's form canonical (see `canonical_host_error`).
  if (host === '::1') return true;
  const octets = host.split('.');
  if (octets.length !== 4) return false;
  if (!octets.every((o) => /^\d{1,3}$/.test(o) && Number(o) <= 255)) return false;
  return octets[0] === '127';
}

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
  // fix(#1555): NO `/api` PATH. The persistent-setting validator has always
  // rejected an app URL that names the API base, and the environment path did
  // not — so `PUBLIC_APP_URL=https://maps.example.com/api` arrived here through
  // tile-config and built `/api/api/maps/...` card links and `/api/m/...`
  // iframe sources. `is_api_base_path` (backend/app/core/public_urls.py) is now
  // the one statement of it, and both entry points ask it.
  if (parsed.pathname.replace(/\/+$/, '').endsWith('/api')) return null;
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
  if (!hostIsAlreadyCanonical(url, parsed)) return null;
  return parsed;
}

/**
 * Is the host spelled the way this parser serializes it?
 *
 * fix(#1548 review r11): Python and the browser disagree about the canonical
 * spelling of numeric hosts, and the backend stores Python's. Measured:
 * `192.168.1` is `192.168.1` to urlsplit and `192.168.0.1` here; `010.0.0.1` is
 * read as OCTAL and becomes `8.0.0.1`; `0x7f.1` becomes `127.0.0.1`; an
 * uncompressed IPv6 literal is compressed. Each is a spelling the shell would
 * present while the stored self-origin said something else.
 *
 * This side has it easy: it can ask the browser parser and compare. The backend
 * has to state the rule outright — see `canonical_host_error` in
 * backend/app/core/public_urls.py, and note the trap recorded there, that
 * `192.168.1` round-trips through urlsplit unchanged, so a stability check
 * would pass it. The two methods are held to the same answers by
 * `__tests__/public-app-url-shape.cases.json`.
 *
 * Case is compared insensitively because both parsers lowercase, so an
 * uppercase host is not a disagreement. A trailing dot IS refused: both
 * preserve it, so it is a policy choice rather than a correctness one, and
 * `maps.example.com.` is a different origin from the one the operator means.
 */
function hostIsAlreadyCanonical(url: string, parsed: URL): boolean {
  const authority = url.slice(url.indexOf('//') + 2).split(/[/?#]/, 1)[0];
  // Drop userinfo, then the port — an IPv6 literal keeps its brackets, which is
  // also how `URL.hostname` reports it.
  const hostAndPort = authority.slice(authority.lastIndexOf('@') + 1);
  const written = hostAndPort.startsWith('[')
    ? hostAndPort.slice(0, hostAndPort.indexOf(']') + 1)
    : hostAndPort.split(':')[0];
  if (written.endsWith('.')) return false;
  // fix(#1555): an IPv4-MAPPED literal has no spelling both sides call
  // canonical. This parser renders `[::ffff:127.0.0.1]` as `[::ffff:7f00:1]`
  // and Python renders `::ffff:7f00:1` as `::ffff:127.0.0.1`, so each side
  // calls the other's output wrong: before this, `[::ffff:192.168.1.5]` was
  // accepted by the backend and refused here. Both refuse the class now — the
  // plain IPv4 form is unambiguous. Tested against `parsed.hostname`, which is
  // this parser's canonical spelling, so it catches the class rather than one
  // spelling of it; the pattern is the mapped block `::ffff:0:0/96`, which
  // always serializes as `::ffff:` plus exactly two hex groups.
  if (/^\[::ffff:[0-9a-f]{1,4}:[0-9a-f]{1,4}\]$/.test(parsed.hostname)) return false;
  return written.toLowerCase() === parsed.hostname.toLowerCase();
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
    return current !== null && isLoopbackHostname(current.hostname);
  })();

  if (isLoopbackHostname(parsed.hostname) && !currentIsLoopback) {
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
