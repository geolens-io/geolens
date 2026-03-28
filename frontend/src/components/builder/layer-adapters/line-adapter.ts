import type { Map as MaplibreMap } from 'maplibre-gl';
import type { AdapterLayerInput, LayerAdapter } from './types';
import { simplifyPaint, stripCustomProps, finalizeLayer, getCompoundOpacity } from './shared';
import { CUSTOM_PAINT_PROPS } from '@/components/builder/map-sync';
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
      const linePaint = stripCustomProps(basePaint);
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
        'source-layer': sourceLayer,
        paint: linePaint,
        layout: {
          'line-cap': 'round',
          'line-join': 'round',
          ...restLayout,
        },
      });
      finalizeLayer(map, layerId, rawPaint, 'line', opacity ?? 1, filter, hasExpressions);
    } catch (e) {
      console.warn(`[map-sync] addLayer failed for ${layerId}:`, e);
    }
  },

  syncPaint(map: MaplibreMap, input: AdapterLayerInput): void {
    const { layerId, paint: rawPaint, opacity, filter } = input;
    if (!map.getLayer(layerId)) return;
    for (const [prop, val] of Object.entries(rawPaint)) {
      if (CUSTOM_PAINT_PROPS.has(prop)) continue;
      try {
        const current = map.getPaintProperty(layerId, prop);
        if (JSON.stringify(current) !== JSON.stringify(val)) {
          map.setPaintProperty(layerId, prop, val);
        }
      } catch (e) {
        if (import.meta.env.DEV) console.debug(`[map-sync] Failed to set ${prop} on ${layerId}:`, e);
      }
    }
    map.setPaintProperty(layerId, 'line-opacity', getCompoundOpacity(rawPaint, 'line', opacity ?? 1));
    if (filter && Array.isArray(filter) && filter.length > 0) {
      map.setFilter(layerId, filter);
    } else {
      map.setFilter(layerId, null);
    }
  },

  syncOpacity(map: MaplibreMap, input: AdapterLayerInput): void {
    const { layerId, paint: rawPaint, opacity } = input;
    if (!map.getLayer(layerId)) return;
    map.setPaintProperty(layerId, 'line-opacity', getCompoundOpacity(rawPaint, 'line', opacity ?? 1));
  },

  syncVisibility(map: MaplibreMap, input: AdapterLayerInput): void {
    const { layerId, visible } = input;
    const vis = visible ? 'visible' : 'none';
    if (map.getLayer(layerId)) {
      map.setLayoutProperty(layerId, 'visibility', vis);
    }
  },

  getLayerIds(layerId: string): string[] {
    return [layerId];
  },
};
