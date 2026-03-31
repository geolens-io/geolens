import type { Map as MaplibreMap } from 'maplibre-gl';

/** Custom paint props stored in layer JSON but not valid MapLibre paint properties.
 *  These are read separately and applied to the outline line layer for polygons. */
export const CUSTOM_PAINT_PROPS = new Set([
  '_outline-width', '_outline-color',
  'outline-width', 'outline-color',
  '_fill-disabled', '_stroke-disabled',
  '_fill-opacity-saved', '_outline-width-saved',
  '_heatmap-ramp', '_heatmap-weight-column',
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
    if (Array.isArray(value) && value.length >= 3) {
      const op = value[0];
      const fallback = op === 'match' ? value[value.length - 1] : value[2];
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

export const OPACITY_DEFAULTS: Record<string, number> = {
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

/** Strip custom paint properties that are not valid MapLibre paint props. */
export function stripCustomProps(paint: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(Object.entries(paint).filter(([k]) => !CUSTOM_PAINT_PROPS.has(k)));
}

/** Replay expression-based paint properties via setPaintProperty (avoids addLayer failures). */
export function replayExpressions(map: MaplibreMap, layerId: string, rawPaint: Record<string, unknown>) {
  for (const [prop, val] of Object.entries(rawPaint)) {
    if (Array.isArray(val) && !CUSTOM_PAINT_PROPS.has(prop)) {
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
  if (hasExpressions) replayExpressions(map, layerId, rawPaint);
  map.setPaintProperty(layerId, `${geomType}-opacity`, getCompoundOpacity(rawPaint, geomType, masterOpacity));
  if (filter && Array.isArray(filter) && filter.length > 0) {
    map.setFilter(layerId, filter);
  }
}

/** Resolve the adapter type based on geometry type and optional style_config.
 *  If style_config.render_mode === 'heatmap' and the layer is a point layer,
 *  returns 'heatmap'. Otherwise falls back to getLayerType(). */
export function resolveAdapterType(
  geometryType: string | null,
  styleConfig?: { render_mode?: string } | null,
): string {
  if (
    styleConfig?.render_mode === 'heatmap' &&
    getLayerType(geometryType) === 'circle'
  ) {
    return 'heatmap';
  }
  return getLayerType(geometryType);
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

/** Sync paint properties for a vector layer, skipping custom props. */
export function syncVectorPaint(map: MaplibreMap, layerId: string, rawPaint: Record<string, unknown>) {
  for (const [prop, val] of Object.entries(rawPaint)) {
    if (CUSTOM_PAINT_PROPS.has(prop)) continue;
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
