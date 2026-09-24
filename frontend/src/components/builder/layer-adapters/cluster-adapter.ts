import type { FilterSpecification } from 'maplibre-gl';
import { MAP_COLORS } from '@/lib/map-colors';
import { LABEL_FONT_STACK, labelLayerId, removeLabelCompanionIfCleared, withLabelCompanion } from '../label-layer-utils';
import { writeDescribedLayer, writeDescribedVisibility } from '../layer-writer';
import type { AdapterLayerInput, LayerAdapter, LayerDrawing } from './types';
import { getBuilderStyleConfig, getExpressionSafeOpacity, sourceLayerSpec } from './shared';
// builder-audit #338 ADAPT-03: the unclustered point mirrors the standalone circle adapter —
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

function clusterFilter(_input: AdapterLayerInput): FilterSpecification {
  // fix(#394) FL-01/B-020: never AND the layer's data filter into the cluster
  // bubble/count layers — cluster features only carry point_count/cluster_id,
  // so any feature-property predicate fails for every cluster and blanks the
  // whole low-zoom map. Ceiling: cluster counts include filtered-out points
  // (clusters don't re-aggregate); filtering at the source would fix that at
  // the cost of a per-filter tile refetch.
  return ['has', 'point_count'];
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
    'circle-stroke-color': MAP_COLORS.cluster.stroke,
    'circle-stroke-width': 1.5,
    'circle-stroke-opacity': Math.min(opacity + 0.1, 1),
  };
}

// ux(#839): the count label is optional — absent flag means visible, so every
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
          filter: clusterFilter(input),
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
          filter: clusterFilter(input),
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
    removeLabelCompanionIfCleared(map, input);
    writeDescribedLayer(map, describeCluster(input));
  },

  syncVisibility(map, input) {
    writeDescribedVisibility(map, describeCluster(input));
  },

  getLayerIds(layerId: string): string[] {
    return [clusterCircleLayerId(layerId), clusterCountLayerId(layerId), layerId, labelLayerId(layerId)];
  },
};
