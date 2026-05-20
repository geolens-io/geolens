import type { ReactNode } from 'react';
import { render, screen, waitFor } from '@/test/test-utils';
import { ViewerMap } from '../ViewerMap';
import { applyBasemapConfigToMap, syncLayersToMap } from '@/components/builder/map-sync';
import { applySublayerOverrides } from '@/lib/builder/basemap-style-mutation';
import { fetchBoundedGeoJson } from '@/api/geojson-z';
import type { MapBasemapConfig, SharedLayerResponse } from '@/types/api';

type FakeMap = {
  isStyleLoaded: ReturnType<typeof vi.fn>;
  on: ReturnType<typeof vi.fn>;
  off: ReturnType<typeof vi.fn>;
  once: ReturnType<typeof vi.fn>;
  setTransformRequest: ReturnType<typeof vi.fn>;
  getLayer: ReturnType<typeof vi.fn>;
  getSource: ReturnType<typeof vi.fn>;
  queryRenderedFeatures: ReturnType<typeof vi.fn>;
  getCanvas: ReturnType<typeof vi.fn>;
  getZoom: ReturnType<typeof vi.fn>;
  easeTo: ReturnType<typeof vi.fn>;
  setLayoutProperty: ReturnType<typeof vi.fn>;
  triggerRepaint: ReturnType<typeof vi.fn>;
  emit: (event: string, payload?: unknown) => void;
};

const mapState = vi.hoisted(() => {
  const handlers = new Map<string, Set<(payload?: unknown) => void>>();
  const canvas = {
    width: 800,
    height: 600,
    clientWidth: 800,
    clientHeight: 600,
    style: { cursor: '' },
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  };
  const fakeMap: FakeMap = {
    isStyleLoaded: vi.fn(() => true),
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
    getLayer: vi.fn(() => false),
    getSource: vi.fn(() => null),
    queryRenderedFeatures: vi.fn(() => []),
    getCanvas: vi.fn(() => canvas),
    getZoom: vi.fn(() => 5),
    easeTo: vi.fn(),
    setLayoutProperty: vi.fn(),
    triggerRepaint: vi.fn(),
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
      fakeMap.isStyleLoaded.mockClear();
      fakeMap.on.mockClear();
      fakeMap.off.mockClear();
      fakeMap.once.mockClear();
      fakeMap.setTransformRequest.mockClear();
      fakeMap.getLayer.mockClear();
      fakeMap.getSource.mockClear();
      fakeMap.queryRenderedFeatures.mockClear();
      fakeMap.getCanvas.mockClear();
      fakeMap.getZoom.mockClear();
      fakeMap.easeTo.mockClear();
      fakeMap.setLayoutProperty.mockClear();
      fakeMap.triggerRepaint.mockClear();
      canvas.style.cursor = '';
      canvas.addEventListener.mockClear();
      canvas.removeEventListener.mockClear();
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
    FullscreenControl: () => null,
    AttributionControl: () => null,
    TerrainControl: () => null,
    Popup: ({ children }: { children?: ReactNode }) => <div data-testid="feature-popup">{children}</div>,
  };
});

vi.mock('@/hooks/use-settings', () => ({
  useBasemaps: () => ({ data: [] }),
  useTileConfig: () => ({ data: { cdn_base_url: null } }),
}));

vi.mock('@/hooks/use-webgl-recovery', () => ({
  useWebGLRecovery: () => ({ contextLost: false, reload: vi.fn() }),
}));

vi.mock('@/components/viewer/hooks/use-viewer-tokens', () => ({
  useViewerTokens: () => ({ tokenMap: new Map() }),
}));

vi.mock('@/components/viewer/hooks/use-viewer-terrain', () => ({
  useViewerTerrain: () => ({ terrainReady: false, reseedTerrainOnStyleLoad: vi.fn() }),
}));

vi.mock('@/components/map/MapCoordReadout', () => ({
  MapCoordReadout: () => null,
}));

vi.mock('@/components/builder/map-sync', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/components/builder/map-sync')>();
  return {
    ...actual,
    applyBasemapConfigToMap: vi.fn(),
    syncLayersToMap: vi.fn(),
  };
});

vi.mock('@/lib/builder/basemap-style-mutation', () => ({
  applySublayerOverrides: vi.fn(),
}));

vi.mock('@/api/geojson-z', () => ({
  fetchBoundedGeoJson: vi.fn(async () => ({
    type: 'FeatureCollection',
    features: [
      {
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [0, 0] },
        properties: { name: 'A' },
      },
    ],
    total_count: 1,
    truncated: false,
  })),
  asFeatureCollection: (data: GeoJSON.FeatureCollection & { features: GeoJSON.Feature[] }) => ({
    type: 'FeatureCollection',
    features: data.features,
  }),
}));

const applyBasemapConfigToMapMock = vi.mocked(applyBasemapConfigToMap);
const applySublayerOverridesMock = vi.mocked(applySublayerOverrides);
const syncLayersToMapMock = vi.mocked(syncLayersToMap);
const fetchBoundedGeoJsonMock = vi.mocked(fetchBoundedGeoJson);

const BASEMAP_CONFIG: MapBasemapConfig = {
  label_mode: 'subtle',
  road_visibility: 'hidden',
  boundary_visibility: 'subtle',
  building_visibility: false,
  land_water_tone: 'monochrome',
  relief_contrast: 'strong',
};

const BASEMAP_CONFIG_WITH_OVERRIDES: MapBasemapConfig = {
  ...BASEMAP_CONFIG,
  sublayer_overrides: {
    road: {
      stroke_color: '#ff0000',
      stroke_width: 2,
      min_zoom: 5,
      max_zoom: 18,
    },
    boundary: {
      casing_color: '#000000',
      casing_width: 1,
    },
    building: {
      opacity: 0.5,
    },
  },
};

function renderViewer(config: MapBasemapConfig | null = BASEMAP_CONFIG, showBasemapLabels = true) {
  return render(
    <ViewerMap
      layers={[]}
      basemapStyle="openfreemap-positron"
      basemapConfig={config}
      showBasemapLabels={showBasemapLabels}
      terrainConfig={null}
      initialViewState={{
        center_lng: 0,
        center_lat: 0,
        zoom: 2,
        bearing: 0,
        pitch: 0,
      }}
      visibleLayers={new Set()}
    />,
  );
}

describe('ViewerMap basemap config runtime', () => {
  beforeEach(() => {
    mapState.reset();
    applyBasemapConfigToMapMock.mockClear();
    applySublayerOverridesMock.mockClear();
    syncLayersToMapMock.mockClear();
    fetchBoundedGeoJsonMock.mockClear();
  });

  it('applies representative basemap config after load, style reload, and runtime changes', async () => {
    const { rerender } = renderViewer();

    await waitFor(() => {
      expect(applyBasemapConfigToMapMock).toHaveBeenCalledWith(
        mapState.fakeMap,
        BASEMAP_CONFIG,
        true,
        'viewer-source-',
      );
    });

    applyBasemapConfigToMapMock.mockClear();
    mapState.fakeMap.emit('style.load');

    expect(applyBasemapConfigToMapMock).toHaveBeenCalledWith(
      mapState.fakeMap,
      BASEMAP_CONFIG,
      true,
      'viewer-source-',
    );

    const changedConfig: MapBasemapConfig = {
      ...BASEMAP_CONFIG,
      label_mode: 'hidden',
      road_visibility: 'subtle',
      land_water_tone: 'contrast',
    };
    applyBasemapConfigToMapMock.mockClear();
    rerender(
      <ViewerMap
        layers={[]}
        basemapStyle="openfreemap-positron"
        basemapConfig={changedConfig}
        showBasemapLabels={false}
        terrainConfig={null}
        initialViewState={{
          center_lng: 0,
          center_lat: 0,
          zoom: 2,
          bearing: 0,
          pitch: 0,
        }}
        visibleLayers={new Set()}
      />,
    );

    await waitFor(() => {
      expect(applyBasemapConfigToMapMock).toHaveBeenCalledWith(
        mapState.fakeMap,
        changedConfig,
        false,
        'viewer-source-',
      );
    });
  });

  it('applies sublayer_overrides after initial style load (Phase 1059 BSE-01)', async () => {
    renderViewer(BASEMAP_CONFIG_WITH_OVERRIDES);
    await waitFor(() => {
      expect(applySublayerOverridesMock).toHaveBeenCalledWith(
        mapState.fakeMap,
        BASEMAP_CONFIG_WITH_OVERRIDES.sublayer_overrides,
        'viewer-source-',
      );
    });
  });

  it('reapplies sublayer_overrides on style.load reload', async () => {
    renderViewer(BASEMAP_CONFIG_WITH_OVERRIDES);
    await waitFor(() => {
      expect(applySublayerOverridesMock).toHaveBeenCalled();
    });
    applySublayerOverridesMock.mockClear();
    mapState.fakeMap.emit('style.load');
    expect(applySublayerOverridesMock).toHaveBeenCalledWith(
      mapState.fakeMap,
      BASEMAP_CONFIG_WITH_OVERRIDES.sublayer_overrides,
      'viewer-source-',
    );
  });

  it('passes updated overrides on runtime basemapConfig change', async () => {
    const { rerender } = renderViewer(BASEMAP_CONFIG_WITH_OVERRIDES);
    await waitFor(() => {
      expect(applySublayerOverridesMock).toHaveBeenCalled();
    });
    applySublayerOverridesMock.mockClear();
    const changedConfig: MapBasemapConfig = {
      ...BASEMAP_CONFIG_WITH_OVERRIDES,
      sublayer_overrides: {
        road: { stroke_color: '#00ff00', stroke_width: 5 },
      },
    };
    rerender(
      <ViewerMap
        layers={[]}
        basemapStyle="openfreemap-positron"
        basemapConfig={changedConfig}
        showBasemapLabels={true}
        terrainConfig={null}
        initialViewState={{ center_lng: 0, center_lat: 0, zoom: 2, bearing: 0, pitch: 0 }}
        visibleLayers={new Set()}
      />,
    );
    await waitFor(() => {
      expect(applySublayerOverridesMock).toHaveBeenCalledWith(
        mapState.fakeMap,
        changedConfig.sublayer_overrides,
        'viewer-source-',
      );
    });
  });

  it('legacy basemap_config without sublayer_overrides passes null (zero-migration backward compat)', async () => {
    // ROADMAP.md Phase 1059 Acceptance Criterion 4: legacy saved maps without
    // sublayer_overrides continue to render with default basemap styling.
    renderViewer(BASEMAP_CONFIG); // no sublayer_overrides field
    await waitFor(() => {
      expect(applySublayerOverridesMock).toHaveBeenCalled();
    });
    const lastCall = applySublayerOverridesMock.mock.calls.at(-1);
    expect(lastCall?.[0]).toBe(mapState.fakeMap);
    // Plan B wire-up: `basemapConfig?.sublayer_overrides ?? null` — legacy configs
    // without the field produce null here.
    expect(lastCall?.[1]).toBeNull();
    expect(lastCall?.[2]).toBe('viewer-source-');
  });

  it('null basemapConfig still calls helper with null overrides (graceful no-op)', async () => {
    renderViewer(null);
    await waitFor(() => {
      // Helper invoked even with null basemapConfig because the call site is
      // unconditional after applyBasemapConfigToMap. Helper itself short-circuits
      // on null/undefined overrides per Plan B Task 2.
      expect(applySublayerOverridesMock).toHaveBeenCalled();
    });
    const lastCall = applySublayerOverridesMock.mock.calls.at(-1);
    expect(lastCall?.[1]).toBeNull();
  });

  it('syncs duplicate sort-order layers with stable viewer layer IDs', async () => {
    const duplicateOrderLayers: SharedLayerResponse[] = [
      {
        id: 'layer-a',
        dataset_id: 'dataset-a',
        dataset_name: 'First copy',
        display_name: 'First copy',
        table_name: 'first_copy',
        geometry_type: 'POINT',
        column_info: null,
        sort_order: 0,
        visible: true,
        opacity: 1,
        paint: {},
        layout: {},
        filter: null,
        label_config: null,
        popup_config: null,
        style_config: null,
        tile_url: '',
      },
      {
        id: 'layer-b',
        dataset_id: 'dataset-b',
        dataset_name: 'Second copy',
        display_name: 'Second copy',
        table_name: 'second_copy',
        geometry_type: 'POINT',
        column_info: null,
        sort_order: 0,
        visible: true,
        opacity: 1,
        paint: {},
        layout: {},
        filter: null,
        label_config: null,
        popup_config: null,
        style_config: null,
        tile_url: '',
      },
    ];

    render(
      <ViewerMap
        layers={duplicateOrderLayers}
        basemapStyle="openfreemap-positron"
        basemapConfig={null}
        showBasemapLabels={true}
        terrainConfig={null}
        initialViewState={{
          center_lng: 0,
          center_lat: 0,
          zoom: 2,
          bearing: 0,
          pitch: 0,
        }}
        visibleLayers={new Set()}
        embedToken="embed-token"
      />,
    );

    await waitFor(() => {
      expect(syncLayersToMapMock).toHaveBeenCalled();
    });

    const syncInputs = syncLayersToMapMock.mock.calls.at(-1)?.[1];
    expect(syncInputs?.map((layer) => layer.id)).toEqual(['layer-a', 'layer-b']);
  });

  it('syncs eligible shared cluster layers after bounded GeoJSON data arrives', async () => {
    const clusterLayers: SharedLayerResponse[] = [
      {
        id: 'cluster-layer',
        dataset_id: 'dataset-cluster',
        dataset_name: 'Stops',
        display_name: 'Stops',
        table_name: 'stops',
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
        style_config: {
          render_mode: 'cluster',
          builder: {
            clusterRadius: 64,
            clusterMaxZoom: 12,
          },
        } as SharedLayerResponse['style_config'],
        tile_url: '',
        feature_count: 1,
      },
    ];

    render(
      <ViewerMap
        layers={clusterLayers}
        basemapStyle="openfreemap-positron"
        basemapConfig={null}
        showBasemapLabels={true}
        terrainConfig={null}
        initialViewState={{
          center_lng: 0,
          center_lat: 0,
          zoom: 2,
          bearing: 0,
          pitch: 0,
        }}
        visibleLayers={new Set(['cluster-layer'])}
        embedToken="embed-token"
      />,
    );

    await waitFor(() => {
      expect(fetchBoundedGeoJsonMock).toHaveBeenCalledWith('dataset-cluster', {
        apiKey: undefined,
        embedToken: 'embed-token',
      });
    });
    await waitFor(() => {
      const geojsonDataMap = syncLayersToMapMock.mock.calls.at(-1)?.[6];
      expect(geojsonDataMap?.get('cluster-layer')).toMatchObject({
        type: 'FeatureCollection',
        features: [expect.objectContaining({ type: 'Feature' })],
      });
    });
  });

  it('does not fetch bounded GeoJSON for large shared cluster layers', async () => {
    const largeClusterLayers: SharedLayerResponse[] = [
      {
        id: 'large-cluster-layer',
        dataset_id: 'dataset-large-cluster',
        dataset_name: 'Large Stops',
        display_name: 'Large Stops',
        table_name: 'large_stops',
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
        style_config: {
          render_mode: 'cluster',
          builder: {
            clusterRadius: 64,
            clusterMaxZoom: 12,
          },
        } as SharedLayerResponse['style_config'],
        tile_url: '',
        feature_count: 20_000,
      },
    ];

    render(
      <ViewerMap
        layers={largeClusterLayers}
        basemapStyle="openfreemap-positron"
        basemapConfig={null}
        showBasemapLabels={true}
        terrainConfig={null}
        initialViewState={{
          center_lng: 0,
          center_lat: 0,
          zoom: 2,
          bearing: 0,
          pitch: 0,
        }}
        visibleLayers={new Set(['large-cluster-layer'])}
        embedToken="embed-token"
      />,
    );

    await waitFor(() => {
      expect(syncLayersToMapMock).toHaveBeenCalled();
    });

    expect(fetchBoundedGeoJsonMock).not.toHaveBeenCalled();
    const syncInputs = syncLayersToMapMock.mock.calls.at(-1)?.[1];
    expect(syncInputs?.[0]).toMatchObject({
      id: 'large-cluster-layer',
      feature_count: 20_000,
      style_config: expect.objectContaining({ render_mode: 'cluster' }),
    });
  });

  it('queries cluster companion layers and zooms from server cluster clicks', async () => {
    const largeClusterLayers: SharedLayerResponse[] = [
      {
        id: 'large-cluster-layer',
        dataset_id: 'dataset-large-cluster',
        dataset_name: 'Large Stops',
        display_name: 'Large Stops',
        table_name: 'large_stops',
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
        style_config: {
          render_mode: 'cluster',
          builder: {
            clusterRadius: 64,
            clusterMaxZoom: 12,
          },
        } as SharedLayerResponse['style_config'],
        tile_url: '',
        feature_count: 20_000,
      },
    ];
    const clusterFeature = {
      layer: { id: 'viewer-layer-large-cluster-layer-cluster' },
      properties: {
        point_count: 20_000,
        point_count_abbreviated: '20k',
        expansion_zoom: 9,
        cluster_id: '8:11:22:0',
      },
      geometry: { type: 'Point', coordinates: [-73.9, 40.7] },
    };
    mapState.fakeMap.getLayer.mockImplementation((id: string) => [
      'viewer-layer-large-cluster-layer-cluster',
      'viewer-layer-large-cluster-layer-cluster-count',
      'viewer-layer-large-cluster-layer',
    ].includes(id));
    mapState.fakeMap.queryRenderedFeatures.mockReturnValue([clusterFeature]);

    render(
      <ViewerMap
        layers={largeClusterLayers}
        basemapStyle="openfreemap-positron"
        basemapConfig={null}
        showBasemapLabels={true}
        terrainConfig={null}
        initialViewState={{
          center_lng: 0,
          center_lat: 0,
          zoom: 2,
          bearing: 0,
          pitch: 0,
        }}
        visibleLayers={new Set(['large-cluster-layer'])}
        embedToken="embed-token"
      />,
    );

    await waitFor(() => {
      expect(mapState.fakeMap.on).toHaveBeenCalledWith('click', expect.any(Function));
    });

    mapState.fakeMap.emit('click', {
      point: { x: 100, y: 100 },
      lngLat: { lng: -73.9, lat: 40.7 },
    });

    await waitFor(() => {
      expect(mapState.fakeMap.easeTo).toHaveBeenCalledWith({
        center: [-73.9, 40.7],
        zoom: 9,
        duration: 500,
      });
    });
    expect(mapState.fakeMap.queryRenderedFeatures).toHaveBeenCalledWith(
      { x: 100, y: 100 },
      {
        layers: expect.arrayContaining([
          'viewer-layer-large-cluster-layer-cluster',
          'viewer-layer-large-cluster-layer-cluster-count',
          'viewer-layer-large-cluster-layer',
        ]),
      },
    );
    expect(screen.getByText('Cluster: 20,000 features')).toBeInTheDocument();
    expect(screen.getByText('Server-side cluster tile')).toBeInTheDocument();
  });
});
