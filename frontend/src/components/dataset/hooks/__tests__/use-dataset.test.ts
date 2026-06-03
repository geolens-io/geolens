import { renderHook, waitFor } from '@/test/test-utils';
import { vi } from 'vitest';
import { useRef } from 'react';
import { useQueryClient, type QueryClient } from '@tanstack/react-query';

vi.mock('@/api/datasets', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/datasets')>();
  return {
    ...actual,
    getDataset: vi.fn(),
    getDatasetRows: vi.fn(),
    reuploadCommit: vi.fn(),
  };
});

import { getDataset, getDatasetRows, reuploadCommit } from '@/api/datasets';
import { useDataset, useDatasetRows, useReuploadCommit } from '@/components/dataset/hooks/use-dataset';
import { queryKeys } from '@/lib/query-keys';

const mockGetDataset = vi.mocked(getDataset);
const mockGetDatasetRows = vi.mocked(getDatasetRows);
const mockReuploadCommit = vi.mocked(reuploadCommit);

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

  it('passes datasetId, jobId, sridOverride, token, layerName through to reuploadCommit', async () => {
    mockReuploadCommit.mockResolvedValueOnce({ message: 'ok' } as never);
    const { result } = renderWithClient();

    await result.current.mutateAsync({
      datasetId: 'ds-1',
      jobId: 'j1',
      sridOverride: 4326,
      token: 'tok',
      layerName: 'layer-a',
    });

    expect(mockReuploadCommit).toHaveBeenCalledWith('ds-1', 'j1', 4326, 'tok', 'layer-a');
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
