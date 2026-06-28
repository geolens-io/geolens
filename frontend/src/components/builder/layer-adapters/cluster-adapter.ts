import type { FilterSpecification, Map as MaplibreMap } from 'maplibre-gl';
import { MAP_COLORS } from '@/lib/map-colors';
import { LABEL_FONT_STACK } from '../label-layer-utils';
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
// builder-audit #338 ADAPT-03: the unclustered point mirrors the standalone circle adapter —
// reuse its exact owned-property set and default paint instead of duplicating them.
import { CIRCLE_OWNED_PAINT_PROPERTIES } from './circle-adapter';
import { DEFAULT_CIRCLE_PAINT } from './builder-defaults';

export function clusterCircleLayerId(layerId: string) {
  return `${layerId}-cluster`;
}

export function clusterCountLayerId(layerId: string) {
  return `${layerId}-cluster-count`;
}

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

// #347 (BLDR-02): build the cluster circle-color value. With a 2+ stop ramp (sorted
// ascending by point_count) emit a MapLibre `step` expression — parity with the
// MapLibre "create and style clusters" example. Otherwise fall back to the flat
// color so existing single-color clusters are unchanged. Step inputs must be
// strictly ascending and > 0, so duplicate/out-of-order thresholds are dropped.
export function clusterColorValue(ramp: unknown, flatColor: string): unknown {
  if (!Array.isArray(ramp)) return flatColor;
  const stops = ramp
    .filter(
      (s): s is { count: number; color: string } =>
        !!s &&
        typeof s.count === 'number' &&
        Number.isFinite(s.count) &&
        typeof s.color === 'string',
    )
    .sort((a, b) => a.count - b.count);
  if (stops.length < 2) return flatColor;
  const expr: unknown[] = ['step', ['get', 'point_count'], stops[0].color];
  let lastCount = 0;
  for (let i = 1; i < stops.length; i++) {
    const count = stops[i].count;
    if (count <= lastCount) continue; // step inputs must be strictly ascending & > 0
    expr.push(count, stops[i].color);
    lastCount = count;
  }
  // need a base plus at least one threshold (length > 3) to be a valid ramp
  return expr.length > 3 ? expr : flatColor;
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
  const circleColor = clusterColorValue(builder.clusterColorRamp, clusterColor);
  const textColor = typeof builder.clusterTextColor === 'string'
    ? builder.clusterTextColor
    : '#ffffff';
  const textSize = numericBuilderValue(builder.clusterTextSize, 12, 8, 24);
  return { clusterColor, circleColor, textColor, textSize };
}

function unclusteredPointPaint(input: AdapterLayerInput) {
  const circlePaint = filterPaintForLayerType(input.paint, 'circle');
  return Object.keys(circlePaint).length > 0
    ? circlePaint
    : { ...DEFAULT_CIRCLE_PAINT };
}

// builder-audit #338 ADAPT-04: the cluster-circle paint, cluster-count layout, and
// cluster-count paint are built ONCE here and consumed by both the add-time and
// sync-time paths, so the step bucket thresholds (100/750) and stroke/text styling
// can no longer drift between first render and a subsequent sync.
function clusterCirclePaint(input: AdapterLayerInput): Record<string, unknown> {
  const { circleColor } = clusterStyle(input);
  const opacity = input.opacity ?? 1;
  return {
    'circle-color': circleColor,
    'circle-radius': ['step', ['get', 'point_count'], 16, 100, 21, 750, 27],
    'circle-opacity': opacity,
    'circle-stroke-color': '#ffffff',
    'circle-stroke-width': 1.5,
    'circle-stroke-opacity': Math.min(opacity + 0.1, 1),
  };
}

function clusterCountLayout(input: AdapterLayerInput): Record<string, unknown> {
  const { textSize } = clusterStyle(input);
  return {
    'text-field': ['get', 'point_count_abbreviated'],
    'text-size': textSize,
    'text-font': [...LABEL_FONT_STACK],
    'text-allow-overlap': true,
    'text-ignore-placement': true,
    visibility: input.visible ? 'visible' : 'none',
  };
}

function clusterCountPaint(input: AdapterLayerInput): Record<string, unknown> {
  const { textColor } = clusterStyle(input);
  return {
    'text-color': textColor,
    'text-opacity': input.opacity ?? 1,
    'text-halo-color': 'rgba(0, 0, 0, 0.35)',
    'text-halo-width': 1,
  };
}

function addClusterCircleLayer(map: MaplibreMap, input: AdapterLayerInput) {
  const id = clusterCircleLayerId(input.layerId);
  if (map.getLayer(id)) return;

  map.addLayer({
    id,
    type: 'circle',
    source: input.sourceId,
    ...sourceLayerSpec(input),
    filter: clusterFilter(input),
    paint: clusterCirclePaint(input),
    layout: {
      visibility: input.visible ? 'visible' : 'none',
    },
  });
}

function addClusterCountLayer(map: MaplibreMap, input: AdapterLayerInput) {
  const id = clusterCountLayerId(input.layerId);
  if (map.getLayer(id)) return;

  map.addLayer({
    id,
    type: 'symbol',
    source: input.sourceId,
    ...sourceLayerSpec(input),
    filter: clusterFilter(input),
    layout: clusterCountLayout(input),
    paint: clusterCountPaint(input),
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
  syncOwnedPaintProperties(map, id, clusterCirclePaint(input), {
    geomType: 'circle',
    ownedProperties: CLUSTER_CIRCLE_OWNED_PAINT_PROPERTIES,
  });
  map.setFilter(id, clusterFilter(input));
}

function syncClusterCountLayer(map: MaplibreMap, input: AdapterLayerInput) {
  const id = clusterCountLayerId(input.layerId);
  if (!map.getLayer(id)) return;
  syncOwnedLayoutProperties(map, id, clusterCountLayout(input), {
    ownedProperties: CLUSTER_COUNT_OWNED_LAYOUT_PROPERTIES,
  });
  syncOwnedPaintProperties(map, id, clusterCountPaint(input), {
    ownedProperties: CLUSTER_COUNT_OWNED_PAINT_PROPERTIES,
  });
  map.setFilter(id, clusterFilter(input));
}

function syncUnclusteredPointLayer(map: MaplibreMap, input: AdapterLayerInput) {
  if (!map.getLayer(input.layerId)) return;
  syncOwnedPaintProperties(map, input.layerId, input.paint, {
    geomType: 'circle',
    ownedProperties: CIRCLE_OWNED_PAINT_PROPERTIES,
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
