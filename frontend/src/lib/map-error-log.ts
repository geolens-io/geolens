// fix(#755): the @vis.gl/react-maplibre wrapper subscribes the map `error`
// event unconditionally and, when the <Map> component has no `onError` prop,
// falls back to `console.error(e.error)` for every event — in parallel with
// each surface's own `map.on('error')` handler. For the 401/403 vector-tile
// case that handler already recovers (GUARD-03 cached-token re-sign and/or
// the #621 throttled token re-mint), the raw AJAXError therefore still hits
// the console and lands as an unsuppressed red row in the problem-report
// buffer next to the suppressed recovery warnings, making a recovered
// situation read as a breakage.
//
// Passing `logUnhandledMapError` as the <Map> `onError` prop keeps the
// wrapper's default log for everything else and drops ONLY that handled case.

/** Structural subset of MapLibre's ErrorEvent that this module inspects.
 * MapLibre attaches `status`/`url` to AJAXError instances raised by tile
 * fetches; plain style/runtime errors carry neither. */
export interface MapLibreErrorLike {
  error?: { message?: string; status?: number; url?: string };
}

/** True when `url` targets a first-party GeoLens tile endpoint: a relative or
 * same-origin `/tiles/` path (`/api/tiles/…`, including `/tiles/clusters/…`),
 * or a CDN-fronted tile URL still carrying our signed-tile `sig=` param.
 * Third-party basemap tile URLs (different origin, no GeoLens signature) and
 * raster `/raster-tiles/` paths do not match. */
function isFirstPartyTileUrl(url: string | undefined): boolean {
  if (!url || !url.includes('/tiles/')) return false;
  if (!/^https?:\/\//i.test(url)) return true;
  if (url.startsWith(`${window.location.origin}/`)) return true;
  return /[?&]sig=/.test(url);
}

/** True for a 401/403 on a first-party vector-tile request — the case every
 * map surface's own `error` handler owns end to end (re-sign, re-mint, or the
 * session-expired / embed-expired UX). */
export function isHandledTileAuthError(e: MapLibreErrorLike): boolean {
  const status = e.error?.status;
  if (status !== 401 && status !== 403) return false;
  return isFirstPartyTileUrl(e.error?.url);
}

/** `onError` prop for @vis.gl/react-maplibre's <Map>: replicate the wrapper's
 * default `console.error` fallback, except for handled first-party tile-auth
 * 401/403s, which log nothing — the surface's `map.on('error')` handler
 * recovers those and reports them (suppressed) where applicable. */
export function logUnhandledMapError(e: MapLibreErrorLike): void {
  if (isHandledTileAuthError(e)) return;
  console.error(e.error);
}
