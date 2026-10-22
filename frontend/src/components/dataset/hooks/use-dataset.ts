import { useCallback, useEffect, useRef, useState } from 'react';
import { useQuery, useMutation, useQueryClient, keepPreviousData, type QueryClient } from '@tanstack/react-query';
import { queryKeys } from '@/lib/query-keys';
import { ApiError } from '@/api/client';
import {
  createDataset,
  getDataset,
  getDatasetRows,
  updateDataset,
  setDatasetRetention,
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
  restorePreviousVersion,
  listAttributes,
  updateAttribute,
  validateDataset,
  type DatasetRowsSort,
} from '@/api/datasets';
import { cancelJob } from '@/api/ingest';
import type {
  CreateDatasetRequest,
  DatasetOrigin,
  DatasetUpdateRequest,
  DatasetRetention,
  AttributeMetadataUpdate,
  ReuploadServicePreviewRequest,
  DatasetRefreshRunResponse,
  DatasetRefreshRequest,
  ServiceAuthRequest,
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

export function useDataset(
  id: string,
  options?: {
    refetchInterval?: number | false | ((query: unknown) => number | false);
    staleTime?: number;
    refetchOnWindowFocus?: boolean;
  },
) {
  return useQuery({
    queryKey: queryKeys.datasets.detail(id),
    queryFn: () => getDataset(id),
    enabled: !!id,
    refetchInterval: options?.refetchInterval,
    staleTime: options?.staleTime ?? 60_000,
    // An undefined key would still override the app's default when merged.
    ...(options?.refetchOnWindowFocus !== undefined && {
      refetchOnWindowFocus: options.refetchOnWindowFocus,
    }),
    // A missing dataset stays missing; retrying only delays the not-found page.
    retry: (failureCount, error) =>
      !(error instanceof ApiError && error.status === 404) && failureCount < 1,
  });
}

export function useDatasetRows(
  id: string,
  limit: number,
  cursor: number,
  filters?: Record<string, string>,
  sort?: DatasetRowsSort,
) {
  return useQuery({
    queryKey: queryKeys.datasets.rows(id, limit, cursor, filters, sort),
    queryFn: () => getDatasetRows(id, { limit, after: cursor, filters, sort }),
    enabled: !!id,
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  });
}

/** Publication and visibility changes retire the signatures minted for the dataset. */
function invalidateTileTokens(qc: QueryClient, datasetId: string) {
  qc.invalidateQueries({ queryKey: queryKeys.tileTokens.token(datasetId) });
  qc.invalidateQueries({ queryKey: ['tile-tokens-batch'] });
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
      // The validation query has a 5-minute staleTime; force a refetch so the
      // quality-score badge reflects the recomputed value.
      qc.invalidateQueries({ queryKey: queryKeys.datasets.validation(variables.datasetId) });
      if (variables.data.visibility !== undefined) invalidateTileTokens(qc, variables.datasetId);
    },
  });
}

export function useSetDatasetRetention() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ datasetId, retention, dryRun }: {
      datasetId: string;
      retention: DatasetRetention | null;
      dryRun?: boolean;
    }) => setDatasetRetention(datasetId, retention, { dryRun }),
    onSuccess: (_data, variables) => {
      if (variables.dryRun) return;
      qc.invalidateQueries({ queryKey: queryKeys.datasets.detail(variables.datasetId) });
      qc.invalidateQueries({ queryKey: queryKeys.datasets.all });
      qc.invalidateQueries({ queryKey: queryKeys.search.all });
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
      invalidateTileTokens(qc, variables.datasetId);
    },
  });
}

export function useDeleteDataset() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ datasetId, confirmName }: { datasetId: string; confirmName: string }) =>
      deleteDataset(datasetId, confirmName),
    onSuccess: (_data, variables) => {
      // A plain invalidation would refetch a dataset that no longer exists:
      // its detail query, plus related/ and maps/, which live under the
      // ['datasets'] prefix the list invalidation matches. Cancel all three and
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
    // `layerName` picks one layer of a multi-layer file source.
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
    // `layerName` picks one layer of a multi-layer file source.
    mutationFn: ({
      datasetId,
      jobId,
      sridOverride,
      token,
      layerName,
      // The origin the dialog captured when it staged the replacement, so the
      // commit can refuse a mid-flow rebinding.
      expectedOriginKind,
      reviewFingerprint,
    }: {
      datasetId: string;
      jobId: string;
      sridOverride?: number | null;
      token?: string;
      layerName?: string;
      expectedOriginKind?: DatasetOrigin | null;
      reviewFingerprint?: string | null;
    }) => reuploadCommit(
      datasetId,
      jobId,
      sridOverride,
      token,
      layerName,
      expectedOriginKind,
      reviewFingerprint,
    ),
    // Refetch the dataset-detail warnings banner for the new ingest job.
    // useDatasetJobStatus uses `staleTime: Infinity` and would otherwise hold
    // the prior job's value until a hard refresh.
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: queryKeys.ingest.jobStatusByDataset(variables.datasetId) });
      // The commit admitted a run; an open Sources tab shows it.
      qc.invalidateQueries({ queryKey: queryKeys.datasets.refreshRunsPrefix(variables.datasetId) });
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
    mutationFn: ({
      datasetId,
      token,
      auth,
      acceptBlockedRunId,
      verificationPolicy,
    }: {
      datasetId: string;
      token?: string;
      auth?: ServiceAuthRequest;
      acceptBlockedRunId?: string;
      verificationPolicy?: DatasetRefreshRequest['verification_policy'];
    }) => refreshDataset(datasetId, token, auth, acceptBlockedRunId, verificationPolicy),
    // The dispatched run belongs in history immediately (status "pending"),
    // and dataset-detail health/freshness change once the worker finishes —
    // both queries are cheap enough to just invalidate rather than patch.
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: queryKeys.datasets.refreshRunsPrefix(variables.datasetId) });
      qc.invalidateQueries({ queryKey: queryKeys.datasets.detail(variables.datasetId) });
    },
  });
}

export function useRestorePreviousVersion() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ datasetId, versionNumber }: { datasetId: string; versionNumber: number }) =>
      restorePreviousVersion(datasetId, versionNumber),
    // The restore is queued like a refresh: its run appears in history at once,
    // and the detail's kept versions and the version list change when it settles.
    onSettled: (_data, _error, variables) => {
      qc.invalidateQueries({ queryKey: queryKeys.datasets.refreshRunsPrefix(variables.datasetId) });
      qc.invalidateQueries({ queryKey: queryKeys.datasets.detail(variables.datasetId) });
      qc.invalidateQueries({ queryKey: queryKeys.datasets.versionsPrefix(variables.datasetId) });
    },
  });
}

// One-click cancel for the active refresh run, keyed on the run's
// ingest_job_id. Invalidates what dispatch invalidates: the cancelled run
// belongs in history immediately, and dataset health/freshness may change once
// the row is terminal.
export function useCancelRefreshJob() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ jobId }: { jobId: string; datasetId: string }) => cancelJob(jobId),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: queryKeys.datasets.refreshRunsPrefix(variables.datasetId) });
      qc.invalidateQueries({ queryKey: queryKeys.datasets.detail(variables.datasetId) });
    },
  });
}

export function useDatasetRefreshRuns(
  datasetId: string,
  params: { skip?: number; limit?: number; pollWhenScheduled?: boolean } = {},
) {
  const skip = params.skip ?? 0;
  const limit = params.limit ?? 10;
  return useQuery({
    queryKey: queryKeys.datasets.refreshRuns(datasetId, skip, limit),
    queryFn: () => getDatasetRefreshRuns(datasetId, { skip, limit }),
    enabled: !!datasetId,
    placeholderData: keepPreviousData,
    staleTime: 15_000,
    // Observe externally-started refresh runs on tab refocus. The app disables
    // refetchOnWindowFocus globally (main.tsx), and a refresh dispatched from
    // the CLI or another session never touches this client's cache, so the
    // cached "idle" state would never be revalidated. Refocusing the tab is the
    // signal to check, which lets useDatasetRefreshWatch observe a run it never
    // dispatched.
    //
    // 'always', not `true`: `true` refetches only stale data, so an external run
    // started within staleTime (15s) of the last fetch would be missed on the
    // very focus event meant to catch it.
    refetchOnWindowFocus: 'always',
    // keepPreviousData serves the last successful result as a placeholder for
    // any new query, so navigating from one /datasets/:id to another would
    // briefly show the prior dataset's runs (triggered-by identity, error text,
    // active-run disabled state) under the new key. Filtering by dataset_id
    // here covers every consumer at once (SourceHistory does the same for
    // versions).
    select: (data) => ({
      ...data,
      runs: data.runs.filter((run) => run.dataset_id === datasetId),
    }),
    // The dispatch-time invalidation fires one refetch that lands as "pending",
    // and the app disables refetch-on-focus, so without polling the run would
    // sit "active" forever: SourceRefreshAction's busy gate never re-enables
    // and the history status never updates. Poll while the newest run is in
    // flight and stop once it is terminal. Both consumers share this poll.
    //
    // `query.state.data` is the raw cached response (select runs at the
    // observer, not against the cache), so this re-applies the dataset_id
    // filter rather than trusting index 0 belongs to `datasetId`.
    refetchInterval: (query) => {
      const latest = query.state.data?.runs.find((run) => run.dataset_id === datasetId);
      if (latest?.status === 'pending' || latest?.status === 'running') return 5_000;
      return params.pollWhenScheduled ? 10_000 : false;
    },
  });
}

export interface DatasetRefreshWatch {
  latestRun: DatasetRefreshRunResponse | undefined;
  isBusy: boolean;
  /** Call with the run_id from a refresh dispatch's 202 response. */
  trackDispatchedRun: (runId: string) => void;
}

function isRunActive(status: string | undefined): boolean {
  return status === 'pending' || status === 'running';
}

/**
 * Tracks refresh runs for the dataset. Mounted once at the dataset PAGE level
 * because the "sources" TabsContent lives inside Radix Tabs, which unmounts
 * inactive content (components/ui/tabs.tsx); a tracker inside it would lose the
 * dispatched-run ref and the poll on a tab switch, and a refresh that finished
 * meanwhile would never invalidate its caches. SourceRefreshAction only calls
 * `trackDispatchedRun` with the run_id from its 202 and reads
 * `latestRun`/`isBusy` back as props.
 *
 * The goal is to keep the page consistent with refresh activity for this
 * dataset, so a run kicked off from the CLI, another editor's tab, or already
 * in flight when this hook mounted also invalidates when it goes terminal.
 * `dispatchedRunId` covers one extra case: a strategy fast enough to be
 * terminal on the very first observation (a postgis remeasurement can finish
 * in under a second), where no active→terminal transition is ever observed.
 * Either trigger fires the same invalidation, and `invalidatedRunIdRef` makes
 * it idempotent per run id:
 *   (a) wasActive && !isActive  — any run this hook watched go active→terminal,
 *       regardless of who dispatched it;
 *   (b) latestRunId === dispatchedRunId && !isActive — our dispatch, terminal
 *       on the first poll that saw it, never observed active.
 */
export function useDatasetRefreshWatch(datasetId: string): DatasetRefreshWatch {
  const queryClient = useQueryClient();
  const [dispatchedRunId, setDispatchedRunId] = useState<string | null>(null);
  const wasActiveRef = useRef(false);
  const invalidatedRunIdRef = useRef<string | null>(null);

  const { data: runsData } = useDatasetRefreshRuns(datasetId, { limit: 1 });
  const latestRun = runsData?.runs[0];
  const latestRunId = latestRun?.id;
  const latestRunStatus = latestRun?.status;
  const isBusy = isRunActive(latestRunStatus);

  useEffect(() => {
    const active = isRunActive(latestRunStatus);
    const wasActive = wasActiveRef.current;
    wasActiveRef.current = active;

    if (!latestRunId || active) return;
    const transitionedToTerminal = wasActive;
    const ourDispatchTerminalOnFirstObservation = latestRunId === dispatchedRunId;
    if (!transitionedToTerminal && !ourDispatchTerminalOnFirstObservation) return;
    if (invalidatedRunIdRef.current === latestRunId) return;
    invalidatedRunIdRef.current = latestRunId;

    // Every cache derived from this dataset's data. query-keys.ts has no single
    // shared root across dataset-scoped keys, so this is an explicit list.
    //
    // Invalidated:
    //   - detail: freshness, health, last_refreshed_at, feature_count, extent.
    //   - versionsPrefix: a successful service refresh writes a version; a
    //     postgis run does not, but invalidating unconditionally only costs an
    //     unchanged refetch.
    //   - rowsPrefix: the Data tab's table.
    //   - attributes: data_type/example_values/is_nullable are computed from the
    //     live columns and can move on schema drift.
    //   - validation: the quality score is computed from the data.
    //   - maps.columnValuesPrefix / columnStatsPrefix: filter-picker caches over
    //     the live column distribution (as invalidateColumnCaches does in
    //     use-features.ts).
    //   - search.all: catalog search result summaries.
    //   - ingest.jobStatusByDataset: staleTime Infinity, feeds the persistent
    //     ingest-warnings banner (as useReuploadCommit's onSuccess does).
    //   - relationships.recordsPrefix: the joined related-record rows a
    //     RelatedRecordsPanel section renders, stale after a data replace.
    //   - relationships.listPrefix: every list carries its relationships'
    //     `broken` flag, which a replace of either endpoint changes.
    //
    // Left alone:
    //   - refreshRunsPrefix: this is the query driving this effect.
    //   - datasets.history: an audit log of metadata edits, untouched by a
    //     source-data refresh.
    //   - datasets.related / datasets.maps: declared dataset relationships and
    //     map membership, not recomputed from row data. datasets.all only
    //     aliases these two under the shared 'datasets' root.
    //   - search.facets / search.summary: different roots than search.all, and
    //     no other "this dataset's data changed" mutation touches them.
    //   - tileTokens.*: the credential doesn't change; the backend busts tile
    //     caches with a version-bumped URL carried on the (already invalidated)
    //     detail response.
    //   - everything else in query-keys.ts: different domain.
    queryClient.invalidateQueries({ queryKey: queryKeys.datasets.detail(datasetId) });
    queryClient.invalidateQueries({ queryKey: queryKeys.datasets.versionsPrefix(datasetId) });
    queryClient.invalidateQueries({ queryKey: queryKeys.datasets.rowsPrefix(datasetId) });
    queryClient.invalidateQueries({ queryKey: queryKeys.datasets.attributes(datasetId) });
    queryClient.invalidateQueries({ queryKey: queryKeys.datasets.validation(datasetId) });
    queryClient.invalidateQueries({ queryKey: queryKeys.maps.columnValuesPrefix(datasetId) });
    queryClient.invalidateQueries({ queryKey: queryKeys.maps.columnStatsPrefix(datasetId) });
    queryClient.invalidateQueries({ queryKey: queryKeys.search.all });
    queryClient.invalidateQueries({ queryKey: queryKeys.ingest.jobStatusByDataset(datasetId) });
    queryClient.invalidateQueries({ queryKey: queryKeys.relationships.recordsPrefix(datasetId) });
    queryClient.invalidateQueries({ queryKey: queryKeys.relationships.listPrefix });
  }, [latestRunId, latestRunStatus, dispatchedRunId, datasetId, queryClient]);

  const trackDispatchedRun = useCallback((runId: string) => {
    setDispatchedRunId(runId);
  }, []);

  return { latestRun, isBusy, trackDispatchedRun };
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
      // Attribute metadata changes can affect validation warnings.
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
