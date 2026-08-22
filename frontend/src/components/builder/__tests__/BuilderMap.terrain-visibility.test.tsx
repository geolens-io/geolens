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
import { toast } from 'sonner';
import { act, render } from '@/test/test-utils';
import { TERRAIN_SOURCE_ID, applyBasemapConfigToMap, syncLayersToMap } from '../map-sync';
import { resetSmallDemWarning } from '../terrain-coverage';
import type { MapBasemapConfig, MapLayerResponse, MapTerrainConfig } from '@/types/api';
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
  useTileConfig: () => ({
    data: { cdn_base_url: null, mvt_source_layer_prefix: 'data' },
  }),
  useEnabledPlugins: () => ({ data: [], isLoading: false }),
}));

// tileTokenState is hoisted so tests can toggle the token per-test
const tileTokenState = vi.hoisted(() => ({
  tokens: [] as Array<{ data: RasterTileToken | undefined; isLoading: boolean; isError: boolean }>,
}));

vi.mock('@/hooks/use-tile-token', () => ({
  useInvalidateTileTokens: () => vi.fn(),
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
  setMissingStyleImageResolver: ReturnType<typeof vi.fn>;
  setProjection: ReturnType<typeof vi.fn>;
  triggerRepaint: ReturnType<typeof vi.fn>;
  getSource: ReturnType<typeof vi.fn>;
  getLayer: ReturnType<typeof vi.fn>;
  getStyle: ReturnType<typeof vi.fn>;
  getBounds: ReturnType<typeof vi.fn>;
  fitBounds: ReturnType<typeof vi.fn>;
  getZoom: ReturnType<typeof vi.fn>;
  setZoom: ReturnType<typeof vi.fn>;
  emit: (event: string, payload?: unknown) => void;
};

const mapState = vi.hoisted(() => {
  const handlers = new Map<string, Set<(payload?: unknown) => void>>();
  // fix(#1128): the viewport the small-DEM coverage guard measures against.
  // getBounds() used to be absent here, so the guard threw into its own
  // try/catch and no-oped. It defaults to the DEM fixture's own extent — full
  // coverage, no warning — so every test written while it was inert keeps the
  // behavior it was written against. The #1128 cases override it.
  const DEFAULT_VIEWPORT: [number, number, number, number] = [-113, 36, -111.5, 37];
  let viewport = DEFAULT_VIEWPORT;
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
    setMissingStyleImageResolver: vi.fn(),
    setProjection: vi.fn(),
    triggerRepaint: vi.fn(),
    // Pre-register the TERRAIN_SOURCE_ID source so ensureRasterDemTerrainSource's
    // internal source-exists check passes (belt-and-suspenders; the mock is a no-op).
    getSource: vi.fn((id: string) => (id === TERRAIN_SOURCE_ID ? { type: 'raster-dem' } : null)),
    getLayer: vi.fn(() => null),
    getStyle: vi.fn(() => ({ layers: [] })),
    getBounds: vi.fn(() => ({
      getWest: () => viewport[0],
      getSouth: () => viewport[1],
      getEast: () => viewport[2],
      getNorth: () => viewport[3],
    })),
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
    setViewport: (next: [number, number, number, number]) => {
      viewport = next;
    },
    reset: () => {
      viewport = DEFAULT_VIEWPORT;
      handlers.clear();
      fakeMap.on.mockClear();
      fakeMap.off.mockClear();
      fakeMap.once.mockClear();
      fakeMap.setTransformRequest.mockClear();
      fakeMap.isStyleLoaded.mockClear();
      fakeMap.getCanvas.mockClear();
      fakeMap.setTerrain.mockClear();
      fakeMap.setProjection.mockClear();
      fakeMap.triggerRepaint.mockClear();
      fakeMap.getSource.mockClear();
      fakeMap.getLayer.mockClear();
      fakeMap.getStyle.mockClear();
      fakeMap.getBounds.mockClear();
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
  sig: 'sig-fixture',
  exp: 2000000000,
  scope: 'scope-fixture',
  expires_in: 900,
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

  // fix(#454): the intermittent flat-Matterhorn-on-load bug. After a basemap
  // style swap, terrain re-apply is deferred to ONE map.once('idle',
  // applyTerrainConfig). When that idle fired mid style-transition
  // (isStyleLoaded()===false), applyTerrainConfig no-oped silently and an
  // enabled terrain_config rendered a flat map until an unrelated dep changed.
  // It must re-arm on the next idle instead.
  it('re-arms and applies terrain when the deferred idle lands mid style-transition (#454)', async () => {
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
    mapState.fakeMap.setTerrain.mockClear();

    // Basemap swap: style.load fires while the (next) transition is in flight.
    mapState.fakeMap.isStyleLoaded.mockReturnValue(false);
    await act(async () => {
      mapState.fakeMap.emit('style.load');
    });

    // The deferred idle lands mid-transition — the old code dropped the apply
    // here permanently.
    await act(async () => {
      mapState.fakeMap.emit('idle');
    });
    expect(mapState.fakeMap.setTerrain).not.toHaveBeenCalledWith(
      expect.objectContaining({ source: TERRAIN_SOURCE_ID }),
    );

    // Style settles; the re-armed idle must now attach the mesh.
    mapState.fakeMap.isStyleLoaded.mockReturnValue(true);
    await act(async () => {
      mapState.fakeMap.emit('idle');
    });
    const setTerrainCalls = mapState.fakeMap.setTerrain.mock.calls;
    expect(setTerrainCalls.length).toBeGreaterThan(0);
    expect(setTerrainCalls[setTerrainCalls.length - 1][0]).toMatchObject({ source: TERRAIN_SOURCE_ID });
  });
});

// fix(#1128): the small-DEM coverage guard must measure the DEM LAYER's
// `dataset_extent_bbox`, not the tile token's `bounds`. The token carries the
// span form (extent_to_span_bbox, processing/tiles/router.py), which widens a
// seam-crossing footprint to exactly [-180, s, 180, n] — byte-identical to a
// genuinely global DEM. Measuring from it read 100% coverage and said nothing
// about a DEM occupying a fifth of the screen.
//
// Both directions are pinned. A fix that only stops the false negative could
// regress into warning about the DEM that visibly fills the screen, which is
// the #1122 bug arriving from the other side.
describe('BuilderMap #1128: small-DEM coverage reads the layer extent, not the token span', () => {
  // The issue's viewport: 10.5 x 5 degrees, straddling the antimeridian.
  const SEAM_VIEW: [number, number, number, number] = [179.5, -20, 190, -15];
  // What the token carries for EITHER dataset below — the ambiguity itself.
  const TOKEN_SPAN = [-180, -20, 180, -15];

  beforeEach(() => {
    mapState.reset();
    mapState.setViewport(SEAM_VIEW);
    vi.mocked(toast.warning).mockClear();
    // The dedupe store is a module-level WeakMap keyed on the map object, and
    // every test in this file shares the one hoisted fakeMap. Clear it, or the
    // second case below is decided by the first case's leftover key rather
    // than by its own coverage.
    resetSmallDemWarning(mapState.fakeMap);
    tileTokenState.tokens = [
      { data: { ...rasterToken, bounds: [...TOKEN_SPAN] }, isLoading: false, isError: false },
    ];
  });

  async function renderWithExtent(extent: number[]) {
    const demLayer: MapLayerResponse = { ...makeDemLayer(true), dataset_extent_bbox: extent };
    await act(async () => {
      render(
        <BuilderMap
          layers={[demLayer]}
          basemapStyle="openfreemap-positron"
          terrainConfig={terrainConfig}
        />,
      );
    });
  }

  it('warns for a seam-crossing DEM the token span reports as global', async () => {
    // RFC 7946 §5.2 spec form (#1112): 3 degrees wide, 2 of them inside the
    // viewport → 19% coverage, under the 25% threshold.
    await renderWithExtent([178.5, -20, -178.5, -15]);
    expect(toast.warning).toHaveBeenCalledTimes(1);
  });

  it('stays silent for a DEM that genuinely spans the globe', async () => {
    await renderWithExtent([-180, -20, 180, -15]);
    expect(toast.warning).not.toHaveBeenCalled();
  });
});

describe('BuilderMap style.load token gate (fix(#845 Codex P2 r5 on #848))', () => {
  beforeEach(() => {
    mapState.reset();
    vi.mocked(applyBasemapConfigToMap).mockClear();
    vi.mocked(syncLayersToMap).mockClear();
  });

  it('restores basemap appearance and projection when the token gate defers layer sync', async () => {
    // Token still loading → tokenMap has no entry for the layer's dataset,
    // so onStyleLoad hits the missing-token early return.
    tileTokenState.tokens = [{ data: undefined, isLoading: true, isError: false }];
    const basemapConfig = { projection: 'globe' } as MapBasemapConfig;

    await act(async () => {
      render(
        <BuilderMap
          layers={[makeDemLayer(true)]}
          basemapStyle="openfreemap-positron"
          terrainConfig={null}
          basemapConfig={basemapConfig}
        />,
      );
    });
    vi.mocked(applyBasemapConfigToMap).mockClear();
    vi.mocked(syncLayersToMap).mockClear();
    mapState.fakeMap.setProjection.mockClear();

    // Basemap swap resets the style's projection/appearance.
    await act(async () => {
      mapState.fakeMap.emit('style.load');
    });

    // Layer sync stays deferred (no token yet)…
    expect(syncLayersToMap).not.toHaveBeenCalled();
    // …but the live appearance, including the saved projection, is restored.
    expect(applyBasemapConfigToMap).toHaveBeenCalledWith(
      expect.anything(),
      basemapConfig,
      true,
      'source-',
    );
    expect(mapState.fakeMap.setProjection).toHaveBeenCalledWith({ type: 'globe' });
  });
});
