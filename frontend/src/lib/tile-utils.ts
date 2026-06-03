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
  tileVersion?: string | null,
  extraCols?: string[] | null,
): string {
  const base = tileBaseUrl
    ? tileBaseUrl.replace(/\/$/, '')
    : `${window.location.origin}/api`;
  const url = `${base}/tiles/data.${tableName}/{z}/{x}/{y}.pbf`;
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
  tileVersion?: string | null,
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
  tileVersion?: string | null,
  options: { clusterRadius?: number; clusterMaxZoom?: number } = {},
): string {
  const base = tileBaseUrl
    ? tileBaseUrl.replace(/\/$/, '')
    : `${window.location.origin}/api`;
  const url = `${base}/tiles/clusters/data.${tableName}/{z}/{x}/{y}.pbf`;
  return appendTileParams(url, tileToken, tileVersion, {
    cluster_radius: options.clusterRadius,
    cluster_max_zoom: options.clusterMaxZoom,
  });
}
