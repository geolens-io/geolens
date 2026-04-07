import { getEnvConfig } from '@/lib/env';

/**
 * Resolve the tile base URL from env config or tile config CDN setting.
 */
export function resolveTileBaseUrl(tileConfig?: { cdn_base_url?: string } | null): string | undefined {
  return getEnvConfig().TILE_BASE_URL || tileConfig?.cdn_base_url || undefined;
}

/**
 * Build a tile URL template for a given table name.
 * When cdnBaseUrl is set, tiles are fetched from the CDN origin via /tiles/ path.
 * Otherwise, tiles are fetched from the FastAPI tile endpoint at /api/tiles/.
 */
export function buildTileUrl(tableName: string, cdnBaseUrl?: string | null): string {
  if (cdnBaseUrl) {
    const base = cdnBaseUrl.replace(/\/$/, '');
    return `${base}/tiles/data.${tableName}/{z}/{x}/{y}.pbf`;
  }
  return `${window.location.origin}/api/tiles/data.${tableName}/{z}/{x}/{y}.pbf`;
}

/**
 * Resolve a tile_url path (from API response) to a full absolute URL,
 * using CDN base when available.
 */
export function resolveTileUrl(tileUrl: string, cdnBaseUrl?: string | null): string {
  if (cdnBaseUrl) {
    const base = cdnBaseUrl.replace(/\/$/, '');
    return `${base}${tileUrl}`;
  }
  return `${window.location.origin}${tileUrl}`;
}

/**
 * Build a signed tile URL with query-param auth.
 * When tileToken is provided, appends sig/exp/scope as query params.
 * When tileToken is null (public dataset), returns URL without params.
 */
export function buildSignedTileUrl(
  tableName: string,
  tileToken: { sig: string; exp: number; scope: string } | null,
  tileBaseUrl?: string | null,
  tileVersion?: string | null,
): string {
  const base = tileBaseUrl
    ? tileBaseUrl.replace(/\/$/, '')
    : `${window.location.origin}/api`;
  const url = `${base}/tiles/data.${tableName}/{z}/{x}/{y}.pbf`;
  const params: string[] = [];
  if (tileToken) {
    params.push(`sig=${tileToken.sig}`, `exp=${tileToken.exp}`, `scope=${tileToken.scope}`);
  }
  if (tileVersion) {
    params.push(`_v=${encodeURIComponent(tileVersion)}`);
  }
  return params.length > 0 ? `${url}?${params.join('&')}` : url;
}
