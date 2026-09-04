import { renderHook, waitFor } from '@/test/test-utils';
import { act, renderHook as renderHookRTL } from '@testing-library/react';
import { vi } from 'vitest';
import { createElement, useRef, type ReactNode } from 'react';
import { useQueryClient, QueryClient, QueryClientProvider, focusManager } from '@tanstack/react-query';

vi.mock('@/api/datasets', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/datasets')>();
  return {
    ...actual,
    getDataset: vi.fn(),
    getDatasetRows: vi.fn(),
    reuploadCommit: vi.fn(),
    deleteDataset: vi.fn(),
    getDatasetRefreshRuns: vi.fn(),
  };
});

import {
  getDataset,
  getDatasetRows,
  reuploadCommit,
  deleteDataset,
  getDatasetRefreshRuns,
} from '@/api/datasets';
import {
  useDataset,
  useDatasetRows,
  useReuploadCommit,
  useDeleteDataset,
  useDatasetRefreshRuns,
  useDatasetRefreshWatch,
} from '@/components/dataset/hooks/use-dataset';
import { queryKeys } from '@/lib/query-keys';
import type { DatasetRefreshRunResponse } from '@/types/api';

const mockGetDataset = vi.mocked(getDataset);
const mockGetDatasetRows = vi.mocked(getDatasetRows);
const mockReuploadCommit = vi.mocked(reuploadCommit);
const mockDeleteDataset = vi.mocked(deleteDataset);
const mockGetDatasetRefreshRuns = vi.mocked(getDatasetRefreshRuns);

describe('useDataset', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('fetches dataset by id', async () => {
    const mockData = { id: 'ds-1', title: 'Test Dataset' };
    mockGetDataset.mockResolvedValueOnce(mockData as never);

    const { result } = renderHook(() => useDataset('ds-1'));

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(mockData);
    expect(mockGetDataset).toHaveBeenCalledWith('ds-1');
  });

  it('does not fetch when id is empty', () => {
    renderHook(() => useDataset(''));

    expect(mockGetDataset).not.toHaveBeenCalled();
  });

  it('returns error state on failure', async () => {
    mockGetDataset.mockRejectedValueOnce(new Error('Not found'));

    const { result } = renderHook(() => useDataset('bad-id'));

    await waitFor(() => expect(result.current.isError).toBe(true));
  });

  it('returns error state on 404', async () => {
    mockGetDataset.mockRejectedValueOnce(Object.assign(new Error('Not Found'), { status: 404 }));

    const { result } = renderHook(() => useDataset('nonexistent'));

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.data).toBeUndefined();
  });

  it('starts in loading state', () => {
    mockGetDataset.mockReturnValueOnce(new Promise(() => {}) as never);

    const { result } = renderHook(() => useDataset('ds-1'));

    expect(result.current.isLoading).toBe(true);
    expect(result.current.data).toBeUndefined();
  });
});

describe('useDatasetRows', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('fetches rows with pagination params', async () => {
    const mockRows = { rows: [{ name: 'a' }], total: 1 };
    mockGetDatasetRows.mockResolvedValueOnce(mockRows as never);

    const { result } = renderHook(() => useDatasetRows('ds-1', 10, 0));

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(mockRows);
    expect(mockGetDatasetRows).toHaveBeenCalledWith('ds-1', { limit: 10, after: 0, filters: undefined });
  });

  it('does not fetch when id is empty', () => {
    renderHook(() => useDatasetRows('', 10, 0));

    expect(mockGetDatasetRows).not.toHaveBeenCalled();
  });
});

/**
 * REMED-01 (ingest-audit P2-06): useReuploadCommit must invalidate
 * jobStatusByDataset on success so the dataset-detail warnings banner
 * refetches the new job's warnings instead of holding the prior job's
 * cached value (staleTime: Infinity on useDatasetJobStatus).
 */
describe('useReuploadCommit', () => {
  beforeEach(() => vi.clearAllMocks());

  /**
   * Capture the QueryClient from inside the renderHook wrapper so we can
   * spy on invalidateQueries. We co-render useReuploadCommit and a sibling
   * useQueryClient() call to expose the same client the mutation uses.
   */
  function renderWithClient() {
    let captured: QueryClient | null = null;
    const { result } = renderHook(() => {
      const qc = useQueryClient();
      // Capture once on first render — keep a stable reference for assertions.
      const ref = useRef<QueryClient | null>(null);
      if (ref.current === null) ref.current = qc;
      captured = ref.current;
      return useReuploadCommit();
    });
    if (!captured) throw new Error('QueryClient capture failed');
    return { result, qc: captured as QueryClient };
  }

  it('invalidates jobStatusByDataset(datasetId) on success', async () => {
    mockReuploadCommit.mockResolvedValueOnce({ message: 'ok' } as never);
    const { result, qc } = renderWithClient();
    const spy = vi.spyOn(qc, 'invalidateQueries');

    await result.current.mutateAsync({ datasetId: 'ds-1', jobId: 'j1' });

    expect(spy).toHaveBeenCalledWith({
      queryKey: queryKeys.ingest.jobStatusByDataset('ds-1'),
    });
  });

  // fix(#1768): expectedOriginKind joined the positional tail.
  it('passes datasetId, jobId, sridOverride, token, layerName, expectedOriginKind through to reuploadCommit', async () => {
    mockReuploadCommit.mockResolvedValueOnce({ message: 'ok' } as never);
    const { result } = renderWithClient();

    await result.current.mutateAsync({
      datasetId: 'ds-1',
      jobId: 'j1',
      sridOverride: 4326,
      token: 'tok',
      layerName: 'layer-a',
      expectedOriginKind: 'service',
    });

    expect(mockReuploadCommit).toHaveBeenCalledWith(
      'ds-1',
      'j1',
      4326,
      'tok',
      'layer-a',
      'service',
    );
  });

  it('forwards an absent expectedOriginKind as undefined, asserting nothing', async () => {
    mockReuploadCommit.mockResolvedValueOnce({ message: 'ok' } as never);
    const { result } = renderWithClient();

    await result.current.mutateAsync({ datasetId: 'ds-1', jobId: 'j1' });

    expect(mockReuploadCommit).toHaveBeenCalledWith(
      'ds-1',
      'j1',
      undefined,
      undefined,
      undefined,
      undefined,
    );
  });

  it('does NOT invalidate jobStatusByDataset when reuploadCommit rejects', async () => {
    mockReuploadCommit.mockRejectedValueOnce(new Error('boom'));
    const { result, qc } = renderWithClient();
    const spy = vi.spyOn(qc, 'invalidateQueries');

    await expect(
      result.current.mutateAsync({ datasetId: 'ds-1', jobId: 'j1' }),
    ).rejects.toThrow('boom');

    expect(spy).not.toHaveBeenCalledWith({
      queryKey: queryKeys.ingest.jobStatusByDataset('ds-1'),
    });
  });
});

/**
 * fix(#787 item 5): deleting a dataset fired three refetches at the resource that
 * had just been deleted — `/datasets/:id`, plus `/related/` and `/maps/`, which sit
 * under the ['datasets'] prefix the list invalidation matches. All three 404'd.
 */
describe('useDeleteDataset', () => {
  beforeEach(() => vi.clearAllMocks());

  function renderWithClient() {
    let captured: QueryClient | null = null;
    const { result } = renderHook(() => {
      const qc = useQueryClient();
      const ref = useRef<QueryClient | null>(null);
      if (ref.current === null) ref.current = qc;
      captured = ref.current;
      return useDeleteDataset();
    });
    if (!captured) throw new Error('QueryClient capture failed');
    return { result, qc: captured as QueryClient };
  }

  it('marks the deleted dataset own queries stale without fetching them', async () => {
    mockDeleteDataset.mockResolvedValueOnce({ message: 'ok' } as never);
    const { result, qc } = renderWithClient();
    const cancel = vi.spyOn(qc, 'cancelQueries');
    const remove = vi.spyOn(qc, 'removeQueries');
    const invalidate = vi.spyOn(qc, 'invalidateQueries');

    await result.current.mutateAsync({ datasetId: 'ds-1', confirmName: 'Test' });

    for (const queryKey of [
      queryKeys.datasets.detail('ds-1'),
      queryKeys.datasets.related('ds-1'),
      queryKeys.datasets.maps('ds-1'),
    ]) {
      expect(cancel).toHaveBeenCalledWith({ queryKey });
      // Stale, but explicitly not refetched: the observers are still mounted here.
      expect(invalidate).toHaveBeenCalledWith({ queryKey, refetchType: 'none' });
      expect(invalidate).not.toHaveBeenCalledWith({ queryKey });
    }
    // Removing an ACTIVE query makes its observer rebuild and fetch — a live run
    // measured that as one more 404 than marking it stale.
    expect(remove).not.toHaveBeenCalled();
  });

  it('keeps the dataset-list invalidation off the deleted id', async () => {
    mockDeleteDataset.mockResolvedValueOnce({ message: 'ok' } as never);
    const { result, qc } = renderWithClient();
    const invalidate = vi.spyOn(qc, 'invalidateQueries');

    await result.current.mutateAsync({ datasetId: 'ds-1', confirmName: 'Test' });

    const listCall = invalidate.mock.calls.find(
      ([filters]) => filters?.queryKey === queryKeys.datasets.all,
    );
    expect(listCall).toBeDefined();
    const predicate = listCall![0]!.predicate!;
    // related/ and maps/ for the deleted dataset match the ['datasets'] prefix.
    expect(predicate({ queryKey: queryKeys.datasets.related('ds-1') } as never)).toBe(false);
    expect(predicate({ queryKey: queryKeys.datasets.maps('ds-1') } as never)).toBe(false);
    // Everything else under the prefix still refetches.
    expect(predicate({ queryKey: queryKeys.datasets.all } as never)).toBe(true);
    expect(predicate({ queryKey: queryKeys.datasets.related('ds-2') } as never)).toBe(true);
  });
});

/**
 * fix(#1285 codex round 2): `placeholderData: keepPreviousData` shows the
 * last successful result for ANY new query invocation, not just a re-fetch
 * of the same dataset's runs — so navigating straight from one
 * /datasets/:id to another briefly serves the PRIOR dataset's runs under
 * the new query key. SourceHistory already filters `versions` by
 * `dataset_id === dataset.id` for the identical reason; this hook does the
 * same for `runs` so both consumers (SourceRefreshAction's busy gate and
 * SourcePanel's Refresh history section) are fixed from one place.
 */
describe('useDatasetRefreshRuns', () => {
  beforeEach(() => vi.clearAllMocks());

  function makeRun(overrides: Partial<DatasetRefreshRunResponse> = {}): DatasetRefreshRunResponse {
    return {
      id: 'run-1',
      dataset_id: 'ds-1',
      dataset_version_id: null,
      ingest_job_id: 'job-1',
      origin_kind: 'service',
      trigger: 'api',
      status: 'succeeded',
      triggered_by: null,
      triggered_by_username: null,
      started_at: '2026-08-05T00:00:00Z',
      claimed_at: '2026-08-05T00:00:01Z',
      finished_at: '2026-08-05T00:00:30Z',
      feature_count_before: 10,
      feature_count_after: 12,
      schema_diff: null,
      error_code: null,
      error_message: null,
      ...overrides,
    };
  }

  it('drops a run whose dataset_id does not match the requested dataset', async () => {
    mockGetDatasetRefreshRuns.mockResolvedValueOnce({
      runs: [
        makeRun({ id: 'run-stale', dataset_id: 'ds-PREVIOUS' }),
        makeRun({ id: 'run-current', dataset_id: 'ds-1' }),
      ],
      total: 2,
    });

    const { result } = renderHook(() => useDatasetRefreshRuns('ds-1'));

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.runs.map((run) => run.id)).toEqual(['run-current']);
  });

  it('returns every run unfiltered when they all belong to the requested dataset', async () => {
    mockGetDatasetRefreshRuns.mockResolvedValueOnce({
      runs: [makeRun({ id: 'run-a' }), makeRun({ id: 'run-b' })],
      total: 2,
    });

    const { result } = renderHook(() => useDatasetRefreshRuns('ds-1'));

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.runs.map((run) => run.id)).toEqual(['run-a', 'run-b']);
  });

  it('does not fetch when datasetId is empty', () => {
    renderHook(() => useDatasetRefreshRuns(''));

    expect(mockGetDatasetRefreshRuns).not.toHaveBeenCalled();
  });

  /**
   * fix(#1328): main.tsx sets refetchOnWindowFocus: false as the GLOBAL
   * default because a refresh dispatched from the CLI or another editor's
   * session never touches this client's cache — without a per-query
   * override, this query's cached "idle" state is never re-validated by
   * returning focus to the tab. The shared test client (test-utils.tsx)
   * doesn't set that global default, so asserting against it would pass
   * even without the fix (react-query's own default is already `true`).
   * Build a client that mirrors main.tsx's global `false` instead, so a
   * refetch here can only be explained by this query's own override.
   *
   * fix(#1328 codex review): the override must be 'always', not `true`.
   * `true` only refetches when the cached data is already stale, but an
   * external run can start and this tab can regain focus inside the SAME
   * 15s staleTime window as this query's last fetch — the exact case a
   * user "checking after a colleague ran a refresh" is likely to hit, and
   * the one `true` silently drops (worse, nothing schedules a fetch once
   * the data merely becomes stale afterward, since refetchInterval is off
   * in the idle state — the page would wait on a second, unrelated focus
   * or a remount to notice). Assert the fresh-window case directly rather
   * than the now-irrelevant "skipped while fresh" behavior.
   */
  it('refetches on window focus regardless of staleness, including while data is still fresh', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      mockGetDatasetRefreshRuns.mockResolvedValue({
        runs: [makeRun({ id: 'run-1', status: 'succeeded' })],
        total: 1,
      });

      const queryClient = new QueryClient({
        defaultOptions: { queries: { retry: false, gcTime: 0, refetchOnWindowFocus: false } },
      });
      function Wrapper({ children }: { children: ReactNode }) {
        return createElement(QueryClientProvider, { client: queryClient }, children);
      }

      const { result } = renderHookRTL(() => useDatasetRefreshRuns('ds-1'), { wrapper: Wrapper });

      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(result.current.isSuccess).toBe(true);
      expect(mockGetDatasetRefreshRuns).toHaveBeenCalledTimes(1);

      // Still well inside the 15s staleTime — an external run could have
      // started and finished in this window. This is the case
      // refetchOnWindowFocus: true would have missed.
      await act(async () => {
        focusManager.setFocused(true);
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(mockGetDatasetRefreshRuns).toHaveBeenCalledTimes(2);

      // Merely becoming stale, with no focus/mount/reconnect event, still
      // doesn't schedule a fetch on its own.
      focusManager.setFocused(false);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(15_001);
      });
      expect(mockGetDatasetRefreshRuns).toHaveBeenCalledTimes(2);

      // A later focus event still refetches once the data is genuinely
      // stale too — 'always' keeps covering the case `true` covered, it
      // just no longer depends on it.
      await act(async () => {
        focusManager.setFocused(true);
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(mockGetDatasetRefreshRuns).toHaveBeenCalledTimes(3);
    } finally {
      focusManager.setFocused(undefined);
      vi.useRealTimers();
    }
  });
});

/**
 * fix(#1285 codex round 4): this hook is the extracted "watch a dispatched
 * refresh run" concern, meant to be mounted at the dataset PAGE level so its
 * poll and its run-id tracking survive a tab switch away from "sources"
 * (SourceRefreshAction used to own this and lived inside a Radix
 * TabsContent, which unmounts inactive tabs). The invalidation set below is
 * the full "this dataset's DATA changed" sweep — the same class of caches
 * `invalidateColumnCaches` / `invalidateFeatureDerived` in use-features.ts
 * already invalidate for a feature edit, plus versionsPrefix (a service
 * refresh writes a version; a feature edit never does).
 */
describe('useDatasetRefreshWatch', () => {
  beforeEach(() => vi.clearAllMocks());

  function makeRun(overrides: Partial<DatasetRefreshRunResponse> = {}): DatasetRefreshRunResponse {
    return {
      id: 'run-1',
      dataset_id: 'ds-1',
      dataset_version_id: null,
      ingest_job_id: 'job-1',
      origin_kind: 'service',
      trigger: 'api',
      status: 'succeeded',
      triggered_by: null,
      triggered_by_username: null,
      started_at: '2026-08-05T00:00:00Z',
      claimed_at: '2026-08-05T00:00:01Z',
      finished_at: '2026-08-05T00:00:30Z',
      feature_count_before: 10,
      feature_count_after: 12,
      schema_diff: null,
      error_code: null,
      error_message: null,
      ...overrides,
    };
  }

  const DATA_DERIVED_KEYS = [
    queryKeys.datasets.detail('ds-1'),
    queryKeys.datasets.versionsPrefix('ds-1'),
    queryKeys.datasets.rowsPrefix('ds-1'),
    queryKeys.datasets.attributes('ds-1'),
    queryKeys.datasets.validation('ds-1'),
    queryKeys.maps.columnValuesPrefix('ds-1'),
    queryKeys.maps.columnStatsPrefix('ds-1'),
    queryKeys.search.all,
    // fix(#1285 codex round 5): staleTime Infinity, feeds the persistent
    // ingest-warnings banner (mirrors useReuploadCommit's own invalidation).
    queryKeys.ingest.jobStatusByDataset('ds-1'),
    // fix(#1285 codex round 5): the joined related-record rows a mounted
    // RelatedRecordsPanel section renders — stale after a data replace.
    queryKeys.relationships.recordsPrefix('ds-1'),
  ];

  function renderWithClient() {
    let captured: QueryClient | null = null;
    const { result } = renderHook(() => {
      const qc = useQueryClient();
      const ref = useRef<QueryClient | null>(null);
      if (ref.current === null) ref.current = qc;
      captured = ref.current;
      return useDatasetRefreshWatch('ds-1');
    });
    if (!captured) throw new Error('QueryClient capture failed');
    return { result, qc: captured as QueryClient };
  }

  it('reports isBusy from the latest run and stays false with none', async () => {
    mockGetDatasetRefreshRuns.mockResolvedValue({ runs: [], total: 0 });
    const { result } = renderWithClient();

    await waitFor(() => expect(result.current.latestRun).toBeUndefined());
    expect(result.current.isBusy).toBe(false);
  });

  it('invalidates the full data-derived cache set once the tracked run is first observed terminal', async () => {
    mockGetDatasetRefreshRuns.mockResolvedValue({
      runs: [makeRun({ id: 'run-1', status: 'succeeded' })],
      total: 1,
    });
    const { result, qc } = renderWithClient();
    const spy = vi.spyOn(qc, 'invalidateQueries');

    await waitFor(() => expect(result.current.latestRun?.id).toBe('run-1'));
    // Simulates SourceRefreshAction reporting its 202 response's run_id.
    act(() => result.current.trackDispatchedRun('run-1'));

    for (const queryKey of DATA_DERIVED_KEYS) {
      await waitFor(() => expect(spy).toHaveBeenCalledWith({ queryKey }));
    }
  });

  it('does not invalidate while the tracked run is still active', async () => {
    mockGetDatasetRefreshRuns.mockResolvedValue({
      runs: [makeRun({ id: 'run-1', status: 'running' })],
      total: 1,
    });
    const { result, qc } = renderWithClient();
    const spy = vi.spyOn(qc, 'invalidateQueries');

    await waitFor(() => expect(result.current.latestRun?.id).toBe('run-1'));
    expect(result.current.isBusy).toBe(true);
    act(() => result.current.trackDispatchedRun('run-1'));

    expect(spy).not.toHaveBeenCalled();
  });

  it('does not invalidate for a run that is ALREADY terminal on the very first observation and was never dispatched from here', async () => {
    // Distinct from the "fast dispatch" case below: nothing was cached
    // before this run completed from this hook's perspective (a fresh
    // mount/page load), so there is nothing stale to invalidate — and
    // trackDispatchedRun is never called, so rule (b) can't fire either.
    mockGetDatasetRefreshRuns.mockResolvedValue({
      runs: [makeRun({ id: 'run-1', status: 'succeeded' })],
      total: 1,
    });
    const { result, qc } = renderWithClient();
    const spy = vi.spyOn(qc, 'invalidateQueries');

    await waitFor(() => expect(result.current.latestRun?.id).toBe('run-1'));
    expect(spy).not.toHaveBeenCalled();
  });

  // fix(#1285 codex round 5): the core round-5 bug. Round 4 gated the whole
  // invalidation effect on `latestRunId === dispatchedRunId`, so a run this
  // hook never dispatched — the CLI, another editor's session, or one
  // already active when this hook mounted — could transition all the way to
  // terminal under this hook's OWN continuous polling and invalidate
  // nothing. dispatchedRunId stays null for the hook's entire lifetime here.
  it('invalidates everything when an OBSERVED run transitions active -> terminal, even though this hook never dispatched it', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      mockGetDatasetRefreshRuns.mockResolvedValue({
        runs: [makeRun({ id: 'run-external', status: 'running' })],
        total: 1,
      });
      const { result, qc } = renderWithClient();
      const spy = vi.spyOn(qc, 'invalidateQueries');

      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(result.current.latestRun?.id).toBe('run-external');
      expect(result.current.isBusy).toBe(true);
      expect(spy).not.toHaveBeenCalled();

      // useDatasetRefreshRuns polls every 5s while the latest run is active.
      mockGetDatasetRefreshRuns.mockResolvedValue({
        runs: [makeRun({ id: 'run-external', status: 'succeeded' })],
        total: 1,
      });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(6_000);
      });

      for (const queryKey of DATA_DERIVED_KEYS) {
        expect(spy).toHaveBeenCalledWith({ queryKey });
      }
    } finally {
      vi.useRealTimers();
    }
  });
});
