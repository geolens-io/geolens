import { act, renderHook, waitFor } from '@/test/test-utils';
import { vi } from 'vitest';

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
  });

  it('keeps All at the untyped total across All, a type, and back', async () => {
    mockSearchDatasets.mockResolvedValue({ numberMatched: 12, features: [] } as never);

    useSearchStore.getState().setFilter('record_type', 'vector_dataset');
    const { result, rerender } = renderHook(({ total }) => useAllTypesTotal(total), {
      initialProps: { total: 10 as number | undefined },
    });

    await waitFor(() => expect(result.current).toBe(12));
    const [params] = mockSearchDatasets.mock.calls[0];
    expect(params).toMatchObject({ limit: '1' });
    expect(params).not.toHaveProperty('record_type');

    act(() => useSearchStore.getState().setFilter('record_type', ''));
    rerender({ total: 12 });
    expect(result.current).toBe(12);
  });

  it('treats a zero untyped total as authoritative with and without a type', async () => {
    mockSearchDatasets.mockResolvedValue({ numberMatched: 0, features: [] } as never);

    useSearchStore.getState().setFilter('record_type', 'vector_dataset');
    const { result, rerender } = renderHook(({ total }) => useAllTypesTotal(total), {
      initialProps: { total: 0 as number | undefined },
    });

    await waitFor(() => expect(result.current).toBe(0));

    act(() => useSearchStore.getState().setFilter('record_type', ''));
    rerender({ total: 0 });
    expect(result.current).toBe(0);
  });

  it('makes no request and returns the result total when no type is selected', () => {
    const { result } = renderHook(() => useAllTypesTotal(12));

    expect(result.current).toBe(12);
    expect(mockSearchDatasets).not.toHaveBeenCalled();
  });
});
