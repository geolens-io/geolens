import type { Map as MaplibreMap } from 'maplibre-gl';
import type { AdapterLayerInput, LayerAdapter } from './types';
import {
  simplifyPaint,
  filterPaintForLayerType,
  finalizeLayer,
  getExpressionSafeOpacity,
  syncOwnedPaintProperties,
  syncSingleLayerVisibility,
  syncLayerFilter,
} from './shared';
import { DEFAULT_CIRCLE_PAINT } from './builder-defaults';

// builder-audit #338 ADAPT-03: exported so cluster-adapter's unclustered point reuses
// this exact owned set (was a byte-identical UNCLUSTERED_OWNED_PAINT_PROPERTIES copy).
// builder-audit #338 SPEC-06: 'circle-stroke-blur' removed — it is not a MapLibre GL paint
// property (the spec has circle-blur + circle-stroke-{width,color,opacity}, no stroke-blur);
// it was a silent no-op swallowed by setPaintProperty's try/catch.
export const CIRCLE_OWNED_PAINT_PROPERTIES = [
  'circle-radius',
  'circle-color',
  'circle-blur',
  'circle-opacity',
  'circle-translate',
  'circle-translate-anchor',
  'circle-pitch-scale',
  'circle-pitch-alignment',
  'circle-stroke-width',
  'circle-stroke-color',
  'circle-stroke-opacity',
] as const;

export const circleAdapter: LayerAdapter = {
  type: 'circle',

  addLayers(map: MaplibreMap, input: AdapterLayerInput): void {
    const { layerId, sourceId, sourceLayer, paint: rawPaint, layout, opacity, filter, visible } = input;
    const hasExpressions = Object.values(rawPaint).some(Array.isArray);
    try {
      const basePaint = hasExpressions ? simplifyPaint(rawPaint) : rawPaint;
      const circlePaint = filterPaintForLayerType(basePaint, 'circle');
      // BUG-01: honor input.visible at initial add — see fill-adapter for rationale.
      const initialLayout = visible === false
        ? { ...layout, visibility: 'none' as const }
        : layout;
      map.addLayer({
        id: layerId,
        type: 'circle',
        source: sourceId,
        ...(input.sourceType !== 'geojson' && { 'source-layer': sourceLayer }),
        paint: Object.keys(circlePaint).length ? circlePaint : { ...DEFAULT_CIRCLE_PAINT },
        layout: initialLayout,
      });
      finalizeLayer(map, layerId, rawPaint, 'circle', opacity ?? 1, filter, hasExpressions);
    } catch (e) {
      if (import.meta.env.DEV) console.warn(`[map-sync] addLayer failed for ${layerId}:`, e);
    }
  },

  syncPaint(map: MaplibreMap, input: AdapterLayerInput): void {
    const { layerId, paint: rawPaint, opacity, filter } = input;
    if (!map.getLayer(layerId)) return;
    syncOwnedPaintProperties(map, layerId, rawPaint, {
      geomType: 'circle',
      ownedProperties: CIRCLE_OWNED_PAINT_PROPERTIES,
    });
    map.setPaintProperty(layerId, 'circle-opacity', getExpressionSafeOpacity(rawPaint, 'circle', opacity ?? 1));
    syncLayerFilter(map, layerId, filter);
  },

  syncVisibility(map: MaplibreMap, input: AdapterLayerInput): void {
    syncSingleLayerVisibility(map, input.layerId, input.visible);
  },

  getLayerIds(layerId: string): string[] {
    return [layerId];
  },
};
