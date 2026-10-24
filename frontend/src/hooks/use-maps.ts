import { useQuery, useMutation, useQueryClient, keepPreviousData, type QueryClient } from '@tanstack/react-query';
import { queryKeys } from '@/lib/query-keys';
import { formatMutationError } from '@/lib/error-map';
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
  nonPublicDatasetsFromError,
  createShareToken,
  revokeShareToken,
  duplicateMap,
  fetchColumnValues,
  fetchColumnStats,
  fetchDatasetMaps,
  exportMapStyleJson,
  importMapStyleJson,
  listMapIcons,
  uploadMapIcon,
  setMapGroups,
  checkMapVisibility,
} from '@/api/maps';
import type { ShareExpirationInput } from '@/api/maps';
import type { MapGroupsConfirm, MapResponse, MapUpdateRequest, MapLayerDiffRequest, MapLayerInput, MapBrowseParams, MapVisibility, VisibilityCheckResponse } from '@/types/api';
import { toast } from 'sonner';
import i18n from '@/i18n/i18n';
import { useAnalysisAddedStore } from '@/stores/analysis-job-store';
import { ApiError } from '@/api/client';



function invalidateMapHistory(qc: QueryClient, mapId: string | undefined) {
  qc.invalidateQueries({ queryKey: queryKeys.maps.historyPrefix(mapId) });
}

/**
 * A dataset's "used in maps" list (useDatasetMaps) is keyed under the
 * 'datasets' root (['datasets', id, 'maps']), so 'maps'-rooted invalidations
 * never match it. Dataset ids aren't reliably available on every mutation, so
 * invalidate the 'datasets' root broadly; that covers the dataset-scoped map
 * lists and the browse list without touching the 'dataset'-rooted detail
 * caches.
 */
function invalidateDatasetMapLists(qc: QueryClient) {
  qc.invalidateQueries({ queryKey: queryKeys.datasets.all });
}

export function useMaps(params: MapBrowseParams = {}) {
  return useQuery({
    queryKey: queryKeys.maps.list(params),
    queryFn: () => listMaps(params),
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  });
}

const NO_LAYER_IDS: ReadonlySet<string> = new Set();

function gapLayerIds(check: VisibilityCheckResponse): ReadonlySet<string> {
  return new Set((check.hidden_from_groups ?? []).map((gap) => gap.layer_id));
}

/**
 * The layers of a restricted map that some of its groups can't read, as the
 * server answers it. Only the owner and admins receive `groups`, and only
 * they may ask.
 */
export function useLayersHiddenFromMapGroups(
  mapId: string | undefined,
  visibility: MapVisibility | undefined,
  groups: readonly unknown[] | null | undefined,
): ReadonlySet<string> {
  const enabled = visibility === 'restricted' && groups != null;
  const { data } = useQuery({
    queryKey: queryKeys.maps.groupGaps(mapId),
    queryFn: () => checkMapVisibility(mapId!),
    enabled: enabled && !!mapId,
    select: gapLayerIds,
  });
  // A disabled query still returns what it cached while the map was restricted.
  return (enabled && data) || NO_LAYER_IDS;
}

export function useMap(id: string | undefined, opts?: { refetchOnWindowFocus?: boolean }) {
  return useQuery({
    queryKey: queryKeys.maps.detail(id),
    queryFn: () => getMap(id!),
    enabled: !!id,
    staleTime: 60_000,
    refetchOnWindowFocus: opts?.refetchOnWindowFocus,
    // A missing or forbidden map stays that way; retrying only delays the not-found state.
    retry: (failureCount, error) =>
      !(error instanceof ApiError && (error.status === 404 || error.status === 403)) && failureCount < 1,
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
      invalidateDatasetMapLists(qc);
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
      invalidateDatasetMapLists(qc);
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
      invalidateDatasetMapLists(qc);
    },
    onError: () => { toast.error(i18n.t('builder:toasts.mapDuplicateFailed')); },
  });
}

export function useDeleteMap() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => deleteMap(id),
    onSuccess: (_data, id) => {
      // Remove the deleted map's detail, share-token, history and embed-token
      // entries: a re-mounted consumer would otherwise refetch the deleted
      // map's endpoints and produce 404s. ``maps.all`` is invalidated so the
      // list stays fresh.
      qc.removeQueries({ queryKey: queryKeys.maps.detail(id) });
      qc.removeQueries({ queryKey: queryKeys.maps.shareToken(id) });
      qc.removeQueries({ queryKey: queryKeys.maps.embedTokens(id) });
      qc.removeQueries({ queryKey: queryKeys.maps.historyPrefix(id) });
      qc.invalidateQueries({ queryKey: queryKeys.maps.all });
      invalidateDatasetMapLists(qc);
    },
    // The hook owns the error toast; callers must not raise a second one.
    // `formatMutationError` keeps the specific backend reason.
    onError: (err) => { toast.error(formatMutationError('common:maps.deleteFailed', err)); },
  });
}

export function useAddLayer() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ mapId, data }: { mapId: string; data: MapLayerInput }) =>
      addLayerToMapApi(mapId, data),
    // The analysis add-to-map guard settles HERE, not in per-call mutate()
    // callbacks: when two adds overlap, the shared observer drops the earlier
    // call's callbacks and strands a pending claim. These run once per
    // request and are no-ops unless an analysis affordance claimed this
    // dataset.
    onSuccess: (_data, variables) => {
      const guard = useAnalysisAddedStore.getState();
      if (guard.pendingAddIds.includes(variables.data.dataset_id)) {
        guard.confirmAdded(variables.data.dataset_id);
      }
      qc.invalidateQueries({ queryKey: queryKeys.maps.detail(variables.mapId) });
      invalidateMapHistory(qc, variables.mapId);
    },
    onError: (_err, variables) => {
      useAnalysisAddedStore.getState().clearPending(variables.data.dataset_id);
      toast.error(i18n.t('builder:toasts.layerAddFailed'));
    },
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
    queryKey: queryKeys.mapIcons.all,
    queryFn: listMapIcons,
    staleTime: 60_000,
  });
}

export function useUploadMapIcon() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: uploadMapIcon,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.mapIcons.all });
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

export function useSharedMap(token: string | undefined, embedToken?: string) {
  return useQuery({
    queryKey: queryKeys.maps.sharedMap(token, embedToken),
    queryFn: () => getSharedMap(token!, embedToken),
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
    // A map with groups cannot go private directly (the server keeps it
    // restricted), so "private" unshares it first.
    mutationFn: async ({ id, visibility }: { id: string; visibility: MapVisibility }) => {
      const hasGroups = Boolean(qc.getQueryData<MapResponse>(queryKeys.maps.detail(id))?.groups?.length);
      const clearedGroups = visibility === 'private' && hasGroups;
      if (clearedGroups && (await setMapGroups(id, [])).visibility === visibility) {
        return { clearedGroups, visibility };
      }
      return { clearedGroups, visibility: (await publishMap(id, visibility)).visibility };
    },
    // Settled, not success: the groups may already be cleared when publishMap fails.
    onSettled: (_data, _error, variables) => {
      qc.invalidateQueries({ queryKey: queryKeys.maps.detail(variables.id) });
      qc.invalidateQueries({ queryKey: queryKeys.maps.all });
      invalidateMapHistory(qc, variables.id);
    },
    // The non-public-datasets refusal has its own inline message in
    // SharePanel; every other publishMap failure gets this toast.
    onError: (err) => {
      if (nonPublicDatasetsFromError(err)) return;
      toast.error(i18n.t('builder:toasts.visibilityFailed'));
    },
  });
}

export function useSetMapGroups() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ mapId, groupIds, confirm }: { mapId: string; groupIds: string[]; confirm?: MapGroupsConfirm }) =>
      setMapGroups(mapId, groupIds, confirm),
    onSuccess: (data, variables) => {
      // Sharing the layers' datasets changes those datasets too.
      for (const datasetId of data.shared_dataset_ids ?? []) {
        qc.invalidateQueries({ queryKey: queryKeys.datasets.detail(datasetId) });
      }
      if (data.shared_dataset_ids?.length) invalidateDatasetMapLists(qc);
      qc.invalidateQueries({ queryKey: queryKeys.maps.detail(variables.mapId) });
      qc.invalidateQueries({ queryKey: queryKeys.maps.all });
      invalidateMapHistory(qc, variables.mapId);
    },
  });
}

export function useUpdateShareToken() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ mapId, ...expiration }: { mapId: string } & ShareExpirationInput) =>
      updateShareTokenExpiration(mapId, expiration),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: queryKeys.maps.shareToken(variables.mapId) });
    },
    onError: () => { toast.error(i18n.t('builder:toasts.shareTokenUpdateFailed')); },
  });
}

export function useCreateShareToken() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ mapId, ...expiration }: { mapId: string } & ShareExpirationInput) =>
      createShareToken(mapId, expiration),
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
    staleTime: 5 * 60 * 1000,
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
