import type { Map as MaplibreMap } from 'maplibre-gl';
import type { MapLayerResponse } from '@/types/api';
import type { TileToken } from '@/api/tiles';
import { MAP_COLORS } from '@/lib/map-colors';
import { buildSignedTileUrl } from '@/lib/tile-utils';

/** Custom paint props stored in layer JSON but not valid MapLibre paint properties.
 *  These are read separately and applied to the outline line layer for polygons. */
const CUSTOM_PAINT_PROPS = new Set([
  '_outline-width', '_outline-color',
  '_fill-disabled', '_stroke-disabled',
  '_fill-opacity-saved', '_outline-width-saved',
]);

/** Move basemap symbol/label layers above data layers, or hide them. */
export function reorderBasemapLabels(map: MaplibreMap, show: boolean) {
  const style = map.getStyle();
  if (!style?.layers) return;

  const basemapSymbolLayers = style.layers.filter(
    (l) => l.type === 'symbol' && (!('source' in l) || !String(l.source ?? '').startsWith('source-')),
  );

  for (const layer of basemapSymbolLayers) {
    if (show) {
      map.setLayoutProperty(layer.id, 'visibility', 'visible');
      map.moveLayer(layer.id);
    } else {
      map.setLayoutProperty(layer.id, 'visibility', 'none');
    }
  }
}

export function getSourceId(layerId: string) {
  return `source-${layerId}`;
}

export function getLayerId(layerId: string) {
  return `layer-${layerId}`;
}

export function getOutlineLayerId(layerId: string) {
  return `layer-${layerId}-outline`;
}

export function getLabelLayerId(layerId: string) {
  return `layer-${layerId}-label`;
}

export function getLayerType(geometryType: string | null): 'circle' | 'line' | 'fill' {
  const gt = (geometryType ?? '').toUpperCase();
  if (gt.includes('POINT')) return 'circle';
  if (gt.includes('LINE')) return 'line';
  return 'fill';
}

/**
 * Simplify paint properties by stripping expression arrays.
 * Falls back to the first concrete color/number in expressions like
 * ["match", ...] or ["step", ...] so the layer renders with a flat color
 * instead of erroring out.
 */
export function simplifyPaint(paint: Record<string, unknown>): Record<string, unknown> {
  const result: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(paint)) {
    if (Array.isArray(value) && value.length >= 3) {
      // For "step" and "match" expressions, the default/fallback color is at
      // index 2: ["step", ["get", col], defaultColor, ...] or
      //          ["match", ["get", col], val1, color1, ..., fallbackColor]
      const op = value[0];
      const fallback = op === 'match' ? value[value.length - 1] : value[2];
      result[key] = typeof fallback === 'string' || typeof fallback === 'number'
        ? fallback
        : undefined;
    } else if (Array.isArray(value)) {
      result[key] = undefined;
    } else {
      result[key] = value;
    }
  }
  return result;
}

const OPACITY_DEFAULTS: Record<string, number> = {
  fill: 0.3,
  line: 1,
  circle: 1,
};

export function getCompoundOpacity(
  paint: Record<string, unknown>,
  geomType: 'fill' | 'line' | 'circle',
  masterOpacity: number,
): number {
  const propKey = `${geomType}-opacity`;
  const propOpacity = (paint[propKey] as number) ?? OPACITY_DEFAULTS[geomType];
  return propOpacity * masterOpacity;
}

/** Imperatively add all data layers to the map. Safe to call repeatedly. */
export function syncLayersToMap(
  map: MaplibreMap,
  layers: MapLayerResponse[],
  tokenMap: Map<string, TileToken>,
  tileBaseUrl: string | undefined,
  managedSourcesRef: { current: Set<string> },
) {

  const currentSources = new Set(managedSourcesRef.current);
  const desiredSources = new Set<string>();

  for (const layer of layers) {
    const sourceId = getSourceId(layer.id);
    const layerId = getLayerId(layer.id);
    const outlineId = getOutlineLayerId(layer.id);
    const sourceLayer = `data.${layer.dataset_table_name}`;
    const token = tokenMap.get(layer.dataset_id) ?? null;

    // --- Raster layer branch ---
    if (token?.kind === 'raster') {
      if (!map.getSource(sourceId)) {
        map.addSource(sourceId, {
          type: 'raster',
          tiles: [`${window.location.origin}${token.tile_url}`],
          tileSize: token.tile_size ?? 256,
          minzoom: token.minzoom ?? 0,
          maxzoom: token.maxzoom ?? 18,
        });
        map.addLayer({
          id: layerId,
          type: 'raster',
          source: sourceId,
          paint: { 'raster-opacity': layer.opacity ?? 1 },
        });
        if (!layer.visible) {
          map.setLayoutProperty(layerId, 'visibility', 'none');
        }
      } else {
        // Sync opacity and visibility
        if (map.getLayer(layerId)) {
          const currentOpacity = map.getPaintProperty(layerId, 'raster-opacity');
          if (currentOpacity !== (layer.opacity ?? 1)) {
            map.setPaintProperty(layerId, 'raster-opacity', layer.opacity ?? 1);
          }
          const vis = layer.visible ? 'visible' : 'none';
          if (map.getLayoutProperty(layerId, 'visibility') !== vis) {
            map.setLayoutProperty(layerId, 'visibility', vis);
          }
        }
      }
      desiredSources.add(sourceId);
      continue; // skip vector logic for this layer
    }

    const tileUrl = buildSignedTileUrl(layer.dataset_table_name, token, tileBaseUrl);

    desiredSources.add(sourceId);

    // Add source + layer if not on map
    if (!map.getSource(sourceId)) {
      map.addSource(sourceId, {
        type: 'vector',
        tiles: [tileUrl],
        minzoom: 1,
        maxzoom: 22,
      });

      const type = getLayerType(layer.dataset_geometry_type);
      const rawPaint = (layer.paint as Record<string, unknown>) ?? {};

      // Check if paint has expression arrays (data-driven styles from AI).
      // addLayer with expressions can fail on some maplibre versions, so we
      // add the layer with scalar defaults then apply expressions via
      // setPaintProperty (which the chat panel already uses successfully).
      const hasExpressions = Object.values(rawPaint).some(Array.isArray);

      if (type === 'circle') {
        const basePaint = hasExpressions ? simplifyPaint(rawPaint) : rawPaint;
        // Strip custom properties that are not valid MapLibre circle paint props.
        const circlePaint: Record<string, unknown> = {};
        for (const [k, v] of Object.entries(basePaint)) {
          if (!CUSTOM_PAINT_PROPS.has(k)) circlePaint[k] = v;
        }
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
          layout: (layer.layout as Record<string, unknown>) ?? {},
        });
        if (hasExpressions) {
          for (const [prop, val] of Object.entries(rawPaint)) {
            if (Array.isArray(val) && !CUSTOM_PAINT_PROPS.has(prop)) {
              try { map.setPaintProperty(layerId, prop, val); } catch (e) { if (import.meta.env.DEV) console.debug(`[map-sync] Failed to set ${prop} on ${layerId}:`, e); }
            }
          }
        }
        map.setPaintProperty(layerId, 'circle-opacity', getCompoundOpacity(rawPaint, 'circle', layer.opacity ?? 1));
        if (layer.filter && Array.isArray(layer.filter) && layer.filter.length > 0) {
          map.setFilter(layerId, layer.filter);
        }
      } else if (type === 'line') {
        const basePaint = hasExpressions ? simplifyPaint(rawPaint) : rawPaint;
        // line-dasharray is stored in layout JSON but is a MapLibre paint property
        const storedLayout = (layer.layout as Record<string, unknown>) ?? {};
        const { 'line-dasharray': dasharray, ...restLayout } = storedLayout;
        // Strip custom properties that are not valid MapLibre line paint props.
        const linePaint: Record<string, unknown> = {};
        for (const [k, v] of Object.entries(basePaint)) {
          if (!CUSTOM_PAINT_PROPS.has(k)) linePaint[k] = v;
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
          'source-layer': sourceLayer,
          paint: linePaint,
          layout: {
            'line-cap': 'round',
            'line-join': 'round',
            ...restLayout,
          },
        });
        if (hasExpressions) {
          for (const [prop, val] of Object.entries(rawPaint)) {
            if (Array.isArray(val) && !CUSTOM_PAINT_PROPS.has(prop)) {
              try { map.setPaintProperty(layerId, prop, val); } catch (e) { if (import.meta.env.DEV) console.debug(`[map-sync] Failed to set ${prop} on ${layerId}:`, e); }
            }
          }
        }
        map.setPaintProperty(layerId, 'line-opacity', getCompoundOpacity(rawPaint, 'line', layer.opacity ?? 1));
        if (layer.filter && Array.isArray(layer.filter) && layer.filter.length > 0) {
          map.setFilter(layerId, layer.filter);
        }
      } else {
        const basePaint = hasExpressions ? simplifyPaint(rawPaint) : rawPaint;
        // Strip custom properties that are not valid MapLibre fill paint props.
        const fillPaint: Record<string, unknown> = {};
        for (const [k, v] of Object.entries(basePaint)) {
          if (!CUSTOM_PAINT_PROPS.has(k)) fillPaint[k] = v;
        }
        map.addLayer({
          id: layerId,
          type: 'fill',
          source: sourceId,
          'source-layer': sourceLayer,
          paint: Object.keys(fillPaint).length ? fillPaint : {
            'fill-color': MAP_COLORS.default.fill,
            'fill-opacity': MAP_COLORS.default.fillOpacity,
          },
          layout: (layer.layout as Record<string, unknown>) ?? {},
        });
        if (hasExpressions) {
          for (const [prop, val] of Object.entries(rawPaint)) {
            if (Array.isArray(val) && !CUSTOM_PAINT_PROPS.has(prop)) {
              try { map.setPaintProperty(layerId, prop, val); } catch (e) { if (import.meta.env.DEV) console.debug(`[map-sync] Failed to set ${prop} on ${layerId}:`, e); }
            }
          }
        }
        map.setPaintProperty(layerId, 'fill-opacity', getCompoundOpacity(rawPaint, 'fill', layer.opacity ?? 1));
        if (layer.filter && Array.isArray(layer.filter) && layer.filter.length > 0) {
          map.setFilter(layerId, layer.filter);
        }
        // Custom paint properties: '_outline-color' and '_outline-width' are stored
        // in the layer's paint JSON but are NOT standard MapLibre fill paint properties.
        // They are read here and applied to a separate 'line' layer that acts as the
        // polygon outline, because MapLibre's native fill-outline-color is fixed at 1px.
        const outlineColor =
          (layer.paint as Record<string, unknown>)?.['_outline-color'] as string | undefined;
        const outlineWidth =
          (layer.paint as Record<string, unknown>)?.['_outline-width'] as number | undefined;
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
        map.setPaintProperty(outlineId, 'line-opacity', layer.opacity ?? 1);
        if (layer.filter && Array.isArray(layer.filter) && layer.filter.length > 0) {
          map.setFilter(outlineId, layer.filter);
        }
      }

    } else {
      // Source already exists — sync paint properties that may have changed
      // (e.g., data-driven style expressions applied via AI chat)
      const rawPaint = (layer.paint as Record<string, unknown>) ?? {};
      const mapLayerId = getLayerId(layer.id);
      if (map.getLayer(mapLayerId)) {
        for (const [prop, val] of Object.entries(rawPaint)) {
          if (CUSTOM_PAINT_PROPS.has(prop)) continue;
          try {
            const current = map.getPaintProperty(mapLayerId, prop);
            if (JSON.stringify(current) !== JSON.stringify(val)) {
              map.setPaintProperty(mapLayerId, prop, val);
            }
          } catch (e) {
            if (import.meta.env.DEV) console.debug(`[map-sync] Failed to set ${prop} on ${mapLayerId}:`, e);
          }
        }
        // Sync compound opacity (per-property opacity * master layer opacity)
        const geomType = getLayerType(layer.dataset_geometry_type);
        const opacityProp = `${geomType}-opacity`;
        map.setPaintProperty(mapLayerId, opacityProp, getCompoundOpacity(rawPaint, geomType, layer.opacity ?? 1));
        // Sync filter
        if (layer.filter && Array.isArray(layer.filter) && layer.filter.length > 0) {
          map.setFilter(mapLayerId, layer.filter);
        } else {
          map.setFilter(mapLayerId, null);
        }
      }
      // Sync outline layer paint for fill layers
      const outId = getOutlineLayerId(layer.id);
      if (map.getLayer(outId)) {
        const outlineColor = rawPaint['_outline-color'];
        const outlineWidth = rawPaint['_outline-width'];
        if (typeof outlineColor === 'string') {
          try {
            const cur = map.getPaintProperty(outId, 'line-color');
            if (cur !== outlineColor) map.setPaintProperty(outId, 'line-color', outlineColor);
          } catch (e) { if (import.meta.env.DEV) console.debug(`[map-sync] Failed to set line-color on ${outId}:`, e); }
        }
        if (typeof outlineWidth === 'number') {
          try {
            const cur = map.getPaintProperty(outId, 'line-width');
            if (cur !== outlineWidth) map.setPaintProperty(outId, 'line-width', outlineWidth);
          } catch (e) { if (import.meta.env.DEV) console.debug(`[map-sync] Failed to set line-width on ${outId}:`, e); }
        }
        map.setPaintProperty(outId, 'line-opacity', layer.opacity ?? 1);
        // Sync outline filter
        if (layer.filter && Array.isArray(layer.filter) && layer.filter.length > 0) {
          map.setFilter(outId, layer.filter);
        } else {
          map.setFilter(outId, null);
        }
      }
    }

    // Sync label layer for existing sources (add/update/remove)
    const labelId = getLabelLayerId(layer.id);
    if (map.getSource(sourceId)) {
      if (layer.label_config?.column) {
        const lc = layer.label_config;
        const geomType = getLayerType(layer.dataset_geometry_type);

        if (!map.getLayer(labelId)) {
          // Add label layer
          map.addLayer({
            id: labelId,
            type: 'symbol',
            source: sourceId,
            'source-layer': sourceLayer,
            minzoom: lc.minZoom ?? 0,
            maxzoom: lc.maxZoom ?? 22,
            layout: {
              'text-field': ['get', lc.column],
              'text-size': lc.fontSize ?? 12,
              'symbol-placement': geomType === 'line' ? 'line' : 'point',
              'text-allow-overlap': false,
              'text-font': ['Noto Sans Regular'],
              'text-max-width': 10,
              ...(geomType === 'circle' ? { 'text-offset': [0, -1.5] as [number, number] } : {}),
            },
            paint: {
              'text-color': lc.textColor ?? MAP_COLORS.label.color,
              'text-halo-color': lc.haloColor ?? MAP_COLORS.label.halo,
              'text-halo-width': lc.haloWidth ?? 1.5,
            },
          });
          if (layer.filter && Array.isArray(layer.filter) && layer.filter.length > 0) {
            map.setFilter(labelId, layer.filter);
          }
        } else {
          // Update existing label layer properties
          map.setLayoutProperty(labelId, 'text-field', ['get', lc.column]);
          map.setLayoutProperty(labelId, 'text-size', lc.fontSize ?? 12);
          map.setPaintProperty(labelId, 'text-color', lc.textColor ?? MAP_COLORS.label.color);
          map.setPaintProperty(labelId, 'text-halo-color', lc.haloColor ?? MAP_COLORS.label.halo);
          map.setPaintProperty(labelId, 'text-halo-width', lc.haloWidth ?? 1.5);
          map.setLayerZoomRange(labelId, lc.minZoom ?? 0, lc.maxZoom ?? 22);
          // Sync filter on existing label layer
          if (layer.filter && Array.isArray(layer.filter) && layer.filter.length > 0) {
            map.setFilter(labelId, layer.filter);
          } else {
            map.setFilter(labelId, null);
          }
        }
      } else if (map.getLayer(labelId)) {
        // Remove label layer when config cleared
        map.removeLayer(labelId);
      }
    }

    // Update visibility
    const vis = layer.visible ? 'visible' : 'none';
    if (map.getLayer(layerId)) {
      map.setLayoutProperty(layerId, 'visibility', vis);
    }
    if (map.getLayer(outlineId)) {
      map.setLayoutProperty(outlineId, 'visibility', vis);
    }
    if (map.getLayer(labelId)) {
      map.setLayoutProperty(labelId, 'visibility', vis);
    }
  }

  // Remove stale layers/sources
  for (const sourceId of currentSources) {
    if (!desiredSources.has(sourceId)) {
      // Derive layer IDs from source ID
      const id = sourceId.replace('source-', '');
      const layerId = getLayerId(id);
      const outlineId = getOutlineLayerId(id);
      const labelId = getLabelLayerId(id);
      if (map.getLayer(labelId)) map.removeLayer(labelId);
      if (map.getLayer(outlineId)) map.removeLayer(outlineId);
      if (map.getLayer(layerId)) map.removeLayer(layerId);
      if (map.getSource(sourceId)) map.removeSource(sourceId);
    }
  }

  managedSourcesRef.current = desiredSources;

  reorderDataLayers(map, layers);
}

/** Reorder MapLibre layers so first in array renders on top (matches UI list).
 *  Reverse iterate: moveLayer() without beforeId moves to top of stack,
 *  so last-processed (index 0) ends up on top.
 *  Labels are moved above all data layers so they are never obscured. */
export function reorderDataLayers(
  map: MaplibreMap,
  layers: Pick<MapLayerResponse, 'id'>[],
) {
  for (let i = layers.length - 1; i >= 0; i--) {
    const lid = getLayerId(layers[i].id);
    const oid = getOutlineLayerId(layers[i].id);
    if (map.getLayer(lid)) map.moveLayer(lid);
    if (map.getLayer(oid)) map.moveLayer(oid);
  }
  for (let i = layers.length - 1; i >= 0; i--) {
    const labelId = getLabelLayerId(layers[i].id);
    if (map.getLayer(labelId)) map.moveLayer(labelId);
  }
}
