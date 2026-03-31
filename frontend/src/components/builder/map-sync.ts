import type { Map as MaplibreMap } from 'maplibre-gl';
import type { MapLayerResponse } from '@/types/api';
import type { TileToken } from '@/api/tiles';
import { buildSignedTileUrl } from '@/lib/tile-utils';
import { getAdapter } from './layer-adapters/registry';
import type { AdapterLayerInput } from './layer-adapters/types';
import { buildLabelLayerSpec, syncLabelLayer } from './label-layer-utils';

// Import shared utilities used locally
import { getLayerType, resolveAdapterType } from './layer-adapters/shared';
// Re-export for backward compatibility with existing consumers
export { CUSTOM_PAINT_PROPS, getLayerType, resolveAdapterType, simplifyPaint, getCompoundOpacity, stripCustomProps } from './layer-adapters/shared';

/** Move basemap symbol/label layers above data layers, or hide them. */
export function reorderBasemapLabels(map: MaplibreMap, show: boolean, sourcePrefix = 'source-') {
  const style = map.getStyle();
  if (!style?.layers) return;

  const basemapSymbolLayers = style.layers.filter(
    (l) => l.type === 'symbol' && (!('source' in l) || !String(l.source ?? '').startsWith(sourcePrefix)),
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
    const sourceLayer = `data.${layer.dataset_table_name}`;
    const token = tokenMap.get(layer.dataset_id) ?? null;

    // Build a base adapter input (tileUrl filled in per-branch below)
    const adapterInput: AdapterLayerInput = {
      id: layer.id,
      dataset_table_name: layer.dataset_table_name,
      dataset_geometry_type: layer.dataset_geometry_type,
      opacity: layer.opacity ?? 1,
      visible: layer.visible,
      paint: (layer.paint as Record<string, unknown>) ?? {},
      layout: (layer.layout as Record<string, unknown>) ?? {},
      filter: layer.filter,
      label_config: layer.label_config,
      sourceId,
      layerId,
      sourceLayer,
      tileUrl: '', // set below per branch
    };

    // --- Raster layer branch ---
    if (token?.kind === 'raster') {
      adapterInput.tileUrl = token.tile_url;
      adapterInput.tileSize = token.tile_size ?? 256;
      adapterInput.minzoom = token.minzoom ?? 0;
      adapterInput.maxzoom = token.maxzoom ?? 18;
      const adapter = getAdapter('raster');
      if (!map.getSource(sourceId)) {
        adapter.addLayers(map, adapterInput);
      } else {
        adapter.syncPaint(map, adapterInput);
      }
      desiredSources.add(sourceId);
      continue; // skip vector logic for this layer
    }

    adapterInput.tileUrl = buildSignedTileUrl(layer.dataset_table_name, token, tileBaseUrl);
    desiredSources.add(sourceId);

    const type = resolveAdapterType(layer.dataset_geometry_type, layer.style_config);
    const adapter = getAdapter(type);

    if (!map.getSource(sourceId)) {
      map.addSource(sourceId, {
        type: 'vector',
        tiles: [adapterInput.tileUrl],
        minzoom: 1,
        maxzoom: 22,
      });
      adapter.addLayers(map, adapterInput);
    } else {
      adapter.syncPaint(map, adapterInput);
    }

    // Apply per-layer zoom range from custom layout props (main + outline companion)
    const layerLayout = (layer.layout ?? {}) as Record<string, unknown>;
    const layerMinzoom = (layerLayout['_minzoom'] as number) ?? 0;
    const layerMaxzoom = (layerLayout['_maxzoom'] as number) ?? 22;
    const mapLayerId = `layer-${layer.id}`;
    if (map.getLayer(mapLayerId)) {
      map.setLayerZoomRange(mapLayerId, layerMinzoom, layerMaxzoom);
    }
    const outlineLayerId = `${mapLayerId}-outline`;
    if (map.getLayer(outlineLayerId)) {
      map.setLayerZoomRange(outlineLayerId, layerMinzoom, layerMaxzoom);
    }

    // Sync label layer for existing sources (add/update/remove)
    // Heatmap layers don't support labels — hide any existing label layer
    const labelId = getLabelLayerId(layer.id);
    const isHeatmap = type === 'heatmap';
    if (map.getSource(sourceId)) {
      if (layer.label_config?.column && !isHeatmap) {
        const lc = layer.label_config;
        // Use getLayerType (not resolveAdapterType) — labels are geometry-based, not render-mode-based
        const geomType = getLayerType(layer.dataset_geometry_type);

        if (!map.getLayer(labelId)) {
          map.addLayer(buildLabelLayerSpec({ labelId, sourceId, sourceLayer, lc, geomType }));
          if (layer.filter && Array.isArray(layer.filter) && layer.filter.length > 0) {
            map.setFilter(labelId, layer.filter);
          }
        } else {
          syncLabelLayer(map, labelId, lc, geomType);
          if (layer.filter && Array.isArray(layer.filter) && layer.filter.length > 0) {
            map.setFilter(labelId, layer.filter);
          } else {
            map.setFilter(labelId, null);
          }
        }
      } else if (map.getLayer(labelId)) {
        // Remove label layer when config cleared or when switching to heatmap
        if (isHeatmap) {
          map.setLayoutProperty(labelId, 'visibility', 'none');
        } else {
          map.removeLayer(labelId);
        }
      }
    }

    // Update visibility via adapter (handles main + companion layers)
    adapter.syncVisibility(map, adapterInput);
    // Also sync label visibility (keep hidden for heatmap layers)
    if (map.getLayer(labelId) && !isHeatmap) {
      const vis = layer.visible ? 'visible' : 'none';
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

  // Only reorder when layer order actually changed (not on every paint/visibility sync)
  const orderKey = layers.map((l) => l.id).join(',');
  if (orderKey !== lastOrderKeyRef.current) {
    lastOrderKeyRef.current = orderKey;
    reorderDataLayers(map, layers);
  }
}

/** Tracks the last layer order to avoid redundant moveLayer calls. */
const lastOrderKeyRef = { current: '' };

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
