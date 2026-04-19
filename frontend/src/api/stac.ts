import { apiFetch } from './client';
import type {
  StacConnectResponse,
  StacCollectionsResponse,
  StacSearchRequest,
  StacSearchResponse,
  StacImportItem,
  StacImportResponse,
} from '@/types/api';

export async function connectStac(url: string): Promise<StacConnectResponse> {
  return apiFetch<StacConnectResponse>('/services/stac/connect', {
    method: 'POST',
    body: JSON.stringify({ url }),
  });
}

export async function fetchStacCollections(url: string): Promise<StacCollectionsResponse> {
  return apiFetch<StacCollectionsResponse>('/services/stac/collections', {
    method: 'POST',
    body: JSON.stringify({ url }),
  });
}

export async function searchStacItems(request: StacSearchRequest): Promise<StacSearchResponse> {
  return apiFetch<StacSearchResponse>('/services/stac/search', {
    method: 'POST',
    body: JSON.stringify(request),
  });
}

export async function importStacItems(
  url: string,
  items: StacImportItem[],
  visibility: string = 'private',
): Promise<StacImportResponse> {
  return apiFetch<StacImportResponse>('/services/stac/import', {
    method: 'POST',
    body: JSON.stringify({ url, items, visibility }),
  });
}
