import { useCallback, useEffect, useRef, useState } from 'react';
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
import { cancelJob } from '@/api/ingest';
import type {
  CreateDatasetRequest,
  DatasetUpdateRequest,
  AttributeMetadataUpdate,
  ReuploadServicePreviewRequest,
  DatasetRefreshRunResponse,
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

// feat(#1677): one-click cancel for the active refresh run, keyed on the
// run's ingest_job_id. Invalidates exactly what dispatch invalidates: the
// cancelled run belongs in history immediately, and dataset health/freshness
// may change once the row is terminal.
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
    // fix(#1328): observe externally-started refresh runs on tab refocus.
    // The app disables refetchOnWindowFocus globally (main.tsx) because a
    // refresh dispatched from the CLI or another editor's session never
    // touches this client's cache — under the global default, this query's
    // cached "idle" state (no active run) is otherwise never re-validated
    // until something else remounts or invalidates it. Overriding the
    // default here means returning focus to the tab re-fetches runs, so
    // useDatasetRefreshWatch's active->terminal transition guard gets a
    // chance to observe a run it never dispatched and never saw start.
    //
    // 'always', not `true`: plain `true` only refetches if the cached data
    // is already stale, so an external run started less than staleTime
    // (15s) after this query's last fetch would be missed on the very
    // focus event meant to catch it — and since becoming stale later is
    // passive (nothing schedules a fetch once refetchInterval is off), the
    // page could then wait on a second, unrelated focus/remount to notice.
    // Focus returning to the tab IS the signal to check for an external
    // run, independent of this query's own freshness clock.
    refetchOnWindowFocus: 'always',
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
 * fix(#1285 codex round 4): SourceRefreshAction used to own this tracking
 * itself, but it lives inside the "sources" TabsContent, and Radix Tabs
 * unmounts inactive content by default (components/ui/tabs.tsx) — switching
 * tabs mid-refresh destroyed the dispatched-run ref AND stopped the poll, so
 * a refresh that finished while the user was looking at another tab never
 * got its caches invalidated. Mount this hook once at the dataset PAGE level
 * instead, where it survives every tab switch; SourceRefreshAction only
 * calls `trackDispatchedRun` with the run_id from its 202 and reads
 * `latestRun`/`isBusy` back as props.
 *
 * fix(#1285 codex round 5): round 4 gated the whole invalidation effect on
 * `latestRunId === dispatchedRunId`, so a run this hook never dispatched —
 * kicked off from the CLI, another editor's tab, or already in flight when
 * this hook mounted (a page navigation, a reload) — could transition all
 * the way to terminal under continuous polling and invalidate nothing. This
 * hook's job is "keep the page consistent with refresh activity for this
 * dataset", not "track my own dispatch", so the transition check below no
 * longer requires having dispatched anything. `dispatchedRunId` is kept for
 * exactly one remaining case: a strategy fast enough to already be terminal
 * on the very FIRST observation (round 3 — a postgis remeasurement can
 * finish in under a second), where no active→terminal transition is ever
 * observed to catch. Two independent triggers, either one fires the same
 * invalidation, and `invalidatedRunIdRef` makes it idempotent per run id:
 *   (a) wasActive && !isActive  — any run this hook watched go active→terminal,
 *       regardless of who dispatched it;
 *   (b) latestRunId === dispatchedRunId && !isActive — OUR dispatch, terminal
 *       on the first poll that ever saw it, never observed active.
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

    // fix(#1285 codex round 5): the full sweep of caches derived from this
    // dataset's DATA. query-keys.ts's own header notes there is no single
    // shared root across dataset-scoped keys ("Some domains use different
    // roots for list vs detail"), confirmed by walking every entry in the
    // file — so this is an EXHAUSTIVE enumeration, not a prefix shortcut.
    //
    // Included, and why:
    //   - detail: freshness/health/last_refreshed_at/feature_count/extent.
    //   - versionsPrefix: a successful SERVICE refresh writes a version
    //     (tasks_reupload.py); a postgis run does not, but invalidating
    //     unconditionally just costs an unchanged refetch.
    //   - rowsPrefix: the Data tab's table.
    //   - attributes: data_type/example_values/is_nullable are computed
    //     from the live columns and can move on schema drift.
    //   - validation: the quality score is computed from the data.
    //   - maps.columnValuesPrefix / columnStatsPrefix: filter-picker caches
    //     over the live column distribution (mirrors invalidateColumnCaches
    //     in use-features.ts, the same-class precedent for "this dataset's
    //     rows changed").
    //   - search.all: catalog search result summaries.
    //   - ingest.jobStatusByDataset: staleTime Infinity, feeds the
    //     persistent ingest-warnings banner (mirrors useReuploadCommit's own
    //     onSuccess a few lines up — a refresh is an ingest-adjacent
    //     operation on this dataset exactly like a reupload).
    //   - relationships.recordsPrefix: the actual joined related-record
    //     ROWS a RelatedRecordsPanel section renders, fetched by feature —
    //     genuinely stale after a data replace.
    //
    // Considered and excluded, and why:
    //   - refreshRunsPrefix: this IS the query driving this effect; already
    //     the freshest data there is, nothing to invalidate.
    //   - datasets.history: an AUDIT LOG of metadata edits (getDatasetHistory
    //     -> AuditLogListResponse), not touched by a source-data refresh.
    //   - datasets.related / datasets.maps: declared dataset-to-dataset
    //     relationships and map-membership lists — not recomputed from row
    //     data. datasets.all exists only to alias these two under the
    //     shared 'datasets' root (see useUpdateDataset), so it adds nothing
    //     once both are excluded.
    //   - relationships.list: the relationship DEFINITION (source/target
    //     column) is user-configured, not recomputed by a refresh.
    //   - search.facets / search.summary: different root than search.all
    //     (['facets', params] / ['catalog-summary'], not ['search', ...]) —
    //     confirmed no existing "this dataset's data changed" mutation in
    //     this codebase touches them either (invalidateFeatureDerived does
    //     not), so this does not invent a wider net than that precedent.
    //   - tileTokens.*: the credential doesn't change; the backend already
    //     busts tile caches with a version-bumped URL carried on the (already
    //     invalidated) detail response.
    //   - vrt.* / ogcRecords.* / collections.* / admin.* / settings.* /
    //     everything else in query-keys.ts: different domain entirely.
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
