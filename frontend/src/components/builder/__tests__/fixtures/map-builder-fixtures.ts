import { vi } from 'vitest';
import type { Map as MaplibreMap } from 'maplibre-gl';
import type {
  MapBasemapConfig,
  MapLayerResponse,
  MapResponse,
  MapTerrainConfig,
} from '@/types/api';

type BuilderMapOverrides = Omit<Partial<MapResponse>, 'layers'> & {
  layers?: MapLayerResponse[];
  group_meta?: Record<string, { expanded: boolean }>;
};

export function makeBuilderLayer(overrides: Partial<MapLayerResponse> = {}): MapLayerResponse {
  return {
    id: 'layer-1',
    dataset_id: 'ds-1',
    dataset_name: 'Test',
    dataset_geometry_type: 'Polygon',
    dataset_table_name: 'test_table',
    visible: true,
    opacity: 1,
    paint: {},
    layout: {},
    sort_order: 0,
    filter: null,
    display_name: null,
    layer_type: 'vector_geolens',
    dataset_extent_bbox: null,
    dataset_column_info: null,
    dataset_feature_count: null,
    dataset_sample_values: null,
    dataset_record_type: undefined,
    label_config: null,
    popup_config: null,
    style_config: null,
    show_in_legend: true,
    is_dem: false,
    dem_vertical_units: null,
    ...overrides,
  };
}

export function makeBuilderMap(
  layers: MapLayerResponse[] = [],
  overrides: BuilderMapOverrides = {},
): MapResponse {
  const resolvedLayers = overrides.layers ?? layers;
  return {
    id: 'map-1',
    name: 'Test Map',
    description: null,
    notes: null,
    center_lng: 0,
    center_lat: 0,
    zoom: 2,
    bearing: 0,
    pitch: 0,
    basemap_style: 'positron',
    show_basemap_labels: true,
    basemap_config: null,
    terrain_config: null,
    visibility: 'private',
    thumbnail_url: null,
    created_by: null,
    created_by_username: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    layers: resolvedLayers,
    layer_count: resolvedLayers.length,
    forked_from_id: null,
    forked_from_name: null,
    ...overrides,
  } as MapResponse;
}

export function makeBasemapConfig(overrides: Partial<MapBasemapConfig> = {}): MapBasemapConfig {
  return {
    label_mode: 'full',
    road_visibility: 'full',
    boundary_visibility: 'full',
    building_visibility: true,
    land_water_tone: 'default',
    relief_contrast: 'standard',
    opacity: 1,
    background_color: null,
    basemap_position: 'bottom',
    sublayer_overrides: {},
    ...overrides,
  };
}

export function makeTerrainConfig(overrides: Partial<MapTerrainConfig> = {}): MapTerrainConfig {
  return {
    enabled: true,
    source_dataset_id: 'dem-ds-1',
    exaggeration: 1.5,
    ...overrides,
  };
}

export function makeMapLibreMock(
  initial: {
    sources?: string[];
    layers?: string[];
    styleLoaded?: boolean;
  } = {},
): MaplibreMap {
  const sources = new Set(initial.sources ?? []);
  const layers = new Set(initial.layers ?? []);

  return {
    getSource: vi.fn((id: string) =>
      sources.has(id) ? { tiles: ['/tiles/mock/{z}/{x}/{y}.pbf'] } : null,
    ),
    addSource: vi.fn((id: string) => {
      sources.add(id);
    }),
    removeSource: vi.fn((id: string) => {
      sources.delete(id);
    }),
    getLayer: vi.fn((id: string) => (layers.has(id) ? { id } : null)),
    addLayer: vi.fn((layer: { id: string }) => {
      layers.add(layer.id);
    }),
    removeLayer: vi.fn((id: string) => {
      layers.delete(id);
    }),
    setLayoutProperty: vi.fn(),
    setPaintProperty: vi.fn(),
    setFilter: vi.fn(),
    isStyleLoaded: vi.fn(() => initial.styleLoaded ?? true),
    getStyle: vi.fn(() => ({ layers: [] })),
    moveLayer: vi.fn(),
    setLayerZoomRange: vi.fn(),
    fitBounds: vi.fn(),
    on: vi.fn(),
    off: vi.fn(),
    setTransformRequest: vi.fn(),
    resize: vi.fn(),
  } as unknown as MaplibreMap;
}
