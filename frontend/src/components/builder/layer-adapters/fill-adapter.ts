import type { Map as MaplibreMap } from 'maplibre-gl';
import type { AdapterLayerInput, LayerAdapter } from './types';
import { simplifyPaint, stripCustomProps, finalizeLayer, getCompoundOpacity, syncVectorPaint, getBuilderStyleConfig } from './shared';
import { MAP_COLORS } from '@/lib/map-colors';

export const fillAdapter: LayerAdapter = {
  type: 'fill',

  addLayers(map: MaplibreMap, input: AdapterLayerInput): void {
    const { layerId, sourceId, sourceLayer, paint: rawPaint, layout, opacity, filter } = input;
    const builder = getBuilderStyleConfig(input);
    const outlineId = `${input.layerId}-outline`;
    const heightColumn = builder.heightColumn ?? (rawPaint['_height_column'] as string | undefined);
    const hasExpressions = Object.values(rawPaint).some(Array.isArray);
    try {
      const basePaint = hasExpressions ? simplifyPaint(rawPaint) : rawPaint;
      const fillPaint = stripCustomProps(basePaint);
      const strokeDisabled = builder.strokeDisabled ?? !!(rawPaint['_stroke-disabled']);
      const effectiveFillPaint: Record<string, unknown> = Object.keys(fillPaint).length
        ? { ...fillPaint }
        : {
            'fill-color': MAP_COLORS.default.fill,
            'fill-opacity': MAP_COLORS.default.fillOpacity,
          };
      // Suppress native 1px fill outline when stroke is disabled
      if (strokeDisabled) {
        effectiveFillPaint['fill-outline-color'] = 'rgba(0,0,0,0)';
      }
      map.addLayer({
        id: layerId,
        type: 'fill',
        source: sourceId,
        ...(input.sourceType !== 'geojson' && { 'source-layer': sourceLayer }),
        paint: effectiveFillPaint,
        layout,
      });
      finalizeLayer(map, layerId, rawPaint, 'fill', opacity ?? 1, filter, hasExpressions);

      const outlineColor =
        builder.outlineColor
        ?? (rawPaint['_outline-color'] as string | undefined)
        ?? (rawPaint['outline-color'] as string | undefined);
      const outlineWidth =
        builder.outlineWidth
        ?? (rawPaint['_outline-width'] as number | undefined)
        ?? (rawPaint['outline-width'] as number | undefined);
      map.addLayer({
        id: outlineId,
        type: 'line',
        source: sourceId,
        ...(input.sourceType !== 'geojson' && { 'source-layer': sourceLayer }),
        paint: {
          'line-color': (typeof outlineColor === 'string' ? outlineColor : null) ?? MAP_COLORS.default.stroke,
          'line-width': outlineWidth ?? 1,
        },
      });
      map.setPaintProperty(outlineId, 'line-opacity', opacity ?? 1);
      if (strokeDisabled) {
        map.setLayoutProperty(outlineId, 'visibility', 'none');
      }
      if (filter && Array.isArray(filter) && filter.length > 0) {
        map.setFilter(outlineId, filter);
      }

      // Companion fill-extrusion layer: only when a builder height column is set
      if (heightColumn) {
        const extrusionId = `${layerId}-extrusion`;
        const fillColor = (rawPaint['fill-color'] as string | undefined) ?? MAP_COLORS.default.fill;
        map.addLayer({
          id: extrusionId,
          type: 'fill-extrusion',
          source: sourceId,
          ...(input.sourceType !== 'geojson' && { 'source-layer': sourceLayer }),
          minzoom: 14,
          paint: {
            'fill-extrusion-height': ['coalesce', ['to-number', ['get', heightColumn], 0], 0],
            'fill-extrusion-base': 0,
            'fill-extrusion-color': fillColor,
            'fill-extrusion-opacity': Math.min(opacity ?? 1, 0.85),
            'fill-extrusion-vertical-gradient': true,
          },
        });
        if (filter && Array.isArray(filter) && filter.length > 0) {
          map.setFilter(extrusionId, filter);
        }
      }
    } catch (e) {
      if (import.meta.env.DEV) console.warn(`[map-sync] addLayer failed for ${layerId}:`, e);
    }
  },

  syncPaint(map: MaplibreMap, input: AdapterLayerInput): void {
    const { layerId, paint: rawPaint, opacity, filter } = input;
    const builder = getBuilderStyleConfig(input);
    const outlineId = `${input.layerId}-outline`;
    if (map.getLayer(layerId)) {
      syncVectorPaint(map, layerId, rawPaint);
      map.setPaintProperty(layerId, 'fill-opacity', getCompoundOpacity(rawPaint, 'fill', opacity ?? 1));
      if (filter && Array.isArray(filter) && filter.length > 0) {
        map.setFilter(layerId, filter);
      } else {
        if (map.getFilter(layerId) != null) map.setFilter(layerId, null);
      }
      const strokeDisabled = builder.strokeDisabled ?? !!rawPaint['_stroke-disabled'];
      const outlineColor = (builder.outlineColor ?? rawPaint['_outline-color'] ?? rawPaint['outline-color']) as string | undefined;
      try {
        map.setPaintProperty(layerId, 'fill-outline-color', strokeDisabled ? 'rgba(0,0,0,0)' : (outlineColor ?? 'rgba(0,0,0,0)'));
      } catch (e) { if (import.meta.env.DEV) console.debug(`[map-sync] fill-outline-color may not be supported on all styles:`, e); }
    }
    // Sync outline companion layer
    if (map.getLayer(outlineId)) {
      const outlineStrokeDisabled = builder.strokeDisabled ?? !!rawPaint['_stroke-disabled'];
      const outlineColor = builder.outlineColor ?? rawPaint['_outline-color'] ?? rawPaint['outline-color'];
      const outlineWidth = builder.outlineWidth ?? rawPaint['_outline-width'] ?? rawPaint['outline-width'];
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
      map.setLayoutProperty(outlineId, 'visibility', outlineStrokeDisabled ? 'none' : 'visible');
      if (filter && Array.isArray(filter) && filter.length > 0) {
        map.setFilter(outlineId, filter);
      } else {
        if (map.getFilter(outlineId) != null) map.setFilter(outlineId, null);
      }
    }
    // Sync fill-extrusion companion layer
    const extrusionId = `${layerId}-extrusion`;
    if (map.getLayer(extrusionId)) {
      const heightColumn = builder.heightColumn ?? (rawPaint['_height_column'] as string | undefined);
      if (heightColumn) {
        // Update height expression when column changes
        try {
          map.setPaintProperty(extrusionId, 'fill-extrusion-height',
            ['coalesce', ['to-number', ['get', heightColumn], 0], 0]);
        } catch (e) { if (import.meta.env.DEV) console.debug(`[map-sync] Failed to set extrusion height:`, e); }
        const fillColor = rawPaint['fill-color'] as string | undefined;
        if (fillColor) {
          try {
            map.setPaintProperty(extrusionId, 'fill-extrusion-color', fillColor);
          } catch (e) { if (import.meta.env.DEV) console.debug(`[map-sync] Failed to set extrusion color:`, e); }
        }
        map.setPaintProperty(extrusionId, 'fill-extrusion-opacity', Math.min(opacity ?? 1, 0.85));
        if (filter && Array.isArray(filter) && filter.length > 0) {
          map.setFilter(extrusionId, filter);
        } else {
          if (map.getFilter(extrusionId) != null) map.setFilter(extrusionId, null);
        }
        // Workaround MapLibre v5 bug: setPaintProperty only applies every other call with terrain active
        try { map.triggerRepaint(); } catch (e) { if (import.meta.env.DEV) console.debug('[map-sync] triggerRepaint not available:', e); }
      }
    }
  },

  syncVisibility(map: MaplibreMap, input: AdapterLayerInput): void {
    const { layerId, visible } = input;
    const outlineId = `${input.layerId}-outline`;
    const extrusionId = `${input.layerId}-extrusion`;
    const vis = visible ? 'visible' : 'none';
    if (map.getLayer(layerId)) {
      map.setLayoutProperty(layerId, 'visibility', vis);
    }
    if (map.getLayer(outlineId)) {
      map.setLayoutProperty(outlineId, 'visibility', vis);
    }
    if (map.getLayer(extrusionId)) {
      map.setLayoutProperty(extrusionId, 'visibility', vis);
    }
  },

  getLayerIds(layerId: string): string[] {
    return [layerId, `${layerId}-outline`, `${layerId}-extrusion`];
  },
};
