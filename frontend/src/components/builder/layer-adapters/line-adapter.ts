import type { Map as MaplibreMap } from 'maplibre-gl';
import type { AdapterLayerInput, LayerAdapter } from './types';
import { simplifyPaint, filterPaintForLayerType, finalizeLayer, getExpressionSafeOpacity, syncVectorPaint, syncSingleLayerVisibility } from './shared';
import { MAP_COLORS } from '@/lib/map-colors';

export const lineAdapter: LayerAdapter = {
  type: 'line',

  addLayers(map: MaplibreMap, input: AdapterLayerInput): void {
    const { layerId, sourceId, sourceLayer, paint: rawPaint, layout: storedLayout, opacity, filter } = input;
    const hasExpressions = Object.values(rawPaint).some(Array.isArray);
    try {
      const basePaint = hasExpressions ? simplifyPaint(rawPaint) : rawPaint;
      // line-dasharray is stored in layout JSON but is a MapLibre paint property
      const { 'line-dasharray': dasharray, ...restLayout } = storedLayout;
      const linePaint = filterPaintForLayerType(basePaint, 'line');
      // line-gradient REQUIRES an expression that consumes ['line-progress'] — there is no
      // valid scalar fallback. simplifyPaint flattens arrays to scalar fallbacks (e.g.
      // `interpolate`'s value[4] color stop), which produces a plain string that MapLibre
      // rejects on addLayer. Drop it here and let finalizeLayer's replayExpressions install
      // the real expression after addLayer succeeds. See REVIEW.md WR-02.
      if (hasExpressions && Array.isArray(rawPaint['line-gradient'])) {
        delete linePaint['line-gradient'];
      }
      if (Object.keys(linePaint).length === 0) {
        linePaint['line-color'] = MAP_COLORS.default.fill;
        linePaint['line-width'] = 2;
      }
      if (dasharray) {
        linePaint['line-dasharray'] = dasharray;
      }
      map.addLayer({
        id: layerId,
        type: 'line',
        source: sourceId,
        ...(input.sourceType !== 'geojson' && { 'source-layer': sourceLayer }),
        paint: linePaint,
        layout: {
          'line-cap': 'round',
          'line-join': 'round',
          ...restLayout,
        },
      });
      finalizeLayer(map, layerId, rawPaint, 'line', opacity ?? 1, filter, hasExpressions);
    } catch (e) {
      if (import.meta.env.DEV) console.warn(`[map-sync] addLayer failed for ${layerId}:`, e);
    }
  },

  syncPaint(map: MaplibreMap, input: AdapterLayerInput): void {
    const { layerId, paint: rawPaint, opacity, filter } = input;
    if (!map.getLayer(layerId)) return;
    syncVectorPaint(map, layerId, rawPaint, 'line');
    map.setPaintProperty(layerId, 'line-opacity', getExpressionSafeOpacity(rawPaint, 'line', opacity ?? 1));
    const dasharray = input.layout?.['line-dasharray'];
    if (map.getLayer(layerId)) {
      map.setPaintProperty(layerId, 'line-dasharray', dasharray ?? undefined);
    }
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
