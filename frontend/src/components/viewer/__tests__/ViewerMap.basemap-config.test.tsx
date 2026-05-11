import type { ReactNode } from 'react';
import { render, waitFor } from '@/test/test-utils';
import { ViewerMap } from '../ViewerMap';
import { applyBasemapConfigToMap, syncLayersToMap } from '@/components/builder/map-sync';
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
  triggerRepaint: ReturnType<typeof vi.fn>;
  emit: (event: string) => void;
};

const mapState = vi.hoisted(() => {
  const handlers = new Map<string, Set<() => void>>();
  const fakeMap: FakeMap = {
    isStyleLoaded: vi.fn(() => true),
    on: vi.fn((event: string, handler: () => void) => {
      const existing = handlers.get(event) ?? new Set();
      existing.add(handler);
      handlers.set(event, existing);
    }),
    off: vi.fn((event: string, handler: () => void) => {
      handlers.get(event)?.delete(handler);
    }),
    once: vi.fn((event: string, handler: () => void) => {
      const wrapped = () => {
        handler();
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
    getCanvas: vi.fn(() => ({ style: { cursor: '' } })),
    triggerRepaint: vi.fn(),
    emit: (event: string) => {
      for (const handler of Array.from(handlers.get(event) ?? [])) {
        handler();
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
      fakeMap.triggerRepaint.mockClear();
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

const applyBasemapConfigToMapMock = vi.mocked(applyBasemapConfigToMap);
const syncLayersToMapMock = vi.mocked(syncLayersToMap);

const BASEMAP_CONFIG: MapBasemapConfig = {
  label_mode: 'subtle',
  road_visibility: 'hidden',
  boundary_visibility: 'subtle',
  building_visibility: false,
  land_water_tone: 'monochrome',
  relief_contrast: 'strong',
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
    syncLayersToMapMock.mockClear();
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
});
