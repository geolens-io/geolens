// BUG-037: the ViewerMap visibility-only effect dropped layer toggles issued
// while the basemap style was transitioning — a plain early-return on
// !isStyleLoaded() with no idle retry, and prevVisibleRef left unadvanced. The
// fix registers map.once('idle', applyVisibilityDiff) so the toggle re-applies
// once the map settles (mirrors the BuilderMap idle-retry pattern).
import type { ReactNode } from 'react';
import { render, waitFor } from '@/test/test-utils';
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

const mapState = vi.hoisted(() => {
  const handlers = new Map<string, Set<(payload?: unknown) => void>>();
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
    getSource: vi.fn(() => null),
    getStyle: vi.fn(() => ({ version: 8, sources: {}, layers: [] })),
    queryRenderedFeatures: vi.fn(() => []),
    getCanvas: vi.fn(() => canvas),
    getZoom: vi.fn(() => 5),
    easeTo: vi.fn(),
    moveLayer: vi.fn(),
    removeSource: vi.fn(),
    setTerrain: vi.fn(),
    setLayoutProperty: vi.fn(),
    setPaintProperty: vi.fn(),
    setFilter: vi.fn(),
    addLayer: vi.fn(),
    addSource: vi.fn(),
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
  useViewerTokens: () => ({ tokenMap: new Map([['dataset-pt', { kind: 'vector', token: 't' }]]) }),
}));
vi.mock('@/components/viewer/hooks/use-viewer-terrain', () => ({
  useViewerTerrain: () => ({ terrainReady: false, reseedTerrainOnStyleLoad: vi.fn() }),
  isViewerTerrainExpected: () => false,
}));
vi.mock('@/components/map/MapCoordReadout', () => ({ MapCoordReadout: () => null }));
vi.mock('@/components/builder/map-sync', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/components/builder/map-sync')>();
  return { ...actual, applyBasemapConfigToMap: vi.fn(), syncLayersToMap: vi.fn() };
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
});
