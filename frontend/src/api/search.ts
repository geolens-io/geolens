import { apiFetch } from './client';
import type { CatalogCollectionResponse, FacetResponse, SearchResponse } from '@/types/api';

function buildSearchParams(params: Record<string, string>): string {
  const sp = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (key === 'keywords' && value) {
      // Split comma-joined keywords into repeated params for FastAPI
      for (const kw of value.split(',')) {
        if (kw) sp.append('keywords', kw);
      }
    } else {
      sp.set(key, value);
    }
  }
  return sp.toString();
}

export async function searchDatasets(
  params: Record<string, string>,
  options?: RequestInit,
): Promise<SearchResponse> {
  const query = buildSearchParams(params);
  return apiFetch<SearchResponse>(`/search/datasets?${query}`, options);
}

export async function fetchFacets(
  params: Record<string, string>,
): Promise<FacetResponse> {
  const query = buildSearchParams(params);
  return apiFetch<FacetResponse>(`/search/facets?${query}`);
}

export async function fetchCatalogSummary(): Promise<CatalogCollectionResponse> {
  return apiFetch<CatalogCollectionResponse>('/collections/datasets');
}
