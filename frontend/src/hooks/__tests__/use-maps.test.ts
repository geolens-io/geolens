import { renderHook, waitFor } from '@/test/test-utils';
import { vi } from 'vitest';

vi.mock('@/api/maps', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/maps')>();
  return { ...actual, listMaps: vi.fn(), getMap: vi.fn() };
});

import { listMaps, getMap } from '@/api/maps';
import { useMaps, useMap } from '@/hooks/use-maps';

const mockListMaps = vi.mocked(listMaps);
const mockGetMap = vi.mocked(getMap);

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
