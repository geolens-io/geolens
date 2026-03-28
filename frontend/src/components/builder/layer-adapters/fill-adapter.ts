import type { Map as MaplibreMap } from 'maplibre-gl';
import type { AdapterLayerInput, LayerAdapter } from './types';
import { simplifyPaint, stripCustomProps, finalizeLayer, getCompoundOpacity } from './shared';
import { CUSTOM_PAINT_PROPS } from '@/components/builder/map-sync';
import { MAP_COLORS } from '@/lib/map-colors';

export const fillAdapter: LayerAdapter = {
  type: 'fill',

  addLayers(map: MaplibreMap, input: AdapterLayerInput): void {
    const { layerId, sourceId, sourceLayer, paint: rawPaint, layout, opacity, filter } = input;
    const outlineId = `${input.layerId}-outline`;
    const hasExpressions = Object.values(rawPaint).some(Array.isArray);
    try {
      const basePaint = hasExpressions ? simplifyPaint(rawPaint) : rawPaint;
      const fillPaint = stripCustomProps(basePaint);
      const strokeDisabled = !!(rawPaint['_stroke-disabled']);
      const effectiveFillPaint = Object.keys(fillPaint).length ? { ...fillPaint } : {
        'fill-color': MAP_COLORS.default.fill,
        'fill-opacity': MAP_COLORS.default.fillOpacity,
      };
      // Suppress native 1px fill outline when stroke is disabled
      if (strokeDisabled) {
        effectiveFillPaint['fill-outline-color'] = 'transparent';
      }
      map.addLayer({
        id: layerId,
        type: 'fill',
        source: sourceId,
        'source-layer': sourceLayer,
        paint: effectiveFillPaint,
        layout,
      });
      finalizeLayer(map, layerId, rawPaint, 'fill', opacity ?? 1, filter, hasExpressions);

      // Companion outline layer: reads _outline-color/_outline-width from raw paint
      const outlineColor =
        (rawPaint['_outline-color'] as string | undefined)
        ?? (rawPaint['outline-color'] as string | undefined);
      const outlineWidth =
        (rawPaint['_outline-width'] as number | undefined)
        ?? (rawPaint['outline-width'] as number | undefined);
      map.addLayer({
        id: outlineId,
        type: 'line',
        source: sourceId,
        'source-layer': sourceLayer,
        paint: {
          'line-color': (typeof outlineColor === 'string' ? outlineColor : null) ?? MAP_COLORS.default.stroke,
          'line-width': outlineWidth ?? 1,
        },
      });
      map.setPaintProperty(outlineId, 'line-opacity', opacity ?? 1);
      if (filter && Array.isArray(filter) && filter.length > 0) {
        map.setFilter(outlineId, filter);
      }
    } catch (e) {
      console.warn(`[map-sync] addLayer failed for ${layerId}:`, e);
    }
  },

  syncPaint(map: MaplibreMap, input: AdapterLayerInput): void {
    const { layerId, paint: rawPaint, opacity, filter } = input;
    const outlineId = `${input.layerId}-outline`;
    if (map.getLayer(layerId)) {
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
      map.setPaintProperty(layerId, 'fill-opacity', getCompoundOpacity(rawPaint, 'fill', opacity ?? 1));
      if (filter && Array.isArray(filter) && filter.length > 0) {
        map.setFilter(layerId, filter);
      } else {
        map.setFilter(layerId, null);
      }
      // Sync fill-outline-color based on _stroke-disabled
      const strokeDisabled = !!rawPaint['_stroke-disabled'];
      try {
        map.setPaintProperty(layerId, 'fill-outline-color', strokeDisabled ? 'transparent' : undefined);
      } catch { /* fill-outline-color may not be supported on all styles */ }
    }
    // Sync outline companion layer
    if (map.getLayer(outlineId)) {
      const outlineColor = rawPaint['_outline-color'] ?? rawPaint['outline-color'];
      const outlineWidth = rawPaint['_outline-width'] ?? rawPaint['outline-width'];
      if (typeof outlineColor === 'string') {
        try {
          const cur = map.getPaintProperty(outlineId, 'line-color');
          if (cur !== outlineColor) map.setPaintProperty(outlineId, 'line-color', outlineColor);
        } catch (e) { if (import.meta.env.DEV) console.debug(`[map-sync] Failed to set line-color on ${outlineId}:`, e); }
      }
      if (typeof outlineWidth === 'number') {
        try {
          const cur = map.getPaintProperty(outlineId, 'line-width');
          if (cur !== outlineWidth) map.setPaintProperty(outlineId, 'line-width', outlineWidth);
        } catch (e) { if (import.meta.env.DEV) console.debug(`[map-sync] Failed to set line-width on ${outlineId}:`, e); }
      }
      map.setPaintProperty(outlineId, 'line-opacity', opacity ?? 1);
      if (filter && Array.isArray(filter) && filter.length > 0) {
        map.setFilter(outlineId, filter);
      } else {
        map.setFilter(outlineId, null);
      }
    }
  },

  syncOpacity(map: MaplibreMap, input: AdapterLayerInput): void {
    const { layerId, paint: rawPaint, opacity } = input;
    const outlineId = `${input.layerId}-outline`;
    if (map.getLayer(layerId)) {
      map.setPaintProperty(layerId, 'fill-opacity', getCompoundOpacity(rawPaint, 'fill', opacity ?? 1));
    }
    if (map.getLayer(outlineId)) {
      map.setPaintProperty(outlineId, 'line-opacity', opacity ?? 1);
    }
  },

  syncVisibility(map: MaplibreMap, input: AdapterLayerInput): void {
    const { layerId, visible } = input;
    const outlineId = `${input.layerId}-outline`;
    const vis = visible ? 'visible' : 'none';
    if (map.getLayer(layerId)) {
      map.setLayoutProperty(layerId, 'visibility', vis);
    }
    if (map.getLayer(outlineId)) {
      map.setLayoutProperty(outlineId, 'visibility', vis);
    }
  },

  getLayerIds(layerId: string): string[] {
    // layerId is "layer-{id}", outline is "layer-{id}-outline"
    return [layerId, `${layerId}-outline`];
  },
};
