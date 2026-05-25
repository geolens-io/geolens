import type { ReactNode } from 'react';
import { act, render, screen, waitFor } from '@/test/test-utils';
import { toast } from 'sonner';
import { BuilderMap } from '../BuilderMap';
import { ensureRasterDemTerrainSource, TERRAIN_SOURCE_ID } from '../map-sync';
import type { MapLayerResponse, MapTerrainConfig } from '@/types/api';

vi.mock('@/hooks/use-settings', () => ({
  useBasemaps: () => ({
    data: [
      {
        id: 'openfreemap-positron',
        label: 'Light',
        url: 'https://tiles.example.com/styles/basic',
        enabled: true,
      },
      {
        id: 'openfreemap-bright',
        label: 'Bright',
        url: 'https://tiles.example.com/styles/bright',
        enabled: true,
      },
    ],
  }),
  useMapDefaults: () => ({ data: { center_lng: 0, center_lat: 0, zoom: 2 } }),
  useTileConfig: () => ({ data: null }),
  useEnabledWidgets: () => ({ data: [], isLoading: false }),
}));

const tileTokenState = vi.hoisted(() => ({
  tokens: [] as unknown[],
}));

vi.mock('@/hooks/use-tile-token', () => ({
  useTileTokens: () => tileTokenState.tokens,
}));

vi.mock('@/hooks/use-webgl-recovery', () => ({
  useWebGLRecovery: () => ({ contextLost: false, reload: vi.fn() }),
}));

vi.mock('@/components/map/MapCoordReadout', () => ({
  MapCoordReadout: () => null,
}));

vi.mock('sonner', () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
    warning: vi.fn(),
  },
}));

// No-op the sync helpers — these touch `map.getStyle()` and other internals we
// don't model on the fake map. We're only exercising the error-handler latch.
vi.mock('@/components/builder/map-sync', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/components/builder/map-sync')>();
  return {
    ...actual,
    syncLayersToMap: vi.fn(),
    applyBasemapConfigToMap: vi.fn(),
    reorderBasemapLabels: vi.fn(),
    reorderDataLayers: vi.fn(),
    ensureRasterDemTerrainSource: vi.fn(),
  };
});

// SF-08: Shared map state mock that exposes a manual `emit` so tests can trigger
// MapLibre `map.on('error')` after onLoad fires. Mirrors the ViewerMap
// basemap-config test pattern (`ViewerMap.basemap-config.test.tsx:25-93`).
type FakeMap = {
  on: ReturnType<typeof vi.fn>;
  off: ReturnType<typeof vi.fn>;
  once: ReturnType<typeof vi.fn>;
  setTransformRequest: ReturnType<typeof vi.fn>;
  isStyleLoaded: ReturnType<typeof vi.fn>;
  getCanvas: ReturnType<typeof vi.fn>;
  setTerrain: ReturnType<typeof vi.fn>;
  getSource: ReturnType<typeof vi.fn>;
  getLayer: ReturnType<typeof vi.fn>;
  getStyle: ReturnType<typeof vi.fn>;
  fitBounds: ReturnType<typeof vi.fn>;
  getZoom: ReturnType<typeof vi.fn>;
  setZoom: ReturnType<typeof vi.fn>;
  emit: (event: string, payload?: unknown) => void;
};

const mapState = vi.hoisted(() => {
  const handlers = new Map<string, Set<(payload?: unknown) => void>>();
  const fakeMap: FakeMap = {
    on: vi.fn((event: string, handler: (payload?: unknown) => void) => {
      const existing = handlers.get(event) ?? new Set();
      existing.add(handler);
      handlers.set(event, existing);
    }),
    off: vi.fn((event: string, handler: (payload?: unknown) => void) => {
      handlers.get(event)?.delete(handler);
    }),
    once: vi.fn((event: string, handler: (payload?: unknown) => void) => {
      const wrapped = (payload?: unknown) => {
        handler(payload);
        handlers.get(event)?.delete(wrapped);
      };
      const existing = handlers.get(event) ?? new Set();
      existing.add(wrapped);
      handlers.set(event, existing);
    }),
    setTransformRequest: vi.fn(),
    isStyleLoaded: vi.fn(() => true),
    getCanvas: vi.fn(() => ({ style: { cursor: '' }, addEventListener: vi.fn(), removeEventListener: vi.fn() })),
    setTerrain: vi.fn(),
    getSource: vi.fn(() => null),
    getLayer: vi.fn(() => null),
    getStyle: vi.fn(() => ({ layers: [] })),
    fitBounds: vi.fn(),
    getZoom: vi.fn(() => 2),
    setZoom: vi.fn(),
    emit: (event: string, payload?: unknown) => {
      for (const handler of Array.from(handlers.get(event) ?? [])) {
        handler(payload);
      }
    },
  };

  return {
    fakeMap,
    reset: () => {
      handlers.clear();
      fakeMap.on.mockClear();
      fakeMap.off.mockClear();
      fakeMap.once.mockClear();
      fakeMap.setTransformRequest.mockClear();
      fakeMap.isStyleLoaded.mockClear();
      fakeMap.getCanvas.mockClear();
      fakeMap.setTerrain.mockClear();
      fakeMap.getSource.mockClear();
      fakeMap.getLayer.mockClear();
      fakeMap.getStyle.mockClear();
      fakeMap.fitBounds.mockClear();
      fakeMap.getZoom.mockClear();
      fakeMap.setZoom.mockClear();
    },
  };
});

vi.mock('@vis.gl/react-maplibre', async () => {
  const React = await import('react');
  return {
    Map: ({ children, onLoad }: { children?: ReactNode; onLoad?: (event: { target: FakeMap }) => void }) => {
      React.useEffect(() => {
        onLoad?.({ target: mapState.fakeMap });
      }, [onLoad]);
      return <div data-testid="mapgl">{children}</div>;
    },
    NavigationControl: () => null,
    ScaleControl: () => null,
  };
});

describe('BuilderMap accessibility recovery copy', () => {
  const originalFetch = globalThis.fetch;

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it('surfaces a non-blocking basemap recovery notice when the basemap style fails', async () => {
    globalThis.fetch = vi.fn(() => Promise.reject(new Error('network unavailable'))) as typeof fetch;

    render(
      <BuilderMap
        layers={[]}
        basemapStyle="openfreemap-positron"
      />,
    );

    await waitFor(() => {
      expect(screen.getByRole('status')).toHaveTextContent('Basemap connection issue');
    });
    expect(screen.getByRole('status')).toHaveTextContent('Your data layers are still editable');
  });
});

describe('BuilderMap basemap connection toast (SF-08)', () => {
  const originalFetch = globalThis.fetch;
  const toastErrorSpy = vi.mocked(toast.error);

  beforeEach(() => {
    mapState.reset();
    tileTokenState.tokens = [];
    toastErrorSpy.mockClear();
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it('suppresses transient tile error toast when basemap loaded successfully', async () => {
    // Resolve the style fetch so the latch is set.
    const validStyle = {
      version: 8,
      sources: {},
      layers: [],
    };
    globalThis.fetch = vi.fn(() =>
      Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve(validStyle),
      } as Response),
    ) as typeof fetch;

    render(
      <BuilderMap
        layers={[]}
        basemapStyle="openfreemap-positron"
      />,
    );

    // Wait for onLoad to register the error handler.
    await waitFor(() => {
      expect(mapState.fakeMap.on).toHaveBeenCalledWith('error', expect.any(Function));
    });

    // Wait for the style fetch effect to resolve (latch set).
    await waitFor(() => {
      // setBasemapNotice(null) was called from the success branch — to confirm
      // the latch ran we wait for the fetch promise to flush.
      expect(globalThis.fetch).toHaveBeenCalled();
    });
    // Flush any pending microtasks so the latch assignment lands.
    await new Promise((resolve) => setTimeout(resolve, 0));

    // Now emit a transient 5xx error — should be suppressed.
    mapState.fakeMap.emit('error', { error: { status: 503, message: 'Service Unavailable' } });

    // Banner should NOT appear; toast.error should NOT be called for the map error.
    // (toast.error may still be called for other reasons — assert by id.)
    expect(screen.queryByRole('status')).toBeNull();
    const mapErrorCalls = toastErrorSpy.mock.calls.filter(
      ([, options]) => (options as { id?: string } | undefined)?.id === 'builder-map-error',
    );
    expect(mapErrorCalls).toHaveLength(0);
  });

  it('still surfaces tile error toast when basemap never loaded', async () => {
    // Style fetch never resolves — latch stays null.
    globalThis.fetch = vi.fn(() => new Promise(() => {
      // Pending forever
    })) as typeof fetch;

    render(
      <BuilderMap
        layers={[]}
        basemapStyle="openfreemap-positron"
      />,
    );

    await waitFor(() => {
      expect(mapState.fakeMap.on).toHaveBeenCalledWith('error', expect.any(Function));
    });

    // Emit a 5xx error before the style has loaded — banner SHOULD appear.
    mapState.fakeMap.emit('error', { error: { status: 503, message: 'Service Unavailable' } });

    await waitFor(() => {
      expect(screen.getByRole('status')).toHaveTextContent('Basemap connection issue');
    });
    const mapErrorCalls = toastErrorSpy.mock.calls.filter(
      ([, options]) => (options as { id?: string } | undefined)?.id === 'builder-map-error',
    );
    expect(mapErrorCalls.length).toBeGreaterThan(0);
  });

  // WR-02 (Phase 1050-rev): the latch must NOT permanently suppress 5xx
  // errors. After ~3s post-load, a 5xx is no longer "transient save-time
  // basemap reload" — it's an ongoing tile-server outage, and the user
  // must see a banner + toast so they know the system is degraded.
  it('still surfaces tile error toast when 5xx arrives well after latch arming (WR-02)', async () => {
    vi.useFakeTimers();
    try {
      const validStyle = { version: 8, sources: {}, layers: [] };
      globalThis.fetch = vi.fn(() =>
        Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve(validStyle),
        } as Response),
      ) as typeof fetch;

      render(
        <BuilderMap
          layers={[]}
          basemapStyle="openfreemap-positron"
        />,
      );

      // Walk the timers / microtasks far enough for the style fetch to
      // resolve and arm the latch (basemapLoadedAtRef = Date.now()).
      await vi.advanceTimersByTimeAsync(0);
      await vi.advanceTimersByTimeAsync(0);

      // Confirm error handler registered.
      expect(mapState.fakeMap.on).toHaveBeenCalledWith('error', expect.any(Function));

      // Jump well past the 3000 ms suppression window — any 5xx now must
      // be a real outage signal, not a save-time transient.
      vi.advanceTimersByTime(10000);

      mapState.fakeMap.emit('error', { error: { status: 503, message: 'Service Unavailable' } });

      // Banner SHOULD appear; toast.error SHOULD be called with the
      // builder-map-error id (real outage signal must not be silenced).
      // Pump the React state update so the banner renders.
      vi.useRealTimers();
      await waitFor(() => {
        expect(screen.getByRole('status')).toHaveTextContent('Basemap connection issue');
      });
      const mapErrorCalls = toastErrorSpy.mock.calls.filter(
        ([, options]) => (options as { id?: string } | undefined)?.id === 'builder-map-error',
      );
      expect(mapErrorCalls.length).toBeGreaterThan(0);
    } finally {
      vi.useRealTimers();
    }
  });

  it('resets latch on basemap change so new basemap first-load failure still surfaces', async () => {
    // First fetch resolves (latch set), second fetch rejects (latch should reset → null).
    let fetchCallCount = 0;
    const validStyle = { version: 8, sources: {}, layers: [] };
    globalThis.fetch = vi.fn(() => {
      fetchCallCount += 1;
      if (fetchCallCount === 1) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve(validStyle),
        } as Response);
      }
      return Promise.reject(new Error('network unavailable'));
    }) as typeof fetch;

    const { rerender } = render(
      <BuilderMap
        layers={[]}
        basemapStyle="openfreemap-positron"
      />,
    );

    await waitFor(() => {
      expect(mapState.fakeMap.on).toHaveBeenCalledWith('error', expect.any(Function));
    });
    // Flush microtasks so the first fetch's success branch runs and sets the latch.
    await new Promise((resolve) => setTimeout(resolve, 0));

    // Change basemap → effect re-runs, latch should reset to null before new fetch begins.
    rerender(
      <BuilderMap
        layers={[]}
        basemapStyle="openfreemap-bright"
      />,
    );

    // Wait for the second fetch to be initiated (latch should reset at the start of that effect).
    await waitFor(() => {
      expect(fetchCallCount).toBe(2);
    });

    // Now emit a 5xx error — since the new basemap never loaded successfully,
    // the latch is null and the banner SHOULD appear.
    mapState.fakeMap.emit('error', { error: { status: 503, message: 'Service Unavailable' } });

    await waitFor(() => {
      expect(screen.getByRole('status')).toHaveTextContent('Basemap connection issue');
    });
  });
});

describe('BuilderMap terrain activation', () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    mapState.reset();
    tileTokenState.tokens = [];
    vi.mocked(ensureRasterDemTerrainSource).mockClear();
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it('retries DEM terrain activation after the MapLibre style finishes loading', async () => {
    const terrainToken = {
      kind: 'raster',
      tile_url: '/raster-tiles/dem-dataset/tiles/{z}/{x}/{y}.png',
      bounds: [-74.05, 44.08, -73.85, 44.32],
      minzoom: 0,
      maxzoom: 17,
      tile_size: 256,
      format: 'png',
    };
    tileTokenState.tokens = [
      { data: terrainToken, isLoading: false, isError: false, error: null },
    ];
    let styleLoaded = false;
    mapState.fakeMap.isStyleLoaded.mockImplementation(() => styleLoaded);
    globalThis.fetch = vi.fn(() =>
      Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve({ version: 8, sources: {}, layers: [] }),
      } as Response),
    ) as typeof fetch;

    const demLayer = {
      id: 'dem-layer',
      dataset_id: 'dem-dataset',
      dataset_name: 'Demo DEM',
      dataset_geometry_type: null,
      dataset_table_name: 'raster_demo',
      dataset_extent_bbox: null,
      dataset_column_info: null,
      dataset_feature_count: null,
      dataset_sample_values: null,
      display_name: 'Demo DEM',
      sort_order: 0,
      visible: true,
      opacity: 1,
      paint: {},
      layout: {},
      layer_type: 'raster_geolens',
      dataset_record_type: 'raster_dataset',
      filter: null,
      label_config: null,
      popup_config: null,
      style_config: { mode: 'categorical', column: '', ramp: '', render_mode: 'terrain' } as unknown as MapLayerResponse['style_config'],
      show_in_legend: true,
      is_3d: null,
      is_dem: true,
      dem_vertical_units: null,
    } as MapLayerResponse;
    const terrainConfig: MapTerrainConfig = {
      enabled: true,
      source_dataset_id: 'dem-dataset',
      exaggeration: 2.4,
    };

    render(
      <BuilderMap
        layers={[demLayer]}
        basemapStyle="openfreemap-positron"
        terrainConfig={terrainConfig}
      />,
    );

    await waitFor(() => {
      expect(mapState.fakeMap.once).toHaveBeenCalledWith('idle', expect.any(Function));
    });
    expect(ensureRasterDemTerrainSource).not.toHaveBeenCalled();

    styleLoaded = true;
    act(() => {
      mapState.fakeMap.emit('idle');
    });

    expect(ensureRasterDemTerrainSource).toHaveBeenCalledWith(mapState.fakeMap, terrainToken.tile_url, {
      tileSize: 256,
      minzoom: 0,
      maxzoom: 17,
      bounds: [-74.05, 44.08, -73.85, 44.32],
    });
    expect(mapState.fakeMap.setTerrain).toHaveBeenCalledWith({
      source: TERRAIN_SOURCE_ID,
      exaggeration: 2.4,
    });
  });
});
