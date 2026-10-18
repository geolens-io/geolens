// The @vis.gl/react-maplibre wrapper falls back to `console.error(e.error)` for
// every map `error` event when <Map> has no `onError` prop, in parallel with
// each surface's own `map.on('error')` handler. For a recovered 401/403
// vector-tile error that raw AJAXError would still land as an unsuppressed red
// row in the problem-report buffer. Passing `logUnhandledMapError` as `onError`
// keeps the default log for everything else and drops ONLY that handled case.

import { isSessionRenewalPending } from '@/hooks/use-tile-auth-recovery';

/** Structural subset of MapLibre's ErrorEvent that this module inspects.
 * MapLibre attaches `status`/`url` to AJAXError instances raised by tile
 * fetches; plain style/runtime errors carry neither. */
interface MapLibreErrorLike {
  error?: { message?: string; status?: number; url?: string };
}

/** True when `url` is a GeoLens raster/DEM tile request:
 * `/raster-tiles/{id}/tiles/{z}/{x}/{y}.png`.
 *
 * Its second `/tiles/` segment satisfies the first-party vector match below,
 * which would misclassify raster 401/403s as handled. Raster auth rides the
 * `Authorization` header from `setTransformRequest`, not the signed-tile `sig=`
 * param, so neither re-sign nor re-mint can cure a raster auth failure.
 *
 * Exported so the surfaces' `error` handlers agree with `isHandledTileAuthError`
 * on what "handled" means. */
export function isRasterTileUrl(url: string | undefined): boolean {
  return !!url && url.includes('/raster-tiles/');
}

/** True when `url` targets a first-party GeoLens tile endpoint: a relative or
 * same-origin `/tiles/` path (including `/tiles/clusters/…`), or a CDN-fronted
 * tile URL carrying our signed-tile `sig=` param. Third-party basemap tiles and
 * raster `/raster-tiles/` paths do not match. */
function isFirstPartyTileUrl(url: string | undefined): boolean {
  if (!url || !url.includes('/tiles/')) return false;
  if (isRasterTileUrl(url)) return false;
  if (!/^https?:\/\//i.test(url)) return true;
  if (url.startsWith(`${window.location.origin}/`)) return true;
  return /[?&]sig=/.test(url);
}

/** True for a 401/403 on a first-party vector-tile request, which every map
 * surface's own `error` handler owns end to end. */
export function isHandledTileAuthError(e: MapLibreErrorLike): boolean {
  const status = e.error?.status;
  if (status !== 401 && status !== 403) return false;
  return isFirstPartyTileUrl(e.error?.url);
}

/** The raster tile-auth case a session refresh can cure: a 401 (expired
 * credential). A 403 is an upstream denial that a fresh JWT does not change, so
 * suppressing it during a renewal would hide a real failure and leave a blank
 * map with no error overlay. */
export function isRefreshableRasterAuthError(e: MapLibreErrorLike): boolean {
  return e.error?.status === 401 && isRasterTileUrl(e.error?.url);
}

/** A 401/403 on a raster/DEM tile: the one tile-auth case NO surface can recover
 * (see `isRasterTileUrl`). Surfaces use it to skip their vector re-sign /
 * re-mint path so the failure surfaces once instead of as a suppressed
 * "recovered" entry beside an unsuppressed console row. */
export function isRasterTileAuthError(e: MapLibreErrorLike): boolean {
  const status = e.error?.status;
  if (status !== 401 && status !== 403) return false;
  return isRasterTileUrl(e.error?.url);
}

/** `onError` prop for @vis.gl/react-maplibre's <Map>: the wrapper's default
 * `console.error` fallback, except for handled first-party tile-auth 401/403s,
 * which the surface's `map.on('error')` handler recovers and reports (suppressed).
 *
 * A raster/DEM 401 is handled too, but only while a session renewal is in
 * flight: that renewal fixes it and the post-rotation reload retries the tiles.
 * Outside that window a raster auth failure is unrecoverable and still logs. */
export function logUnhandledMapError(e: MapLibreErrorLike): void {
  if (isHandledTileAuthError(e)) return;
  if (isRefreshableRasterAuthError(e) && isSessionRenewalPending()) return;
  console.error(e.error);
}
