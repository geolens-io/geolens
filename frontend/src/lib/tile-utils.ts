import { getEnvConfig } from '@/lib/env';

/**
 * Resolve the tile base URL from env config or tile config CDN setting.
 */
export function resolveTileBaseUrl(
  tileConfig?: { cdn_base_url?: string | null } | null,
): string | undefined {
  return getEnvConfig().TILE_BASE_URL || tileConfig?.cdn_base_url || undefined;
}

/**
 * builder-audit #338 P1-01: the single MVT `source-layer` name helper.
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
 * `extraCols` (2026-05-18): runtime opt-in column names that any
 * layer rendering from this source needs at all zoom levels —
 * typically data-driven styling columns (`style_config.column`,
 * heatmap weight column, etc.). Without these, Phase 269 H-23's
 * z<10 attribute budget strips the data from MVT tiles and
 * data-driven paint expressions fall to their default branch.
 * Names are joined with a comma and sorted for cache-key stability;
 * the server validates each against the dataset's column_info.
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
  options: { clusterRadius?: number; clusterMaxZoom?: number } = {},
  extraCols?: string[] | null,
): string {
  const base = tileBaseUrl
    ? tileBaseUrl.replace(/\/$/, '')
    : `${window.location.origin}/api`;
  const url = `${base}/tiles/clusters/${getMvtSourceLayerName(tableName)}/{z}/{x}/{y}.pbf`;
  // fix(#403): unclustered features (past cluster_max_zoom / single-point
  // buckets) need the data-driven styling + popup columns projected, exactly
  // like the plain vector path — without cols= the server used to emit
  // attribute-less features and categorical paint/popups silently broke.
  const cols = normalizeExtraCols(extraCols);
  return appendTileParams(url, tileToken, tileVersion, {
    cluster_radius: options.clusterRadius,
    cluster_max_zoom: options.clusterMaxZoom,
    ...(cols ? { cols } : {}),
  });
}
