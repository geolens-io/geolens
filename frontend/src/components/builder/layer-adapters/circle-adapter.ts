import type { Map as MaplibreMap } from 'maplibre-gl';
import type { AdapterLayerInput, LayerAdapter } from './types';
import { simplifyPaint, stripCustomProps, finalizeLayer, getCompoundOpacity, syncVectorPaint, syncSingleLayerVisibility } from './shared';
import { MAP_COLORS } from '@/lib/map-colors';

export const circleAdapter: LayerAdapter = {
  type: 'circle',

  addLayers(map: MaplibreMap, input: AdapterLayerInput): void {
    const { layerId, sourceId, sourceLayer, paint: rawPaint, layout, opacity, filter } = input;
    const hasExpressions = Object.values(rawPaint).some(Array.isArray);
    try {
      const basePaint = hasExpressions ? simplifyPaint(rawPaint) : rawPaint;
      const circlePaint = stripCustomProps(basePaint);
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
        layout,
      });
      finalizeLayer(map, layerId, rawPaint, 'circle', opacity ?? 1, filter, hasExpressions);
    } catch (e) {
      if (import.meta.env.DEV) console.warn(`[map-sync] addLayer failed for ${layerId}:`, e);
    }
  },

  syncPaint(map: MaplibreMap, input: AdapterLayerInput): void {
    const { layerId, paint: rawPaint, opacity, filter } = input;
    if (!map.getLayer(layerId)) return;
    syncVectorPaint(map, layerId, rawPaint);
    map.setPaintProperty(layerId, 'circle-opacity', getCompoundOpacity(rawPaint, 'circle', opacity ?? 1));
    if (filter && Array.isArray(filter) && filter.length > 0) {
      map.setFilter(layerId, filter);
    } else {
      if (map.getFilter(layerId) != null) map.setFilter(layerId, null);
    }
  },

  syncVisibility(map: MaplibreMap, input: AdapterLayerInput): void {
    syncSingleLayerVisibility(map, input.layerId, input.visible);
  },

  getLayerIds(layerId: string): string[] {
    return [layerId];
  },
};
