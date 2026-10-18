/**
 * Pure layer-style clipboard helpers: extract a geometry-compatible style
 * snapshot from one layer and apply it to a compatible target. No React, no
 * MapLibre instance, no I/O. The hook layer (use-builder-layers.ts) owns the
 * session clipboard ref and live-map sync.
 *
 * A polygon style (fill-color, fill-opacity, data-driven categories) is only
 * meaningful on another polygon layer; pasting it onto a point layer would carry
 * `fill-*` paint keys MapLibre would reject. `isStyleCompatible` gates
 * paste/bulk-apply to same-class targets.
 *
 * Copied: deep clones of `paint` and `style_config` (portable data-driven keys
 * and builder sub-keys). Not copied: layer-identity fields (id, dataset_id,
 * display_name, ...), which stay on the target. The payload carries only paint,
 * style_config and the derived geometryClass tag.
 */

import type { GeometryTypeName, MapLayerResponse, StyleConfig } from '@/types/api';
// Imported rather than restated so paste and the editor share one fill rule.
import {
  resolveFillExclusions,
  stashExcludedFillColor,
} from '@/components/builder/hooks/use-layer-map-sync';

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

// structuredClone with a JSON round-trip fallback; paint/style_config are plain
// JSON-serializable objects, so both strategies are equivalent.
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
 * Produce a NEW layer object with the copied style applied. Never mutates
 * `target` or `copied`. Mirrors the merge shape of handleStyleConfigChange
 * (use-layer-map-sync.ts): target paint keys are preserved, copied paint keys
 * overlay them, and style_config is replaced wholesale. Layer-identity fields on
 * the target are left untouched.
 *
 * The merge can make a paste collide: a target-only `fill-pattern` survives a
 * copied `fill-color` and vice versa, and paint carrying both breaks the fill
 * exclusions (MapLibre gives the pattern precedence while the legend, editor and
 * saved JSON report the colour). So the fill family is resolved AFTER the merge,
 * through the same `resolveFillExclusions` the style-editor funnel and bulk
 * apply-style call.
 *
 * That rule is a provenance diff, which is why the target's own paint is passed
 * as the baseline: whichever fill key the merge just introduced is the one the
 * copied style asserted. Keys count as ACTIVE, not merely present: a target
 * carrying `fill-pattern: null` has no pattern to defend and must not swallow
 * the pasted colour.
 */
export function applyCopiedStyleToLayer(
  target: MapLayerResponse,
  copied: CopiedStyle,
): MapLayerResponse {
  const targetPaint: Record<string, unknown> = target.paint ?? {};
  const mergedPaint: Record<string, unknown> = {
    ...targetPaint,
    ...deepClone(copied.paint),
  };
  const styleConfig = copied.style_config ? deepClone(copied.style_config) : null;
  // Stash alongside the resolution. A copied style can carry BOTH an active
  // pattern and a raw string colour (imported or API-authored, no
  // fillColorSaved); the resolution drops that colour here, so this is the only
  // place that still knows it. Deferring to the write boundary would stash the
  // TARGET's previous colour instead. `stashExcludedFillColor` writes only when
  // `fillColorSaved` is undefined, so a stash the copied style carries wins.
  const resolution = resolveFillExclusions(styleConfig, mergedPaint, targetPaint);
  return {
    ...target,
    paint: resolution.paint,
    style_config: stashExcludedFillColor(styleConfig, resolution),
  };
}
