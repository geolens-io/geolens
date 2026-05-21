import { renderHook, waitFor } from '@/test/test-utils';
import { vi } from 'vitest';
import { useRef } from 'react';
import { useQueryClient, type QueryClient } from '@tanstack/react-query';

vi.mock('@/api/vrt', () => ({
  listVrtSources: vi.fn(),
  addVrtSource: vi.fn(),
  removeVrtSource: vi.fn(),
  getVrtStatus: vi.fn(),
  getVrtGenerations: vi.fn(),
  regenerateVrt: vi.fn(),
}));

import {
  listVrtSources,
  addVrtSource,
  removeVrtSource,
  getVrtStatus,
  regenerateVrt,
} from '@/api/vrt';
import {
  useVrtSources,
  useAddVrtSource,
  useRemoveVrtSource,
  useVrtStatus,
  useRegenerateVrt,
} from '@/components/import/hooks/use-vrt';
import { queryKeys } from '@/lib/query-keys';

const mockListVrtSources = vi.mocked(listVrtSources);
const mockAddVrtSource = vi.mocked(addVrtSource);
const mockRemoveVrtSource = vi.mocked(removeVrtSource);
const mockGetVrtStatus = vi.mocked(getVrtStatus);
const mockRegenerateVrt = vi.mocked(regenerateVrt);

/**
 * Render a hook factory with access to the wrapper's QueryClient so we can
 * spy on invalidateQueries. Mirrors the helper in use-dataset.test.ts.
 */
function renderWithClient<T>(factory: () => T): { result: { current: T }; qc: QueryClient } {
  let captured: QueryClient | null = null;
  const { result } = renderHook(() => {
    const qc = useQueryClient();
    const ref = useRef<QueryClient | null>(null);
    if (ref.current === null) ref.current = qc;
    captured = ref.current;
    return factory();
  });
  if (!captured) throw new Error('QueryClient capture failed');
  return { result, qc: captured as QueryClient };
}

describe('useVrtSources', () => {
  beforeEach(() => vi.clearAllMocks());

  it('fetches VRT sources for a dataset', async () => {
    const data = { sources: [{ dataset_id: 'ds-2', title: 'Source A' }], total: 1 };
    mockListVrtSources.mockResolvedValueOnce(data as never);

    const { result } = renderHook(() => useVrtSources('ds-1'));

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(data);
    expect(mockListVrtSources).toHaveBeenCalledWith('ds-1');
  });

  it('does not fetch when datasetId is empty', () => {
    const { result } = renderHook(() => useVrtSources(''));

    expect(result.current.fetchStatus).toBe('idle');
    expect(mockListVrtSources).not.toHaveBeenCalled();
  });

  it('returns error state on failure', async () => {
    mockListVrtSources.mockRejectedValueOnce(new Error('Not found'));

    const { result } = renderHook(() => useVrtSources('ds-1'));

    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

describe('useAddVrtSource', () => {
  beforeEach(() => vi.clearAllMocks());

  it('calls addVrtSource on mutate', async () => {
    const response = { message: 'Source added' };
    mockAddVrtSource.mockResolvedValueOnce(response as never);

    const { result } = renderHook(() => useAddVrtSource('ds-1'));

    await result.current.mutateAsync('ds-2');

    expect(mockAddVrtSource).toHaveBeenCalledWith('ds-1', 'ds-2');
  });

  // REMED-01 (ingest-audit P2-06)
  it('invalidates jobStatusByDataset(datasetId) AND existing keys on success', async () => {
    mockAddVrtSource.mockResolvedValueOnce({ message: 'ok' } as never);
    const { result, qc } = renderWithClient(() => useAddVrtSource('ds-1'));
    const spy = vi.spyOn(qc, 'invalidateQueries');

    await result.current.mutateAsync('ds-2');

    // New invalidation (this plan)
    expect(spy).toHaveBeenCalledWith({
      queryKey: queryKeys.ingest.jobStatusByDataset('ds-1'),
    });
    // Existing invalidations preserved
    expect(spy).toHaveBeenCalledWith({ queryKey: queryKeys.vrt.sources('ds-1') });
    expect(spy).toHaveBeenCalledWith({ queryKey: queryKeys.datasets.detail('ds-1') });
  });
});

describe('useRemoveVrtSource', () => {
  beforeEach(() => vi.clearAllMocks());

  // REMED-01 (ingest-audit P2-06)
  it('invalidates jobStatusByDataset(datasetId) AND existing keys on success', async () => {
    mockRemoveVrtSource.mockResolvedValueOnce({ message: 'ok' } as never);
    const { result, qc } = renderWithClient(() => useRemoveVrtSource('ds-1'));
    const spy = vi.spyOn(qc, 'invalidateQueries');

    await result.current.mutateAsync('ds-2');

    expect(mockRemoveVrtSource).toHaveBeenCalledWith('ds-1', 'ds-2');
    expect(spy).toHaveBeenCalledWith({
      queryKey: queryKeys.ingest.jobStatusByDataset('ds-1'),
    });
    expect(spy).toHaveBeenCalledWith({ queryKey: queryKeys.vrt.sources('ds-1') });
    expect(spy).toHaveBeenCalledWith({ queryKey: queryKeys.datasets.detail('ds-1') });
  });
});

describe('useVrtStatus', () => {
  beforeEach(() => vi.clearAllMocks());

  it('fetches VRT status', async () => {
    const data = { status: 'ready', source_count: 3 };
    mockGetVrtStatus.mockResolvedValueOnce(data as never);

    const { result } = renderHook(() => useVrtStatus('ds-1', false));

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(data);
  });

  it('returns error state on failure', async () => {
    mockGetVrtStatus.mockRejectedValueOnce(new Error('Server error'));

    const { result } = renderHook(() => useVrtStatus('ds-1', false));

    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

describe('useRegenerateVrt', () => {
  beforeEach(() => vi.clearAllMocks());

  it('calls regenerateVrt on mutate', async () => {
    const response = { message: 'Regenerating' };
    mockRegenerateVrt.mockResolvedValueOnce(response as never);

    const { result } = renderHook(() => useRegenerateVrt('ds-1'));

    await result.current.mutateAsync();

    expect(mockRegenerateVrt).toHaveBeenCalledWith('ds-1');
  });

  // REMED-01 (ingest-audit P2-06)
  it('invalidates jobStatusByDataset(datasetId) AND existing keys on success', async () => {
    mockRegenerateVrt.mockResolvedValueOnce({ message: 'ok' } as never);
    const { result, qc } = renderWithClient(() => useRegenerateVrt('ds-1'));
    const spy = vi.spyOn(qc, 'invalidateQueries');

    await result.current.mutateAsync();

    expect(spy).toHaveBeenCalledWith({
      queryKey: queryKeys.ingest.jobStatusByDataset('ds-1'),
    });
    // Existing invalidations preserved
    expect(spy).toHaveBeenCalledWith({ queryKey: queryKeys.datasets.detail('ds-1') });
    expect(spy).toHaveBeenCalledWith({ queryKey: queryKeys.vrt.sources('ds-1') });
    expect(spy).toHaveBeenCalledWith({ queryKey: queryKeys.vrt.status('ds-1') });
    expect(spy).toHaveBeenCalledWith({ queryKey: queryKeys.vrt.generations('ds-1') });
  });
});
