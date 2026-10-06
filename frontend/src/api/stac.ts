import { apiFetch } from './client';
import type {
  ServiceAuthRequest,
  StacConnectResponse,
  StacCollectionsResponse,
  StacAssetSizesResponse,
  StacSearchRequest,
  StacSearchResponse,
  StacImportItem,
  StacImportResponse,
} from '@/types/api';

// feat(#1764): `auth` is applied to the call that carries it.
// `/services/stac/import` takes none: it contacts no catalog, so accepting
// one there would take a credential the request then drops.
export async function connectStac(
  url: string,
  auth?: ServiceAuthRequest,
): Promise<StacConnectResponse> {
  return apiFetch<StacConnectResponse>('/services/stac/connect', {
    method: 'POST',
    body: JSON.stringify({ url, ...(auth ? { auth } : {}) }),
  });
}

export async function fetchStacCollections(
  url: string,
  auth?: ServiceAuthRequest,
): Promise<StacCollectionsResponse> {
  return apiFetch<StacCollectionsResponse>('/services/stac/collections', {
    method: 'POST',
    body: JSON.stringify({ url, ...(auth ? { auth } : {}) }),
  });
}

export async function searchStacItems(request: StacSearchRequest): Promise<StacSearchResponse> {
  return apiFetch<StacSearchResponse>('/services/stac/search', {
    method: 'POST',
    body: JSON.stringify(request),
  });
}

// Sizes of assets whose item omits `file:size`; an unknown size is null.
export async function fetchStacAssetSizes(
  url: string,
  assets: { id: string; href: string }[],
  auth?: ServiceAuthRequest,
): Promise<StacAssetSizesResponse> {
  return apiFetch<StacAssetSizesResponse>('/services/stac/asset-sizes', {
    method: 'POST',
    body: JSON.stringify({ url, assets, ...(auth ? { auth } : {}) }),
  });
}

// feat(#1764): `catalogAuthRequired` is a boolean, never the credential.
// It marks the dataset so its first refresh asks for one instead of failing
// anonymously against a catalog that needs it.
export async function importStacItems(
  url: string,
  items: StacImportItem[],
  visibility: string = 'private',
  catalogAuthRequired: boolean = false,
): Promise<StacImportResponse> {
  return apiFetch<StacImportResponse>('/services/stac/import', {
    method: 'POST',
    body: JSON.stringify({
      url,
      items,
      visibility,
      catalog_auth_required: catalogAuthRequired,
    }),
  });
}
