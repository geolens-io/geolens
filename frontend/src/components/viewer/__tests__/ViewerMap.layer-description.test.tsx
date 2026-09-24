// The viewer describes its layers as the builder does: a toggle hands the adapter
// a clean input, sources fit their extent, and only cluster layers fetch GeoJSON.
import type { ReactNode } from 'react';
import type { FilterSpecification, Map as MaplibreMap } from 'maplibre-gl';
import { render, waitFor } from '@/test/test-utils';
import { BLANK_BASEMAP_ID } from '@/lib/basemap-utils';
import { sanitizeNullableNumericFilter } from '@/lib/maplibre-filter-utils';
import { fetchBoundedGeoJson } from '@/api/geojson-z';
import { circleAdapter } from '@/components/builder/layer-adapters/circle-adapter';
import { fillAdapter } from '@/components/builder/layer-adapters/fill-adapter';
import type { AdapterLayerInput } from '@/components/builder/layer-adapters/types';
import { syncLayersToMap } from '@/components/builder/map-sync';
import { SAVED_LAYERS, toSharedLayer } from '@/test/fixtures/saved-layers';
import type { SharedLayerResponse } from '@/types/api';
import { ViewerMap, toViewerSyncInput } from '../ViewerMap';

const mapState = vi.hoisted(() => {
  const handlers = new Map<string, Set<(payload?: unknown) => void>>();
  const listen = (event: string, handler: (payload?: unknown) => void) => {
    const existing = handlers.get(event) ?? new Set();
    existing.add(handler);
    handlers.set(event, existing);
  };
  const canvas = {
    width: 800, height: 600, clientWidth: 800, clientHeight: 600,
    style: { cursor: '' },
    addEventListener: vi.fn(), removeEventListener: vi.fn(),
  };
  return {
    fakeMap: {
      isStyleLoaded: vi.fn(() => true),
      on: vi.fn(listen),
      off: vi.fn((event: string, handler: (payload?: unknown) => void) => {
        handlers.get(event)?.delete(handler);
      }),
      once: vi.fn(listen),
      setTransformRequest: vi.fn(),
      getLayer: vi.fn(() => ({ id: 'x' })),
      getSource: vi.fn(() => null),
      getStyle: vi.fn(() => ({ version: 8, sources: {}, layers: [] })),
      queryRenderedFeatures: vi.fn(() => []),
      getCanvas: vi.fn(() => canvas),
      getZoom: vi.fn(() => 5),
      setMissingStyleImageResolver: vi.fn(),
      setLayoutProperty: vi.fn(),
      setTerrain: vi.fn(),
      triggerRepaint: vi.fn(),
    },
  };
});

vi.mock('@vis.gl/react-maplibre', async () => {
  const React = await import('react');
  return {
    Map: ({ children, onLoad }: { children?: ReactNode; onLoad?: (e: { target: unknown }) => void }) => {
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
  useTileConfig: () => ({ data: { cdn_base_url: null, mvt_source_layer_prefix: 'data' } }),
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
  isViewerTerrainExpected: () => false,
}));
vi.mock('@/components/map/MapCoordReadout', () => ({ MapCoordReadout: () => null }));
vi.mock('@/api/geojson-z', async (importOriginal) => ({
  ...await importOriginal<typeof import('@/api/geojson-z')>(),
  fetchBoundedGeoJson: vi.fn(async () => ({ type: 'FeatureCollection', features: [], truncated: false, total_count: 0 })),
}));
vi.mock('@/components/builder/map-composition-sync', async (importOriginal) => ({
  ...await importOriginal<typeof import('@/components/builder/map-composition-sync')>(),
  applyMapBasemapAppearance: vi.fn(),
  syncMapComposition: vi.fn(),
}));

const NUMERIC_FILTER = ['>', ['get', 'pop'], 100] as FilterSpecification;

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
  layout: { visibility: 'visible', _minzoom: 4, _maxzoom: 16 },
  filter: NUMERIC_FILTER,
  label_config: null,
  popup_config: null,
  style_config: null,
  tile_url: '',
};

function viewer(visibleLayers: Set<string>) {
  return (
    <ViewerMap
      layers={[LAYER]}
      basemapStyle={BLANK_BASEMAP_ID}
      initialViewState={{ center_lng: 0, center_lat: 0, zoom: 2, bearing: 0, pitch: 0 }}
      visibleLayers={visibleLayers}
    />
  );
}

describe('ViewerMap visibility toggle', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('hands the adapter a layout without private keys and a sanitised filter', async () => {
    const received = vi.spyOn(circleAdapter, 'syncVisibility');
    const { rerender } = render(viewer(new Set(['pt-layer'])));
    rerender(viewer(new Set()));

    await waitFor(() => {
      expect(received).toHaveBeenCalledWith(mapState.fakeMap, expect.objectContaining({ visible: false }));
    });
    const input: AdapterLayerInput = received.mock.calls.at(-1)![1];
    expect(input.layout).toEqual({ visibility: 'visible' });
    expect(input.filter).toEqual(sanitizeNullableNumericFilter(NUMERIC_FILTER));
  });
});

describe('viewer sources', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('fits a shared layer\'s vector source to its dataset extent', () => {
    vi.spyOn(fillAdapter, 'addLayers').mockImplementation(() => {});
    const { id } = SAVED_LAYERS.polygon;
    const shared = toSharedLayer(SAVED_LAYERS.polygon);
    const map = {
      getSource: vi.fn(() => undefined),
      addSource: vi.fn(),
      getLayer: vi.fn(() => undefined),
      getStyle: vi.fn(() => ({ layers: [] })),
      setLayerZoomRange: vi.fn(),
      setLayoutProperty: vi.fn(),
    } as unknown as MaplibreMap;

    syncLayersToMap(
      map,
      [toViewerSyncInput(shared, id, new Set([id]))],
      new Map(),
      undefined,
      { current: new Set() },
      { current: '' },
      undefined,
      { idPrefix: 'viewer-', mvtSourceLayerPrefix: 'data' },
    );

    expect(map.addSource).toHaveBeenCalledWith(
      'viewer-source-data-parcels',
      expect.objectContaining({ bounds: [-74.1, 40.6, -73.8, 40.9] }),
    );
  });

  it('fetches bounded GeoJSON for a cluster layer and not for a small 3D layer', async () => {
    const small3d = toSharedLayer({
      ...SAVED_LAYERS.polygon,
      id: 'layer-3d',
      dataset_id: 'dataset-3d',
      is_3d: true,
      dataset_feature_count: 100,
    });
    const cluster = toSharedLayer(SAVED_LAYERS.boundedCluster);
    render(
      <ViewerMap
        layers={[small3d, cluster]}
        basemapStyle={BLANK_BASEMAP_ID}
        initialViewState={{ center_lng: 0, center_lat: 0, zoom: 2, bearing: 0, pitch: 0 }}
        visibleLayers={new Set(['layer-3d', SAVED_LAYERS.boundedCluster.id])}
      />,
    );

    await waitFor(() => expect(fetchBoundedGeoJson).toHaveBeenCalledWith(cluster.dataset_id, expect.anything()));
    expect(fetchBoundedGeoJson).not.toHaveBeenCalledWith(small3d.dataset_id, expect.anything());
  });
});
