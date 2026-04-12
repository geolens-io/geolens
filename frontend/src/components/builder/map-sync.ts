import type { Map as MaplibreMap } from 'maplibre-gl';
import type { FilterSpecification } from 'maplibre-gl';
import type { MapLayerResponse, LabelConfig, StyleConfig } from '@/types/api';
import type { TileToken } from '@/api/tiles';
import { buildSignedTileUrl } from '@/lib/tile-utils';
import { getAdapter } from './layer-adapters/registry';
import type { AdapterLayerInput } from './layer-adapters/types';
import { buildLabelLayerSpec, syncLabelLayer } from './label-layer-utils';

// Import shared utilities used locally
import { getLayerType, resolveAdapterType } from './layer-adapters/shared';
// Re-export for backward compatibility with existing consumers
export { CUSTOM_PAINT_PROPS, getLayerType, resolveAdapterType, simplifyPaint, getCompoundOpacity, stripCustomProps } from './layer-adapters/shared';

// ---------------------------------------------------------------------------
// Normalized layer input — allows both Builder and Viewer to call syncLayersToMap
// ---------------------------------------------------------------------------

/** Normalized layer descriptor accepted by syncLayersToMap. */
export interface SyncLayerInput {
  /** Unique key used to derive source/layer/label IDs */
  id: string;
  dataset_id: string;
  dataset_table_name: string;
  dataset_geometry_type: string | null;
  opacity: number;
  visible: boolean;
  paint: Record<string, unknown>;
  layout: Record<string, unknown>;
  filter: FilterSpecification | null;
  label_config?: LabelConfig | null;
  style_config?: StyleConfig | null;
  is_3d?: boolean | null;
  feature_count?: number | null;
}

/** Options that vary between Builder and Viewer contexts. */
export interface SyncOptions {
  /** Prefix for generated source/layer IDs (default: no prefix, uses "source-"/"layer-" scheme) */
  idPrefix?: string;
  /** When provided, run basemap label reorder using this source prefix after layer order changes */
  showBasemapLabels?: boolean;
}

/** Convert a MapLayerResponse (builder context) to a SyncLayerInput. */
export function toSyncInput(layer: MapLayerResponse): SyncLayerInput {
  return {
    id: layer.id,
    dataset_id: layer.dataset_id,
    dataset_table_name: layer.dataset_table_name,
    dataset_geometry_type: layer.dataset_geometry_type,
    opacity: layer.opacity ?? 1,
    visible: layer.visible,
    paint: (layer.paint as Record<string, unknown>) ?? {},
    layout: (layer.layout as Record<string, unknown>) ?? {},
    filter: layer.filter,
    label_config: layer.label_config,
    style_config: layer.style_config,
    is_3d: layer.is_3d,
    feature_count: layer.dataset_feature_count,
  };
}

// ---------------------------------------------------------------------------
// ID helpers (parameterized by prefix)
// ---------------------------------------------------------------------------

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

function prefixedSourceId(id: string, prefix?: string) {
  return prefix ? `${prefix}source-${id}` : `source-${id}`;
}

function prefixedLayerId(id: string, prefix?: string) {
  return prefix ? `${prefix}layer-${id}` : `layer-${id}`;
}

function prefixedOutlineLayerId(id: string, prefix?: string) {
  return `${prefixedLayerId(id, prefix)}-outline`;
}

function prefixedLabelLayerId(id: string, prefix?: string) {
  return `${prefixedLayerId(id, prefix)}-label`;
}

// Keep the original non-prefixed exports for backward compatibility
export function getSourceId(layerId: string) {
  return `source-${layerId}`;
}

export function getLayerId(layerId: string) {
  return `layer-${layerId}`;
}

export function getLabelLayerId(layerId: string) {
  return `layer-${layerId}-label`;
}

/** Imperatively add/sync all data layers to the map. Safe to call repeatedly.
 *  Works with both Builder (MapLayerResponse) and Viewer (SharedLayerResponse)
 *  contexts via the normalized SyncLayerInput interface. */
export function syncLayersToMap(
  map: MaplibreMap,
  layers: SyncLayerInput[],
  tokenMap: Map<string, TileToken>,
  tileBaseUrl: string | undefined,
  managedSourcesRef: { current: Set<string> },
  lastOrderKeyRef: { current: string },
  geojsonDataMap?: Map<string, GeoJSON.FeatureCollection>,
  options?: SyncOptions,
) {
  const prefix = options?.idPrefix;
  const sourcePrefix = prefix ? `${prefix}source-` : 'source-';

  const currentSources = new Set(managedSourcesRef.current);
  const desiredSources = new Set<string>();

  for (const layer of layers) {
    const sourceId = prefixedSourceId(layer.id, prefix);
    const layerId = prefixedLayerId(layer.id, prefix);
    const sourceLayer = `data.${layer.dataset_table_name}`;
    const token = tokenMap.get(layer.dataset_id) ?? null;

    // Build a base adapter input (tileUrl filled in per-branch below)
    const adapterInput: AdapterLayerInput = {
      id: layer.id,
      dataset_table_name: layer.dataset_table_name,
      dataset_geometry_type: layer.dataset_geometry_type,
      opacity: layer.opacity ?? 1,
      visible: layer.visible,
      paint: layer.paint ?? {},
      layout: layer.layout ?? {},
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

    // --- GeoJSON-Z branch: 3D small datasets use GeoJSON source instead of MVT ---
    const isGeoJsonZ = layer.is_3d && layer.feature_count != null && layer.feature_count <= 5000;
    if (isGeoJsonZ && geojsonDataMap?.has(layer.id)) {
      const geojsonData = geojsonDataMap.get(layer.id)!;
      adapterInput.sourceType = 'geojson';
      if (!map.getSource(sourceId)) {
        map.addSource(sourceId, { type: 'geojson', data: geojsonData });
        adapter.addLayers(map, adapterInput);
      } else {
        (map.getSource(sourceId) as maplibregl.GeoJSONSource).setData(geojsonData as GeoJSON.GeoJSON);
        adapter.syncPaint(map, adapterInput);
      }
      desiredSources.add(sourceId);
      adapter.syncVisibility(map, adapterInput);
      continue;
    }

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
    const layerLayout = layer.layout ?? {};
    const layerMinzoom = (layerLayout['_minzoom'] as number) ?? 0;
    const layerMaxzoom = (layerLayout['_maxzoom'] as number) ?? 22;
    if (map.getLayer(layerId)) {
      map.setLayerZoomRange(layerId, layerMinzoom, layerMaxzoom);
    }
    const outlineLayerId = prefixedOutlineLayerId(layer.id, prefix);
    if (map.getLayer(outlineLayerId)) {
      map.setLayerZoomRange(outlineLayerId, layerMinzoom, layerMaxzoom);
    }

    // Sync label layer for existing sources (add/update/remove)
    // Heatmap layers don't support labels — hide any existing label layer
    const labelId = prefixedLabelLayerId(layer.id, prefix);
    const isHeatmap = type === 'heatmap';
    if (map.getSource(sourceId)) {
      if (layer.label_config?.column && !isHeatmap) {
        const lc = layer.label_config;
        // Use getLayerType (not resolveAdapterType) — labels are geometry-based, not render-mode-based
        const geomType = getLayerType(layer.dataset_geometry_type);
        const vis = layer.visible ? 'visible' : 'none';

        if (!map.getLayer(labelId)) {
          map.addLayer(buildLabelLayerSpec({ labelId, sourceId, sourceLayer, lc, geomType, visibility: vis }));
          if (layer.filter) {
            map.setFilter(labelId, layer.filter);
          }
        } else {
          syncLabelLayer(map, labelId, lc, geomType);
          if (layer.filter) {
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
      const id = sourceId.replace(sourcePrefix, '');
      const layerId = prefixedLayerId(id, prefix);
      const outlineId = prefixedOutlineLayerId(id, prefix);
      const labelId = prefixedLabelLayerId(id, prefix);
      if (map.getLayer(labelId)) map.removeLayer(labelId);
      if (map.getLayer(outlineId)) map.removeLayer(outlineId);
      if (map.getLayer(layerId)) map.removeLayer(layerId);
      if (map.getSource(sourceId)) map.removeSource(sourceId);
    }
  }

  managedSourcesRef.current = desiredSources;

  // Only reorder when layer order actually changed (not on every paint/visibility sync)
  const orderKey = layers.map((l) => l.id).join(',')
    + (options?.showBasemapLabels !== undefined ? `|${String(options.showBasemapLabels)}` : '');
  if (orderKey !== lastOrderKeyRef.current) {
    lastOrderKeyRef.current = orderKey;
    reorderDataLayers(map, layers, prefix);
    if (options?.showBasemapLabels !== undefined) {
      reorderBasemapLabels(map, options.showBasemapLabels, sourcePrefix);
    }
  }
}

/** Reorder MapLibre layers so first in array renders on top (matches UI list).
 *  Reverse iterate: moveLayer() without beforeId moves to top of stack,
 *  so last-processed (index 0) ends up on top.
 *  Labels are moved above all data layers so they are never obscured. */
export function reorderDataLayers(
  map: MaplibreMap,
  layers: Pick<SyncLayerInput, 'id'>[],
  idPrefix?: string,
) {
  for (let i = layers.length - 1; i >= 0; i--) {
    const lid = prefixedLayerId(layers[i].id, idPrefix);
    const oid = prefixedOutlineLayerId(layers[i].id, idPrefix);
    if (map.getLayer(lid)) map.moveLayer(lid);
    if (map.getLayer(oid)) map.moveLayer(oid);
  }
  for (let i = layers.length - 1; i >= 0; i--) {
    const labelId = prefixedLabelLayerId(layers[i].id, idPrefix);
    if (map.getLayer(labelId)) map.moveLayer(labelId);
  }
}
