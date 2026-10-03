import { act, renderHook, waitFor } from '@/test/test-utils';
import { vi } from 'vitest';
import { useQueryClient } from '@tanstack/react-query';

vi.mock('@/api/search', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/search')>();
  return { ...actual, searchDatasets: vi.fn(), fetchCatalogSummary: vi.fn(), fetchFacets: vi.fn() };
});

vi.mock('@/api/maps', () => ({ listMaps: vi.fn() }));

import { searchDatasets, fetchCatalogSummary, fetchFacets } from '@/api/search';
import { listMaps } from '@/api/maps';
import { useSearchResults, useMapSearchResults, useFacets, useCatalogSummary, useAllTypesTotal } from '@/components/search/hooks/use-search';
import { useSearchStore } from '@/stores/search-store';

const mockSearchDatasets = vi.mocked(searchDatasets);
const mockFetchFacets = vi.mocked(fetchFacets);
const mockFetchCatalogSummary = vi.mocked(fetchCatalogSummary);
const mockListMaps = vi.mocked(listMaps);

const initialState = useSearchStore.getState();

describe('useSearchResults', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useSearchStore.setState(initialState, true);
  });

  it('fetches search results based on store params', async () => {
    const mockData = {
      type: 'FeatureCollection',
      features: [{ id: 'ds-1', properties: { title: 'Test' } }],
      numberMatched: 1,
    };
    mockSearchDatasets.mockResolvedValueOnce(mockData as never);

    const { result } = renderHook(() => useSearchResults());

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(mockData);
  });
});

describe('useMapSearchResults', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useSearchStore.setState(initialState, true);
  });

  it('uses only the text query, not catalog filters', async () => {
    useSearchStore.getState().setQuery('Matterhorn');
    useSearchStore.getState().setFilter('record_type', 'vector');
    mockListMaps.mockResolvedValueOnce({ maps: [], total: 0 } as never);

    const { result } = renderHook(() => useMapSearchResults());

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockListMaps).toHaveBeenCalledWith({ search: 'Matterhorn', limit: 6 });
  });
});

describe('useFacets', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useSearchStore.setState(initialState, true);
  });

  it('fetches facets', async () => {
    const mockData = { geometry_type: { Point: 5, Polygon: 3 } };
    mockFetchFacets.mockResolvedValueOnce(mockData as never);

    const { result } = renderHook(() => useFacets());

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(mockData);
  });
});

describe('useCatalogSummary', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('fetches catalog summary', async () => {
    const mockData = { summaries: { total_datasets: 10, total_features: 1000 } };
    mockFetchCatalogSummary.mockResolvedValueOnce(mockData as never);

    const { result } = renderHook(() => useCatalogSummary());

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(mockData.summaries);
  });
});

describe('useSearchResults – error and empty states', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useSearchStore.setState(initialState, true);
  });

  it('returns error state on API failure', async () => {
    mockSearchDatasets.mockRejectedValueOnce(new Error('Search failed'));

    const { result } = renderHook(() => useSearchResults());

    await waitFor(() => expect(result.current.isError).toBe(true));
  });

  it('handles empty search results', async () => {
    const emptyData = { type: 'FeatureCollection', features: [], numberMatched: 0 };
    mockSearchDatasets.mockResolvedValueOnce(emptyData as never);

    const { result } = renderHook(() => useSearchResults());

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.features).toEqual([]);
    expect(result.current.data?.numberMatched).toBe(0);
  });
});

describe('useAllTypesTotal', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useSearchStore.setState(initialState, true);
    mockSearchDatasets.mockImplementation((async (params: Record<string, string>) => ({
      numberMatched: params.record_type ? 3 : 12,
      features: [],
    })) as never);
  });

  function useAll() {
    const results = useSearchResults();
    const total = results.data ? results.data.numberMatched : undefined;
    return {
      results,
      all: useAllTypesTotal(total, results.isPlaceholderData),
    };
  }

  it('keeps All at the cached untyped total across All, a type, and back without extra requests', async () => {
    const { result } = renderHook(useAll);
    await waitFor(() => expect(result.current.all).toBe(12));

    act(() => useSearchStore.getState().setFilter('record_type', 'vector_dataset'));
    await waitFor(() => expect(result.current.results.data?.numberMatched).toBe(3));
    expect(result.current.all).toBe(12);

    act(() => useSearchStore.getState().setFilter('record_type', ''));
    expect(result.current.all).toBe(12);
    await waitFor(() => expect(result.current.results.isPlaceholderData).toBe(false));
    expect(result.current.all).toBe(12);

    expect(mockSearchDatasets).toHaveBeenCalledTimes(2);
    for (const [params] of mockSearchDatasets.mock.calls) {
      expect(params).not.toHaveProperty('limit', '1');
    }
  });

  it('lets the shared results query refetch after an invalidation', async () => {
    const { result } = renderHook(() => {
      const client = useQueryClient();
      return { ...useAll(), client };
    });
    await waitFor(() => expect(result.current.all).toBe(12));
    expect(mockSearchDatasets).toHaveBeenCalledTimes(1);

    await act(() => result.current.client.invalidateQueries({ queryKey: ['search'] }));

    await waitFor(() => expect(mockSearchDatasets).toHaveBeenCalledTimes(2));
    expect(result.current.results.isError).toBe(false);
    expect(result.current.all).toBe(12);
  });

  it('does not carry the previous search total to an uncached untyped key', async () => {
    const { result } = renderHook(useAll);
    await waitFor(() => expect(result.current.all).toBe(12));

    act(() => useSearchStore.getState().setFilter('record_type', 'vector_dataset'));
    await waitFor(() => expect(result.current.results.data?.numberMatched).toBe(3));
    act(() => useSearchStore.getState().setFilter('q', 'other'));

    expect(result.current.all).toBeUndefined();
  });

  it('drops an invalidated untyped total that nothing will refetch', async () => {
    const { result } = renderHook(() => {
      const client = useQueryClient();
      return { ...useAll(), client };
    });
    await waitFor(() => expect(result.current.all).toBe(12));
    act(() => useSearchStore.getState().setFilter('record_type', 'vector_dataset'));
    await waitFor(() => expect(result.current.results.data?.numberMatched).toBe(3));
    expect(result.current.all).toBe(12);

    mockSearchDatasets.mockImplementation((async () => ({ numberMatched: 20, features: [] })) as never);
    await act(() => result.current.client.invalidateQueries({ queryKey: ['search'] }));
    await waitFor(() => expect(result.current.results.data?.numberMatched).toBe(20));

    expect(result.current.all).toBeUndefined();
  });

  it('is undefined when nothing is cached for the untyped params', async () => {
    useSearchStore.getState().setFilter('record_type', 'vector_dataset');
    const { result } = renderHook(useAll);
    await waitFor(() => expect(result.current.results.data?.numberMatched).toBe(3));

    expect(result.current.all).toBeUndefined();
  });

  it('treats a zero cached untyped total as authoritative', async () => {
    mockSearchDatasets.mockImplementation((async (params: Record<string, string>) => ({
      numberMatched: params.record_type ? 3 : 0,
      features: [],
    })) as never);
    const { result } = renderHook(useAll);
    await waitFor(() => expect(result.current.all).toBe(0));

    act(() => useSearchStore.getState().setFilter('record_type', 'vector_dataset'));
    await waitFor(() => expect(result.current.results.data?.numberMatched).toBe(3));
    expect(result.current.all).toBe(0);
  });
});
