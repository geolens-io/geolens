// fix(#943): the BuilderMap click/mousemove hit-test path had no unit test in
// any of the seven BuilderMap.* files, and #729's consumer half was equally
// unpinned — the suppression suite covered only the store-flag producer, never
// the two refs the handlers actually read (`measureActiveRef`, `drawActiveRef`).
//
// Uses the vi.hoisted fakeMap + @vis.gl/react-maplibre recipe from
// BuilderMap.terrain-visibility.test.tsx, with queryRenderedFeatures added so a
// click can resolve a hit, and FeaturePopup stubbed so what the pipeline
// produced is readable from the DOM.

import type { ReactNode } from 'react';
import { act, render, screen } from '@/test/test-utils';
import type { MapLayerResponse } from '@/types/api';
import type { VectorTileToken } from '@/api/tiles';
import { BuilderMap } from '../BuilderMap';
import { useMapDrawStore } from '@/stores/map-draw-store';
import { usePluginStore } from '@/stores/map-plugin-store';

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
  useTileConfig: () => ({ data: { cdn_base_url: null, mvt_source_layer_prefix: 'data' } }),
  useEnabledPlugins: () => ({ data: ['measurement'], isLoading: false }),
}));

const vectorToken: VectorTileToken = {
  kind: 'vector',
  sig: 'sig',
  exp: 9_999_999_999,
  scope: 'test',
  expires_in: 900,
} as VectorTileToken;

vi.mock('@/hooks/use-tile-token', () => ({
  useInvalidateTileTokens: () => vi.fn(),
  useTileTokens: () => [{ data: vectorToken, isLoading: false, isError: false }],
}));

vi.mock('@/hooks/use-webgl-recovery', () => ({
  useWebGLRecovery: () => ({ contextLost: false, reload: vi.fn() }),
}));

vi.mock('@/components/map/MapCoordReadout', () => ({ MapCoordReadout: () => null }));

vi.mock('sonner', () => ({
  toast: { error: vi.fn(), success: vi.fn(), warning: vi.fn() },
}));

// The popup's own rendering is not under test — what it was handed is.
vi.mock('@/components/map/FeaturePopup', () => ({
  FeaturePopup: ({ features }: { features: Array<{ layerName: string }> }) => (
    <div data-testid="feature-popup">{features.map((f) => f.layerName).join(',')}</div>
  ),
}));

// Layer sync is not under test; the handlers read queryLayerIdsRef, which is
// refreshed from `map.getLayer` after each sync.
vi.mock('@/components/builder/map-sync', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/components/builder/map-sync')>();
  return {
    ...actual,
    syncLayersToMap: vi.fn(),
    applyBasemapConfigToMap: vi.fn(),
    reorderBasemapLabels: vi.fn(),
    reorderDataLayers: vi.fn(),
    applyTerrainConfig: vi.fn(),
    ensureRasterDemTerrainSource: vi.fn(),
  };
});

type QueriedFeature = {
  layer: { id: string };
  properties: Record<string, unknown>;
};

const mapState = vi.hoisted(() => {
  const handlers = new Map<string, Set<(payload?: unknown) => void>>();
  const hits: { features: unknown[] } = { features: [] };
  const canvas = {
    style: { cursor: '' },
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  };
  const fakeMap = {
    on: vi.fn((event: string, handler: (payload?: unknown) => void) => {
      const existing = handlers.get(event) ?? new Set();
      existing.add(handler);
      handlers.set(event, existing);
    }),
    off: vi.fn((event: string, handler: (payload?: unknown) => void) => {
      handlers.get(event)?.delete(handler);
    }),
    once: vi.fn((event: string, handler: (payload?: unknown) => void) => {
      const existing = handlers.get(event) ?? new Set();
      existing.add(handler);
      handlers.set(event, existing);
    }),
    setTransformRequest: vi.fn(),
    isStyleLoaded: vi.fn(() => true),
    getCanvas: vi.fn(() => canvas),
    setTerrain: vi.fn(),
    setMissingStyleImageResolver: vi.fn(),
    setProjection: vi.fn(),
    triggerRepaint: vi.fn(),
    getSource: vi.fn(() => null),
    // Every id the builder asks about exists, so refreshQueryLayerIds keeps them.
    getLayer: vi.fn((id: string) => ({ id })),
    getStyle: vi.fn(() => ({ layers: [] })),
    fitBounds: vi.fn(),
    getZoom: vi.fn(() => 8),
    setZoom: vi.fn(),
    queryRenderedFeatures: vi.fn(() => hits.features),
    emit: (event: string, payload?: unknown) => {
      for (const handler of Array.from(handlers.get(event) ?? [])) handler(payload);
    },
  };

  return {
    fakeMap,
    canvas,
    hits,
    reset: () => {
      handlers.clear();
      hits.features = [];
      canvas.style.cursor = '';
      vi.clearAllMocks();
      fakeMap.isStyleLoaded.mockReturnValue(true);
      fakeMap.getCanvas.mockReturnValue(canvas);
      fakeMap.getLayer.mockImplementation((id: string) => ({ id }));
      fakeMap.getZoom.mockReturnValue(8);
      fakeMap.queryRenderedFeatures.mockImplementation(() => hits.features);
      fakeMap.getStyle.mockReturnValue({ layers: [] });
      fakeMap.getSource.mockReturnValue(null);
    },
  };
});

vi.mock('@vis.gl/react-maplibre', async () => {
  const React = await import('react');
  return {
    Map: ({ children, onLoad }: { children?: ReactNode; onLoad?: (e: { target: unknown }) => void }) => {
      React.useEffect(() => {
        onLoad?.({ target: mapState.fakeMap });
      }, [onLoad]);
      return <div data-testid="mapgl">{children}</div>;
    },
    NavigationControl: () => null,
    ScaleControl: () => null,
  };
});

function makeLayer(overrides: Partial<MapLayerResponse> = {}): MapLayerResponse {
  return {
    id: 'layer-1',
    dataset_id: 'ds-1',
    dataset_name: 'Parcels',
    dataset_geometry_type: 'POLYGON',
    dataset_table_name: 'parcels',
    dataset_extent_bbox: null,
    dataset_column_info: null,
    dataset_feature_count: null,
    dataset_sample_values: null,
    display_name: 'Parcels',
    sort_order: 0,
    visible: true,
    opacity: 1,
    paint: {},
    layout: {},
    filter: null,
    label_config: null,
    popup_config: null,
    style_config: null,
    layer_type: null,
    dataset_record_type: 'vector_dataset',
    show_in_legend: true,
    is_dem: false,
    dem_vertical_units: null,
    ...(overrides as object),
  } as unknown as MapLayerResponse;
}

/** The MapLibre layer id BuilderMap gives a layer row. */
const MAP_LAYER_ID = 'layer-layer-1';

function featureHit(properties: Record<string, unknown> = { name: 'Lot 4' }): QueriedFeature {
  return { layer: { id: MAP_LAYER_ID }, properties };
}

async function renderMap(layers: MapLayerResponse[]) {
  await act(async () => {
    render(<BuilderMap layers={layers} basemapStyle="openfreemap-positron" />);
  });
}

function clickMap() {
  act(() => {
    mapState.fakeMap.emit('click', { point: { x: 10, y: 10 }, lngLat: { lng: 1, lat: 2 } });
  });
}

beforeEach(() => {
  mapState.reset();
  useMapDrawStore.setState({ drawActive: false });
  usePluginStore.setState({ activePlugins: new Set<string>() });
});

describe('BuilderMap popup pipeline (fix #943)', () => {
  it('opens a popup for a hit on a popup-enabled layer', async () => {
    await renderMap([makeLayer()]);
    mapState.hits.features = [featureHit()];

    clickMap();

    expect(screen.getByTestId('feature-popup')).toHaveTextContent('Parcels');
  });

  it('opens no popup when the layer has popups disabled', async () => {
    await renderMap([
      makeLayer({ popup_config: { enabled: false } as MapLayerResponse['popup_config'] }),
    ]);
    mapState.hits.features = [featureHit()];

    clickMap();

    expect(screen.queryByTestId('feature-popup')).not.toBeInTheDocument();
  });

  it('opens no popup when the click resolves to no known layer', async () => {
    await renderMap([makeLayer()]);
    mapState.hits.features = [{ layer: { id: 'some-basemap-layer' }, properties: {} }];

    clickMap();

    expect(screen.queryByTestId('feature-popup')).not.toBeInTheDocument();
  });

  it('closes an open popup when a later click hits nothing', async () => {
    await renderMap([makeLayer()]);
    mapState.hits.features = [featureHit()];
    clickMap();
    expect(screen.getByTestId('feature-popup')).toBeInTheDocument();

    mapState.hits.features = [];
    clickMap();

    expect(screen.queryByTestId('feature-popup')).not.toBeInTheDocument();
  });

  it('sets a pointer cursor over an interactive feature and clears it off one', async () => {
    await renderMap([makeLayer()]);
    mapState.hits.features = [featureHit()];

    act(() => {
      mapState.fakeMap.emit('mousemove', { point: { x: 5, y: 5 }, lngLat: { lng: 0, lat: 0 } });
    });
    await act(async () => {
      await new Promise((resolve) => requestAnimationFrame(resolve));
    });
    expect(mapState.canvas.style.cursor).toBe('pointer');

    mapState.hits.features = [];
    act(() => {
      mapState.fakeMap.emit('mousemove', { point: { x: 5, y: 5 }, lngLat: { lng: 0, lat: 0 } });
    });
    await act(async () => {
      await new Promise((resolve) => requestAnimationFrame(resolve));
    });
    expect(mapState.canvas.style.cursor).toBe('');
  });
});

// fix(#729): a draw mode (the analysis clip mask) owns the pointer while it
// runs. The producer side — the store flag — was already pinned; these cover
// the two refs the click/mousemove handlers actually read.
describe('BuilderMap draw and measure guards (fix #943, consumer half of #729)', () => {
  it('opens no popup while a draw mode owns the pointer', async () => {
    await renderMap([makeLayer()]);
    mapState.hits.features = [featureHit()];

    act(() => useMapDrawStore.setState({ drawActive: true }));
    clickMap();

    expect(screen.queryByTestId('feature-popup')).not.toBeInTheDocument();
  });

  it('dismisses an already-open popup when drawing starts', async () => {
    await renderMap([makeLayer()]);
    mapState.hits.features = [featureHit()];
    clickMap();
    expect(screen.getByTestId('feature-popup')).toBeInTheDocument();

    act(() => useMapDrawStore.setState({ drawActive: true }));

    expect(screen.queryByTestId('feature-popup')).not.toBeInTheDocument();
  });

  it('reopens popups once drawing ends', async () => {
    await renderMap([makeLayer()]);
    mapState.hits.features = [featureHit()];

    act(() => useMapDrawStore.setState({ drawActive: true }));
    clickMap();
    act(() => useMapDrawStore.setState({ drawActive: false }));
    clickMap();

    expect(screen.getByTestId('feature-popup')).toBeInTheDocument();
  });

  it('opens no popup while the measurement plugin is active', async () => {
    await renderMap([makeLayer()]);
    mapState.hits.features = [featureHit()];

    act(() => usePluginStore.setState({ activePlugins: new Set(['measurement']) }));
    clickMap();

    expect(screen.queryByTestId('feature-popup')).not.toBeInTheDocument();
  });

  it('leaves the cursor alone while a draw mode owns the pointer', async () => {
    await renderMap([makeLayer()]);
    mapState.hits.features = [featureHit()];

    act(() => useMapDrawStore.setState({ drawActive: true }));
    act(() => {
      mapState.fakeMap.emit('mousemove', { point: { x: 5, y: 5 }, lngLat: { lng: 0, lat: 0 } });
    });
    await act(async () => {
      await new Promise((resolve) => requestAnimationFrame(resolve));
    });

    expect(mapState.canvas.style.cursor).toBe('');
  });
});
