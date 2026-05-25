import type { Map as MaplibreMap } from 'maplibre-gl';
import type { MapBasemapConfig } from '@/types/api';
import { applySublayerOverrides } from '@/lib/builder/basemap-style-mutation';
import {
  applyBasemapConfigToMap,
  reorderBasemapAboveData,
  reorderBasemapLabels,
  reorderDataLayers,
  syncLayersToMap,
  type SyncLayerInput,
} from '../map-sync';
import { applyMapBasemapAppearance, syncMapComposition } from '../map-composition-sync';

vi.mock('../map-sync', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../map-sync')>();
  return {
    ...actual,
    applyBasemapConfigToMap: vi.fn(),
    reorderBasemapAboveData: vi.fn(),
    reorderBasemapLabels: vi.fn(),
    reorderDataLayers: vi.fn(),
    syncLayersToMap: vi.fn(),
  };
});

vi.mock('@/lib/builder/basemap-style-mutation', () => ({
  applySublayerOverrides: vi.fn(),
}));

const syncLayersToMapMock = vi.mocked(syncLayersToMap);
const applyBasemapConfigToMapMock = vi.mocked(applyBasemapConfigToMap);
const applySublayerOverridesMock = vi.mocked(applySublayerOverrides);
const reorderBasemapLabelsMock = vi.mocked(reorderBasemapLabels);
const reorderDataLayersMock = vi.mocked(reorderDataLayers);
const reorderBasemapAboveDataMock = vi.mocked(reorderBasemapAboveData);

function map(styleLoaded = true) {
  return {
    isStyleLoaded: vi.fn(() => styleLoaded),
  } as unknown as MaplibreMap;
}

function layer(id = 'layer-1'): SyncLayerInput {
  return {
    id,
    dataset_id: `dataset-${id}`,
    dataset_table_name: `table_${id}`,
    dataset_geometry_type: 'LINESTRING',
    opacity: 1,
    visible: true,
    paint: {},
    layout: {},
    filter: null,
  };
}

describe('map composition sync', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('syncs layers before applying basemap appearance and caller callbacks', () => {
    const callOrder: string[] = [];
    syncLayersToMapMock.mockImplementation(() => { callOrder.push('layers'); });
    reorderBasemapLabelsMock.mockImplementation(() => { callOrder.push('labels'); });
    applyBasemapConfigToMapMock.mockImplementation(() => { callOrder.push('basemap-config'); });
    applySublayerOverridesMock.mockImplementation(() => { callOrder.push('sublayer-overrides'); });
    reorderDataLayersMock.mockImplementation(() => { callOrder.push('data-restack'); });
    reorderBasemapAboveDataMock.mockImplementation(() => { callOrder.push('basemap-position'); });

    const basemapConfig: MapBasemapConfig = {
      label_mode: 'subtle',
      road_visibility: 'full',
      boundary_visibility: 'full',
      building_visibility: true,
      land_water_tone: 'default',
      relief_contrast: null,
      basemap_position: 'top',
      sublayer_overrides: {
        road: { opacity: 0.5 },
      },
    };
    const layers = [layer('roads')];
    const tokenMap = new Map();
    const managedSourcesRef = { current: new Set<string>() };
    const orderKeyRef = { current: '' };

    syncMapComposition({
      map: map(),
      layers,
      tokenMap,
      tileBaseUrl: '/tiles',
      managedSourcesRef,
      orderKeyRef,
      syncOptions: { idPrefix: 'viewer-', showBasemapLabels: false },
      basemapConfig,
      showBasemapLabels: false,
      afterSync: () => { callOrder.push('after'); },
    });

    expect(syncLayersToMapMock).toHaveBeenCalledWith(
      expect.anything(),
      layers,
      tokenMap,
      '/tiles',
      managedSourcesRef,
      orderKeyRef,
      undefined,
      { idPrefix: 'viewer-', showBasemapLabels: false, basemapPosition: 'top' },
    );
    expect(applyBasemapConfigToMapMock).toHaveBeenCalledWith(
      expect.anything(),
      basemapConfig,
      false,
      'viewer-source-',
    );
    expect(applySublayerOverridesMock).toHaveBeenCalledWith(
      expect.anything(),
      basemapConfig.sublayer_overrides,
      'viewer-source-',
    );
    expect(reorderDataLayersMock).toHaveBeenCalledWith(expect.anything(), layers, 'viewer-');
    expect(callOrder).toEqual([
      'layers',
      'labels',
      'basemap-config',
      'sublayer-overrides',
      'data-restack',
      'basemap-position',
      'after',
    ]);
  });

  it('lets sublayer override retry logic handle unloaded styles', () => {
    const basemapConfig: MapBasemapConfig = {
      label_mode: 'full',
      road_visibility: 'full',
      boundary_visibility: 'full',
      building_visibility: true,
      land_water_tone: 'default',
      relief_contrast: null,
      sublayer_overrides: {
        label: { opacity: 0.4 },
      },
    };

    applyMapBasemapAppearance({
      map: map(false),
      basemapConfig,
      idPrefix: 'viewer-',
    });

    expect(applySublayerOverridesMock).toHaveBeenCalledWith(
      expect.anything(),
      basemapConfig.sublayer_overrides,
      'viewer-source-',
    );
    expect(applyBasemapConfigToMapMock).not.toHaveBeenCalled();
    expect(reorderBasemapLabelsMock).not.toHaveBeenCalled();
    expect(reorderDataLayersMock).not.toHaveBeenCalled();
    expect(reorderBasemapAboveDataMock).not.toHaveBeenCalled();
  });
});
