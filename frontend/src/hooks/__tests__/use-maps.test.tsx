import { renderHook, waitFor } from '@/test/test-utils';
import { renderHook as renderHookWithWrapper, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { vi } from 'vitest';

vi.mock('@/api/maps', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/maps')>();
  return {
    ...actual,
    listMaps: vi.fn(),
    getMap: vi.fn(),
    deleteMap: vi.fn(),
    createMap: vi.fn(),
  };
});

import { listMaps, getMap, deleteMap, createMap } from '@/api/maps';
import { useMaps, useMap, useDeleteMap, useCreateMap } from '@/hooks/use-maps';
import { queryKeys } from '@/lib/query-keys';

const mockListMaps = vi.mocked(listMaps);
const mockGetMap = vi.mocked(getMap);
const mockDeleteMap = vi.mocked(deleteMap);
const mockCreateMap = vi.mocked(createMap);

describe('useMaps', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('fetches maps list', async () => {
    const mockData = { maps: [{ id: 'm1', name: 'Map 1' }], total: 1 };
    mockListMaps.mockResolvedValueOnce(mockData as never);

    const { result } = renderHook(() => useMaps());

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(mockData);
  });

  it('passes browse params to API', async () => {
    mockListMaps.mockResolvedValueOnce({ maps: [], total: 0 } as never);

    const params = { search: 'test', limit: 5 };
    renderHook(() => useMaps(params));

    await waitFor(() => expect(mockListMaps).toHaveBeenCalledWith(params));
  });
});

describe('useMap', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('fetches single map by id', async () => {
    const mockData = { id: 'm1', name: 'Map 1', layers: [] };
    mockGetMap.mockResolvedValueOnce(mockData as never);

    const { result } = renderHook(() => useMap('m1'));

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(mockData);
  });

  it('does not fetch when id is undefined', () => {
    renderHook(() => useMap(undefined));

    expect(mockGetMap).not.toHaveBeenCalled();
  });

  it('returns error state on failure', async () => {
    mockGetMap.mockRejectedValueOnce(new Error('Not found'));

    const { result } = renderHook(() => useMap('bad-id'));

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.data).toBeUndefined();
  });
});

describe('useDeleteMap', () => {
  beforeEach(() => vi.clearAllMocks());

  it('removes per-map cache entries on successful delete (SMOKE-v1013-F3)', async () => {
    // Set up a QueryClient with cached entries for the soon-to-be-deleted map.
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
    });
    const deletedId = 'map-to-be-deleted';
    const otherId = 'other-map';
    qc.setQueryData(queryKeys.maps.detail(deletedId), { id: deletedId });
    qc.setQueryData(queryKeys.maps.shareToken(deletedId), { token: 'abc' });
    qc.setQueryData(queryKeys.maps.embedTokens(deletedId), [{ id: 't1' }]);
    qc.setQueryData(['map-history', deletedId, 'list'], { history: [] });
    // Unrelated map should NOT be evicted.
    qc.setQueryData(queryKeys.maps.detail(otherId), { id: otherId });

    mockDeleteMap.mockResolvedValueOnce(undefined as never);

    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    );

    const { result } = renderHookWithWrapper(() => useDeleteMap(), { wrapper });
    await act(async () => {
      await result.current.mutateAsync(deletedId);
    });

    // Per-map caches for the deleted map are removed entirely.
    expect(qc.getQueryData(queryKeys.maps.detail(deletedId))).toBeUndefined();
    expect(qc.getQueryData(queryKeys.maps.shareToken(deletedId))).toBeUndefined();
    expect(qc.getQueryData(queryKeys.maps.embedTokens(deletedId))).toBeUndefined();
    expect(qc.getQueryData(['map-history', deletedId, 'list'])).toBeUndefined();
    // Unrelated map's cache survives.
    expect(qc.getQueryData(queryKeys.maps.detail(otherId))).toEqual({ id: otherId });
  });

});

// BUG-039: map mutations must invalidate the dataset-scoped "used in maps"
// lists (queryKeys.datasets.maps = ['datasets', id, 'maps']). Pre-fix only
// 'maps'-rooted keys were touched, so a dataset's panel kept showing a
// deleted/renamed/newly-created map until the 60s staleTime elapsed.
describe('BUG-039: map mutations invalidate dataset "used in maps" lists', () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(() => vi.restoreAllMocks());

  function makeQc() {
    return new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
    });
  }

  // queryKeys.datasets.all === ['datasets'] is the prefix that matches the
  // dataset-scoped map lists (['datasets', id, 'maps']). Assert it was invalidated.
  function invalidatedDatasetsRoot(calls: Array<unknown[]>) {
    return calls.some((c) => {
      const k = (c[0] as { queryKey?: unknown[] })?.queryKey;
      return Array.isArray(k) && k.length === 1 && k[0] === 'datasets';
    });
  }

  it('useDeleteMap invalidates the dataset maps list', async () => {
    const qc = makeQc();
    const spy = vi.spyOn(qc, 'invalidateQueries');
    mockDeleteMap.mockResolvedValueOnce(undefined as never);

    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    );
    const { result } = renderHookWithWrapper(() => useDeleteMap(), { wrapper });
    await act(async () => {
      await result.current.mutateAsync('m1');
    });

    expect(invalidatedDatasetsRoot(spy.mock.calls)).toBe(true);
  });

  it('useCreateMap invalidates the dataset maps list', async () => {
    const qc = makeQc();
    const spy = vi.spyOn(qc, 'invalidateQueries');
    mockCreateMap.mockResolvedValueOnce({ id: 'new-map' } as never);

    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    );
    const { result } = renderHookWithWrapper(() => useCreateMap(), { wrapper });
    await act(async () => {
      await result.current.mutateAsync({ name: 'New', layers: [] } as never);
    });

    expect(invalidatedDatasetsRoot(spy.mock.calls)).toBe(true);
  });
});

describe('useMaps – empty list', () => {
  beforeEach(() => vi.clearAllMocks());

  it('handles empty maps list', async () => {
    mockListMaps.mockResolvedValueOnce({ maps: [], total: 0 } as never);

    const { result } = renderHook(() => useMaps());

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual({ maps: [], total: 0 });
  });

  it('returns error state on API failure', async () => {
    mockListMaps.mockRejectedValueOnce(new Error('Server error'));

    const { result } = renderHook(() => useMaps());

    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});
