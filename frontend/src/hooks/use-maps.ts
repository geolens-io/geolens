import { useQuery, useMutation, useQueryClient, keepPreviousData, type QueryClient } from '@tanstack/react-query';
import { queryKeys } from '@/lib/query-keys';
import {
  listMaps,
  getMap,
  getMapAccess,
  getMapHistory,
  createMap,
  updateMap,
  patchMapLayers,
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
  exportMapStyleJson,
  importMapStyleJson,
  listMapIcons,
  uploadMapIcon,
} from '@/api/maps';
import type { MapUpdateRequest, MapLayerDiffRequest, MapLayerInput, MapBrowseParams } from '@/types/api';
import { toast } from 'sonner';
import i18n from '@/i18n/i18n';

export type { MapBrowseParams };

function invalidateMapHistory(qc: QueryClient, mapId: string | undefined) {
  qc.invalidateQueries({ queryKey: queryKeys.maps.historyPrefix(mapId) });
}

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

export function useMapAccess(id: string | undefined, opts?: { enabled?: boolean }) {
  return useQuery({
    queryKey: queryKeys.maps.access(id),
    queryFn: () => getMapAccess(id!),
    enabled: !!id && (opts?.enabled ?? true),
    staleTime: 30_000,
    retry: false,
  });
}

export function useMapHistory(mapId: string | undefined, skip = 0, limit = 50) {
  return useQuery({
    queryKey: queryKeys.maps.history(mapId, skip, limit),
    queryFn: () => getMapHistory(mapId!, { skip, limit }),
    enabled: !!mapId,
    placeholderData: keepPreviousData,
    staleTime: 15_000,
  });
}

export function useCreateMap() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: createMap,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.maps.all });
    },
    onError: () => { toast.error(i18n.t('builder:mapCreate.createFailed')); },
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
      invalidateMapHistory(qc, variables.id);
    },
    onError: (err: unknown) => {
      // Surface backend validator messages (e.g. popup_config: "expression
      // must be 500 characters or fewer") so the user sees the specific cause.
      const detail = err instanceof Error ? err.message : null;
      toast.error(detail
        ? i18n.t('builder:toasts.saveFailedWithDetail', { detail })
        : i18n.t('builder:toasts.saveFailed'));
    },
  });
}

export function usePatchMapLayers() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, diff }: { id: string; diff: MapLayerDiffRequest }) =>
      patchMapLayers(id, diff),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: queryKeys.maps.detail(variables.id) });
      qc.invalidateQueries({ queryKey: queryKeys.maps.all });
      invalidateMapHistory(qc, variables.id);
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
    onError: () => { toast.error(i18n.t('builder:toasts.mapDuplicateFailed')); },
  });
}

export function useDeleteMap() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => deleteMap(id),
    onSuccess: (_data, id) => {
      // SMOKE-v1013-F3: previously only ``maps.all`` was invalidated, leaving
      // stale ``maps.detail(id)``, ``maps.shareToken(id)``, ``maps.history*``,
      // and ``maps.embedTokens(id)`` entries in the React Query cache. Any
      // subsequent component that re-mounted those queries (recent-maps lists,
      // a tab pinned to the deleted map's builder, an admin panel) would
      // refetch from the deleted map's endpoints — yielding 404 noise and the
      // ``/api/maps/shared/{deleted_id}`` errors seen in v1013 smoke.
      //
      // ``removeQueries`` drops the data entirely; ``invalidateQueries`` on
      // ``maps.all`` keeps the list fresh for navigation. Strip the per-map
      // queries that no longer make sense after delete.
      qc.removeQueries({ queryKey: queryKeys.maps.detail(id) });
      qc.removeQueries({ queryKey: queryKeys.maps.shareToken(id) });
      qc.removeQueries({ queryKey: queryKeys.maps.embedTokens(id) });
      qc.removeQueries({ queryKey: queryKeys.maps.historyPrefix(id) });
      qc.invalidateQueries({ queryKey: queryKeys.maps.all });
    },
    onError: () => { toast.error(i18n.t('common:maps.deleteFailed')); },
  });
}

export function useAddLayer() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ mapId, data }: { mapId: string; data: MapLayerInput }) =>
      addLayerToMapApi(mapId, data),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: queryKeys.maps.detail(variables.mapId) });
      invalidateMapHistory(qc, variables.mapId);
    },
    onError: () => { toast.error(i18n.t('builder:toasts.layerAddFailed')); },
  });
}

export function useExportMapStyleJson() {
  return useMutation({
    mutationFn: (mapId: string) => exportMapStyleJson(mapId),
  });
}

export function useImportMapStyleJson() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: importMapStyleJson,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.maps.all });
    },
  });
}

export function useMapIcons() {
  return useQuery({
    queryKey: ['maps', 'icons'],
    queryFn: listMapIcons,
    staleTime: 60_000,
  });
}

export function useUploadMapIcon() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: uploadMapIcon,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['maps', 'icons'] });
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
      invalidateMapHistory(qc, variables.mapId);
    },
    onError: () => { toast.error(i18n.t('builder:toasts.layerRemoveFailed')); },
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
      invalidateMapHistory(qc, variables.id);
    },
    onError: () => { toast.error(i18n.t('builder:toasts.visibilityFailed')); },
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
    onError: () => { toast.error(i18n.t('builder:toasts.shareTokenUpdateFailed')); },
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
    onError: () => { toast.error(i18n.t('builder:toasts.shareLinkFailed')); },
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
    onError: () => { toast.error(i18n.t('builder:toasts.revokeFailed')); },
  });
}

export function useGenerateMap() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: generateMap,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.maps.all });
    },
    onError: () => { toast.error(i18n.t('builder:mapCreate.generateFailed')); },
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
