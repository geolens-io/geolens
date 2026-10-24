import { renderHook, waitFor } from '@/test/test-utils';
import { renderHook as renderHookWithWrapper, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { vi } from 'vitest';
import { toast } from 'sonner';

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

vi.mock('@/api/maps', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/maps')>();
  return {
    ...actual,
    listMaps: vi.fn(),
    getMap: vi.fn(),
    deleteMap: vi.fn(),
    createMap: vi.fn(),
    publishMap: vi.fn(),
    setMapGroups: vi.fn(),
    checkMapVisibility: vi.fn(),
  };
});

import { ApiError } from '@/api/client';
import { listMaps, getMap, deleteMap, createMap, publishMap, setMapGroups, checkMapVisibility } from '@/api/maps';
import { useMaps, useMap, useDeleteMap, useCreateMap, usePublishMap, useSetMapGroups, useLayersHiddenFromMapGroups } from '@/hooks/use-maps';
import { queryKeys } from '@/lib/query-keys';
import type { MapVisibility } from '@/types/api';

const mockListMaps = vi.mocked(listMaps);
const mockGetMap = vi.mocked(getMap);
const mockDeleteMap = vi.mocked(deleteMap);
const mockCreateMap = vi.mocked(createMap);
const mockPublishMap = vi.mocked(publishMap);
const mockSetMapGroups = vi.mocked(setMapGroups);
const mockCheckMapVisibility = vi.mocked(checkMapVisibility);

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
    mockGetMap.mockRejectedValueOnce(new ApiError('Not found', 404));

    const { result } = renderHook(() => useMap('bad-id'));

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.data).toBeUndefined();
  });

  function retryingWrapper({ children }: { children: ReactNode }) {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: 1, retryDelay: 0 } } });
    return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  }

  it.each([404, 403])('requests a map once when the API answers %i', async (status) => {
    mockGetMap.mockRejectedValue(new ApiError('nope', status));

    const { result } = renderHookWithWrapper(() => useMap('gone'), { wrapper: retryingWrapper });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(mockGetMap).toHaveBeenCalledTimes(1);
  });

  it('retries a server error once', async () => {
    mockGetMap.mockRejectedValue(new ApiError('boom', 503));

    const { result } = renderHookWithWrapper(() => useMap('flaky'), { wrapper: retryingWrapper });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(mockGetMap).toHaveBeenCalledTimes(2);
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

// Map mutations must invalidate the dataset-scoped "used in maps"
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

// usePublishMap's onError used to fire the generic
// "failed to update visibility" toast on EVERY rejection, including the
// non-public-datasets 400 that SharePanel now surfaces inline — so that one
// case showed both a generic toast and the specific inline message. The hook
// skips its own toast only for that one case (via the shared
// `nonPublicDatasetsFromError` predicate); every other failure still gets it.
describe('usePublishMap', () => {
  beforeEach(() => vi.clearAllMocks());

  function makeQc() {
    return new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
    });
  }

  function wrapperFor(qc: QueryClient) {
    return ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    );
  }

  function seedGroups(qc: QueryClient, groups: { id: string; name: string }[]) {
    qc.setQueryData(queryKeys.maps.detail('map-1'), { id: 'map-1', groups });
  }

  it('unshares a map with groups first, and skips the visibility PUT once it is private', async () => {
    mockSetMapGroups.mockResolvedValueOnce({ visibility: 'private', groups: [] });
    const qc = makeQc();
    seedGroups(qc, [{ id: 'g-1', name: 'Surveyors' }]);
    const { result } = renderHookWithWrapper(() => usePublishMap(), { wrapper: wrapperFor(qc) });

    let outcome;
    await act(async () => {
      outcome = await result.current.mutateAsync({ id: 'map-1', visibility: 'private' });
    });

    expect(mockSetMapGroups).toHaveBeenCalledWith('map-1', []);
    expect(mockPublishMap).not.toHaveBeenCalled();
    expect(outcome).toEqual({ clearedGroups: true, visibility: 'private' });
  });

  it('still sets the visibility when unsharing leaves the map somewhere else', async () => {
    mockSetMapGroups.mockResolvedValueOnce({ visibility: 'internal', groups: [] });
    mockPublishMap.mockResolvedValueOnce({} as never);
    const qc = makeQc();
    seedGroups(qc, [{ id: 'g-1', name: 'Surveyors' }]);
    const { result } = renderHookWithWrapper(() => usePublishMap(), { wrapper: wrapperFor(qc) });

    await act(async () => {
      await result.current.mutateAsync({ id: 'map-1', visibility: 'private' });
    });

    expect(mockPublishMap).toHaveBeenCalledWith('map-1', 'private');
  });

  it('refetches the map when the visibility PUT fails after the groups were cleared', async () => {
    mockSetMapGroups.mockResolvedValueOnce({ visibility: 'internal', groups: [] });
    mockPublishMap.mockRejectedValueOnce(new ApiError('Internal Server Error', 500));
    const qc = makeQc();
    seedGroups(qc, [{ id: 'g-1', name: 'Surveyors' }]);
    const invalidate = vi.spyOn(qc, 'invalidateQueries');
    const { result } = renderHookWithWrapper(() => usePublishMap(), { wrapper: wrapperFor(qc) });

    await act(async () => {
      await expect(
        result.current.mutateAsync({ id: 'map-1', visibility: 'private' }),
      ).rejects.toThrow();
    });

    expect(invalidate).toHaveBeenCalledWith({ queryKey: queryKeys.maps.detail('map-1') });
  });

  it('leaves groups alone for a map without any', async () => {
    mockPublishMap.mockResolvedValueOnce({} as never);
    const qc = makeQc();
    seedGroups(qc, []);
    const { result } = renderHookWithWrapper(() => usePublishMap(), { wrapper: wrapperFor(qc) });

    await act(async () => {
      await result.current.mutateAsync({ id: 'map-1', visibility: 'private' });
    });

    expect(mockSetMapGroups).not.toHaveBeenCalled();
  });

  it('fires the generic toast on an ordinary failure', async () => {
    mockPublishMap.mockRejectedValueOnce(new ApiError('Internal Server Error', 500));
    const qc = makeQc();
    const { result } = renderHookWithWrapper(() => usePublishMap(), { wrapper: wrapperFor(qc) });

    await act(async () => {
      await expect(
        result.current.mutateAsync({ id: 'map-1', visibility: 'public' }),
      ).rejects.toThrow();
    });

    expect(vi.mocked(toast.error)).toHaveBeenCalledTimes(1);
  });

  it('does not fire the generic toast when the map holds non-public datasets', async () => {
    mockPublishMap.mockRejectedValueOnce(
      new ApiError('Cannot set visibility to public: map contains non-public datasets', 400, {
        message: 'Cannot set visibility to public: map contains non-public datasets',
        datasets: 'Large Lakes',
      }),
    );
    const qc = makeQc();
    const { result } = renderHookWithWrapper(() => usePublishMap(), { wrapper: wrapperFor(qc) });

    await act(async () => {
      await expect(
        result.current.mutateAsync({ id: 'map-1', visibility: 'public' }),
      ).rejects.toThrow();
    });

    expect(vi.mocked(toast.error)).not.toHaveBeenCalled();
  });
});

// The Share dialog rebuilds its group draft from the cached map right after a
// save; a cache still holding the replaced groups would send them again.
describe('map audience cache', () => {
  beforeEach(() => vi.clearAllMocks());

  const SURVEYORS = { id: 'g-1', name: 'Surveyors' };
  const PLANNERS = { id: 'g-2', name: 'Planners' };

  function keepingQc() {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    qc.setQueryData(queryKeys.maps.detail('map-1'), { id: 'map-1', visibility: 'restricted', groups: [SURVEYORS] });
    return qc;
  }

  function wrapperFor(qc: QueryClient) {
    return ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    );
  }

  it('holds the saved groups before a group save resolves', async () => {
    mockSetMapGroups.mockResolvedValueOnce({ visibility: 'restricted', groups: [PLANNERS] });
    const qc = keepingQc();
    const { result } = renderHookWithWrapper(() => useSetMapGroups(), { wrapper: wrapperFor(qc) });

    await act(async () => {
      await result.current.mutateAsync({ mapId: 'map-1', groupIds: ['g-2'] });
    });

    expect(qc.getQueryData(queryKeys.maps.detail('map-1'))).toMatchObject({
      visibility: 'restricted',
      groups: [PLANNERS],
    });
  });

  it("sends a visibility change only after the same map's group save settles", async () => {
    let finishSave!: (value: { visibility: string; groups: typeof PLANNERS[] }) => void;
    mockSetMapGroups.mockReturnValueOnce(new Promise((resolve) => { finishSave = resolve; }) as never);
    mockPublishMap.mockResolvedValueOnce({ visibility: 'internal' } as never);
    const qc = keepingQc();
    const { result } = renderHookWithWrapper(
      () => ({ save: useSetMapGroups('map-1'), publish: usePublishMap('map-1') }),
      { wrapper: wrapperFor(qc) },
    );

    act(() => {
      result.current.save.mutate({ mapId: 'map-1', groupIds: ['g-2'] });
      result.current.publish.mutate({ id: 'map-1', visibility: 'internal' });
    });
    await waitFor(() => expect(mockSetMapGroups).toHaveBeenCalled());
    expect(mockPublishMap).not.toHaveBeenCalled();

    await act(async () => finishSave({ visibility: 'restricted', groups: [PLANNERS] }));
    await waitFor(() => expect(mockPublishMap).toHaveBeenCalledWith('map-1', 'internal'));
  });

  it("refetches the map's share link and embed tokens after a group save", async () => {
    mockSetMapGroups.mockResolvedValueOnce({ visibility: 'restricted', groups: [PLANNERS] });
    const qc = keepingQc();
    const invalidate = vi.spyOn(qc, 'invalidateQueries');
    const { result } = renderHookWithWrapper(() => useSetMapGroups('map-1'), { wrapper: wrapperFor(qc) });

    await act(async () => {
      await result.current.mutateAsync({ mapId: 'map-1', groupIds: ['g-2'] });
    });

    expect(invalidate).toHaveBeenCalledWith({ queryKey: queryKeys.maps.shareToken('map-1') });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: queryKeys.maps.embedTokens('map-1') });
  });

  it('holds the cleared groups once "Only you" unshares the map', async () => {
    mockSetMapGroups.mockResolvedValueOnce({ visibility: 'private', groups: [] });
    const qc = keepingQc();
    const { result } = renderHookWithWrapper(() => usePublishMap(), { wrapper: wrapperFor(qc) });

    await act(async () => {
      await result.current.mutateAsync({ id: 'map-1', visibility: 'private' });
    });

    expect(qc.getQueryData(queryKeys.maps.detail('map-1'))).toMatchObject({ visibility: 'private', groups: [] });
  });
});

describe('useLayersHiddenFromMapGroups', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockCheckMapVisibility.mockResolvedValue({
      non_public_datasets: [],
      has_non_public: false,
      hidden_from_groups: [
        {
          layer_id: 'layer-1',
          layer_title: 'Parcels',
          dataset_id: 'ds-1',
          dataset_title: 'Parcels',
          group_ids: ['g-1'],
          can_share: true,
        },
      ],
    });
  });

  function renderGaps(visibility: MapVisibility, groups: { id: string }[] | null) {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const view = renderHookWithWrapper(
      (props: { visibility: MapVisibility; groups: { id: string }[] | null }) =>
        useLayersHiddenFromMapGroups('map-1', props.visibility, props.groups),
      {
        initialProps: { visibility, groups },
        wrapper: ({ children }: { children: ReactNode }) => (
          <QueryClientProvider client={qc}>{children}</QueryClientProvider>
        ),
      },
    );
    return { qc, ...view };
  }

  it("names the layers the server says the map's groups can't read", async () => {
    const { result } = renderGaps('restricted', [{ id: 'g-1' }]);

    await waitFor(() => expect(result.current.has('layer-1')).toBe(true));
    expect(result.current.has('layer-2')).toBe(false);
    expect(mockCheckMapVisibility).toHaveBeenCalledWith('map-1');
  });

  it('asks again when the map is refetched, and forgets the answer once the map is not restricted', async () => {
    const { qc, result, rerender } = renderGaps('restricted', [{ id: 'g-1' }]);
    await waitFor(() => expect(result.current.size).toBe(1));

    await act(async () => {
      await qc.invalidateQueries({ queryKey: queryKeys.maps.detail('map-1') });
    });
    expect(mockCheckMapVisibility).toHaveBeenCalledTimes(2);

    rerender({ visibility: 'internal', groups: [{ id: 'g-1' }] });
    expect(result.current.size).toBe(0);
  });

  it("never asks for someone who doesn't receive the map's groups", () => {
    const { result } = renderGaps('restricted', null);

    expect(result.current.size).toBe(0);
    expect(mockCheckMapVisibility).not.toHaveBeenCalled();
  });
});
