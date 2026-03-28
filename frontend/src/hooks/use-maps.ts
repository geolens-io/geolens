import { useQuery, useMutation, useQueryClient, keepPreviousData } from '@tanstack/react-query';
import { queryKeys } from '@/lib/query-keys';
import {
  listMaps,
  getMap,
  createMap,
  updateMap,
  deleteMap,
  addLayerToMapApi,
  removeLayerFromMapApi,
  getSharedMap,
  getMapShareToken,
  updateShareTokenExpiration,
  publishMap,
  createShareToken,
  revokeShareToken,
  duplicateMap,
  generateMap,
  fetchColumnValues,
  fetchColumnStats,
  fetchDatasetMaps,
} from '@/api/maps';
import type { MapUpdateRequest, MapLayerInput } from '@/types/api';

export interface MapBrowseParams {
  skip?: number;
  limit?: number;
  search?: string;
  sort_by?: string;
  sort_dir?: string;
  visibility?: string;
}

export function useMaps(params: MapBrowseParams = {}) {
  return useQuery({
    queryKey: queryKeys.maps.list(params),
    queryFn: () => listMaps(params),
    placeholderData: keepPreviousData,
  });
}

export function useMap(id: string | undefined) {
  return useQuery({
    queryKey: queryKeys.maps.detail(id),
    queryFn: () => getMap(id!),
    enabled: !!id,
  });
}

export function useCreateMap() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: createMap,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.maps.all });
    },
  });
}

export function useUpdateMap() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: MapUpdateRequest }) =>
      updateMap(id, data),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: queryKeys.maps.detail(variables.id) });
      qc.invalidateQueries({ queryKey: queryKeys.maps.all });
    },
  });
}

export function useDuplicateMap() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (mapId: string) => duplicateMap(mapId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.maps.all });
    },
  });
}

export function useDeleteMap() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => deleteMap(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.maps.all });
    },
  });
}

export function useAddLayer() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ mapId, data }: { mapId: string; data: MapLayerInput }) =>
      addLayerToMapApi(mapId, data),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: queryKeys.maps.detail(variables.mapId) });
    },
  });
}

export function useRemoveLayer() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ mapId, layerId }: { mapId: string; layerId: string }) =>
      removeLayerFromMapApi(mapId, layerId),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: queryKeys.maps.detail(variables.mapId) });
    },
  });
}

export function useSharedMap(token: string | undefined, apiKey?: string) {
  return useQuery({
    queryKey: queryKeys.maps.sharedMap(token, apiKey),
    queryFn: () => getSharedMap(token!, apiKey),
    enabled: !!token,
    retry: false,
  });
}

export function useMapShareToken(mapId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.maps.shareToken(mapId),
    queryFn: () => getMapShareToken(mapId!),
    enabled: !!mapId,
  });
}

export function usePublishMap() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, visibility }: { id: string; visibility: 'public' | 'private' | 'internal' }) =>
      publishMap(id, visibility),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: queryKeys.maps.detail(variables.id) });
      qc.invalidateQueries({ queryKey: queryKeys.maps.all });
    },
  });
}

export function useUpdateShareToken() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ mapId, expiresAt }: { mapId: string; expiresAt: string | null }) =>
      updateShareTokenExpiration(mapId, expiresAt),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: queryKeys.maps.shareToken(variables.mapId) });
    },
  });
}

export function useCreateShareToken() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ mapId, expiresAt }: { mapId: string; expiresAt?: string }) =>
      createShareToken(mapId, expiresAt),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: queryKeys.maps.shareToken(variables.mapId) });
    },
  });
}

export function useRevokeShareToken() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (mapId: string) => revokeShareToken(mapId),
    onSuccess: (_data, mapId) => {
      qc.invalidateQueries({ queryKey: queryKeys.maps.shareToken(mapId) });
      qc.invalidateQueries({ queryKey: queryKeys.maps.embedTokens(mapId) });
      qc.invalidateQueries({ queryKey: queryKeys.maps.detail(mapId) });
      qc.invalidateQueries({ queryKey: queryKeys.maps.all });
    },
  });
}

export function useGenerateMap() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: generateMap,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.maps.all });
    },
  });
}

export function useDatasetMaps(datasetId: string) {
  return useQuery({
    queryKey: queryKeys.datasets.maps(datasetId),
    queryFn: () => fetchDatasetMaps(datasetId),
  });
}

export function useColumnValues(datasetId: string | undefined, columnName: string | undefined) {
  return useQuery({
    queryKey: queryKeys.maps.columnValues(datasetId, columnName),
    queryFn: () => fetchColumnValues(datasetId!, columnName!),
    enabled: !!datasetId && !!columnName,
    staleTime: 5 * 60 * 1000, // 5 min cache
  });
}

export function useColumnStats(datasetId: string | undefined, columnName: string | undefined) {
  return useQuery({
    queryKey: queryKeys.maps.columnStats(datasetId, columnName),
    queryFn: () => fetchColumnStats(datasetId!, columnName!),
    enabled: !!datasetId && !!columnName,
    staleTime: 5 * 60 * 1000,
  });
}
