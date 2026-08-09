import { useQuery, useMutation, useQueryClient, keepPreviousData } from '@tanstack/react-query';
import { queryKeys } from '@/lib/query-keys';
import {
  createDataset,
  getDataset,
  getDatasetRows,
  updateDataset,
  setTargetStatus,
  deleteDataset,
  getDatasetHistory,
  reuploadDataset,
  reuploadPreview,
  reuploadServicePreview,
  reuploadCommit,
  getDatasetVersions,
  refreshDataset,
  getDatasetRefreshRuns,
  listAttributes,
  updateAttribute,
  validateDataset,
} from '@/api/datasets';
import type {
  CreateDatasetRequest,
  DatasetUpdateRequest,
  AttributeMetadataUpdate,
  ReuploadServicePreviewRequest,
} from '@/types/api';

export function useCreateDataset() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: CreateDatasetRequest) => createDataset(data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.datasets.all });
      qc.invalidateQueries({ queryKey: queryKeys.search.all });
    },
  });
}

export function useDataset(id: string, options?: { refetchInterval?: number | false | ((query: unknown) => number | false) }) {
  return useQuery({
    queryKey: queryKeys.datasets.detail(id),
    queryFn: () => getDataset(id),
    enabled: !!id,
    refetchInterval: options?.refetchInterval,
    staleTime: 60_000,
  });
}

export function useDatasetRows(id: string, limit: number, cursor: number, filters?: Record<string, string>) {
  return useQuery({
    queryKey: queryKeys.datasets.rows(id, limit, cursor, filters),
    queryFn: () => getDatasetRows(id, { limit, after: cursor, filters }),
    enabled: !!id,
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  });
}

export function useUpdateDataset() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ datasetId, data }: { datasetId: string; data: DatasetUpdateRequest }) =>
      updateDataset(datasetId, data),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: queryKeys.datasets.detail(variables.datasetId) });
      qc.invalidateQueries({ queryKey: queryKeys.datasets.all });
      qc.invalidateQueries({ queryKey: queryKeys.search.all });
      // PERF-D1: validation query has a 5-minute staleTime so it wouldn't
      // otherwise refetch after a metadata edit. Force invalidation so the
      // quality-score badge reflects the freshly-computed value.
      qc.invalidateQueries({ queryKey: queryKeys.datasets.validation(variables.datasetId) });
    },
  });
}

export function useSetTargetStatus() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ datasetId, status }: { datasetId: string; status: string }) =>
      setTargetStatus(datasetId, status),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: queryKeys.datasets.detail(variables.datasetId) });
      qc.invalidateQueries({ queryKey: queryKeys.datasets.all });
      qc.invalidateQueries({ queryKey: queryKeys.search.all });
      qc.invalidateQueries({ queryKey: queryKeys.datasets.validation(variables.datasetId) });
    },
  });
}

export function useDeleteDataset() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ datasetId, confirmName }: { datasetId: string; confirmName: string }) =>
      deleteDataset(datasetId, confirmName),
    onSuccess: (_data, variables) => {
      // fix(#787 item 5): invalidating fired three refetches at a dataset that no
      // longer exists — its detail query, plus related/ and maps/, which live under
      // the ['datasets'] prefix the list invalidation matches. Cancel all three and
      // keep the list invalidation off the deleted id.
      //
      // `refetchType: 'none'`, not a plain invalidate and not a remove. The caller
      // navigates away only after this resolves, so the detail observer is still
      // mounted: a plain invalidate refetches it, and removing an active query makes
      // the observer rebuild and fetch — both measured as a 404. Marking it stale
      // without fetching puts nothing in flight now AND still forces a real request
      // if the user comes back to the URL, so browser Back gets a not-found instead
      // of a cached ghost of the dataset it just deleted.
      const deadKeys = [
        queryKeys.datasets.detail(variables.datasetId),
        queryKeys.datasets.related(variables.datasetId),
        queryKeys.datasets.maps(variables.datasetId),
      ];
      for (const queryKey of deadKeys) {
        qc.cancelQueries({ queryKey });
        qc.invalidateQueries({ queryKey, refetchType: 'none' });
      }
      qc.invalidateQueries({
        queryKey: queryKeys.datasets.all,
        predicate: (query) => query.queryKey[1] !== variables.datasetId,
      });
      qc.invalidateQueries({ queryKey: queryKeys.search.all });
      qc.invalidateQueries({ queryKey: queryKeys.admin.stats });
    },
  });
}

export function useDatasetHistory(datasetId: string, skip = 0, limit = 50) {
  return useQuery({
    queryKey: queryKeys.datasets.history(datasetId, skip, limit),
    queryFn: () => getDatasetHistory(datasetId, { skip, limit }),
    enabled: !!datasetId,
    placeholderData: keepPreviousData,
    staleTime: 120_000,
  });
}

export function useReuploadDataset() {
  return useMutation({
    mutationFn: ({ datasetId, file }: { datasetId: string; file: File }) =>
      reuploadDataset(datasetId, file),
  });
}

export function useReuploadPreview() {
  return useMutation({
    // GPKG-01 Phase 1058: optional layerName for multi-layer file sources
    mutationFn: ({ datasetId, jobId, layerName }: { datasetId: string; jobId: string; layerName?: string }) =>
      reuploadPreview(datasetId, jobId, layerName),
  });
}

export function useReuploadServicePreview() {
  return useMutation({
    mutationFn: ({
      datasetId,
      request,
    }: {
      datasetId: string;
      request: ReuploadServicePreviewRequest;
    }) => reuploadServicePreview(datasetId, request),
  });
}

export function useReuploadCommit() {
  const qc = useQueryClient();
  return useMutation({
    // GPKG-01 Phase 1058: optional layerName for multi-layer file sources
    mutationFn: ({
      datasetId,
      jobId,
      sridOverride,
      token,
      layerName,
    }: {
      datasetId: string;
      jobId: string;
      sridOverride?: number | null;
      token?: string;
      layerName?: string;
    }) => reuploadCommit(datasetId, jobId, sridOverride, token, layerName),
    // REMED-01 (ingest-audit P2-06): invalidate the dataset-detail warnings
    // banner cache so it refetches the new ingest job's warnings. The
    // useDatasetJobStatus query uses `staleTime: Infinity` and would
    // otherwise hold the prior job's value until a hard refresh.
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: queryKeys.ingest.jobStatusByDataset(variables.datasetId) });
    },
  });
}

export function useDatasetVersions(datasetId: string, skip = 0, limit = 50) {
  return useQuery({
    queryKey: queryKeys.datasets.versions(datasetId, skip, limit),
    queryFn: () => getDatasetVersions(datasetId, { skip, limit }),
    enabled: !!datasetId,
    placeholderData: keepPreviousData,
    staleTime: 120_000,
  });
}

export function useRefreshDataset() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ datasetId, token }: { datasetId: string; token?: string }) =>
      refreshDataset(datasetId, token),
    // The dispatched run belongs in history immediately (status "pending"),
    // and dataset-detail health/freshness change once the worker finishes —
    // both queries are cheap enough to just invalidate rather than patch.
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: queryKeys.datasets.refreshRunsPrefix(variables.datasetId) });
      qc.invalidateQueries({ queryKey: queryKeys.datasets.detail(variables.datasetId) });
    },
  });
}

export function useDatasetRefreshRuns(
  datasetId: string,
  params: { skip?: number; limit?: number } = {},
) {
  const skip = params.skip ?? 0;
  const limit = params.limit ?? 10;
  return useQuery({
    queryKey: queryKeys.datasets.refreshRuns(datasetId, skip, limit),
    queryFn: () => getDatasetRefreshRuns(datasetId, { skip, limit }),
    enabled: !!datasetId,
    placeholderData: keepPreviousData,
    staleTime: 15_000,
    // fix(#1285 codex round 2): keepPreviousData shows the LAST successful
    // result as a placeholder for ANY new query invocation, not just a
    // paged re-fetch of the same dataset — so navigating straight from one
    // /datasets/:id to another briefly serves the PRIOR dataset's runs under
    // the new query key. Neither consumer checked `run.dataset_id ===
    // datasetId` (SourceHistory already does this for versions, same root
    // cause), so the new page could flash the previous dataset's triggered-by
    // identity, error text, or active-run disabled state. Filtering here
    // fixes every consumer at once rather than duplicating the check.
    select: (data) => ({
      ...data,
      runs: data.runs.filter((run) => run.dataset_id === datasetId),
    }),
    // fix(#1285 codex round 1): the dispatch-time invalidation above fires
    // one refetch that lands as "pending", and the app disables
    // refetch-on-focus (see auth-recovery notes), so without this the run
    // sits "active" in the mounted page forever — SourceRefreshAction's busy
    // gate never re-enables and this section's status never updates once the
    // worker actually finishes. Self-referential like useJobStatus: poll
    // while the newest run is still in flight, stop once it lands on a
    // terminal status. Shared by both consumers (the trigger's gate and this
    // history section), so both pick up the transition from one poll.
    //
    // `query.state.data` here is the RAW cached response (select runs at the
    // observer, not against the cache), so this re-applies the same
    // dataset_id filter rather than trusting index 0 belongs to `datasetId`.
    refetchInterval: (query) => {
      const latest = query.state.data?.runs.find((run) => run.dataset_id === datasetId);
      return latest?.status === 'pending' || latest?.status === 'running' ? 5_000 : false;
    },
  });
}

export function useAttributes(datasetId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.datasets.attributes(datasetId),
    queryFn: () => listAttributes(datasetId!),
    enabled: !!datasetId,
    staleTime: 2 * 60_000,
  });
}

export function useUpdateAttribute(datasetId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ attributeId, data }: { attributeId: string; data: AttributeMetadataUpdate }) =>
      updateAttribute(datasetId!, attributeId, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.datasets.attributes(datasetId) });
      // PERF-D1: attribute metadata changes can affect validation warnings.
      qc.invalidateQueries({ queryKey: queryKeys.datasets.validation(datasetId) });
    },
  });
}

export function useValidation(datasetId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.datasets.validation(datasetId),
    queryFn: () => validateDataset(datasetId!),
    enabled: !!datasetId,
    // Quality score is persisted at ingest time and only changes on explicit
    // edits; the backend returns the cached value by default. 5 minutes avoids
    // re-triggering the (still non-trivial) validation run on every navigation.
    staleTime: 5 * 60_000,
  });
}
