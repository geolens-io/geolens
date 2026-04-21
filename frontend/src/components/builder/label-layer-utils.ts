import { MAP_COLORS } from '@/lib/map-colors';
import type { LabelConfig } from '@/types/api';
import type { AddLayerObject } from 'maplibre-gl';

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
  // LB-04: fill geometries only support point placement — override if mismatched
  let placement = lc.placement ?? (geomType === 'line' ? 'line' : 'point');
  if (geomType === 'fill' && placement !== 'point') placement = 'point';

  return {
    id: labelId,
    type: 'symbol',
    source: sourceId,
    'source-layer': sourceLayer,
    minzoom: lc.minZoom ?? 0,
    maxzoom: lc.maxZoom ?? 22,
    layout: {
      'text-field': ['get', lc.column],
      'text-size': lc.fontSize ?? 12,
      'symbol-placement': placement,
      'text-allow-overlap': lc.allowOverlap ?? false,
      'text-font': ['Noto Sans Regular', 'Open Sans Regular', 'Arial Unicode MS Regular'],
      'text-max-width': 10,
      ...(geomType === 'fill' ? { 'symbol-avoid-edges': true } : {}),
      ...(visibility ? { visibility } : {}),
      ...(placement === 'point' ? {
        'text-anchor': lc.textAnchor ?? 'center',
        'text-offset': lc.textOffset ?? (geomType === 'circle' ? [0, -1.5] : [0, 0]),
      } : {}),
    },
    paint: {
      'text-color': lc.textColor ?? MAP_COLORS.label.color,
      'text-halo-color': lc.haloColor ?? MAP_COLORS.label.halo,
      'text-halo-width': lc.haloWidth ?? 1.5,
    },
  } as AddLayerObject;
}

/**
 * Apply label layout/paint properties to an existing label layer.
 * Shared update logic across map-sync.ts, use-builder-layers.ts, and ViewerMap.tsx.
 */
export function syncLabelLayer(
  map: { setLayoutProperty: (id: string, prop: string, val: unknown) => void; setPaintProperty: (id: string, prop: string, val: unknown) => void; setLayerZoomRange: (id: string, min: number, max: number) => void },
  labelId: string,
  lc: LabelConfig,
  geomType: string,
) {
  // LB-04: fill geometries only support point placement — override if mismatched
  let placement = lc.placement ?? (geomType === 'line' ? 'line' : 'point');
  if (geomType === 'fill' && placement !== 'point') placement = 'point';
  map.setLayoutProperty(labelId, 'text-field', ['get', lc.column]);
  map.setLayoutProperty(labelId, 'text-size', lc.fontSize ?? 12);
  map.setLayoutProperty(labelId, 'symbol-placement', placement);
  map.setLayoutProperty(labelId, 'text-allow-overlap', lc.allowOverlap ?? false);
  map.setLayoutProperty(labelId, 'text-font', ['Noto Sans Regular', 'Open Sans Regular', 'Arial Unicode MS Regular']);
  map.setLayoutProperty(labelId, 'text-max-width', 10);
  if (placement === 'point') {
    map.setLayoutProperty(labelId, 'text-anchor', lc.textAnchor ?? 'center');
    map.setLayoutProperty(labelId, 'text-offset', lc.textOffset ?? (geomType === 'circle' ? [0, -1.5] : [0, 0]));
  } else {
    map.setLayoutProperty(labelId, 'text-anchor', 'center');
    map.setLayoutProperty(labelId, 'text-offset', [0, 0]);
  }
  map.setPaintProperty(labelId, 'text-color', lc.textColor ?? MAP_COLORS.label.color);
  map.setPaintProperty(labelId, 'text-halo-color', lc.haloColor ?? MAP_COLORS.label.halo);
  map.setPaintProperty(labelId, 'text-halo-width', lc.haloWidth ?? 1.5);
  map.setPaintProperty(labelId, 'text-opacity', lc.textOpacity ?? 1);
  map.setLayerZoomRange(labelId, lc.minZoom ?? 0, lc.maxZoom ?? 22);
}
