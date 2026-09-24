import type { FilterSpecification } from 'maplibre-gl';
import { convertFilter } from '@maplibre/maplibre-gl-style-spec';
import { MAP_COLORS } from '@/lib/map-colors';
import type { AdapterLayerInput, LayerAdapter, LayerDrawing } from './types';
import {
  filterPaintForLayerType,
  getBuilderStyleConfig,
  getExpressionSafeOpacity,
  getFeatureOpacity,
  sourceLayerSpec,
} from './shared';
// builder-audit #338 ADAPT-03 precedent (cluster-adapter): sibling sublayers reuse
// the standalone adapters' owned-property sets and defaults instead of duplicating them.
import { CIRCLE_OWNED_PAINT_PROPERTIES, resolveCirclePaint } from './circle-adapter';
import {
  FILL_OWNED_PAINT_PROPERTIES,
  OUTLINE_OWNED_PAINT_PROPERTIES,
  tintFillPattern,
} from './fill-adapter';
import { FILL_PATTERN_IMAGES } from './fill-pattern-images';
import { LINE_OWNED_LAYOUT_PROPERTIES, LINE_OWNED_PAINT_PROPERTIES, resolveLinePaint } from './line-adapter';
import { DEFAULT_FILL_PAINT } from './builder-defaults';
import { writeDescribedLayer, writeDescribedVisibility } from '../layer-writer';
import { labelLayerId, removeLabelCompanionIfCleared, withLabelCompanion } from '../label-layer-utils';

/**
 * fix(#430 codex r23): renderer for the generic GEOMETRY sentinel.
 *
 * A created (sketch) dataset that mixes geometry families keeps
 * `geometry_type='GEOMETRY'` (see backend `_derive_created_geometry_type`).
 * The classifier used to route that sentinel to the fill adapter, so point and
 * line features added to a map silently disappeared. This adapter installs one
 * sublayer per family, each hard-filtered on `['geometry-type']` — mirroring
 * the dataset-detail map's generic branch (use-map-layers.ts) and the
 * cluster adapter's filtered-sublayer pattern.
 *
 * The family filter is part of each sublayer's identity: it must ALWAYS be
 * composed with (never replaced by) the user's data filter, so each sublayer's
 * spec carries the composed filter.
 */

export function mixedLinesLayerId(layerId: string) {
  return `${layerId}-lines`;
}

export function mixedPointsLayerId(layerId: string) {
  return `${layerId}-points`;
}

/** Sublayer ids that carry feature hits for popups/hover (the polygon outline
 *  is excluded — the fill primary already covers polygon hits). */
export function mixedInteractiveLayerIds(primaryLayerId: string) {
  return [primaryLayerId, mixedLinesLayerId(primaryLayerId), mixedPointsLayerId(primaryLayerId)];
}

type MixedFamily = 'polygon' | 'line' | 'point';

// Expression-syntax geometry-type filters, matching the merged generic-dataset
// branch in use-map-layers.ts. `['geometry-type']` may return Multi* variants
// for MVT features, so both singular and Multi forms are listed.
const MIXED_FAMILY_FILTERS: Record<MixedFamily, FilterSpecification> = {
  polygon: ['in', ['geometry-type'], ['literal', ['Polygon', 'MultiPolygon']]] as unknown as FilterSpecification,
  line: ['in', ['geometry-type'], ['literal', ['LineString', 'MultiLineString']]] as unknown as FilterSpecification,
  point: ['in', ['geometry-type'], ['literal', ['Point', 'MultiPoint']]] as unknown as FilterSpecification,
};

/** Compose the family filter with the user's data filter (never replace it). */
export function mixedFamilyFilter(
  family: MixedFamily,
  filter: FilterSpecification | unknown[] | null | undefined,
): FilterSpecification {
  const base = MIXED_FAMILY_FILTERS[family];
  if (!Array.isArray(filter) || filter.length === 0) return base;
  // fix(#431 codex r3): normalize legacy-syntax data filters (e.g.
  // ['==', 'status', 'open'] from older saved maps) to expression syntax
  // before composing. A single legacy child makes MapLibre classify the whole
  // ['all', ...] as a LEGACY filter, which then rejects the expression-syntax
  // ['geometry-type'] family predicate and fails addLayer/setFilter.
  // convertFilter passes expression-syntax filters through unchanged.
  let expressionFilter: unknown = filter;
  try {
    expressionFilter = convertFilter(filter as Parameters<typeof convertFilter>[0]);
  } catch (e) {
    if (import.meta.env.DEV) console.warn('[map-sync] mixed filter conversion failed, dropping data filter:', e);
    return base;
  }
  return ['all', base, expressionFilter] as FilterSpecification;
}

/** The fill paint a mixed layer's polygon family adds, before the pattern tint. */
export function resolveMixedFillPaint(paint: Record<string, unknown>): Record<string, unknown> {
  const fillPaint = filterPaintForLayerType(paint, 'fill');
  return Object.keys(fillPaint).length > 0 ? fillPaint : { ...DEFAULT_FILL_PAINT };
}

/**
 * The outline under a mixed layer's polygons: the default stroke at 1px.
 * Render-As offers no stroke toggles or outline overrides for mixed layers, so
 * no builder state is read.
 */
export function resolveMixedOutline(): { color: string; width: number } {
  return { color: MAP_COLORS.default.stroke, width: 1 };
}

function mixedOutlinePaint(input: AdapterLayerInput): Record<string, unknown> {
  const outline = resolveMixedOutline();
  return {
    'line-color': outline.color,
    'line-width': outline.width,
    'line-layer-opacity': input.opacity ?? 1,
  };
}

// fix(#431 codex r3): the line-family sublayer honors authored line layout
// (line-cap/line-join via Advanced JSON), mirroring the standalone line
// adapter's defaults + owned-layout handling. Other layout keys are excluded —
// a circle-*/fill-* layout key on a line layer would abort addLayer entirely.
function mixedLineLayout(input: AdapterLayerInput): Record<string, unknown> {
  const stored = (input.layout ?? {}) as Record<string, unknown>;
  const owned = Object.fromEntries(
    LINE_OWNED_LAYOUT_PROPERTIES
      .filter((key) => stored[key] != null)
      .map((key) => [key, stored[key]]),
  );
  return {
    'line-cap': 'round',
    'line-join': 'round',
    ...owned,
    visibility: input.visible === false ? 'none' : 'visible',
  };
}

// The master opacity slider rides on `line-layer-opacity`, so a write keeps it in step too.
const MIXED_LINE_OWNED_PAINT_PROPERTIES = [...LINE_OWNED_PAINT_PROPERTIES, 'line-layer-opacity'] as const;

/**
 * One sublayer per geometry family. A layer's stored paint usually carries only
 * fill keys (GEOMETRY seeds as the polygon family), so the line and point
 * sublayers take their defaults until family keys are authored.
 */
function describeMixed(input: AdapterLayerInput): LayerDrawing {
  const { paint } = input;
  const opacity = input.opacity ?? 1;
  const visibility = input.visible ? 'visible' : 'none';
  const source = { source: input.sourceId, ...sourceLayerSpec(input) };
  const fill = tintFillPattern(resolveMixedFillPaint(paint), paint, getBuilderStyleConfig(input));
  return withLabelCompanion(input, {
    specs: [
      {
        layer: {
          id: input.layerId,
          type: 'fill',
          ...source,
          filter: mixedFamilyFilter('polygon', input.filter),
          layout: { visibility },
          paint: { ...fill.paint, 'fill-opacity': getFeatureOpacity(paint, 'fill'), 'fill-layer-opacity': opacity },
        },
        ownedPaint: FILL_OWNED_PAINT_PROPERTIES,
        ownedLayout: [],
      },
      {
        layer: {
          id: `${input.layerId}-outline`,
          type: 'line',
          ...source,
          filter: mixedFamilyFilter('polygon', input.filter),
          layout: { visibility },
          paint: mixedOutlinePaint(input),
        },
        ownedPaint: OUTLINE_OWNED_PAINT_PROPERTIES,
        ownedLayout: [],
      },
      {
        layer: {
          id: mixedLinesLayerId(input.layerId),
          type: 'line',
          ...source,
          filter: mixedFamilyFilter('line', input.filter),
          layout: mixedLineLayout(input),
          paint: { ...resolveLinePaint(paint), 'line-opacity': getFeatureOpacity(paint, 'line'), 'line-layer-opacity': opacity },
        },
        ownedPaint: MIXED_LINE_OWNED_PAINT_PROPERTIES,
        ownedLayout: LINE_OWNED_LAYOUT_PROPERTIES,
      },
      {
        layer: {
          id: mixedPointsLayerId(input.layerId),
          type: 'circle',
          ...source,
          filter: mixedFamilyFilter('point', input.filter),
          layout: { visibility },
          // Circles have no layer opacity, so the master slider multiplies the per-feature value.
          paint: { ...resolveCirclePaint(paint), 'circle-opacity': getExpressionSafeOpacity(paint, 'circle', opacity) },
        },
        ownedPaint: CIRCLE_OWNED_PAINT_PROPERTIES,
        ownedLayout: [],
      },
    ],
    images: [...FILL_PATTERN_IMAGES, ...fill.images],
  });
}

export const mixedAdapter: LayerAdapter = {
  type: 'mixed',
  describe: describeMixed,

  addLayers(map, input) {
    writeDescribedLayer(map, describeMixed(input));
  },

  // Self-heals missing sublayers (cluster-adapter pattern) so a partial
  // teardown never leaves a family invisible until remount.
  syncPaint(map, input) {
    removeLabelCompanionIfCleared(map, input);
    writeDescribedLayer(map, describeMixed(input));
  },

  syncVisibility(map, input) {
    writeDescribedVisibility(map, describeMixed(input));
  },

  getLayerIds(layerId: string): string[] {
    return [
      layerId,
      `${layerId}-outline`,
      mixedLinesLayerId(layerId),
      mixedPointsLayerId(layerId),
      labelLayerId(layerId),
    ];
  },
};
