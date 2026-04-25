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
import type { MapUpdateRequest, MapLayerInput, MapBrowseParams } from '@/types/api';
import { toast } from 'sonner';

export type { MapBrowseParams };

export function useMaps(params: MapBrowseParams = {}) {
  return useQuery({
    queryKey: queryKeys.maps.list(params),
    queryFn: () => listMaps(params),
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  });
}

export function useMap(id: string | undefined, opts?: { refetchOnWindowFocus?: boolean }) {
  return useQuery({
    queryKey: queryKeys.maps.detail(id),
    queryFn: () => getMap(id!),
    enabled: !!id,
    staleTime: 60_000,
    refetchOnWindowFocus: opts?.refetchOnWindowFocus,
  });
}

export function useCreateMap() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: createMap,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.maps.all });
    },
    onError: () => { toast.error('Failed to create map'); },
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
    onError: (err: unknown) => {
      // Surface backend validator messages (e.g. popup_config: "expression
      // must be 500 characters or fewer") so the user sees the specific cause.
      const detail = err instanceof Error ? err.message : null;
      toast.error(detail ? `Failed to save map: ${detail}` : 'Failed to save map');
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
    onError: () => { toast.error('Failed to duplicate map'); },
  });
}

export function useDeleteMap() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => deleteMap(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.maps.all });
    },
    onError: () => { toast.error('Failed to delete map'); },
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
    onError: () => { toast.error('Failed to add layer'); },
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
    onError: () => { toast.error('Failed to remove layer'); },
  });
}

export function useSharedMap(token: string | undefined, apiKey?: string) {
  return useQuery({
    queryKey: queryKeys.maps.sharedMap(token, apiKey),
    queryFn: () => getSharedMap(token!, apiKey),
    enabled: !!token,
    retry: false,
    staleTime: 30_000,
  });
}

export function useMapShareToken(mapId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.maps.shareToken(mapId),
    queryFn: () => getMapShareToken(mapId!),
    enabled: !!mapId,
    staleTime: 5 * 60_000,
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
    onError: () => { toast.error('Failed to update map visibility'); },
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
    onError: () => { toast.error('Failed to update share token'); },
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
    onError: () => { toast.error('Failed to create share token'); },
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
    onError: () => { toast.error('Failed to revoke share token'); },
  });
}

export function useGenerateMap() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: generateMap,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.maps.all });
    },
    onError: () => { toast.error('Failed to generate map'); },
  });
}

export function useDatasetMaps(datasetId: string) {
  return useQuery({
    queryKey: queryKeys.datasets.maps(datasetId),
    queryFn: () => fetchDatasetMaps(datasetId),
    staleTime: 60_000,
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
