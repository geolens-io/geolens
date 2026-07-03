import type { FilterSpecification, Map as MaplibreMap } from 'maplibre-gl';
import type { StyleConfig } from '@/types/api';

/** Custom paint props stored in layer JSON but not valid MapLibre paint properties.
 *  These are read separately and applied to the outline line layer for polygons. */
export const CUSTOM_PAINT_PROPS = new Set([
  '_outline-width', '_outline-color',
  'outline-width', 'outline-color',
  '_fill-disabled', '_stroke-disabled',
  '_fill-opacity-saved', '_outline-width-saved',
  '_heatmap-ramp', '_heatmap-weight-column',
  '_height_column',
  '_hypso-enabled', '_hypso-ramp',
]);

/** Canonical geometry family. `other` covers null/empty and tokens that are
 *  neither point/line/polygon (e.g. GEOMETRYCOLLECTION). */
export type GeometryFamily = 'point' | 'line' | 'polygon' | 'other';

/**
 * builder-audit #338 ADAPT-02/DRY-05: single canonical geometry classifier.
 * getLayerType, renderAs.geometryFamily, layer-capabilities, and
 * color-ramps.getColorProperty all DERIVE from this one uppercase+substring scan
 * so a new geometry token or normalization rule is patched in exactly one place.
 */
export function classifyGeometry(geometryType: string | null): GeometryFamily {
  const gt = (geometryType ?? '').toUpperCase();
  if (gt.includes('POINT')) return 'point';
  if (gt.includes('LINE')) return 'line';
  if (gt.includes('POLYGON')) return 'polygon';
  return 'other';
}

/** MapLibre vector layer type for a geometry. polygon/other both render as fill. */
export function getLayerType(geometryType: string | null): 'circle' | 'line' | 'fill' {
  switch (classifyGeometry(geometryType)) {
    case 'point': return 'circle';
    case 'line': return 'line';
    default: return 'fill';
  }
}

/** Raster bounds as a fixed [west, south, east, north] tuple. */
export type RasterBounds = [number, number, number, number];

/**
 * builder-audit #338 ADAPT-01: single raster-bounds guard hoisted from the verbatim
 * copies in raster-adapter, hillshade-adapter, and map-sync. Returns the bounds
 * as a 4-tuple, or undefined when the input is not exactly four finite numbers.
 */
export function normalizeRasterBounds(bounds: number[] | null | undefined): RasterBounds | undefined {
  if (!Array.isArray(bounds) || bounds.length !== 4) return undefined;
  if (!bounds.every((value) => Number.isFinite(value))) return undefined;
  return [bounds[0], bounds[1], bounds[2], bounds[3]];
}

/**
 * builder-audit #338 ADAPT-08/SPEC-10: extract a flat scalar fallback from a MapLibre
 * expression using EXPLICIT per-op shape guards. Each op verifies the expression
 * has enough elements before reading a positional index, so a malformed or
 * newly-shaped expression (interpolate-hcl, single-stop step, multi-pair case,
 * unknown op) degrades to undefined instead of mis-indexing a wrong color/width.
 * The fallback is only the pre-addLayer scalar; finalizeLayer replays the real
 * expression via replayExpressions.
 */
function expressionFallback(value: unknown[]): unknown {
  if (value.length < 3) return undefined;
  const op = value[0];
  switch (op) {
    case 'match':
      // ["match", input, label0, output0, ..., fallback]; fallback is the last element.
      // Smallest meaningful form has one label/output pair + fallback => length 5.
      return value.length >= 5 ? value[value.length - 1] : undefined;
    case 'interpolate':
    case 'interpolate-hcl':
    case 'interpolate-lab':
      // ["interpolate", method, input, stop0, output0, ...]; first output at index 4.
      return value.length >= 5 ? value[4] : undefined;
    case 'step':
      // ["step", input, default, stop0, output0, ...]; default output at index 2.
      return value[2];
    case 'case':
      return caseFallback(value);
    default:
      return undefined;
  }
}

/** GeoLens wraps step/interpolate in a null-guard case:
 *  ["case", cond, fallbackOutput, innerExpr]. Prefer the nested expression's own
 *  fallback; otherwise use the case's literal fallback output at index 2. */
function caseFallback(value: unknown[]): unknown {
  const inner = value[value.length - 1];
  if (Array.isArray(inner) && inner.length >= 3) {
    return expressionFallback(inner);
  }
  return value.length >= 3 ? value[2] : undefined;
}

/**
 * Simplify paint properties by stripping expression arrays.
 * Falls back to a concrete color/number pulled from expressions like
 * ["match", ...] or ["step", ...] so the layer renders with a flat color
 * instead of erroring out. Non-scalar fallbacks collapse to undefined.
 */
export function simplifyPaint(paint: Record<string, unknown>): Record<string, unknown> {
  const result: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(paint)) {
    if (typeof value === 'boolean') { result[key] = value; continue; }
    if (Array.isArray(value)) {
      const fallback = expressionFallback(value);
      result[key] = typeof fallback === 'string' || typeof fallback === 'number'
        ? fallback
        : undefined;
    } else {
      result[key] = value;
    }
  }
  return result;
}

const OPACITY_DEFAULTS: Record<string, number> = {
  fill: 0.3,
  line: 1,
  circle: 1,
};

export function getCompoundOpacity(
  paint: Record<string, unknown>,
  geomType: 'fill' | 'line' | 'circle',
  masterOpacity: number,
): number {
  const propKey = `${geomType}-opacity`;
  const propOpacity = (paint[propKey] as number) ?? OPACITY_DEFAULTS[geomType];
  return propOpacity * masterOpacity;
}

export function getExpressionSafeOpacity(
  paint: Record<string, unknown>,
  geomType: 'fill' | 'line' | 'circle',
  masterOpacity: number,
): unknown {
  const propKey = `${geomType}-opacity`;
  const propOpacity = paint[propKey];
  if (Array.isArray(propOpacity)) {
    return propOpacity;
  }
  if (typeof propOpacity === 'number') {
    return propOpacity * masterOpacity;
  }
  return OPACITY_DEFAULTS[geomType] * masterOpacity;
}

/** Strip custom paint properties that are not valid MapLibre paint props. */
export function stripCustomProps(paint: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(Object.entries(paint).filter(([k]) => !CUSTOM_PAINT_PROPS.has(k)));
}

function isPaintPropertyForLayerType(prop: string, geomType: 'fill' | 'line' | 'circle') {
  if (CUSTOM_PAINT_PROPS.has(prop)) return false;
  if (!prop.startsWith(`${geomType}-`)) return false;
  if (geomType === 'fill' && prop.startsWith('fill-extrusion-')) return false;
  return !prop.endsWith('-sort-key');
}

function isOwnedLayoutProperty(prop: string) {
  return !prop.startsWith('_') && !CUSTOM_PAINT_PROPS.has(prop);
}

/** Keep only MapLibre paint properties supported by the target vector layer type. */
export function filterPaintForLayerType(
  paint: Record<string, unknown>,
  geomType: 'fill' | 'line' | 'circle',
): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(paint).filter(([prop, value]) =>
      value != null && isPaintPropertyForLayerType(prop, geomType),
    ),
  );
}

/** B-002/CH-01: Style-Spec numeric bounds for paint properties, mirroring backend
 *  `_PAINT_BOUNDS` (backend/app/processing/ai/schemas.py) so AI-produced paint is
 *  clamped identically on both sides of the wire. */
const PAINT_BOUNDS: Record<string, [number, number]> = {
  'fill-opacity': [0, 1],
  'line-opacity': [0, 1],
  'line-width': [0, 50],
  'line-gap-width': [0, 50],
  'line-blur': [0, 50],
  'line-offset': [-50, 50],
  'circle-opacity': [0, 1],
  'circle-radius': [0, 200],
  'circle-blur': [0, 50],
  'circle-stroke-opacity': [0, 1],
  'circle-stroke-width': [0, 20],
  'heatmap-radius': [1, 200],
  'heatmap-weight': [0, 10],
  'heatmap-intensity': [0, 10],
  'heatmap-opacity': [0, 1],
  'fill-extrusion-opacity': [0, 1],
  'fill-extrusion-height': [0, 10000],
  'fill-extrusion-base': [0, 10000],
};

/**
 * Clamp numeric paint values to their Style-Spec bounds (e.g. AI-produced
 * `circle-radius: 99999` -> 200). Expression (array) values and non-numeric
 * values pass through untouched — only flat numerics whose key has a bound
 * are clamped.
 */
export function clampPaintBounds(paint: Record<string, unknown>): Record<string, unknown> {
  const result: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(paint)) {
    const bounds = PAINT_BOUNDS[key];
    if (bounds && typeof value === 'number') {
      const [lo, hi] = bounds;
      result[key] = Math.min(hi, Math.max(lo, value));
    } else {
      result[key] = value;
    }
  }
  return result;
}

/** Replay expression-based paint properties via setPaintProperty (avoids addLayer failures). */
function replayExpressions(
  map: MaplibreMap,
  layerId: string,
  rawPaint: Record<string, unknown>,
  geomType: 'fill' | 'line' | 'circle',
) {
  for (const [prop, val] of Object.entries(rawPaint)) {
    if (Array.isArray(val) && isPaintPropertyForLayerType(prop, geomType)) {
      try { map.setPaintProperty(layerId, prop, val); }
      catch (e) { if (import.meta.env.DEV) console.debug(`[map-sync] Failed to set ${prop} on ${layerId}:`, e); }
    }
  }
}

/** Apply expression replay, compound opacity, and filter after addLayer. */
export function finalizeLayer(
  map: MaplibreMap,
  layerId: string,
  rawPaint: Record<string, unknown>,
  geomType: 'fill' | 'line' | 'circle',
  masterOpacity: number,
  filter: import('maplibre-gl').FilterSpecification | null,
  hasExpressions: boolean,
) {
  if (!map.getLayer(layerId)) return;
  if (hasExpressions) replayExpressions(map, layerId, rawPaint, geomType);
  map.setPaintProperty(layerId, `${geomType}-opacity`, getExpressionSafeOpacity(rawPaint, geomType, masterOpacity));
  if (filter && Array.isArray(filter) && filter.length > 0) {
    map.setFilter(layerId, filter);
  }
}

/**
 * Set a paint or layout property on a MapLibre layer, swallowing any errors
 * that arise from attempting to set an unsupported property (e.g. calling
 * setPaintProperty before addLayer completes, or setting a property not valid
 * for the layer type).  In DEV mode the error is surfaced as console.debug.
 *
 * Extracted from 7+ repeated try-catch wrapped setPaintProperty occurrences
 * across layer adapters (CA-03 remediation).
 */
export function setLayerProperty(
  map: MaplibreMap,
  layerId: string,
  property: string,
  value: unknown,
  kind: 'paint' | 'layout' = 'paint',
): void {
  try {
    if (kind === 'paint') {
      map.setPaintProperty(layerId, property, value);
    } else {
      map.setLayoutProperty(layerId, property, value);
    }
  } catch (e) {
    if (import.meta.env.DEV) {
      console.debug(`[map-sync] Failed to set ${kind} property ${property} on ${layerId}:`, e);
    }
  }
}

/**
 * Sync the MapLibre layer filter for a given layer ID.
 * If `filter` is a non-empty array it is applied directly; otherwise the filter
 * is cleared by passing `null`.  Safe to call when the layer does not exist
 * (no-op). Extracted from duplicated filter-checking branches across adapters (CA-01).
 */
export function syncLayerFilter(
  map: MaplibreMap,
  layerId: string,
  filter: FilterSpecification | unknown[] | null | undefined,
): void {
  if (!map.getLayer(layerId)) return;
  if (filter && Array.isArray(filter) && filter.length > 0) {
    map.setFilter(layerId, filter as FilterSpecification);
  } else {
    map.setFilter(layerId, null);
  }
}

/** Infer adapter type from paint property key prefixes (fallback for null geometry). */
function inferTypeFromPaint(paint?: Record<string, unknown>): string | null {
  if (!paint) return null;
  const keys = Object.keys(paint);
  if (keys.some(k => k.startsWith('heatmap-'))) return 'heatmap';
  if (keys.some(k => k.startsWith('circle-'))) return 'circle';
  if (keys.some(k => k.startsWith('line-'))) return 'line';
  if (keys.some(k => k.startsWith('fill-'))) return 'fill';
  return null;
}

/** Resolve the adapter type based on geometry type, style_config, and paint.
 *  Priority: explicit render_mode > geometry type > paint key inference > 'fill'. */
export function resolveAdapterType(
  geometryType: string | null,
  styleConfig?: { render_mode?: string } | null,
  paint?: Record<string, unknown>,
): string {
  // Explicit render_mode always wins
  if (styleConfig?.render_mode === 'heatmap') {
    return 'heatmap';
  }
  if (styleConfig?.render_mode === 'symbol') {
    return 'symbol';
  }
  if (styleConfig?.render_mode === 'arrow') {
    return 'line';
  }
  if (styleConfig?.render_mode === 'cluster') {
    return 'cluster';
  }
  // Use geometry type when available
  if (geometryType) {
    return getLayerType(geometryType);
  }
  // Fallback: infer from paint property prefixes
  return inferTypeFromPaint(paint) ?? getLayerType(geometryType);
}

/** Sync visibility for a single layer (used by circle, line, heatmap adapters). */
export function syncSingleLayerVisibility(map: MaplibreMap, layerId: string, visible: boolean): void {
  const vis = visible ? 'visible' : 'none';
  if (map.getLayer(layerId)) {
    map.setLayoutProperty(layerId, 'visibility', vis);
  }
}

/** Check if two paint values differ. Uses strict equality for scalars, JSON.stringify for arrays/objects. */
export function paintValueChanged(current: unknown, incoming: unknown): boolean {
  if (current === incoming) return false;
  if (typeof incoming !== 'object' || incoming === null) return current !== incoming;
  return JSON.stringify(current) !== JSON.stringify(incoming);
}

type VectorGeomType = 'fill' | 'line' | 'circle';

export interface OwnedPaintSyncOptions {
  ownedProperties: readonly string[];
  geomType?: VectorGeomType;
  clearMissing?: boolean;
}

export interface OwnedLayoutSyncOptions {
  ownedProperties: readonly string[];
  clearMissing?: boolean;
}

function shouldSyncOwnedPaintProperty(prop: string, geomType?: VectorGeomType) {
  if (geomType) return isPaintPropertyForLayerType(prop, geomType);
  return !CUSTOM_PAINT_PROPS.has(prop);
}

function debugPropertySyncFailure(
  layerId: string,
  property: string,
  kind: 'paint' | 'layout',
  action: 'get' | 'set',
  error: unknown,
) {
  if (import.meta.env.DEV) {
    console.debug(`[map-sync] Failed to ${action} ${kind} property ${property} on ${layerId}:`, error);
  }
}

/** Reconcile an explicit paint ownership set against the live MapLibre layer. */
export function syncOwnedPaintProperties(
  map: MaplibreMap,
  layerId: string,
  rawPaint: Record<string, unknown>,
  options: OwnedPaintSyncOptions,
) {
  if (!map.getLayer(layerId)) return;
  const { ownedProperties, geomType, clearMissing = true } = options;
  const filteredPaint = geomType ? filterPaintForLayerType(rawPaint, geomType) : stripCustomProps(rawPaint);

  for (const prop of ownedProperties) {
    if (!shouldSyncOwnedPaintProperty(prop, geomType)) continue;

    const hasDesired = Object.prototype.hasOwnProperty.call(filteredPaint, prop);
    if (!hasDesired && !clearMissing) continue;

    let current: unknown;
    let currentKnown = false;
    try {
      current = map.getPaintProperty(layerId, prop);
      currentKnown = true;
    } catch (e) {
      debugPropertySyncFailure(layerId, prop, 'paint', 'get', e);
    }

    if (!hasDesired) {
      if (!currentKnown || current === undefined) continue;
      try {
        map.setPaintProperty(layerId, prop, undefined);
      } catch (e) {
        debugPropertySyncFailure(layerId, prop, 'paint', 'set', e);
      }
      continue;
    }

    const desired = filteredPaint[prop];
    if (currentKnown && !paintValueChanged(current, desired)) continue;
    try {
      map.setPaintProperty(layerId, prop, desired);
    } catch (e) {
      debugPropertySyncFailure(layerId, prop, 'paint', 'set', e);
    }
  }
}

/** Reconcile an explicit layout ownership set against the live MapLibre layer. */
export function syncOwnedLayoutProperties(
  map: MaplibreMap,
  layerId: string,
  layout: Record<string, unknown>,
  options: OwnedLayoutSyncOptions,
) {
  if (!map.getLayer(layerId)) return;
  const { ownedProperties, clearMissing = true } = options;

  for (const prop of ownedProperties) {
    if (!isOwnedLayoutProperty(prop)) continue;

    const hasDesired = Object.prototype.hasOwnProperty.call(layout, prop) && layout[prop] != null;
    if (!hasDesired && !clearMissing) continue;

    let current: unknown;
    let currentKnown = false;
    try {
      current = map.getLayoutProperty(layerId, prop);
      currentKnown = true;
    } catch (e) {
      debugPropertySyncFailure(layerId, prop, 'layout', 'get', e);
    }

    if (!hasDesired) {
      if (!currentKnown || current === undefined) continue;
      try {
        map.setLayoutProperty(layerId, prop, undefined);
      } catch (e) {
        debugPropertySyncFailure(layerId, prop, 'layout', 'set', e);
      }
      continue;
    }

    const desired = layout[prop];
    if (currentKnown && !paintValueChanged(current, desired)) continue;
    try {
      map.setLayoutProperty(layerId, prop, desired);
    } catch (e) {
      debugPropertySyncFailure(layerId, prop, 'layout', 'set', e);
    }
  }
}

/** Sync paint properties for a vector layer, skipping custom and cross-geometry props. */
export function syncVectorPaint(
  map: MaplibreMap,
  layerId: string,
  rawPaint: Record<string, unknown>,
  geomType?: 'fill' | 'line' | 'circle',
) {
  const paint = geomType ? filterPaintForLayerType(rawPaint, geomType) : stripCustomProps(rawPaint);
  for (const [prop, val] of Object.entries(paint)) {
    try {
      const current = map.getPaintProperty(layerId, prop);
      if (paintValueChanged(current, val)) {
        map.setPaintProperty(layerId, prop, val);
      }
    } catch (e) {
      if (import.meta.env.DEV) console.debug(`[map-sync] Failed to set ${prop} on ${layerId}:`, e);
    }
  }
}

/** builder-audit #338 SPEC-08 / cross-cutting DRY-02: the single canonical frontend
 *  snake_case -> camelCase builder-key alias map. normalize-style-config imports
 *  this instead of maintaining a second copy (the two had diverged: this map was
 *  missing the folder_group_* keys, added below as a harmless consistency fix). */
export const BUILDER_STYLE_KEY_ALIASES: Record<string, string> = {
  fill_disabled: 'fillDisabled',
  stroke_disabled: 'strokeDisabled',
  fill_opacity_saved: 'fillOpacitySaved',
  outline_width_saved: 'outlineWidthSaved',
  outline_color: 'outlineColor',
  outline_width: 'outlineWidth',
  heatmap_ramp: 'heatmapRamp',
  heatmap_weight_column: 'heatmapWeightColumn',
  height_column: 'heightColumn',
  height_scale: 'heightScale',
  extrusion_min_zoom: 'extrusionMinZoom',
  extrusion_opacity: 'extrusionOpacity',
  arrow_color: 'arrowColor',
  arrow_size: 'arrowSize',
  arrow_spacing: 'arrowSpacing',
  cluster_radius: 'clusterRadius',
  cluster_max_zoom: 'clusterMaxZoom',
  cluster_color: 'clusterColor',
  cluster_text_color: 'clusterTextColor',
  cluster_text_size: 'clusterTextSize',
  cluster_color_ramp: 'clusterColorRamp',
  folder_group_id: 'folderGroupId',
  folder_group_name: 'folderGroupName',
  folder_group_expanded: 'folderGroupExpanded',
};

export function getBuilderStyleConfig(input: unknown): NonNullable<StyleConfig['builder']> {
  const builder = (input as { style_config?: StyleConfig | null }).style_config?.builder;
  if (!builder) return {};

  const normalized = Object.entries(builder as Record<string, unknown>).reduce<Record<string, unknown>>(
    (acc, [key, value]) => {
      const aliasKey = BUILDER_STYLE_KEY_ALIASES[key];
      const canonicalKey = aliasKey ?? key;
      if (!aliasKey || acc[canonicalKey] === undefined) {
        acc[canonicalKey] = value;
      }
      return acc;
    },
    {},
  );

  return normalized as NonNullable<StyleConfig['builder']>;
}
