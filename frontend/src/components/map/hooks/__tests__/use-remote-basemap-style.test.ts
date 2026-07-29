// chore(#835): shared remote-basemap-style fetch path for BuilderMap and
// ViewerMap. Pins the parameterized divergence: the viewer falls back to the
// raw style URL on fetch failure; the builder keeps the placeholder and
// surfaces a notice via onFetchError (Phase 1051 WR-06).
import { renderHook, waitFor } from '@testing-library/react';
import type { RefObject } from 'react';
import type { Map as MaplibreMap, StyleSpecification } from 'maplibre-gl';
import { useRemoteBasemapStyle } from '../use-remote-basemap-style';

vi.mock('@/components/builder/map-sync', () => ({
  clearTerrainForStyleSwap: vi.fn(),
}));

import { clearTerrainForStyleSwap } from '@/components/builder/map-sync';

const REMOTE_URL = 'https://tiles.openfreemap.org/styles/positron';
const REMOTE_STYLE: StyleSpecification = {
  version: 8,
  sources: {},
  layers: [{ id: 'water', type: 'background' }],
};

const mapRef = { current: null } as RefObject<MaplibreMap | null>;

function isPlaceholder(style: string | StyleSpecification): boolean {
  return typeof style !== 'string'
    && style.layers.length === 1
    && style.layers[0].id === 'background';
}

describe('useRemoteBasemapStyle', () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock);
    fetchMock.mockReset();
    mapRef.current = null;
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it('passes inline styles through without fetching', () => {
    const inline: StyleSpecification = { version: 8, sources: {}, layers: [] };
    const { result } = renderHook(() => useRemoteBasemapStyle({
      styleValue: inline,
      mapRef,
      logLabel: 'Test',
    }));
    expect(result.current).toBe(inline);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('passes non-/styles/ URLs through without fetching (carto fallback shape)', () => {
    const url = 'https://basemaps.cartocdn.com/gl/positron-gl-style/style.json';
    const { result } = renderHook(() => useRemoteBasemapStyle({
      styleValue: url,
      mapRef,
      logLabel: 'Test',
    }));
    expect(result.current).toBe(url);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('shows the placeholder, then the sanitized remote style, and fires callbacks', async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve(REMOTE_STYLE),
    });
    const onFetchStart = vi.fn();
    const onFetchSuccess = vi.fn();
    const { result } = renderHook(() => useRemoteBasemapStyle({
      styleValue: REMOTE_URL,
      mapRef,
      logLabel: 'Test',
      onFetchStart,
      onFetchSuccess,
    }));

    expect(isPlaceholder(result.current)).toBe(true);
    expect(onFetchStart).toHaveBeenCalledTimes(1);

    await waitFor(() => {
      expect(onFetchSuccess).toHaveBeenCalledTimes(1);
    });
    expect(typeof result.current).not.toBe('string');
    expect((result.current as StyleSpecification).layers.some((l) => l.id === 'water')).toBe(true);
  });

  it('falls back to the raw URL on failure when fallbackToRawUrlOnError is set (viewer behavior)', async () => {
    fetchMock.mockResolvedValueOnce({ ok: false, status: 502 });
    const { result } = renderHook(() => useRemoteBasemapStyle({
      styleValue: REMOTE_URL,
      mapRef,
      logLabel: 'Test',
      fallbackToRawUrlOnError: true,
    }));

    await waitFor(() => {
      expect(result.current).toBe(REMOTE_URL);
    });
  });

  it('keeps the placeholder and calls onFetchError on failure by default (builder behavior)', async () => {
    fetchMock.mockResolvedValueOnce({ ok: false, status: 502 });
    const onFetchError = vi.fn();
    const { result } = renderHook(() => useRemoteBasemapStyle({
      styleValue: REMOTE_URL,
      mapRef,
      logLabel: 'Test',
      onFetchError,
    }));

    await waitFor(() => {
      expect(onFetchError).toHaveBeenCalledTimes(1);
    });
    expect(isPlaceholder(result.current)).toBe(true);
  });

  it('clears terrain on the current map before a style swap', () => {
    const fakeMap = {} as MaplibreMap;
    mapRef.current = fakeMap;
    const inline: StyleSpecification = { version: 8, sources: {}, layers: [] };
    renderHook(() => useRemoteBasemapStyle({
      styleValue: inline,
      mapRef,
      logLabel: 'Test',
    }));
    expect(clearTerrainForStyleSwap).toHaveBeenCalledWith(fakeMap);
  });
});
