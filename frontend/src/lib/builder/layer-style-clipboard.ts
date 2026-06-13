/**
 * Phase 1201-01 (ENH-02 / ENH-03) — pure layer-style clipboard helpers.
 *
 * Extract a geometry-compatible style snapshot from one layer and apply it to a
 * geometry-compatible target. These functions are PURE: no React, no MapLibre
 * map instance, no I/O. The hook layer (use-builder-layers.ts) owns the session
 * clipboard ref + live-map sync; this module only computes new layer objects.
 *
 * Geometry-class portability: a polygon style (fill-color, fill-opacity,
 * data-driven categories) is only meaningful on another polygon layer; pasting
 * it onto a point layer would carry `fill-*` paint keys MapLibre would reject.
 * `isStyleCompatible` therefore gates paste/bulk-apply to same-class targets.
 *
 * What is COPIED:
 *  - the full `paint` object (deep clone)
 *  - the full `style_config` object (deep clone), preserving the portable
 *    data-driven keys (mode / column / ramp / method / classCount / breaks /
 *    colors / categories / sizes / sizeRange / target) AND any builder sub-keys.
 *
 * What is NOT copied:
 *  - layer-identity fields (id / dataset_id / display_name / dataset_table_name
 *    etc.) — those stay on the target. The copied payload carries ONLY paint,
 *    style_config and the derived geometryClass tag.
 */

import type { GeometryTypeName, MapLayerResponse, StyleConfig } from '@/types/api';

export type GeometryStyleClass = 'polygon' | 'line' | 'point' | 'other';

export interface CopiedStyle {
  /** Deep-cloned paint object from the source layer. */
  paint: Record<string, unknown>;
  /** Deep-cloned style_config from the source layer (data-driven styling). */
  style_config: StyleConfig | null;
  /** Geometry class the style was authored for — gates compatibility. */
  geometryClass: GeometryStyleClass;
}

/**
 * Derive the portable geometry class from a layer's dataset geometry type.
 * Polygon/MultiPolygon → 'polygon'; LineString/MultiLineString → 'line';
 * Point/MultiPoint → 'point'; everything else (raster, null) → 'other'.
 */
export function geometryClassOf(geometryType: GeometryTypeName | null): GeometryStyleClass {
  if (!geometryType) return 'other';
  const gt = geometryType.toLowerCase().replace('multi', '');
  if (gt.includes('polygon')) return 'polygon';
  if (gt.includes('line')) return 'line';
  if (gt.includes('point')) return 'point';
  return 'other';
}

// Deep clone via structuredClone (jsdom + Node support it). Falls back to a JSON
// round-trip in the unlikely event structuredClone is unavailable. paint/style_config
// are plain JSON-serializable objects, so both strategies are equivalent here.
function deepClone<T>(value: T): T {
  if (value === null || value === undefined) return value;
  if (typeof structuredClone === 'function') return structuredClone(value);
  return JSON.parse(JSON.stringify(value)) as T;
}

/**
 * Extract a geometry-compatible, identity-free style snapshot from a layer.
 * Returns a deep clone so later mutation of the snapshot never touches the
 * source layer's paint or style_config.
 */
export function extractCopyableStyle(layer: MapLayerResponse): CopiedStyle {
  return {
    paint: deepClone(layer.paint ?? {}),
    style_config: layer.style_config ? deepClone(layer.style_config) : null,
    geometryClass: geometryClassOf(layer.dataset_geometry_type),
  };
}

/**
 * True only when the copied style's geometry class matches the target layer's
 * geometry class AND that class is not 'other' (raster/null geometries have no
 * portable vector style). Cross-geometry pastes return false.
 */
export function isStyleCompatible(copied: CopiedStyle, target: MapLayerResponse): boolean {
  const targetClass = geometryClassOf(target.dataset_geometry_type);
  if (targetClass === 'other') return false;
  return copied.geometryClass === targetClass;
}

/**
 * Produce a NEW layer object with the copied style applied. Pure — never mutates
 * `target` or `copied`. Mirrors the merge shape used by handleStyleConfigChange
 * (use-layer-map-sync.ts): target paint keys are preserved, copied paint keys are
 * overlaid on top, and style_config is replaced wholesale by the copied one.
 *
 * Layer-identity fields on the target (id / dataset_id / display_name / …) are
 * left untouched.
 */
export function applyCopiedStyleToLayer(
  target: MapLayerResponse,
  copied: CopiedStyle,
): MapLayerResponse {
  const mergedPaint: Record<string, unknown> = {
    ...(target.paint ?? {}),
    ...deepClone(copied.paint),
  };
  return {
    ...target,
    paint: mergedPaint,
    style_config: copied.style_config ? deepClone(copied.style_config) : null,
  };
}
