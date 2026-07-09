import type { FilterSpecification, Map as MaplibreMap } from 'maplibre-gl';
import { convertFilter } from '@maplibre/maplibre-gl-style-spec';
import { MAP_COLORS } from '@/lib/map-colors';
import type { AdapterLayerInput, LayerAdapter } from './types';
import {
  filterPaintForLayerType,
  finalizeLayer,
  getExpressionSafeOpacity,
  syncOwnedLayoutProperties,
  syncOwnedPaintProperties,
  syncSingleLayerVisibility,
} from './shared';
// builder-audit #338 ADAPT-03 precedent (cluster-adapter): sibling sublayers reuse
// the standalone adapters' owned-property sets and defaults instead of duplicating them.
import { CIRCLE_OWNED_PAINT_PROPERTIES } from './circle-adapter';
import { FILL_OWNED_PAINT_PROPERTIES, OUTLINE_OWNED_PAINT_PROPERTIES } from './fill-adapter';
import { LINE_OWNED_LAYOUT_PROPERTIES, LINE_OWNED_PAINT_PROPERTIES } from './line-adapter';
import { DEFAULT_CIRCLE_PAINT, DEFAULT_FILL_PAINT } from './builder-defaults';

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
 * composed with (never replaced by) the user's data filter, so filter syncing
 * here uses raw `map.setFilter` with the composed filter — the same deliberate
 * exception to `syncLayerFilter` the cluster adapter makes.
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

const DEFAULT_MIXED_LINE_PAINT = {
  'line-color': MAP_COLORS.default.fill,
  'line-width': 2,
} as const;

// ADAPT-04 pattern: each family's effective paint is built ONCE and consumed by
// both the add-time and sync-time paths. The layer's stored paint typically only
// carries fill-* keys (GEOMETRY seeds as the polygon family), so the line/point
// sublayers fall back to defaults until family-specific keys are authored.
function mixedFillPaint(input: AdapterLayerInput): Record<string, unknown> {
  const paint = filterPaintForLayerType(input.paint, 'fill');
  return Object.keys(paint).length > 0 ? paint : { ...DEFAULT_FILL_PAINT };
}

function mixedLinePaint(input: AdapterLayerInput): Record<string, unknown> {
  const paint = filterPaintForLayerType(input.paint, 'line');
  return Object.keys(paint).length > 0 ? paint : { ...DEFAULT_MIXED_LINE_PAINT };
}

function mixedPointPaint(input: AdapterLayerInput): Record<string, unknown> {
  const paint = filterPaintForLayerType(input.paint, 'circle');
  return Object.keys(paint).length > 0 ? paint : { ...DEFAULT_CIRCLE_PAINT };
}

// The polygon outline is deliberately minimal (token stroke, 1px, master
// opacity). Render-As polygon options (stroke toggles, outline overrides) are
// not offered for mixed layers, so none of that builder state is read here.
function mixedOutlinePaint(input: AdapterLayerInput): Record<string, unknown> {
  return {
    'line-color': MAP_COLORS.default.stroke,
    'line-width': 1,
    'line-opacity': input.opacity ?? 1,
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

function sourceLayerSpec(input: AdapterLayerInput) {
  return input.sourceType === 'geojson' ? {} : { 'source-layer': input.sourceLayer };
}

function initialLayout(input: AdapterLayerInput): Record<string, unknown> {
  return { visibility: input.visible === false ? 'none' : 'visible' };
}

function addFillLayer(map: MaplibreMap, input: AdapterLayerInput) {
  if (map.getLayer(input.layerId)) return;
  const hasExpressions = Object.values(input.paint).some(Array.isArray);
  const filter = mixedFamilyFilter('polygon', input.filter);
  map.addLayer({
    id: input.layerId,
    type: 'fill',
    source: input.sourceId,
    ...sourceLayerSpec(input),
    filter,
    paint: mixedFillPaint(input),
    layout: initialLayout(input),
  });
  finalizeLayer(map, input.layerId, input.paint, 'fill', input.opacity ?? 1, filter, hasExpressions);
}

function addOutlineLayer(map: MaplibreMap, input: AdapterLayerInput) {
  const id = `${input.layerId}-outline`;
  if (map.getLayer(id)) return;
  map.addLayer({
    id,
    type: 'line',
    source: input.sourceId,
    ...sourceLayerSpec(input),
    filter: mixedFamilyFilter('polygon', input.filter),
    paint: mixedOutlinePaint(input),
    layout: initialLayout(input),
  });
}

function addLinesLayer(map: MaplibreMap, input: AdapterLayerInput) {
  const id = mixedLinesLayerId(input.layerId);
  if (map.getLayer(id)) return;
  const hasExpressions = Object.values(input.paint).some(Array.isArray);
  const filter = mixedFamilyFilter('line', input.filter);
  map.addLayer({
    id,
    type: 'line',
    source: input.sourceId,
    ...sourceLayerSpec(input),
    filter,
    paint: mixedLinePaint(input),
    layout: mixedLineLayout(input),
  });
  finalizeLayer(map, id, input.paint, 'line', input.opacity ?? 1, filter, hasExpressions);
}

function addPointsLayer(map: MaplibreMap, input: AdapterLayerInput) {
  const id = mixedPointsLayerId(input.layerId);
  if (map.getLayer(id)) return;
  const hasExpressions = Object.values(input.paint).some(Array.isArray);
  const filter = mixedFamilyFilter('point', input.filter);
  map.addLayer({
    id,
    type: 'circle',
    source: input.sourceId,
    ...sourceLayerSpec(input),
    filter,
    paint: mixedPointPaint(input),
    layout: initialLayout(input),
  });
  finalizeLayer(map, id, input.paint, 'circle', input.opacity ?? 1, filter, hasExpressions);
}

function syncFillLayer(map: MaplibreMap, input: AdapterLayerInput) {
  if (!map.getLayer(input.layerId)) return;
  syncOwnedPaintProperties(map, input.layerId, mixedFillPaint(input), {
    geomType: 'fill',
    ownedProperties: FILL_OWNED_PAINT_PROPERTIES,
  });
  map.setPaintProperty(input.layerId, 'fill-opacity', getExpressionSafeOpacity(input.paint, 'fill', input.opacity ?? 1));
  map.setFilter(input.layerId, mixedFamilyFilter('polygon', input.filter));
}

function syncOutlineLayer(map: MaplibreMap, input: AdapterLayerInput) {
  const id = `${input.layerId}-outline`;
  if (!map.getLayer(id)) return;
  syncOwnedPaintProperties(map, id, mixedOutlinePaint(input), {
    geomType: 'line',
    ownedProperties: OUTLINE_OWNED_PAINT_PROPERTIES,
  });
  map.setFilter(id, mixedFamilyFilter('polygon', input.filter));
}

function syncLinesLayer(map: MaplibreMap, input: AdapterLayerInput) {
  const id = mixedLinesLayerId(input.layerId);
  if (!map.getLayer(id)) return;
  syncOwnedPaintProperties(map, id, mixedLinePaint(input), {
    geomType: 'line',
    ownedProperties: LINE_OWNED_PAINT_PROPERTIES,
  });
  // clearMissing: false — mirrors the standalone line adapter (CR-01): addLayers
  // hardcodes 'round'/'round'; a stored layout without cap/join must not reset
  // the live value to MapLibre's spec defaults ('butt'/'miter').
  syncOwnedLayoutProperties(map, id, (input.layout ?? {}) as Record<string, unknown>, {
    ownedProperties: LINE_OWNED_LAYOUT_PROPERTIES,
    clearMissing: false,
  });
  map.setPaintProperty(id, 'line-opacity', getExpressionSafeOpacity(input.paint, 'line', input.opacity ?? 1));
  map.setFilter(id, mixedFamilyFilter('line', input.filter));
}

function syncPointsLayer(map: MaplibreMap, input: AdapterLayerInput) {
  const id = mixedPointsLayerId(input.layerId);
  if (!map.getLayer(id)) return;
  syncOwnedPaintProperties(map, id, mixedPointPaint(input), {
    geomType: 'circle',
    ownedProperties: CIRCLE_OWNED_PAINT_PROPERTIES,
  });
  map.setPaintProperty(id, 'circle-opacity', getExpressionSafeOpacity(input.paint, 'circle', input.opacity ?? 1));
  map.setFilter(id, mixedFamilyFilter('point', input.filter));
}

export const mixedAdapter: LayerAdapter = {
  type: 'mixed',

  addLayers(map: MaplibreMap, input: AdapterLayerInput): void {
    try {
      addFillLayer(map, input);
      addOutlineLayer(map, input);
      addLinesLayer(map, input);
      addPointsLayer(map, input);
    } catch (e) {
      if (import.meta.env.DEV) console.warn(`[map-sync] addLayer (mixed) failed for ${input.layerId}:`, e);
    }
  },

  syncPaint(map: MaplibreMap, input: AdapterLayerInput): void {
    // Self-heal missing sublayers (cluster-adapter pattern) so a partial
    // teardown never leaves a family invisible until remount.
    this.addLayers(map, input);
    syncFillLayer(map, input);
    syncOutlineLayer(map, input);
    syncLinesLayer(map, input);
    syncPointsLayer(map, input);
  },

  syncVisibility(map: MaplibreMap, input: AdapterLayerInput): void {
    for (const id of this.getLayerIds(input.layerId)) {
      syncSingleLayerVisibility(map, id, input.visible);
    }
  },

  getLayerIds(layerId: string): string[] {
    return [
      layerId,
      `${layerId}-outline`,
      mixedLinesLayerId(layerId),
      mixedPointsLayerId(layerId),
    ];
  },
};
