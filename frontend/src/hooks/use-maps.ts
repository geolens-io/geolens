import { useQuery, useMutation, useQueryClient, keepPreviousData } from '@tanstack/react-query';
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
    queryKey: ['maps', params],
    queryFn: () => listMaps(params),
    placeholderData: keepPreviousData,
  });
}

export function useMap(id: string | undefined) {
  return useQuery({
    queryKey: ['map', id],
    queryFn: () => getMap(id!),
    enabled: !!id,
  });
}

export function useCreateMap() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: createMap,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['maps'] });
    },
  });
}

export function useUpdateMap() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: MapUpdateRequest }) =>
      updateMap(id, data),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: ['map', variables.id] });
      qc.invalidateQueries({ queryKey: ['maps'] });
    },
  });
}

export function useDuplicateMap() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (mapId: string) => duplicateMap(mapId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['maps'] });
    },
  });
}

export function useDeleteMap() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => deleteMap(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['maps'] });
    },
  });
}

export function useAddLayer() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ mapId, data }: { mapId: string; data: MapLayerInput }) =>
      addLayerToMapApi(mapId, data),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: ['map', variables.mapId] });
    },
  });
}

export function useRemoveLayer() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ mapId, layerId }: { mapId: string; layerId: string }) =>
      removeLayerFromMapApi(mapId, layerId),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: ['map', variables.mapId] });
    },
  });
}

export function useSharedMap(token: string | undefined, apiKey?: string) {
  return useQuery({
    queryKey: ['shared-map', token, apiKey],
    queryFn: () => getSharedMap(token!, apiKey),
    enabled: !!token,
    retry: false,
  });
}

export function useMapShareToken(mapId: string | undefined) {
  return useQuery({
    queryKey: ['map-share-token', mapId],
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
      qc.invalidateQueries({ queryKey: ['map', variables.id] });
      qc.invalidateQueries({ queryKey: ['maps'] });
    },
  });
}

export function useUpdateShareToken() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ mapId, expiresAt }: { mapId: string; expiresAt: string | null }) =>
      updateShareTokenExpiration(mapId, expiresAt),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: ['map-share-token', variables.mapId] });
    },
  });
}

export function useCreateShareToken() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ mapId, expiresAt }: { mapId: string; expiresAt?: string }) =>
      createShareToken(mapId, expiresAt),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: ['map-share-token', variables.mapId] });
    },
  });
}

export function useRevokeShareToken() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (mapId: string) => revokeShareToken(mapId),
    onSuccess: (_data, mapId) => {
      qc.invalidateQueries({ queryKey: ['map-share-token', mapId] });
      qc.invalidateQueries({ queryKey: ['map-embed-tokens', mapId] });
      qc.invalidateQueries({ queryKey: ['map', mapId] });
      qc.invalidateQueries({ queryKey: ['maps'] });
    },
  });
}

export function useGenerateMap() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: generateMap,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['maps'] });
    },
  });
}

export function useDatasetMaps(datasetId: string) {
  return useQuery({
    queryKey: ['datasets', datasetId, 'maps'],
    queryFn: () => fetchDatasetMaps(datasetId),
  });
}

export function useColumnValues(datasetId: string | undefined, columnName: string | undefined) {
  return useQuery({
    queryKey: ['column-values', datasetId, columnName],
    queryFn: () => fetchColumnValues(datasetId!, columnName!),
    enabled: !!datasetId && !!columnName,
    staleTime: 5 * 60 * 1000, // 5 min cache
  });
}

export function useColumnStats(datasetId: string | undefined, columnName: string | undefined) {
  return useQuery({
    queryKey: ['column-stats', datasetId, columnName],
    queryFn: () => fetchColumnStats(datasetId!, columnName!),
    enabled: !!datasetId && !!columnName,
    staleTime: 5 * 60 * 1000,
  });
}
