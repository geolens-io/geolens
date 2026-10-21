import type { FilterSpecification } from 'maplibre-gl';
import { MAP_COLORS } from '@/lib/map-colors';
import { LABEL_FONT_STACK, labelLayerId, withLabelCompanion } from '../label-layer-utils';
import { writeDescribedLayer, writeDescribedVisibility } from '../layer-writer';
import type { AdapterLayerInput, LayerAdapter, LayerDrawing } from './types';
import { getBuilderStyleConfig, getExpressionSafeOpacity, sourceLayerSpec } from './shared';
// The unclustered point mirrors the standalone circle adapter —
// reuse its exact owned-property set and default paint instead of duplicating them.
import { CIRCLE_OWNED_PAINT_PROPERTIES, resolveCirclePaint } from './circle-adapter';

export function clusterCircleLayerId(layerId: string) {
  return `${layerId}-cluster`;
}

export function clusterCountLayerId(layerId: string) {
  return `${layerId}-cluster-count`;
}

export const CLUSTER_CIRCLE_OWNED_PAINT_PROPERTIES = [
  'circle-color',
  'circle-radius',
  'circle-opacity',
  'circle-stroke-color',
  'circle-stroke-width',
  'circle-stroke-opacity',
] as const;
export const CLUSTER_COUNT_OWNED_PAINT_PROPERTIES = [
  'text-color',
  'text-opacity',
  'text-halo-color',
  'text-halo-width',
] as const;
export const CLUSTER_COUNT_OWNED_LAYOUT_PROPERTIES = [
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

// Cluster features carry only point_count/cluster_id, so a feature-property
// predicate here would hide every bubble. A bounded GeoJSON source filters its
// points before clustering; server tile clusters ignore the layer filter.
const CLUSTER_FILTER: FilterSpecification = ['has', 'point_count'];

function unclusteredFilter(input: AdapterLayerInput) {
  return combineFilter(['!', ['has', 'point_count']], input.filter);
}

function numericBuilderValue(value: unknown, fallback: number, min: number, max: number) {
  return typeof value === 'number' && Number.isFinite(value)
    ? Math.min(Math.max(value, min), max)
    : fallback;
}

// The cluster circle-color ramp as MapLibre reads it. With a 2+ stop ramp
// (sorted ascending by point_count) the lowest stop is the base color and each later stop
// starts at its count. Step inputs must be strictly ascending and > 0, so duplicate or
// out-of-order thresholds are dropped. Null when fewer than two usable stops remain.
export function clusterColorSteps(ramp: unknown): { colors: string[]; breaks: number[] } | null {
  if (!Array.isArray(ramp)) return null;
  const stops = ramp
    .filter(
      (s): s is { count: number; color: string } =>
        !!s &&
        typeof s.count === 'number' &&
        Number.isFinite(s.count) &&
        typeof s.color === 'string',
    )
    .sort((a, b) => a.count - b.count);
  if (stops.length < 2) return null;
  const colors = [stops[0].color];
  const breaks: number[] = [];
  let lastCount = 0;
  for (let i = 1; i < stops.length; i++) {
    const count = stops[i].count;
    if (count <= lastCount) continue;
    colors.push(stops[i].color);
    breaks.push(count);
    lastCount = count;
  }
  return breaks.length > 0 ? { colors, breaks } : null;
}

// Build the cluster circle-color value: a MapLibre `step` expression on point_count (parity
// with the MapLibre "create and style clusters" example), or the flat color when the ramp
// has no usable steps, so existing single-color clusters are unchanged.
export function clusterColorValue(ramp: unknown, flatColor: string): unknown {
  const steps = clusterColorSteps(ramp);
  if (!steps) return flatColor;
  const expr: unknown[] = ['step', ['get', 'point_count'], steps.colors[0]];
  steps.breaks.forEach((count, i) => expr.push(count, steps.colors[i + 1]));
  return expr;
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
    : MAP_COLORS.cluster.text;
  const textSize = numericBuilderValue(builder.clusterTextSize, 12, 8, 24);
  return { clusterColor, circleColor, textColor, textSize };
}

function unclusteredPointPaint(input: AdapterLayerInput) {
  return resolveCirclePaint(input.paint);
}

// The cluster-circle paint, cluster-count layout and cluster-count paint are
// built ONCE here and consumed by both the add-time and sync-time paths, so the
// step bucket thresholds (100/750) and stroke/text styling can't drift between
// first render and a later sync.
export const CLUSTER_STROKE_WIDTH = 1.5;

function clusterCirclePaint(input: AdapterLayerInput): Record<string, unknown> {
  const { circleColor } = clusterStyle(input);
  const opacity = input.opacity ?? 1;
  return {
    'circle-color': circleColor,
    'circle-radius': ['step', ['get', 'point_count'], 16, 100, 21, 750, 27],
    'circle-opacity': opacity,
    'circle-stroke-color': MAP_COLORS.cluster.stroke,
    'circle-stroke-width': CLUSTER_STROKE_WIDTH,
    'circle-stroke-opacity': Math.min(opacity + 0.1, 1),
  };
}

// The count label is optional — absent flag means visible, so every
// existing map keeps its counts. Off = size/color-only clusters.
function clusterCountsEnabled(input: AdapterLayerInput): boolean {
  return getBuilderStyleConfig(input).clusterShowCounts !== false;
}

function clusterCountLayout(input: AdapterLayerInput): Record<string, unknown> {
  const { textSize } = clusterStyle(input);
  return {
    'text-field': ['get', 'point_count_abbreviated'],
    'text-size': textSize,
    'text-font': [...LABEL_FONT_STACK],
    'text-allow-overlap': true,
    'text-ignore-placement': true,
    visibility: input.visible && clusterCountsEnabled(input) ? 'visible' : 'none',
  };
}

function clusterCountPaint(input: AdapterLayerInput): Record<string, unknown> {
  const { textColor } = clusterStyle(input);
  return {
    'text-color': textColor,
    'text-opacity': input.opacity ?? 1,
    'text-halo-color': MAP_COLORS.cluster.textHalo,
    'text-halo-width': 1,
  };
}

function describeCluster(input: AdapterLayerInput): LayerDrawing {
  const visibility = input.visible ? 'visible' : 'none';
  const source = { source: input.sourceId, ...sourceLayerSpec(input) };
  return withLabelCompanion(input, {
    specs: [
      {
        layer: {
          id: clusterCircleLayerId(input.layerId),
          type: 'circle',
          ...source,
          filter: CLUSTER_FILTER,
          layout: { visibility },
          paint: clusterCirclePaint(input),
        },
        ownedPaint: CLUSTER_CIRCLE_OWNED_PAINT_PROPERTIES,
        ownedLayout: [],
      },
      {
        layer: {
          id: clusterCountLayerId(input.layerId),
          type: 'symbol',
          ...source,
          filter: CLUSTER_FILTER,
          layout: clusterCountLayout(input),
          paint: clusterCountPaint(input),
        },
        ownedPaint: CLUSTER_COUNT_OWNED_PAINT_PROPERTIES,
        ownedLayout: CLUSTER_COUNT_OWNED_LAYOUT_PROPERTIES,
      },
      {
        layer: {
          id: input.layerId,
          type: 'circle',
          ...source,
          filter: unclusteredFilter(input),
          layout: { ...input.layout, visibility },
          paint: {
            ...unclusteredPointPaint(input),
            'circle-opacity': getExpressionSafeOpacity(input.paint, 'circle', input.opacity ?? 1),
          },
        },
        ownedPaint: CIRCLE_OWNED_PAINT_PROPERTIES,
        ownedLayout: [],
      },
    ],
    images: [],
  });
}

export const clusterAdapter: LayerAdapter = {
  type: 'cluster',
  describe: describeCluster,

  addLayers(map, input) {
    writeDescribedLayer(map, describeCluster(input));
  },

  syncPaint(map, input) {
    writeDescribedLayer(map, describeCluster(input));
  },

  syncVisibility(map, input) {
    writeDescribedVisibility(map, describeCluster(input));
  },

  getLayerIds(layerId: string): string[] {
    return [clusterCircleLayerId(layerId), clusterCountLayerId(layerId), layerId, labelLayerId(layerId)];
  },
};
