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
import { MAP_COLORS } from '@/lib/map-colors';

const CIRCLE_OWNED_PAINT_PROPERTIES = [
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
  'circle-stroke-blur',
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
        paint: Object.keys(circlePaint).length ? circlePaint : {
          'circle-radius': 5,
          'circle-color': MAP_COLORS.default.fill,
          'circle-stroke-color': MAP_COLORS.default.stroke,
          'circle-stroke-width': 1,
        },
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
