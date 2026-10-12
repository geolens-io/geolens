import { apiFetch } from './client';
import type {
  VrtSourceListResponse,
  VrtStatusResponse,
  VrtGenerationListResponse,
} from '@/types/api';

export async function listVrtSources(datasetId: string): Promise<VrtSourceListResponse> {
  return apiFetch<VrtSourceListResponse>(`/datasets/${encodeURIComponent(datasetId)}/vrt-sources/`);
}

export async function getVrtStatus(datasetId: string): Promise<VrtStatusResponse> {
  return apiFetch<VrtStatusResponse>(`/datasets/${encodeURIComponent(datasetId)}/vrt/status/`);
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
    `/datasets/${encodeURIComponent(datasetId)}/vrt/generations/${query ? `?${query}` : ''}`,
  );
}
