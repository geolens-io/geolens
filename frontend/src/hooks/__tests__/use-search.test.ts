import { renderHook, waitFor } from '@/test/test-utils';
import { vi } from 'vitest';

vi.mock('@/api/search', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/search')>();
  return { ...actual, searchDatasets: vi.fn(), fetchCatalogSummary: vi.fn(), fetchFacets: vi.fn() };
});

import { searchDatasets, fetchCatalogSummary, fetchFacets } from '@/api/search';
import { useSearchResults, useFacets, useCatalogSummary } from '@/hooks/use-search';
import { useSearchStore } from '@/stores/search-store';

const mockSearchDatasets = vi.mocked(searchDatasets);
const mockFetchFacets = vi.mocked(fetchFacets);
const mockFetchCatalogSummary = vi.mocked(fetchCatalogSummary);

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
