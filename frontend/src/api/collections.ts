import { apiFetch } from './client';
import type {
  CollectionResponse,
  CollectionListResponse,
  CollectionCreateRequest,
  CollectionUpdateRequest,
  DatasetListResponse,
} from '@/types/api';

export async function listCollections(
  params: { skip?: number; limit?: number } = {},
): Promise<CollectionListResponse> {
  const query = new URLSearchParams();
  if (params.skip !== undefined) query.set('skip', String(params.skip));
  if (params.limit !== undefined) query.set('limit', String(params.limit));
  const qs = query.toString();
  return apiFetch<CollectionListResponse>(`/catalog/collections/${qs ? `?${qs}` : ''}`);
}

export async function getCollection(id: string): Promise<CollectionResponse> {
  return apiFetch<CollectionResponse>(`/catalog/collections/${id}`);
}

export async function createCollection(
  data: CollectionCreateRequest,
): Promise<CollectionResponse> {
  return apiFetch<CollectionResponse>('/catalog/collections/', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function updateCollection(
  id: string,
  data: CollectionUpdateRequest,
): Promise<CollectionResponse> {
  return apiFetch<CollectionResponse>(`/catalog/collections/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  });
}

export async function deleteCollection(id: string): Promise<void> {
  await apiFetch(`/catalog/collections/${id}`, {
    method: 'DELETE',
  });
}

export async function addDatasetsToCollection(
  collectionId: string,
  datasetIds: string[],
): Promise<{ added: number }> {
  return apiFetch<{ added: number }>(`/catalog/collections/${collectionId}/datasets`, {
    method: 'POST',
    body: JSON.stringify({ dataset_ids: datasetIds }),
  });
}

export async function removeDatasetFromCollection(
  collectionId: string,
  datasetId: string,
): Promise<void> {
  await apiFetch(`/catalog/collections/${collectionId}/datasets/${datasetId}`, {
    method: 'DELETE',
  });
}

export async function getCollectionDatasets(
  collectionId: string,
  params: { skip?: number; limit?: number } = {},
): Promise<DatasetListResponse> {
  const query = new URLSearchParams();
  if (params.skip !== undefined) query.set('skip', String(params.skip));
  if (params.limit !== undefined) query.set('limit', String(params.limit));
  const qs = query.toString();
  return apiFetch<DatasetListResponse>(`/catalog/collections/${collectionId}/datasets${qs ? `?${qs}` : ''}`);
}
