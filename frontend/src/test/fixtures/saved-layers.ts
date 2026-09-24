import type { MapLayerResponse, SharedLayerResponse } from '@/types/api';

/** A saved layer in the builder's response shape, with vector polygon defaults. */
export function savedLayer(overrides: Partial<MapLayerResponse> = {}): MapLayerResponse {
  return {
    id: 'layer-1',
    dataset_id: 'dataset-1',
    dataset_name: 'Dataset 1',
    dataset_geometry_type: 'MULTIPOLYGON',
    dataset_table_name: 'dataset_1',
    dataset_extent_bbox: [-74.1, 40.6, -73.8, 40.9],
    dataset_column_info: null,
    dataset_feature_count: 100,
    dataset_sample_values: null,
    display_name: 'Layer 1',
    sort_order: 0,
    visible: true,
    opacity: 1,
    paint: {},
    layout: {},
    filter: null,
    label_config: null,
    popup_config: null,
    style_config: null,
    layer_type: 'vector_geolens',
    dataset_record_type: 'vector_dataset',
    show_in_legend: true,
    ...overrides,
  };
}

function vectorLayer(key: string, name: string, geometry: string, overrides: Partial<MapLayerResponse> = {}) {
  return savedLayer({
    id: `layer-${key}`,
    dataset_id: `dataset-${key}`,
    dataset_name: `${name} dataset`,
    dataset_table_name: key.replace(/-/g, '_'),
    dataset_geometry_type: geometry,
    display_name: name,
    ...overrides,
  });
}

function rasterLayer(key: string, name: string, overrides: Partial<MapLayerResponse> = {}) {
  return savedLayer({
    id: `layer-${key}`,
    dataset_id: `dataset-${key}`,
    dataset_name: `${name} dataset`,
    dataset_table_name: key.replace(/-/g, '_'),
    dataset_geometry_type: null,
    dataset_feature_count: null,
    display_name: name,
    layer_type: 'raster_geolens',
    dataset_record_type: 'raster_dataset',
    ...overrides,
  });
}

const zoneMatch = ['match', ['get', 'zone'], 'R', '#66c2a5', 'C', '#fc8d62', 'I', '#8da0cb', '#cccccc'];
const kindMatch = ['match', ['get', 'kind'], 'school', '#f472b6', 'clinic', '#60a5fa', '#cccccc'];

/** One saved layer per adapter branch and legend edge case. */
export const SAVED_LAYERS = {
  polygon: vectorLayer('parcels', 'Parcels', 'MULTIPOLYGON', {
    paint: { 'fill-color': '#3b82f6' },
  }),
  strokeOnlyPolygon: vectorLayer('flood-zones', 'Flood zones', 'MULTIPOLYGON', {
    paint: { 'fill-color': '#0ea5e9', 'fill-opacity': 0 },
    style_config: { builder: { fillDisabled: true, fillOpacitySaved: 0.4, outlineColor: '#0369a1', outlineWidth: 2 } },
  }),
  // The paint mirror still says the stroke is off; builder state turned it back on.
  staleMirrorPolygon: vectorLayer('wetlands', 'Wetlands', 'MULTIPOLYGON', {
    paint: { 'fill-color': '#22c55e', '_stroke-disabled': true, '_outline-color': '#000000' },
    style_config: { builder: { strokeDisabled: false, outlineColor: '#15803d', outlineWidth: 1.5 } },
  }),
  patternedPolygon: vectorLayer('parks', 'Parks', 'MULTIPOLYGON', {
    paint: { 'fill-pattern': 'geolens-fill-hatch', 'fill-opacity': 0.8 },
    style_config: { builder: { fillColorSaved: '#16a34a' } },
  }),
  extrusion: vectorLayer('buildings', 'Buildings', 'MULTIPOLYGON', {
    dataset_column_info: [{ name: 'height_m', type: 'double precision' }],
    paint: { 'fill-color': '#f97316', 'fill-opacity': 0.6 },
    style_config: { builder: { heightColumn: 'height_m', heightScale: 1, extrusionMinZoom: 14 } },
  }),
  line: vectorLayer('roads', 'Roads', 'MULTILINESTRING', {
    paint: { 'line-color': '#ef4444', 'line-width': 2 },
  }),
  dashedLine: vectorLayer('trails', 'Trails', 'MULTILINESTRING', {
    paint: { 'line-color': '#a16207', 'line-width': 1.5, 'line-dasharray': [4, 2] },
  }),
  arrowLine: vectorLayer('flow-lines', 'Flow lines', 'MULTILINESTRING', {
    paint: { 'line-color': '#2563eb', 'line-width': 2 },
    layout: { 'line-cap': 'round', 'line-join': 'round' },
    style_config: { render_mode: 'arrow', builder: { arrowColor: '#1e3a8a', arrowSize: 14, arrowSpacing: 80 } },
  }),
  point: vectorLayer('wells', 'Wells', 'MULTIPOINT', {
    paint: { 'circle-radius': 5, 'circle-color': '#3b82f6', 'circle-stroke-color': '#1d4ed8', 'circle-stroke-width': 1 },
  }),
  ringlessPoint: vectorLayer('earthquakes', 'Earthquakes', 'MULTIPOINT', {
    paint: { 'circle-radius': 6, 'circle-color': '#f59e0b' },
  }),
  categorical: vectorLayer('zoning', 'Zoning', 'MULTIPOLYGON', {
    paint: { 'fill-color': ['case', ['==', ['get', 'zone'], null], '#cccccc', zoneMatch], 'fill-opacity': 0.7 },
    style_config: {
      mode: 'categorical',
      column: 'zone',
      ramp: 'Set2',
      categories: [
        { value: 'R', label: 'Residential', color: '#66c2a5' },
        { value: 'C', label: 'Commercial', color: '#fc8d62' },
        { value: 'I', label: 'Industrial', color: '#8da0cb' },
      ],
    },
  }),
  graduatedColor: vectorLayer('tracts', 'Tracts', 'MULTIPOLYGON', {
    paint: {
      'fill-color': ['case', ['==', ['get', 'pop'], null], '#cccccc', ['step', ['get', 'pop'], '#fee8c8', 1000, '#fdbb84', 5000, '#e34a33']],
    },
    style_config: {
      mode: 'graduated',
      column: 'pop',
      target: 'color',
      ramp: 'OrRd',
      classCount: 3,
      method: 'quantile',
      colors: ['#fee8c8', '#fdbb84', '#e34a33'],
      breaks: [1000, 5000],
    },
  }),
  graduatedRadius: vectorLayer('quakes-by-magnitude', 'Quakes by magnitude', 'MULTIPOINT', {
    paint: {
      'circle-color': '#dc2626',
      'circle-radius': ['case', ['==', ['get', 'mag'], null], 0, ['step', ['get', 'mag'], 4, 5, 8, 6, 14]],
    },
    style_config: {
      mode: 'graduated',
      column: 'mag',
      target: 'radius',
      ramp: 'YlOrRd',
      sizes: [4, 8, 14],
      breaks: [5, 6],
      sizeLabel: 'Magnitude',
    },
  }),
  graduatedWidth: vectorLayer('rivers', 'Rivers', 'MULTILINESTRING', {
    paint: {
      'line-color': '#0284c7',
      'line-width': ['case', ['==', ['get', 'flow'], null], 0, ['step', ['get', 'flow'], 1, 10, 3, 100, 6]],
    },
    style_config: {
      mode: 'graduated',
      column: 'flow',
      target: 'width',
      ramp: 'Blues',
      sizes: [1, 3, 6],
      breaks: [10, 100],
    },
  }),
  heatmapByRamp: vectorLayer('incidents', 'Incidents', 'MULTIPOINT', {
    paint: { 'heatmap-radius': 30, 'heatmap-weight': ['get', 'severity'], 'heatmap-intensity': 1, 'heatmap-opacity': 0.8 },
    style_config: {
      mode: 'graduated',
      column: '',
      ramp: 'Blues',
      render_mode: 'heatmap',
      builder: { heatmapRamp: 'Blues', heatmapWeightColumn: 'severity' },
    },
  }),
  reversedHeatmap: vectorLayer('sightings', 'Sightings', 'MULTIPOINT', {
    paint: { 'heatmap-radius': 30, 'heatmap-weight': 1, 'heatmap-intensity': 1, 'heatmap-opacity': 0.8 },
    style_config: {
      mode: 'graduated',
      column: '',
      ramp: 'Viridis',
      render_mode: 'heatmap',
      builder: { heatmapRamp: 'Viridis', heatmapReversed: true },
    },
  }),
  // The stored heatmap-color does not match the builder ramp; the map draws the expression.
  heatmapByExpression: vectorLayer('calls', 'Service calls', 'MULTIPOINT', {
    paint: {
      'heatmap-radius': 30,
      'heatmap-weight': 1,
      'heatmap-intensity': 1,
      'heatmap-opacity': 0.8,
      'heatmap-color': ['interpolate', ['linear'], ['heatmap-density'], 0, 'rgba(0,0,0,0)', 0.5, '#7c3aed', 1, '#f0abfc'],
    },
    style_config: { mode: 'graduated', column: '', ramp: 'YlOrRd', render_mode: 'heatmap', builder: { heatmapRamp: 'YlOrRd' } },
  }),
  boundedCluster: vectorLayer('bike-racks', 'Bike racks', 'MULTIPOINT', {
    dataset_feature_count: 1200,
    paint: { 'circle-radius': 5, 'circle-color': '#0d9488', 'circle-stroke-color': '#134e4a', 'circle-stroke-width': 1 },
    style_config: { render_mode: 'cluster', builder: { clusterColor: '#0d9488', clusterRadius: 48 } },
  }),
  serverCluster: vectorLayer('street-trees', 'Street trees', 'MULTIPOINT', {
    dataset_feature_count: 250_000,
    paint: { 'circle-radius': 4, 'circle-color': '#16a34a' },
    style_config: { render_mode: 'cluster', builder: { clusterColorRamp: [{ count: 0, color: '#bbf7d0' }, { count: 100, color: '#16a34a' }] } },
  }),
  fallbackCluster: vectorLayer('survey-points', 'Survey points', 'MULTIPOINT', {
    dataset_feature_count: null,
    paint: { 'circle-radius': 4, 'circle-color': '#9333ea' },
    style_config: { render_mode: 'cluster' },
  }),
  // Switching a categorical point layer to symbols keeps its classification for the way back.
  symbolWithLeftoverClassification: vectorLayer('facilities', 'Facilities', 'MULTIPOINT', {
    paint: { 'circle-radius': 5, 'circle-color': ['case', ['==', ['get', 'kind'], null], '#cccccc', kindMatch] },
    style_config: {
      render_mode: 'symbol',
      mode: 'categorical',
      column: 'kind',
      categories: [
        { value: 'school', label: 'School', color: '#f472b6' },
        { value: 'clinic', label: 'Clinic', color: '#60a5fa' },
      ],
      symbol: { iconImage: 'marker', iconSize: 1 },
    },
  }),
  mixedGeometry: vectorLayer('sketches', 'Sketches', 'GEOMETRY', {
    paint: { 'fill-color': '#8b5cf6', 'fill-opacity': 0.4 },
  }),
  raster: rasterLayer('orthophoto', 'Orthophoto 2024'),
  hillshadeDem: rasterLayer('relief', 'Elevation relief', {
    is_dem: true,
    paint: { 'hillshade-exaggeration': 0.5 },
    style_config: { render_mode: 'hillshade' },
  }),
  terrainDem: rasterLayer('terrain', 'Elevation (terrain)', {
    is_dem: true,
    style_config: { render_mode: 'terrain' },
  }),
  // Built the way hydrateFolderGroupLayers builds it: the first child's fields under the group's id and name.
  folderRow: {
    ...vectorLayer('transit-stops', 'Transit', 'MULTIPOINT'),
    id: 'group-transit',
    layer_type: 'group:folder',
  } as unknown as MapLayerResponse,
} satisfies Record<string, MapLayerResponse>;

/** The same saved layer in the shared (viewer) response shape, as the server builds it. */
export function toSharedLayer(layer: MapLayerResponse): SharedLayerResponse {
  const isRaster = layer.dataset_record_type === 'raster_dataset' || layer.dataset_record_type === 'vrt_dataset';
  return {
    id: layer.id,
    dataset_id: layer.dataset_id,
    dataset_name: layer.dataset_name,
    display_name: layer.display_name,
    table_name: layer.dataset_table_name,
    geometry_type: layer.dataset_geometry_type,
    column_info: layer.dataset_column_info,
    sort_order: layer.sort_order,
    visible: layer.visible,
    opacity: layer.opacity,
    paint: layer.paint,
    layout: layer.layout,
    filter: layer.filter,
    label_config: layer.label_config ?? null,
    popup_config: layer.popup_config ?? null,
    style_config: layer.style_config ?? null,
    show_in_legend: layer.show_in_legend,
    layer_type: layer.layer_type ?? 'vector_geolens',
    dataset_record_type: layer.dataset_record_type ?? undefined,
    is_dem: layer.is_dem ? true : undefined,
    dem_vertical_units: layer.dem_vertical_units,
    is_3d: layer.is_3d,
    tile_url: isRaster
      ? `/raster-tiles/${layer.dataset_id}/tiles/{z}/{x}/{y}.png`
      : `/tiles/data.${layer.dataset_table_name}/{z}/{x}/{y}.pbf`,
    feature_count: layer.dataset_feature_count,
    tile_version: layer.tile_version,
    dataset_attribution: layer.dataset_attribution,
    dataset_extent_bbox: layer.dataset_extent_bbox,
  };
}

/** The showcase's subway stations: categories that fade in past zoom 12.3. */
export const ZOOM_FADED_STATIONS: MapLayerResponse = savedLayer({
  dataset_geometry_type: 'MULTIPOINT',
  display_name: 'Stations (green = ADA accessible)',
  paint: {
    'circle-radius': ['interpolate', ['linear'], ['zoom'], 12.5, 2.5, 16, 5.5],
    'circle-color': ['match', ['to-number', ['get', 'ada'], 0], 1, '#22c55e', 2, '#a3e635', '#94a3b8'],
    'circle-stroke-color': '#0b0f14',
    'circle-stroke-width': 1,
    'circle-opacity': ['interpolate', ['linear'], ['zoom'], 12.3, 0, 12.9, 0.95],
    'circle-stroke-opacity': ['interpolate', ['linear'], ['zoom'], 12.3, 0, 12.9, 1],
  },
  style_config: {
    mode: 'categorical',
    column: 'ada',
    categories: [
      { value: 1, color: '#22c55e', label: 'ADA accessible' },
      { value: 2, color: '#a3e635', label: 'Partially accessible' },
      { value: 0, color: '#94a3b8', label: 'Not accessible' },
    ],
  },
});
