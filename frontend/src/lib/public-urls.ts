import type { TileConfig } from '@/api/settings';

/**
 * The one place that knows where this deployment is publicly reachable.
 *
 * fix(#1548 review r3): every URL that leaves this browser — a share link
 * pasted into Slack, an iframe snippet a customer pastes on THEIR site, the
 * preview that stands in for it — must be built from the deployment's
 * configured public origin, never from `window.location.origin`.
 *
 * `window.location.origin` is whatever hostname the ADMIN happens to be using.
 * That is the wrong source for a URL someone else will open, and it is wrong
 * independently of domain locking: an operator who administers GeoLens over an
 * internal hostname copies a snippet pointing at an internal URL, which will
 * not resolve for the customer at all.
 *
 * It also silently breaks domain-locked embeds. The shell's own API calls carry
 * the shell's origin, and `_request_origin_is_allowed`
 * (backend/app/modules/embed_tokens/service.py) recognizes only the CONFIGURED
 * origin as first-party — so a snippet built from a different, equally real
 * hostname loads and then returns no layers. Building from the configured value
 * makes the two agree by construction, which is why the backend needs no second
 * validation path for it.
 *
 * Returns null when the deployment has not told us. Callers must surface that
 * rather than substituting the current origin: a snippet that looks right and
 * silently points somewhere private is worse than one the UI declines to emit.
 *
 * `public_app_url` is served by `/settings/tile-config/`, whose own description
 * calls it "the browser-facing app URL used for share links". A configured
 * sub-path (`https://example.com/geolens`) is preserved — only a trailing slash
 * is trimmed — because it is part of where the app lives. The backend compares
 * origins with the path already dropped, so the two still agree.
 */
export function getPublicAppBaseUrl(
  tileConfig?: Pick<TileConfig, 'public_app_url'> | null,
): string | null {
  const configured = tileConfig?.public_app_url?.trim();
  if (!configured) return null;
  return configured.replace(/\/+$/, '') || null;
}
