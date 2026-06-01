// BLDR-02 regression pin: applyTerrainConfig honors the terrain DEM layer's
// visibility toggle. When the DEM layer is hidden (visible===false),
// map.setTerrain(null) must be called; when it is shown, terrain re-attaches
// with { source: TERRAIN_SOURCE_ID }.
//
// Uses the vi.hoisted fakeMap + @vis.gl/react-maplibre mock recipe from
// BuilderMap.a11y.test.tsx. map-sync helpers are selectively mocked so
// ensureRasterDemTerrainSource is a no-op (source is pre-registered on the
// fake map) and applyTerrainConfig runs against the real fakeMap.
//
// useTileTokens is mocked to return a raster token for the DEM dataset so
// the tokenMap has an entry and the attach path can run.

import type { ReactNode } from 'react';
import { act, render } from '@/test/test-utils';
import { TERRAIN_SOURCE_ID } from '../map-sync';
import type { MapLayerResponse, MapTerrainConfig } from '@/types/api';
import type { RasterTileToken } from '@/api/tiles';
import { BuilderMap } from '../BuilderMap';

vi.mock('@/hooks/use-settings', () => ({
  useBasemaps: () => ({
    data: [
      {
        id: 'openfreemap-positron',
        label: 'Light',
        url: 'https://tiles.example.com/styles/basic',
        enabled: true,
      },
    ],
  }),
  useMapDefaults: () => ({ data: { center_lng: 0, center_lat: 0, zoom: 2 } }),
  useTileConfig: () => ({ data: null }),
  useEnabledPlugins: () => ({ data: [], isLoading: false }),
}));

// tileTokenState is hoisted so tests can toggle the token per-test
const tileTokenState = vi.hoisted(() => ({
  tokens: [] as Array<{ data: RasterTileToken | undefined; isLoading: boolean; isError: boolean }>,
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

// Partially mock map-sync: keep real applyTerrainConfig dependencies but stub
// helpers that call getStyle (not modeled on the fake map).
// ensureRasterDemTerrainSource is mocked as a no-op — source is pre-registered
// on fakeMap.getSource so the "source absent" early-return in applyTerrainConfig
// is bypassed without a real addSource call.
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

// ---------------------------------------------------------------------------
// Fake map + @vis.gl/react-maplibre mock (canonical recipe from a11y.test.tsx)
// ---------------------------------------------------------------------------

type FakeMap = {
  on: ReturnType<typeof vi.fn>;
  off: ReturnType<typeof vi.fn>;
  once: ReturnType<typeof vi.fn>;
  setTransformRequest: ReturnType<typeof vi.fn>;
  isStyleLoaded: ReturnType<typeof vi.fn>;
  getCanvas: ReturnType<typeof vi.fn>;
  setTerrain: ReturnType<typeof vi.fn>;
  triggerRepaint: ReturnType<typeof vi.fn>;
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
    triggerRepaint: vi.fn(),
    // Pre-register the TERRAIN_SOURCE_ID source so ensureRasterDemTerrainSource's
    // internal source-exists check passes (belt-and-suspenders; the mock is a no-op).
    getSource: vi.fn((id: string) => (id === TERRAIN_SOURCE_ID ? { type: 'raster-dem' } : null)),
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
      fakeMap.triggerRepaint.mockClear();
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

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const DATASET_ID = 'dem-dataset-uuid-bldr02';

const rasterToken: RasterTileToken = {
  kind: 'raster',
  tile_url: '/raster-tiles/dem/tiles/{z}/{x}/{y}.png',
  bounds: [-113, 36, -111.5, 37],
  minzoom: 2,
  maxzoom: 14,
  tile_size: 512,
  format: 'png',
};

function makeDemLayer(
  visible: boolean,
  renderMode: 'terrain' | 'hillshade' = 'terrain',
): MapLayerResponse {
  return {
    id: 'layer-dem-bldr02',
    dataset_id: DATASET_ID,
    dataset_name: 'DEM',
    dataset_geometry_type: null,
    dataset_table_name: 'dem_table',
    dataset_extent_bbox: [-113, 36, -111.5, 37],
    dataset_column_info: null,
    dataset_feature_count: null,
    dataset_sample_values: null,
    display_name: null,
    sort_order: 0,
    visible,
    opacity: 1,
    paint: {},
    layout: {},
    filter: null,
    label_config: null,
    popup_config: null,
    style_config: { render_mode: renderMode } as MapLayerResponse['style_config'],
    layer_type: null,
    dataset_record_type: 'raster_dataset',
    show_in_legend: true,
    is_dem: true,
    dem_vertical_units: null,
  };
}

const terrainConfig: MapTerrainConfig = {
  enabled: true,
  source_dataset_id: DATASET_ID,
  exaggeration: 1,
};

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('BuilderMap BLDR-02: terrain attach/detach on DEM layer visibility toggle', () => {
  beforeEach(() => {
    mapState.reset();
    // Default: provide the raster token so tokenMap has an entry
    tileTokenState.tokens = [{ data: rasterToken, isLoading: false, isError: false }];
  });

  it('Test A: setTerrain called with { source: TERRAIN_SOURCE_ID } when terrain DEM layer is visible', async () => {
    const demLayer = makeDemLayer(true);

    await act(async () => {
      render(
        <BuilderMap
          layers={[demLayer]}
          basemapStyle="openfreemap-positron"
          terrainConfig={terrainConfig}
        />,
      );
    });

    // applyTerrainConfig runs on mount (isStyleLoaded returns true immediately).
    // With demLayer.visible===true and a valid raster token, the effective
    // terrain is enabled → setTerrain should be called with the source object.
    const setTerrainCalls = mapState.fakeMap.setTerrain.mock.calls;
    expect(setTerrainCalls.length).toBeGreaterThan(0);
    const lastCall = setTerrainCalls[setTerrainCalls.length - 1];
    // The last call should be setTerrain({ source: TERRAIN_SOURCE_ID, exaggeration: ... })
    expect(lastCall[0]).toMatchObject({ source: TERRAIN_SOURCE_ID });
  });

  it('Test B: setTerrain(null) called when terrain DEM layer is hidden (visible===false)', async () => {
    const demLayerHidden = makeDemLayer(false);

    await act(async () => {
      render(
        <BuilderMap
          layers={[demLayerHidden]}
          basemapStyle="openfreemap-positron"
          terrainConfig={terrainConfig}
        />,
      );
    });

    // With demLayer.visible===false, effectiveTerrainEnabled is false even
    // though terrainConfig.enabled===true. applyTerrainConfig must call
    // setTerrain(null) — terrain detached when the DEM layer is hidden.
    const setTerrainCalls = mapState.fakeMap.setTerrain.mock.calls;
    expect(setTerrainCalls.length).toBeGreaterThan(0);
    const lastCall = setTerrainCalls[setTerrainCalls.length - 1];
    expect(lastCall[0]).toBeNull();
  });

  // FIX-3-RESOLVER (D-06): the builder terrain DEM lookup must resolve by
  // terrain_config.source_dataset_id + isTerrainCapableDemLayer ONLY — it must
  // NOT require style_config.render_mode === 'terrain'. This proves a DEM layer
  // in HILLSHADE mode still drives the 3D mesh (mesh + visible hillshade on one
  // DEM), matching the proven viewer resolver in use-viewer-terrain.ts. Before
  // the resolver-alignment fix this test fails (setTerrain(null) instead of the
  // source object) because the render_mode clause dropped the hillshade layer.
  it('Test D (FIX-3): setTerrain called with { source } when the terrain DEM layer is in HILLSHADE mode', async () => {
    const hillshadeDemLayer = makeDemLayer(true, 'hillshade');

    await act(async () => {
      render(
        <BuilderMap
          layers={[hillshadeDemLayer]}
          basemapStyle="openfreemap-positron"
          terrainConfig={terrainConfig}
        />,
      );
    });

    const setTerrainCalls = mapState.fakeMap.setTerrain.mock.calls;
    expect(setTerrainCalls.length).toBeGreaterThan(0);
    const lastCall = setTerrainCalls[setTerrainCalls.length - 1];
    expect(lastCall[0]).toMatchObject({ source: TERRAIN_SOURCE_ID });
  });

  it('Test C: setTerrain(null) called when terrainConfig.enabled is false (control — no demLayer visibility involvement)', async () => {
    const demLayer = makeDemLayer(true);
    const disabledTerrainConfig: MapTerrainConfig = {
      ...terrainConfig,
      enabled: false,
    };

    await act(async () => {
      render(
        <BuilderMap
          layers={[demLayer]}
          basemapStyle="openfreemap-positron"
          terrainConfig={disabledTerrainConfig}
        />,
      );
    });

    const setTerrainCalls = mapState.fakeMap.setTerrain.mock.calls;
    expect(setTerrainCalls.length).toBeGreaterThan(0);
    const lastCall = setTerrainCalls[setTerrainCalls.length - 1];
    expect(lastCall[0]).toBeNull();
  });
});
