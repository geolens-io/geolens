import { renderHook, waitFor, act } from '@/test/test-utils';
import { vi } from 'vitest';

vi.mock('@/api/admin', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/admin')>();
  return { ...actual, getAIStatus: vi.fn() };
});

vi.mock('@/api/settings', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/settings')>();
  return { ...actual, getBasemaps: vi.fn(), getMapDefaults: vi.fn(), getTileConfig: vi.fn(), getConfigMode: vi.fn(), updateSettings: vi.fn() };
});

import { getBasemaps, getMapDefaults, getTileConfig, getConfigMode, updateSettings } from '@/api/settings';
import { getAIStatus } from '@/api/admin';
import { useAIStatus } from '@/hooks/use-admin';
import { useBasemaps, useMapDefaults, useTileConfig, useConfigMode, useUpdateSettings } from '@/hooks/use-settings';

const mockGetBasemaps = vi.mocked(getBasemaps);
const mockGetMapDefaults = vi.mocked(getMapDefaults);
const mockGetTileConfig = vi.mocked(getTileConfig);
const mockGetConfigMode = vi.mocked(getConfigMode);

describe('useBasemaps', () => {
  beforeEach(() => vi.clearAllMocks());

  it('fetches basemaps', async () => {
    const mockData = [{ id: 'osm', name: 'OpenStreetMap' }];
    mockGetBasemaps.mockResolvedValueOnce(mockData as never);

    const { result } = renderHook(() => useBasemaps());

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(mockData);
  });

  it('returns error state on failure', async () => {
    mockGetBasemaps.mockRejectedValueOnce(new Error('Network error'));

    const { result } = renderHook(() => useBasemaps());

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.data).toBeUndefined();
  });

  it('starts in loading state', () => {
    mockGetBasemaps.mockReturnValueOnce(new Promise(() => {}) as never);

    const { result } = renderHook(() => useBasemaps());

    expect(result.current.isLoading).toBe(true);
    expect(result.current.data).toBeUndefined();
  });
});

describe('useMapDefaults', () => {
  beforeEach(() => vi.clearAllMocks());

  it('fetches map defaults', async () => {
    const mockData = { center_lng: -74.0, center_lat: 40.7, zoom: 10 };
    mockGetMapDefaults.mockResolvedValueOnce(mockData as never);

    const { result } = renderHook(() => useMapDefaults());

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(mockData);
  });
});

describe('useTileConfig', () => {
  beforeEach(() => vi.clearAllMocks());

  it('fetches tile config', async () => {
    const mockData = {
      cdn_base_url: null,
      public_app_url: 'http://localhost:8080',
      public_api_url: 'http://localhost:8080/api',
      public_base_url: 'http://localhost:8080',
    };
    mockGetTileConfig.mockResolvedValueOnce(mockData as never);

    const { result } = renderHook(() => useTileConfig());

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(mockData);
  });
});

describe('useConfigMode', () => {
  beforeEach(() => vi.clearAllMocks());

  it('fetches config mode', async () => {
    const mockData = { env_only: false };
    mockGetConfigMode.mockResolvedValueOnce(mockData as never);

    const { result } = renderHook(() => useConfigMode());

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(mockData);
  });
});

describe('useUpdateSettings', () => {
  beforeEach(() => vi.clearAllMocks());

  it('refetches the AI status after a save', async () => {
    vi.mocked(getAIStatus).mockResolvedValue({ semantic_search_enabled: false } as never);
    vi.mocked(updateSettings).mockResolvedValue({} as never);

    const { result } = renderHook(() => ({
      status: useAIStatus({ enabled: true }),
      update: useUpdateSettings(),
    }));
    await waitFor(() => expect(result.current.status.isSuccess).toBe(true));
    expect(getAIStatus).toHaveBeenCalledTimes(1);

    await act(async () => {
      await result.current.update.mutateAsync({ semantic_search_enabled: true });
    });

    await waitFor(() => expect(getAIStatus).toHaveBeenCalledTimes(2));
  });
});
