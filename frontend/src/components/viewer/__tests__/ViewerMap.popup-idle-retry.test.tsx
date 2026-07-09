// Shared-viewer popup inertness (#431 QA finding): the click and mousemove
// effects early-returned on !isStyleLoaded() with no idle retry, so on a cold
// hard load — exactly how a share link opens — map.on('click') was never
// attached and popups were inert for every geometry family. The fix mirrors
// the BUG-037 idle-retry used by the layer-sync/visibility effects.
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
    // Default: style NOT loaded — the cold share-link load.
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

vi.mock('@/hooks/use-settings', () => ({
  useBasemaps: () => ({ data: [] }),
  useTileConfig: () => ({ data: { cdn_base_url: null } }),
  useBranding: () => ({ data: undefined }),
}));
vi.mock('@/hooks/use-webgl-recovery', () => ({
  useWebGLRecovery: () => ({ contextLost: false, reload: vi.fn() }),
}));
vi.mock('@/components/viewer/hooks/use-viewer-tokens', () => ({
  useViewerTokens: () => ({ tokenMap: new Map([['dataset-pt', { kind: 'vector', token: 't' }]]) }),
}));
vi.mock('@/components/viewer/hooks/use-viewer-terrain', () => ({
  useViewerTerrain: () => ({ terrainReady: false, reseedTerrainOnStyleLoad: vi.fn() }),
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

describe('ViewerMap popup listeners idle-retry (shared-viewer cold load)', () => {
  beforeEach(() => { mapState.reset(); });

  it('attaches click and mousemove handlers via idle retry when the style is still transitioning', async () => {
    // Cold load: isStyleLoaded() is false from the very first effect run.
    render(
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

    // The effects must schedule idle retries instead of bailing forever.
    await waitFor(() => {
      expect(mapState.fakeMap.once).toHaveBeenCalledWith('idle', expect.any(Function));
    });
    // Pre-fix behavior: neither listener was ever attached on a cold load.
    expect(mapState.fakeMap.on).not.toHaveBeenCalledWith('click', expect.any(Function));
    expect(mapState.fakeMap.on).not.toHaveBeenCalledWith('mousemove', expect.any(Function));

    // Style settles → the retries attach the interaction listeners.
    mapState.fakeMap.isStyleLoaded.mockReturnValue(true);
    mapState.fakeMap.emit('idle');

    expect(mapState.fakeMap.on).toHaveBeenCalledWith('click', expect.any(Function));
    expect(mapState.fakeMap.on).toHaveBeenCalledWith('mousemove', expect.any(Function));
  });
});
