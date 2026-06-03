import { apiFetch } from './client';
import type {
  VrtSourceListResponse,
  VrtMutationResponse,
  VrtStatusResponse,
  VrtGenerationListResponse,
} from '@/types/api';

export async function listVrtSources(datasetId: string): Promise<VrtSourceListResponse> {
  return apiFetch<VrtSourceListResponse>(`/datasets/${datasetId}/vrt-sources/`);
}

export async function addVrtSource(
  datasetId: string,
  sourceDatasetId: string,
): Promise<VrtMutationResponse> {
  return apiFetch<VrtMutationResponse>(`/ingest/vrt/${datasetId}/sources/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ source_dataset_id: sourceDatasetId }),
  });
}

export async function removeVrtSource(
  datasetId: string,
  sourceDatasetId: string,
): Promise<VrtMutationResponse> {
  return apiFetch<VrtMutationResponse>(`/ingest/vrt/${datasetId}/sources/${sourceDatasetId}/`, {
    method: 'DELETE',
  });
}

export async function getVrtStatus(datasetId: string): Promise<VrtStatusResponse> {
  return apiFetch<VrtStatusResponse>(`/datasets/${datasetId}/vrt/status/`);
}

export async function getVrtGenerations(
  datasetId: string,
  params?: { limit?: number; offset?: number },
): Promise<VrtGenerationListResponse> {
  const qs = new URLSearchParams();
  if (params?.limit) qs.set('limit', String(params.limit));
  if (params?.offset) qs.set('offset', String(params.offset));
  const query = qs.toString();
  return apiFetch<VrtGenerationListResponse>(
    `/datasets/${datasetId}/vrt/generations/${query ? `?${query}` : ''}`,
  );
}

export async function regenerateVrt(datasetId: string): Promise<VrtMutationResponse> {
  return apiFetch<VrtMutationResponse>(`/datasets/${datasetId}/vrt/regenerate/`, {
    method: 'POST',
  });
}
