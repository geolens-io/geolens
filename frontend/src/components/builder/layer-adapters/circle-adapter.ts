import type { Map as MaplibreMap } from 'maplibre-gl';
import type { AdapterLayerInput, LayerAdapter } from './types';
import { simplifyPaint, stripCustomProps, finalizeLayer, getCompoundOpacity } from './shared';
import { CUSTOM_PAINT_PROPS } from '@/components/builder/map-sync';
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
        'source-layer': sourceLayer,
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
    map.setPaintProperty(layerId, 'circle-opacity', getCompoundOpacity(rawPaint, 'circle', opacity ?? 1));
    if (filter && Array.isArray(filter) && filter.length > 0) {
      map.setFilter(layerId, filter);
    } else {
      map.setFilter(layerId, null);
    }
  },

  syncOpacity(map: MaplibreMap, input: AdapterLayerInput): void {
    const { layerId, paint: rawPaint, opacity } = input;
    if (!map.getLayer(layerId)) return;
    map.setPaintProperty(layerId, 'circle-opacity', getCompoundOpacity(rawPaint, 'circle', opacity ?? 1));
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
