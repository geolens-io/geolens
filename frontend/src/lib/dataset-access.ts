import { API_BASE } from '@/lib/constants';
import type { TileConfig } from '@/api/settings';
import type { DatasetResponse, DistributionResponse } from '@/types/api';

const ABSOLUTE_URL_RE = /^[a-zA-Z][a-zA-Z\d+.-]*:/;

function stripTrailingSlashes(value: string): string {
  return value.replace(/\/+$/, '');
}

function isAbsoluteUrl(value: string): boolean {
  return ABSOLUTE_URL_RE.test(value) || value.startsWith('//');
}

function normalizeApiBasePath(value: string): string {
  return value.startsWith('/') ? value : `/${value}`;
}

function getRuntimeApiBaseUrl(): string | null {
  const configuredApiBase = API_BASE.trim();

  if (configuredApiBase) {
    if (isAbsoluteUrl(configuredApiBase)) {
      return stripTrailingSlashes(configuredApiBase);
    }

    if (typeof window !== 'undefined' && window.location.origin) {
      return `${stripTrailingSlashes(window.location.origin)}${normalizeApiBasePath(configuredApiBase)}`;
    }

    return normalizeApiBasePath(configuredApiBase);
  }

  if (typeof window !== 'undefined' && window.location.origin) {
    return `${stripTrailingSlashes(window.location.origin)}/api`;
  }

  return null;
}

export function getPublicApiBaseUrl(
  tileConfig?: Pick<TileConfig, 'public_api_url' | 'public_base_url'> | null,
): string | null {
  const configuredApiUrl = tileConfig?.public_api_url?.trim();
  if (configuredApiUrl) {
    return stripTrailingSlashes(configuredApiUrl);
  }

  const configuredBaseUrl = tileConfig?.public_base_url?.trim();
  if (configuredBaseUrl) {
    if (isAbsoluteUrl(API_BASE.trim())) {
      return stripTrailingSlashes(API_BASE.trim());
    }

    const runtimeApiBaseUrl = getRuntimeApiBaseUrl();
    if (runtimeApiBaseUrl && isAbsoluteUrl(runtimeApiBaseUrl)) {
      try {
        const runtimePath = new URL(runtimeApiBaseUrl).pathname.replace(/\/+$/, '');
        return `${stripTrailingSlashes(configuredBaseUrl)}${runtimePath || '/api'}`;
      } catch {
        return `${stripTrailingSlashes(configuredBaseUrl)}${normalizeApiBasePath(API_BASE)}`;
      }
    }

    return `${stripTrailingSlashes(configuredBaseUrl)}${normalizeApiBasePath(API_BASE)}`;
  }

  return getRuntimeApiBaseUrl();
}

export function resolveDistributionUrl(url: string, publicApiBaseUrl: string | null | undefined): string {
  if (!url) {
    return url;
  }

  if (isAbsoluteUrl(url)) {
    return url;
  }

  if (!publicApiBaseUrl) {
    return url;
  }

  const baseUrl = stripTrailingSlashes(publicApiBaseUrl);
  return url.startsWith('/') ? `${baseUrl}${url}` : `${baseUrl}/${url.replace(/^\/+/, '')}`;
}

/** Resolve distribution URL by type, falling back to null if not found. */
function resolveByType(
  distributions: DistributionResponse[],
  predicate: (d: DistributionResponse) => boolean,
  publicApiBaseUrl: string | null | undefined,
): string | null {
  const dist = distributions.find(predicate);
  return dist ? resolveDistributionUrl(dist.url, publicApiBaseUrl) : null;
}

export interface DatasetAccessEndpoints {
  csvExportUrl: string | null;
  ogcFeaturesUrl: string | null;
  vectorTilesUrl: string | null;
}

export function getDatasetAccessEndpoints(
  dataset: Pick<DatasetResponse, 'id' | 'record_type' | 'table_name'>,
  publicApiBaseUrl: string | null | undefined,
  distributions: DistributionResponse[] = [],
): DatasetAccessEndpoints {
  const isRaster = dataset.record_type === 'raster_dataset';
  const isVrt = dataset.record_type === 'vrt_dataset';
  const isTable = dataset.record_type === 'table';
  const isVectorLike = !isRaster && !isVrt;

  return {
    ogcFeaturesUrl:
      resolveByType(distributions, (d) => d.distribution_type === 'ogc_features', publicApiBaseUrl)
      ?? (isVectorLike ? resolveDistributionUrl(`/collections/${dataset.id}/items`, publicApiBaseUrl) : null),
    csvExportUrl:
      resolveByType(distributions, (d) => d.distribution_type === 'download' && d.format === 'csv', publicApiBaseUrl)
      ?? (isVectorLike ? resolveDistributionUrl(`/datasets/${dataset.id}/export?format=csv`, publicApiBaseUrl) : null),
    vectorTilesUrl:
      resolveByType(distributions, (d) => d.distribution_type === 'vector_tiles', publicApiBaseUrl)
      ?? (!isTable && isVectorLike && dataset.table_name
        ? resolveDistributionUrl(`/tiles/data.${dataset.table_name}/{z}/{x}/{y}.pbf`, publicApiBaseUrl)
        : null),
  };
}
