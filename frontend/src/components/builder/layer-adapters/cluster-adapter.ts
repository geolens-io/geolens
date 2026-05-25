import type { FilterSpecification, Map as MaplibreMap } from 'maplibre-gl';
import { MAP_COLORS } from '@/lib/map-colors';
import type { AdapterLayerInput, LayerAdapter } from './types';
import {
  filterPaintForLayerType,
  finalizeLayer,
  getBuilderStyleConfig,
  getExpressionSafeOpacity,
  syncOwnedLayoutProperties,
  syncOwnedPaintProperties,
  syncSingleLayerVisibility,
} from './shared';

export function clusterCircleLayerId(layerId: string) {
  return `${layerId}-cluster`;
}

export function clusterCountLayerId(layerId: string) {
  return `${layerId}-cluster-count`;
}

const UNCLUSTERED_OWNED_PAINT_PROPERTIES = [
  'circle-radius',
  'circle-color',
  'circle-blur',
  'circle-opacity',
  'circle-translate',
  'circle-translate-anchor',
  'circle-pitch-scale',
  'circle-pitch-alignment',
  'circle-stroke-width',
  'circle-stroke-color',
  'circle-stroke-opacity',
  'circle-stroke-blur',
] as const;
const CLUSTER_CIRCLE_OWNED_PAINT_PROPERTIES = [
  'circle-color',
  'circle-radius',
  'circle-opacity',
  'circle-stroke-color',
  'circle-stroke-width',
  'circle-stroke-opacity',
] as const;
const CLUSTER_COUNT_OWNED_PAINT_PROPERTIES = [
  'text-color',
  'text-opacity',
  'text-halo-color',
  'text-halo-width',
] as const;
const CLUSTER_COUNT_OWNED_LAYOUT_PROPERTIES = [
  'text-field',
  'text-size',
  'text-font',
  'text-allow-overlap',
  'text-ignore-placement',
  'visibility',
] as const;

function hasFilter(filter: FilterSpecification | null | undefined): filter is FilterSpecification {
  return Array.isArray(filter) && filter.length > 0;
}

function combineFilter(base: FilterSpecification, filter: FilterSpecification | null | undefined): FilterSpecification {
  return hasFilter(filter) ? ['all', base, filter] as FilterSpecification : base;
}

function clusterFilter(input: AdapterLayerInput) {
  return combineFilter(['has', 'point_count'], input.filter);
}

function unclusteredFilter(input: AdapterLayerInput) {
  return combineFilter(['!', ['has', 'point_count']], input.filter);
}

function numericBuilderValue(value: unknown, fallback: number, min: number, max: number) {
  return typeof value === 'number' && Number.isFinite(value)
    ? Math.min(Math.max(value, min), max)
    : fallback;
}

function sourceLayerSpec(input: AdapterLayerInput) {
  return input.sourceType === 'geojson' ? {} : { 'source-layer': input.sourceLayer };
}

export function getClusterSourceOptions(input: AdapterLayerInput) {
  const builder = getBuilderStyleConfig(input);
  return {
    clusterRadius: numericBuilderValue(builder.clusterRadius, 48, 1, 256),
    clusterMaxZoom: numericBuilderValue(builder.clusterMaxZoom, 14, 0, 22),
  };
}

function clusterStyle(input: AdapterLayerInput) {
  const builder = getBuilderStyleConfig(input);
  const pointColor = typeof input.paint['circle-color'] === 'string'
    ? input.paint['circle-color']
    : MAP_COLORS.default.fill;
  const clusterColor = typeof builder.clusterColor === 'string'
    ? builder.clusterColor
    : pointColor;
  const textColor = typeof builder.clusterTextColor === 'string'
    ? builder.clusterTextColor
    : '#ffffff';
  const textSize = numericBuilderValue(builder.clusterTextSize, 12, 8, 24);
  return { clusterColor, textColor, textSize };
}

function unclusteredPointPaint(input: AdapterLayerInput) {
  const circlePaint = filterPaintForLayerType(input.paint, 'circle');
  return Object.keys(circlePaint).length > 0
    ? circlePaint
    : {
        'circle-radius': 5,
        'circle-color': MAP_COLORS.default.fill,
        'circle-stroke-color': MAP_COLORS.default.stroke,
        'circle-stroke-width': 1,
      };
}

function addClusterCircleLayer(map: MaplibreMap, input: AdapterLayerInput) {
  const id = clusterCircleLayerId(input.layerId);
  if (map.getLayer(id)) return;
  const { clusterColor } = clusterStyle(input);

  map.addLayer({
    id,
    type: 'circle',
    source: input.sourceId,
    ...sourceLayerSpec(input),
    filter: clusterFilter(input),
    paint: {
      'circle-color': clusterColor,
      'circle-radius': ['step', ['get', 'point_count'], 16, 100, 21, 750, 27],
      'circle-opacity': input.opacity ?? 1,
      'circle-stroke-color': '#ffffff',
      'circle-stroke-width': 1.5,
      'circle-stroke-opacity': Math.min((input.opacity ?? 1) + 0.1, 1),
    },
    layout: {
      visibility: input.visible ? 'visible' : 'none',
    },
  });
}

function addClusterCountLayer(map: MaplibreMap, input: AdapterLayerInput) {
  const id = clusterCountLayerId(input.layerId);
  if (map.getLayer(id)) return;
  const { textColor, textSize } = clusterStyle(input);

  map.addLayer({
    id,
    type: 'symbol',
    source: input.sourceId,
    ...sourceLayerSpec(input),
    filter: clusterFilter(input),
    layout: {
      'text-field': ['get', 'point_count_abbreviated'],
      'text-size': textSize,
      'text-font': ['Open Sans Semibold', 'Arial Unicode MS Bold'],
      'text-allow-overlap': true,
      'text-ignore-placement': true,
      visibility: input.visible ? 'visible' : 'none',
    },
    paint: {
      'text-color': textColor,
      'text-opacity': input.opacity ?? 1,
      'text-halo-color': 'rgba(0, 0, 0, 0.35)',
      'text-halo-width': 1,
    },
  });
}

function addUnclusteredPointLayer(map: MaplibreMap, input: AdapterLayerInput) {
  if (map.getLayer(input.layerId)) return;
  const hasExpressions = Object.values(input.paint).some(Array.isArray);

  map.addLayer({
    id: input.layerId,
    type: 'circle',
    source: input.sourceId,
    ...sourceLayerSpec(input),
    filter: unclusteredFilter(input),
    paint: unclusteredPointPaint(input),
    layout: {
      ...input.layout,
      visibility: input.visible ? 'visible' : 'none',
    },
  });
  finalizeLayer(map, input.layerId, input.paint, 'circle', input.opacity ?? 1, unclusteredFilter(input), hasExpressions);
}

function syncClusterCircleLayer(map: MaplibreMap, input: AdapterLayerInput) {
  const id = clusterCircleLayerId(input.layerId);
  if (!map.getLayer(id)) return;
  const { clusterColor } = clusterStyle(input);
  syncOwnedPaintProperties(map, id, {
    'circle-color': clusterColor,
    'circle-radius': ['step', ['get', 'point_count'], 16, 100, 21, 750, 27],
    'circle-opacity': input.opacity ?? 1,
    'circle-stroke-color': '#ffffff',
    'circle-stroke-width': 1.5,
    'circle-stroke-opacity': Math.min((input.opacity ?? 1) + 0.1, 1),
  }, { geomType: 'circle', ownedProperties: CLUSTER_CIRCLE_OWNED_PAINT_PROPERTIES });
  map.setFilter(id, clusterFilter(input));
}

function syncClusterCountLayer(map: MaplibreMap, input: AdapterLayerInput) {
  const id = clusterCountLayerId(input.layerId);
  if (!map.getLayer(id)) return;
  const { textColor, textSize } = clusterStyle(input);
  syncOwnedLayoutProperties(map, id, {
    'text-field': ['get', 'point_count_abbreviated'],
    'text-size': textSize,
    'text-font': ['Open Sans Semibold', 'Arial Unicode MS Bold'],
    'text-allow-overlap': true,
    'text-ignore-placement': true,
    visibility: input.visible ? 'visible' : 'none',
  }, { ownedProperties: CLUSTER_COUNT_OWNED_LAYOUT_PROPERTIES });
  syncOwnedPaintProperties(map, id, {
    'text-color': textColor,
    'text-opacity': input.opacity ?? 1,
    'text-halo-color': 'rgba(0, 0, 0, 0.35)',
    'text-halo-width': 1,
  }, { ownedProperties: CLUSTER_COUNT_OWNED_PAINT_PROPERTIES });
  map.setFilter(id, clusterFilter(input));
}

function syncUnclusteredPointLayer(map: MaplibreMap, input: AdapterLayerInput) {
  if (!map.getLayer(input.layerId)) return;
  syncOwnedPaintProperties(map, input.layerId, input.paint, {
    geomType: 'circle',
    ownedProperties: UNCLUSTERED_OWNED_PAINT_PROPERTIES,
  });
  map.setPaintProperty(input.layerId, 'circle-opacity', getExpressionSafeOpacity(input.paint, 'circle', input.opacity ?? 1));
  map.setFilter(input.layerId, unclusteredFilter(input));
}

export const clusterAdapter: LayerAdapter = {
  type: 'cluster',

  addLayers(map: MaplibreMap, input: AdapterLayerInput): void {
    try {
      addClusterCircleLayer(map, input);
      addClusterCountLayer(map, input);
      addUnclusteredPointLayer(map, input);
    } catch (e) {
      if (import.meta.env.DEV) console.warn(`[map-sync] addLayer (cluster) failed for ${input.layerId}:`, e);
    }
  },

  syncPaint(map: MaplibreMap, input: AdapterLayerInput): void {
    if (!map.getLayer(clusterCircleLayerId(input.layerId)) || !map.getLayer(clusterCountLayerId(input.layerId)) || !map.getLayer(input.layerId)) {
      addClusterCircleLayer(map, input);
      addClusterCountLayer(map, input);
      addUnclusteredPointLayer(map, input);
    }
    syncClusterCircleLayer(map, input);
    syncClusterCountLayer(map, input);
    syncUnclusteredPointLayer(map, input);
  },

  syncVisibility(map: MaplibreMap, input: AdapterLayerInput): void {
    syncSingleLayerVisibility(map, clusterCircleLayerId(input.layerId), input.visible);
    syncSingleLayerVisibility(map, clusterCountLayerId(input.layerId), input.visible);
    syncSingleLayerVisibility(map, input.layerId, input.visible);
  },

  getLayerIds(layerId: string): string[] {
    return [clusterCircleLayerId(layerId), clusterCountLayerId(layerId), layerId];
  },
};
