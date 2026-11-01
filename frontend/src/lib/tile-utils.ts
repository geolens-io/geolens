import { getEnvConfig } from '@/lib/env';
import { isEmbedViewer } from '@/lib/embed-context';
import { useAuthStore } from '@/stores/auth-store';

/**
 * Resolve the tile base URL from env config or tile config CDN setting.
 */
export function resolveTileBaseUrl(
  tileConfig?: { cdn_base_url?: string | null } | null,
): string | undefined {
  return getEnvConfig().TILE_BASE_URL || tileConfig?.cdn_base_url || undefined;
}

/**
 * First-party vs third-party request classification for map tile/style
 * requests, shared by all three map surfaces.
 *
 * First-party means our own origin or the configured tile CDN origin
 * (`cdn_base_url` / `TILE_BASE_URL`, via `resolveTileBaseUrl()`); self-hosted
 * deployments commonly serve tiles from a separate CDN origin. With no url,
 * default to first-party. A relative path (single leading slash) is always
 * first-party; a protocol-relative URL (`//host/path`) is normalized with the
 * current protocol before the origin check so it isn't misread as relative.
 */
export function isThirdPartyTileUrl(
  url: string | undefined,
  tileConfig?: { cdn_base_url?: string | null } | null,
): boolean {
  if (!url) return false;
  if (url.startsWith('/') && !url.startsWith('//')) return false;
  try {
    const normalized = url.startsWith('//') ? `${window.location.protocol}${url}` : url;
    const requestOrigin = new URL(normalized, window.location.origin).origin;
    if (requestOrigin === window.location.origin) return false;
    const tileBaseUrl = resolveTileBaseUrl(tileConfig);
    if (tileBaseUrl) {
      try {
        if (requestOrigin === new URL(tileBaseUrl, window.location.origin).origin) return false;
      } catch {
        // Malformed configured tile base URL: classify as third-party.
      }
    }
    return true;
  } catch {
    return false;
  }
}

interface TileTransformRequestOptions {
  /** Viewer embed surface: attach `X-Embed-Token` to first-party requests. */
  embedToken?: string;
  /** Read the CURRENT tile config at request time (pass a ref-reader so a
   *  late-arriving `cdn_base_url` is honored without re-registering). */
  getTileConfig?: () => { cdn_base_url?: string | null } | null | undefined;
}

/** A site-relative tile URL made absolute against this page, as MapLibre requests it. */
export function absoluteTileUrl(url: string): string {
  return url.startsWith('/') && !url.startsWith('//') ? `${window.location.origin}${url}` : url;
}

/**
 * Resolve site-relative URLs and attach credentials only to first-party requests.
 * Embed viewers never use the signed-in session, even without an embed token.
 * Other first-party raster requests use the session JWT.
 * First-party vector/cluster tiles use the registered protocol's bounded 429 retry.
 *
 * React MapLibre ignores changes to the transformRequest prop after mount, so
 * each map installs this callback with setTransformRequest in its load handler.
 */
export function buildTileTransformRequest(
  options: TileTransformRequestOptions = {},
): (url: string) => { url: string; headers?: Record<string, string> } {
  return (url: string) => {
    // Absolutify only site-relative paths: a `startsWith('http')` predicate would
    // origin-prefix other schemes, and transformRequest runs before MapLibre's
    // custom-protocol dispatch, so `pmtiles://…` would never reach its handler.
    const absUrl = absoluteTileUrl(url);
    const tileConfig = options.getTileConfig?.() ?? null;
    const headers: Record<string, string> = {};
    if (options.embedToken && !isThirdPartyTileUrl(url, tileConfig)) {
      headers['X-Embed-Token'] = options.embedToken;
    } else if (
      absUrl.includes('/raster-tiles/') &&
      !isThirdPartyTileUrl(url, tileConfig) &&
      !isEmbedViewer()
    ) {
      const token = useAuthStore.getState().token;
      if (token) headers.Authorization = `Bearer ${token}`;
    }
    const requestUrl =
      !isThirdPartyTileUrl(url, tileConfig) &&
      /^https?:/.test(absUrl) &&
      /\/tiles\/(?:clusters\/)?data\.[^/]+\/\d+\/\d+\/\d+\.pbf$/.test(
        new URL(absUrl).pathname,
      )
        ? `geolens-tile://${absUrl}`
        : absUrl;
    return Object.keys(headers).length > 0 ? { url: requestUrl, headers } : { url: requestUrl };
  };
}

/**
 * The single MVT `source-layer` name helper.
 *
 * The MapLibre vector source-layer name must match the layer name the tile
 * server emits inside the MVT payload AND the URL path used to sign tiles. The
 * route always uses the logical `data.<table>` segment, while multi-tenant
 * MVT payloads use the server-provided physical tenant-schema prefix. Passing
 * that prefix here keeps MapLibre aligned without leaking it into tile signing.
 */
export function getMvtSourceLayerName(
  tableName: string,
  sourceLayerPrefix: string | null | undefined = 'data',
): string {
  if (sourceLayerPrefix === null) {
    throw new Error('MVT source-layer prefix is unresolved');
  }
  return `${sourceLayerPrefix ?? 'data'}.${tableName}`;
}

/**
 * Return true only after tile config resolves without the backend's
 * multi-tenant fail-closed `null` sentinel. An omitted field stays compatible
 * with older single-tenant servers and uses the legacy `data` default.
 */
export function isMvtSourceLayerConfigReady(
  tileConfig: { mvt_source_layer_prefix?: string | null } | null | undefined,
): boolean {
  return tileConfig != null && tileConfig.mvt_source_layer_prefix !== null;
}

/**
 * Build a signed tile URL with query-param auth.
 * When tileToken is provided, appends sig/exp/scope as query params.
 * When tileToken is null (public dataset), returns URL without params.
 *
 * `extraCols`: runtime opt-in column names that any layer rendering from this
 * source needs at all zoom levels, typically data-driven styling columns. Without
 * them the z<10 attribute budget strips the data from MVT tiles and data-driven
 * paint expressions fall to their default branch. Names are joined with a comma
 * and sorted for cache-key stability; the server validates each against the
 * dataset's column_info.
 */
export function buildSignedTileUrl(
  tableName: string,
  tileToken: { sig: string; exp: number; scope: string } | null,
  tileBaseUrl?: string | null,
  tileVersion?: string | number | null,
  extraCols?: string[] | null,
): string {
  const base = tileBaseUrl
    ? tileBaseUrl.replace(/\/$/, '')
    : `${window.location.origin}/api`;
  const url = `${base}/tiles/${getMvtSourceLayerName(tableName)}/{z}/{x}/{y}.pbf`;
  const cols = normalizeExtraCols(extraCols);
  return appendTileParams(url, tileToken, tileVersion, cols ? { cols } : {});
}

/** Sort + dedupe + filter falsy entries so the same set always serializes to
 *  the same `cols=` query value (cache-key stability). Returns null when the
 *  set is empty so the URL builder can omit the param. */
function normalizeExtraCols(extraCols?: string[] | null): string | null {
  if (!extraCols || extraCols.length === 0) return null;
  const set = new Set<string>();
  for (const c of extraCols) {
    if (typeof c === 'string' && c.trim()) set.add(c.trim());
  }
  if (set.size === 0) return null;
  return Array.from(set).sort().join(',');
}

function appendTileParams(
  url: string,
  tileToken: { sig: string; exp: number; scope: string } | null,
  tileVersion?: string | number | null,
  extraParams: Record<string, string | number | null | undefined> = {},
) {
  const params: string[] = [];
  if (tileToken) {
    params.push(`sig=${tileToken.sig}`, `exp=${tileToken.exp}`, `scope=${tileToken.scope}`);
  }
  for (const [key, value] of Object.entries(extraParams)) {
    if (value == null) continue;
    params.push(`${key}=${encodeURIComponent(String(value))}`);
  }
  if (tileVersion) {
    params.push(`_v=${encodeURIComponent(tileVersion)}`);
  }
  return params.length > 0 ? `${url}?${params.join('&')}` : url;
}

export function buildClusterTileUrl(
  tableName: string,
  tileToken: { sig: string; exp: number; scope: string } | null,
  tileBaseUrl?: string | null,
  tileVersion?: string | number | null,
  options: { clusterRadius?: number; clusterMaxZoom?: number; filter?: string } = {},
  extraCols?: string[] | null,
): string {
  const base = tileBaseUrl
    ? tileBaseUrl.replace(/\/$/, '')
    : `${window.location.origin}/api`;
  const url = `${base}/tiles/clusters/${getMvtSourceLayerName(tableName)}/{z}/{x}/{y}.pbf`;
  // Unclustered features need the data-driven styling + popup columns projected,
  // like the plain vector path; without cols= the server emits attribute-less
  // features and categorical paint/popups break.
  const cols = normalizeExtraCols(extraCols);
  return appendTileParams(url, tileToken, tileVersion, {
    cluster_radius: options.clusterRadius,
    cluster_max_zoom: options.clusterMaxZoom,
    filter: options.filter,
    ...(cols ? { cols } : {}),
  });
}

/**
 * Reload every raster/DEM source's tiles after the session JWT has been renewed.
 *
 * Renewing the credential isn't enough: MapLibre resumes its tile fetches the
 * moment the tab is visible, racing the refresh, so some raster requests go out
 * with the old Bearer and 401. A raster descriptor doesn't change across a
 * refresh (auth rides the Authorization header), so nothing in the
 * token→setTiles plumbing retries them and the map keeps holes until the user pans.
 *
 * `refreshTiles` is MapLibre's reload-in-place API (it survives a paused
 * TileManager) and needs no URL change, so this is idempotent and safe to call
 * when nothing failed.
 */
export function refreshRasterTileSources(map: MaplibreMapLike | null | undefined): number {
  if (!map) return 0;
  let sources: Record<string, { type?: string }> | undefined;
  try {
    sources = map.getStyle?.()?.sources as Record<string, { type?: string }> | undefined;
  } catch {
    return 0; // style torn down mid-refresh
  }
  let refreshed = 0;
  for (const [sourceId, source] of Object.entries(sources ?? {})) {
    if (source?.type !== 'raster' && source?.type !== 'raster-dem') continue;
    try {
      map.refreshTiles?.(sourceId);
      refreshed += 1;
    } catch {
      /* source removed between the read and the refresh */
    }
  }
  return refreshed;
}

/** The structural subset of the MapLibre map that `refreshRasterTileSources` uses. */
interface MaplibreMapLike {
  getStyle?: () => { sources?: Record<string, unknown> } | undefined;
  refreshTiles?: (sourceId: string) => void;
}

/**
 * The row `gid` of a feature picked from a vector tile. The tile server writes
 * each feature's `gid` as its MVT feature id, so MapLibre reports it as
 * `feature.id`; undefined for anything else, such as a cluster or a feature
 * whose id is not a safe integer.
 */
export function featureGid(feature: { id?: unknown }): number | undefined {
  return typeof feature.id === 'number' && Number.isSafeInteger(feature.id) ? feature.id : undefined;
}
