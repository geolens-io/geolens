// BUG-037: the ViewerMap visibility-only effect dropped layer toggles issued
// while the basemap style was transitioning — a plain early-return on
// !isStyleLoaded() with no idle retry, and prevVisibleRef left unadvanced. The
// fix registers map.once('idle', applyVisibilityDiff) so the toggle re-applies
// once the map settles (mirrors the BuilderMap idle-retry pattern).
import type { ReactNode } from 'react';
import { act, render, waitFor } from '@/test/test-utils';
import { ViewerMap } from '../ViewerMap';
import type { SharedLayerResponse } from '@/types/api';

type FakeMap = {
  isStyleLoaded: ReturnType<typeof vi.fn>;
  on: ReturnType<typeof vi.fn>;
  off: ReturnType<typeof vi.fn>;
  once: ReturnType<typeof vi.fn>;
  setTransformRequest: ReturnType<typeof vi.fn>;
  getLayer: ReturnType<typeof vi.fn>;
  getSource: ReturnType<typeof vi.fn>;
  getStyle: ReturnType<typeof vi.fn>;
  queryRenderedFeatures: ReturnType<typeof vi.fn>;
  getCanvas: ReturnType<typeof vi.fn>;
  getZoom: ReturnType<typeof vi.fn>;
  easeTo: ReturnType<typeof vi.fn>;
  moveLayer: ReturnType<typeof vi.fn>;
  removeSource: ReturnType<typeof vi.fn>;
  setTerrain: ReturnType<typeof vi.fn>;
  setMissingStyleImageResolver: ReturnType<typeof vi.fn>;
  setLayoutProperty: ReturnType<typeof vi.fn>;
  setPaintProperty: ReturnType<typeof vi.fn>;
  setFilter: ReturnType<typeof vi.fn>;
  addLayer: ReturnType<typeof vi.fn>;
  addSource: ReturnType<typeof vi.fn>;
  removeLayer: ReturnType<typeof vi.fn>;
  triggerRepaint: ReturnType<typeof vi.fn>;
  setLayerZoomRange: ReturnType<typeof vi.fn>;
  emit: (event: string, payload?: unknown) => void;
};

type TestToken =
  | { kind: 'vector'; token: string }
  | { kind: 'raster'; tile_url: string };

const mapState = vi.hoisted(() => {
  const handlers = new Map<string, Set<(payload?: unknown) => void>>();
  const sources = new Map<string, { type: string }>();
  const canvas = {
    width: 800, height: 600, clientWidth: 800, clientHeight: 600,
    style: { cursor: '' },
    addEventListener: vi.fn(), removeEventListener: vi.fn(),
  };
  const fakeMap: FakeMap = {
    // Default: style NOT loaded — forces the idle-retry path.
    isStyleLoaded: vi.fn(() => false),
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
    // Return truthy for every layer id so adapter.syncVisibility actually
    // dispatches setLayoutProperty when the diff applies.
    getLayer: vi.fn(() => ({ id: 'x' })),
    getSource: vi.fn((sourceId: string) => sources.get(sourceId) ?? null),
    getStyle: vi.fn(() => ({ version: 8, sources: {}, layers: [] })),
    queryRenderedFeatures: vi.fn(() => []),
    getCanvas: vi.fn(() => canvas),
    getZoom: vi.fn(() => 5),
    easeTo: vi.fn(),
    moveLayer: vi.fn(),
    removeSource: vi.fn(),
    setTerrain: vi.fn(),
    setMissingStyleImageResolver: vi.fn(),
    setLayoutProperty: vi.fn(),
    setPaintProperty: vi.fn(),
    setFilter: vi.fn(),
    addLayer: vi.fn(),
    addSource: vi.fn((sourceId: string, spec: { type: string }) => {
      sources.set(sourceId, { type: spec.type });
    }),
    removeLayer: vi.fn(),
    triggerRepaint: vi.fn(),
    setLayerZoomRange: vi.fn(),
    emit: (event: string, payload?: unknown) => {
      for (const handler of Array.from(handlers.get(event) ?? [])) handler(payload);
    },
  };
  return {
    fakeMap,
    handlers,
    reset: () => {
      handlers.clear();
      sources.clear();
      Object.values(fakeMap).forEach((v) => {
        if (typeof v === 'function' && 'mockClear' in v) (v as ReturnType<typeof vi.fn>).mockClear();
      });
      fakeMap.isStyleLoaded.mockReturnValue(false);
      fakeMap.getLayer.mockReturnValue({ id: 'x' });
    },
  };
});

vi.mock('@vis.gl/react-maplibre', async () => {
  const React = await import('react');
  return {
    Map: ({ children, onLoad }: { children?: ReactNode; onLoad?: (e: { target: FakeMap }) => void }) => {
      React.useEffect(() => { onLoad?.({ target: mapState.fakeMap }); }, [onLoad]);
      return <div data-testid="mapgl">{children}</div>;
    },
    NavigationControl: () => null,
    ScaleControl: () => null,
    FullscreenControl: () => null,
    AttributionControl: () => null,
    TerrainControl: () => null,
    Popup: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
  };
});

const tileConfigState = vi.hoisted(() => ({
  data: {
    cdn_base_url: null,
    mvt_source_layer_prefix: 'data',
  } as {
    cdn_base_url: string | null;
    mvt_source_layer_prefix: string | null;
  } | null,
}));

const tokenState = vi.hoisted(() => ({
  data: new Map<string, TestToken>([['dataset-pt', { kind: 'vector', token: 't' }]]),
}));

const terrainState = vi.hoisted(() => ({
  ready: false,
  expected: false,
}));

vi.mock('@/hooks/use-settings', () => ({
  useBasemaps: () => ({ data: [] }),
  useTileConfig: () => ({ data: tileConfigState.data }),
  useBranding: () => ({ data: undefined }),
}));
vi.mock('@/hooks/use-webgl-recovery', () => ({
  useWebGLRecovery: () => ({ contextLost: false, reload: vi.fn() }),
}));
vi.mock('@/components/viewer/hooks/use-viewer-tokens', () => ({
  // Provide a token so the main sync effect's token gate doesn't short-circuit.
  useViewerTokens: () => ({ tokenMap: tokenState.data }),
}));
vi.mock('@/components/viewer/hooks/use-viewer-terrain', () => ({
  useViewerTerrain: () => ({ terrainReady: terrainState.ready, reseedTerrainOnStyleLoad: vi.fn() }),
  isViewerTerrainExpected: () => terrainState.expected,
}));
vi.mock('@/components/map/MapCoordReadout', () => ({ MapCoordReadout: () => null }));
vi.mock('@/components/builder/map-sync', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/components/builder/map-sync')>();
  return { ...actual, applyBasemapConfigToMap: vi.fn(), syncLayersToMap: vi.fn() };
});
vi.mock('@/components/builder/map-composition-sync', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/components/builder/map-composition-sync')>();
  return {
    ...actual,
    syncMapComposition: vi.fn(({ map, layers, managedSourcesRef }) => {
      if (layers.length === 0) return;
      if (layers.every((layer: { is_dem?: boolean; style_config?: { render_mode?: string } | null }) => (
        layer.is_dem === true && layer.style_config?.render_mode === 'terrain'
      ))) return;
      const sourceId = 'viewer-source-points';
      if (!map.getSource(sourceId)) map.addSource(sourceId, { type: 'vector' });
      managedSourcesRef.current = new Set([sourceId]);
    }),
  };
});
vi.mock('@/lib/builder/basemap-style-mutation', () => ({ applySublayerOverrides: vi.fn() }));

const LAYER: SharedLayerResponse = {
  id: 'pt-layer',
  dataset_id: 'dataset-pt',
  dataset_name: 'Points',
  display_name: 'Points',
  table_name: 'points',
  geometry_type: 'POINT',
  column_info: null,
  sort_order: 0,
  visible: true,
  opacity: 1,
  paint: { 'circle-color': '#2255aa', 'circle-radius': 6 },
  layout: {},
  filter: null,
  label_config: null,
  popup_config: null,
  style_config: null,
  tile_url: '',
};

function renderViewer(visibleLayers: Set<string>) {
  return render(
    <ViewerMap
      layers={[LAYER]}
      basemapStyle="openfreemap-positron"
      basemapConfig={null}
      showBasemapLabels={true}
      terrainConfig={null}
      initialViewState={{ center_lng: 0, center_lat: 0, zoom: 2, bearing: 0, pitch: 0 }}
      visibleLayers={visibleLayers}
    />,
  );
}

describe('ViewerMap visibility idle-retry (BUG-037)', () => {
  beforeEach(() => {
    mapState.reset();
    tileConfigState.data = {
      cdn_base_url: null,
      mvt_source_layer_prefix: 'data',
    };
    tokenState.data = new Map([['dataset-pt', { kind: 'vector', token: 't' }]]);
    terrainState.ready = false;
    terrainState.expected = false;
  });

  it('does not run visibility sync for an unresolved tenant source-layer prefix', async () => {
    tileConfigState.data = {
      cdn_base_url: null,
      mvt_source_layer_prefix: null,
    };
    mapState.fakeMap.isStyleLoaded.mockReturnValue(true);

    renderViewer(new Set(['pt-layer']));

    await waitFor(() => expect(mapState.fakeMap.setTransformRequest).toHaveBeenCalled());
    expect(mapState.fakeMap.setLayoutProperty).not.toHaveBeenCalled();
  });

  it('registers an idle retry when a toggle arrives while the style is transitioning', async () => {
    // Initial render with the style LOADED so the visibility effect advances
    // prevVisibleRef to {pt-layer} (the layer is shown and the baseline is set).
    mapState.fakeMap.isStyleLoaded.mockReturnValue(true);
    const { rerender } = renderViewer(new Set(['pt-layer']));
    await waitFor(() => expect(mapState.fakeMap.isStyleLoaded).toHaveBeenCalled());

    // Now a basemap-style swap is in flight: the style is transitioning.
    mapState.fakeMap.isStyleLoaded.mockReturnValue(false);
    mapState.fakeMap.once.mockClear();
    mapState.fakeMap.setLayoutProperty.mockClear();

    // Toggle the layer OFF while the style is mid-transition (isStyleLoaded=false).
    rerender(
      <ViewerMap
        layers={[LAYER]}
        basemapStyle="openfreemap-positron"
        basemapConfig={null}
        showBasemapLabels={true}
        terrainConfig={null}
        initialViewState={{ center_lng: 0, center_lat: 0, zoom: 2, bearing: 0, pitch: 0 }}
        visibleLayers={new Set()}
      />,
    );

    // The dedicated visibility effect must have scheduled an idle retry rather
    // than silently dropping the toggle.
    await waitFor(() => {
      expect(mapState.fakeMap.once).toHaveBeenCalledWith('idle', expect.any(Function));
    });

    // Now the style settles → the queued diff applies and hides the layer.
    mapState.fakeMap.isStyleLoaded.mockReturnValue(true);
    mapState.fakeMap.emit('idle');

    expect(mapState.fakeMap.setLayoutProperty).toHaveBeenCalledWith(
      'viewer-layer-pt-layer',
      'visibility',
      'none',
    );
  });

  it('does not reuse the initial basemap idle for an asynchronously added data layer', async () => {
    mapState.fakeMap.isStyleLoaded.mockReturnValue(true);
    tokenState.data = new Map();

    const { rerender, getByRole } = renderViewer(new Set(['pt-layer']));
    const mapRegion = getByRole('region', { name: 'Map viewer' });

    await waitFor(() => expect(mapState.fakeMap.setTransformRequest).toHaveBeenCalled());
    act(() => { mapState.fakeMap.emit('idle'); });

    // The basemap has settled, but the data-layer token has not arrived and no
    // ViewerMap-owned source/layer has been composed yet.
    expect(mapRegion).toHaveAttribute('data-tiles-loaded', 'false');
    expect(mapRegion).toHaveAttribute('data-map-ready', 'false');

    tokenState.data = new Map([['dataset-pt', { kind: 'vector', token: 'late' }]]);
    rerender(
      <ViewerMap
        layers={[LAYER]}
        basemapStyle="openfreemap-positron"
        basemapConfig={null}
        showBasemapLabels={true}
        terrainConfig={null}
        initialViewState={{ center_lng: 0, center_lat: 0, zoom: 2, bearing: 0, pitch: 0 }}
        visibleLayers={new Set(['pt-layer'])}
      />,
    );

    await waitFor(() => expect(mapState.fakeMap.addSource).toHaveBeenCalled());
    expect(mapRegion).toHaveAttribute('data-map-ready', 'false');

    // Only an idle observed after the current composition was attached can
    // certify it. Later source activity re-arms the same contract.
    act(() => { mapState.fakeMap.emit('idle'); });
    await waitFor(() => expect(mapRegion).toHaveAttribute('data-map-ready', 'true'));
    expect(mapRegion).toHaveAttribute('data-tiles-loaded', 'true');

    act(() => { mapState.fakeMap.emit('dataloading'); });
    expect(mapRegion).toHaveAttribute('data-map-ready', 'false');
    expect(mapRegion).toHaveAttribute('data-tiles-loaded', 'false');

    act(() => { mapState.fakeMap.emit('idle'); });
    await waitFor(() => expect(mapRegion).toHaveAttribute('data-map-ready', 'true'));
  });

  it('settles a terrain-only composition after the terrain source load cycle', async () => {
    const terrainLayer: SharedLayerResponse = {
      ...LAYER,
      id: 'terrain-layer',
      dataset_id: 'dataset-dem',
      table_name: 'terrain_dem',
      geometry_type: null,
      is_dem: true,
      layer_type: 'raster_geolens',
      style_config: { render_mode: 'terrain' },
    };
    mapState.fakeMap.isStyleLoaded.mockReturnValue(true);
    tokenState.data = new Map([['dataset-dem', { kind: 'raster' as const, tile_url: '/dem/{z}/{x}/{y}.png' }]]);
    terrainState.expected = true;

    const { rerender, getByRole } = render(
      <ViewerMap
        layers={[terrainLayer]}
        basemapStyle="openfreemap-positron"
        terrainConfig={{ enabled: true, source_dataset_id: 'dataset-dem', exaggeration: 1 }}
        initialViewState={{ center_lng: 0, center_lat: 0, zoom: 2, bearing: 0, pitch: 0 }}
        visibleLayers={new Set(['terrain-layer'])}
      />,
    );
    const mapRegion = getByRole('region', { name: 'Map viewer' });

    await waitFor(() => expect(mapState.fakeMap.setTransformRequest).toHaveBeenCalled());
    act(() => { mapState.fakeMap.emit('idle'); });
    expect(mapRegion).toHaveAttribute('data-map-ready', 'false');

    // The terrain hook owns this source outside syncMapComposition. Its data
    // activity re-arms readiness, and terrainReady alone cannot bypass idle.
    act(() => { mapState.fakeMap.emit('dataloading'); });
    terrainState.ready = true;
    rerender(
      <ViewerMap
        layers={[terrainLayer]}
        basemapStyle="openfreemap-positron"
        terrainConfig={{ enabled: true, source_dataset_id: 'dataset-dem', exaggeration: 1 }}
        initialViewState={{ center_lng: 0, center_lat: 0, zoom: 2, bearing: 0, pitch: 0 }}
        visibleLayers={new Set(['terrain-layer'])}
      />,
    );
    expect(mapRegion).toHaveAttribute('data-map-ready', 'false');

    act(() => { mapState.fakeMap.emit('idle'); });
    await waitFor(() => expect(mapRegion).toHaveAttribute('data-map-ready', 'true'));
  });
});
