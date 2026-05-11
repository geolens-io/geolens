import type { Map as MaplibreMap } from 'maplibre-gl';
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
]);

export function getLayerType(geometryType: string | null): 'circle' | 'line' | 'fill' {
  const gt = (geometryType ?? '').toUpperCase();
  if (gt.includes('POINT')) return 'circle';
  if (gt.includes('LINE')) return 'line';
  return 'fill';
}

/**
 * Simplify paint properties by stripping expression arrays.
 * Falls back to the first concrete color/number in expressions like
 * ["match", ...] or ["step", ...] so the layer renders with a flat color
 * instead of erroring out.
 */
export function simplifyPaint(paint: Record<string, unknown>): Record<string, unknown> {
  const result: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(paint)) {
    if (typeof value === 'boolean') { result[key] = value; continue; }
    if (Array.isArray(value) && value.length >= 3) {
      const op = value[0];
      let fallback: unknown;
      if (op === 'case') {
        // case wraps step/interpolate: ["case", cond, fallbackColor, innerExpr]
        const inner = value[value.length - 1];
        if (Array.isArray(inner) && inner.length >= 3) {
          const innerOp = inner[0];
          fallback = innerOp === 'match'
            ? inner[inner.length - 1]
            : innerOp === 'interpolate'
              ? inner[4]
              : inner[2];
        } else {
          fallback = value[2];
        }
      } else {
        fallback = op === 'match'
          ? value[value.length - 1]
          : op === 'interpolate'
            ? value[4]  // first output stop value after [method, input, stop0, output0]
            : value[2]; // step: first output after [input, default]
      }
      result[key] = typeof fallback === 'string' || typeof fallback === 'number'
        ? fallback
        : undefined;
    } else if (Array.isArray(value)) {
      result[key] = undefined;
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

const BUILDER_STYLE_KEY_ALIASES: Record<string, string> = {
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
