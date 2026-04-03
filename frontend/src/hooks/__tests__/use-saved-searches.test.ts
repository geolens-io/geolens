import { renderHook, waitFor } from '@/test/test-utils';
import { vi } from 'vitest';

vi.mock('@/api/saved-searches', () => ({
  fetchSavedSearches: vi.fn(),
  createSavedSearch: vi.fn(),
  deleteSavedSearch: vi.fn(),
}));

import { fetchSavedSearches, createSavedSearch, deleteSavedSearch } from '@/api/saved-searches';
import { useSavedSearches, useSaveSearch, useDeleteSavedSearch } from '@/hooks/use-saved-searches';

const mockFetchSavedSearches = vi.mocked(fetchSavedSearches);
const mockCreateSavedSearch = vi.mocked(createSavedSearch);
const mockDeleteSavedSearch = vi.mocked(deleteSavedSearch);

describe('useSavedSearches', () => {
  beforeEach(() => vi.clearAllMocks());

  it('fetches saved searches', async () => {
    const data = { searches: [{ id: 's1', name: 'My Search', params: { q: 'test' } }], total: 1 };
    mockFetchSavedSearches.mockResolvedValueOnce(data as never);

    const { result } = renderHook(() => useSavedSearches());

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(data);
  });

  it('returns error state on failure', async () => {
    mockFetchSavedSearches.mockRejectedValueOnce(new Error('Server error'));

    const { result } = renderHook(() => useSavedSearches());

    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

describe('useSaveSearch', () => {
  beforeEach(() => vi.clearAllMocks());

  it('calls createSavedSearch on mutate', async () => {
    const created = { id: 's2', name: 'New Search', params: { q: 'geo' }, created_at: '', updated_at: '' };
    mockCreateSavedSearch.mockResolvedValueOnce(created as never);

    const { result } = renderHook(() => useSaveSearch());

    await result.current.mutateAsync({ name: 'New Search', params: { q: 'geo' } });

    expect(mockCreateSavedSearch).toHaveBeenCalledWith({ name: 'New Search', params: { q: 'geo' } }, expect.anything());
  });
});

describe('useDeleteSavedSearch', () => {
  beforeEach(() => vi.clearAllMocks());

  it('calls deleteSavedSearch on mutate', async () => {
    mockDeleteSavedSearch.mockResolvedValueOnce(undefined as never);

    const { result } = renderHook(() => useDeleteSavedSearch());

    await result.current.mutateAsync('s1');

    expect(mockDeleteSavedSearch).toHaveBeenCalledWith('s1', expect.anything());
  });

  it('returns error state on failure', async () => {
    mockDeleteSavedSearch.mockRejectedValueOnce(new Error('Not found'));

    const { result } = renderHook(() => useDeleteSavedSearch());

    await expect(result.current.mutateAsync('bad-id')).rejects.toThrow('Not found');
  });
});
