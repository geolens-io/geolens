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
