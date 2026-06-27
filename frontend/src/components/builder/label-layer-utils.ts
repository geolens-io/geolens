import { MAP_COLORS } from '@/lib/map-colors';
import type { LabelConfig } from '@/types/api';
import type { AddLayerObject } from 'maplibre-gl';

export const LABEL_FONT_STACK = [
  'Noto Sans Regular',
] as const;

/** Phase 20260526-builder-audit BLD-20260526-11: resolve symbol-placement, enforcing point-only for fill geometries. */
export function resolvePlacement(
  lc: Pick<LabelConfig, 'placement'>,
  geomType: string,
): 'point' | 'line' | 'line-center' {
  let placement = lc.placement ?? (geomType === 'line' ? 'line' : 'point');
  if (geomType === 'fill' && placement !== 'point') placement = 'point';
  return placement;
}

/**
 * builder-audit LABEL-01: the single canonical {layout, paint} mapping for a
 * label layer, derived from `LabelConfig` + geometry. Both `buildLabelLayerSpec`
 * (add path) and `syncLabelLayer` (update path) consume this ONE object so the
 * GL property list and its defaults exist exactly once and cannot drift — a new
 * label property is picked up by both add and update automatically.
 *
 * Note: `text-anchor`/`text-offset` are ALWAYS present. For point placement they
 * carry the configured value; for line/line-center placement they are pinned to
 * the neutral `center` / `[0, 0]` so the update path resets them when a layer
 * switches away from point placement (MapLibre keeps the previous value
 * otherwise). On the add path these equal MapLibre's own defaults, so the layer
 * renders identically.
 */
export function buildLabelStyle(
  lc: LabelConfig,
  geomType: string,
  visibility?: 'visible' | 'none',
): { layout: Record<string, unknown>; paint: Record<string, unknown>; placement: 'point' | 'line' | 'line-center' } {
  const placement = resolvePlacement(lc, geomType);
  const layout: Record<string, unknown> = {
    'text-field': ['get', lc.column],
    'text-size': lc.fontSize ?? 12,
    'symbol-placement': placement,
    'text-allow-overlap': lc.allowOverlap ?? false,
    'text-font': [...LABEL_FONT_STACK],
    'text-max-width': 10,
    'text-anchor': placement === 'point' ? (lc.textAnchor ?? 'center') : 'center',
    'text-offset': placement === 'point'
      ? (lc.textOffset ?? (geomType === 'circle' ? [0, -1.5] : [0, 0]))
      : [0, 0],
  };
  if (geomType === 'fill') layout['symbol-avoid-edges'] = true;
  if (visibility) layout['visibility'] = visibility;

  const paint: Record<string, unknown> = {
    'text-color': lc.textColor ?? MAP_COLORS.label.color,
    'text-halo-color': lc.haloColor ?? MAP_COLORS.label.halo,
    'text-halo-width': lc.haloWidth ?? 1.5,
    'text-opacity': lc.textOpacity ?? 1,
  };
  return { layout, paint, placement };
}

/**
 * Build a MapLibre addLayer spec for a symbol/label layer.
 * Shared across map-sync.ts, use-builder-layers.ts, and ViewerMap.tsx
 * to eliminate duplication of label layer construction.
 */
export function buildLabelLayerSpec(opts: {
  labelId: string;
  sourceId: string;
  sourceLayer: string;
  lc: LabelConfig;
  geomType: string;
  visibility?: 'visible' | 'none';
}): AddLayerObject {
  const { labelId, sourceId, sourceLayer, lc, geomType, visibility } = opts;
  const { layout, paint } = buildLabelStyle(lc, geomType, visibility);

  return {
    id: labelId,
    type: 'symbol',
    source: sourceId,
    'source-layer': sourceLayer,
    minzoom: lc.minZoom ?? 0,
    maxzoom: lc.maxZoom ?? 22,
    layout,
    paint,
  } as AddLayerObject;
}

/**
 * Apply label layout/paint properties to an existing label layer.
 * Shared update logic across map-sync.ts, use-builder-layers.ts, and ViewerMap.tsx.
 * Iterates the SAME canonical {layout, paint} object that `buildLabelLayerSpec`
 * spreads, so add and update stay byte-for-byte in lockstep (LABEL-01).
 */
export function syncLabelLayer(
  map: { setLayoutProperty: (id: string, prop: string, val: unknown) => void; setPaintProperty: (id: string, prop: string, val: unknown) => void; setLayerZoomRange: (id: string, min: number, max: number) => void },
  labelId: string,
  lc: LabelConfig,
  geomType: string,
) {
  const { layout, paint } = buildLabelStyle(lc, geomType);
  for (const [prop, value] of Object.entries(layout)) {
    map.setLayoutProperty(labelId, prop, value);
  }
  for (const [prop, value] of Object.entries(paint)) {
    map.setPaintProperty(labelId, prop, value);
  }
  map.setLayerZoomRange(labelId, lc.minZoom ?? 0, lc.maxZoom ?? 22);
}
