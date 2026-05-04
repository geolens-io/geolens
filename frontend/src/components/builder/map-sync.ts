import type { Map as MaplibreMap, GeoJSONSource } from 'maplibre-gl';
import type { FilterSpecification } from 'maplibre-gl';
import { toast } from 'sonner';
import type { MapLayerResponse, LabelConfig, StyleConfig } from '@/types/api';
import type { RasterTileToken, TileToken, VectorTileToken } from '@/api/tiles';
import { buildSignedTileUrl } from '@/lib/tile-utils';
import { getAdapter } from './layer-adapters/registry';
import type { AdapterLayerInput } from './layer-adapters/types';
import { buildLabelLayerSpec, syncLabelLayer } from './label-layer-utils';

// Shared utilities — imported for local use and re-exported for backward compatibility
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
    paint: layer.paint ?? {},
    layout: layer.layout ?? {},
    filter: layer.filter,
    label_config: layer.label_config ?? null,
    style_config: layer.style_config ?? null,
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
    if (!map.getLayer(layer.id)) continue;
    if (show) {
      map.setLayoutProperty(layer.id, 'visibility', 'visible');
      map.moveLayer(layer.id);
    } else {
      map.setLayoutProperty(layer.id, 'visibility', 'none');
    }
  }
}

export function prefixed(kind: 'source' | 'layer' | 'outline' | 'label', id: string, prefix?: string) {
  const p = prefix ?? '';
  switch (kind) {
    case 'source':  return `${p}source-${id}`;
    case 'layer':   return `${p}layer-${id}`;
    case 'outline': return `${p}layer-${id}-outline`;
    case 'label':   return `${p}layer-${id}-label`;
  }
}


export function getSourceId(layerId: string) {
  return prefixed('source', layerId);
}

export function getLayerId(layerId: string) {
  return prefixed('layer', layerId);
}

// ---------------------------------------------------------------------------
// Sync sub-routines — extracted from syncLayersToMap for readability
// ---------------------------------------------------------------------------

/** Add or update a raster layer on the map. */
function syncRasterLayer(
  map: MaplibreMap,
  adapterInput: AdapterLayerInput,
  token: RasterTileToken,
  desiredSources: Set<string>,
) {
  adapterInput.tileUrl = token.tile_url;
  adapterInput.tileSize = token.tile_size ?? 256;
  adapterInput.minzoom = token.minzoom ?? 0;
  adapterInput.maxzoom = token.maxzoom ?? 18;
  const adapter = getAdapter('raster');
  if (!map.getSource(adapterInput.sourceId)) {
    adapter.addLayers(map, adapterInput);
  } else {
    adapter.syncPaint(map, adapterInput);
  }
  desiredSources.add(adapterInput.sourceId);
}

/** Add or update a vector (MVT / GeoJSON-Z) layer, including labels and visibility. */
function syncVectorLayer(
  map: MaplibreMap,
  layer: SyncLayerInput,
  adapterInput: AdapterLayerInput,
  tileBaseUrl: string | undefined,
  token: VectorTileToken | null,
  desiredSources: Set<string>,
  geojsonDataMap: Map<string, GeoJSON.FeatureCollection> | undefined,
  prefix: string | undefined,
) {
  const { sourceId, layerId, sourceLayer } = adapterInput;
  adapterInput.tileUrl = buildSignedTileUrl(layer.dataset_table_name, token, tileBaseUrl);
  desiredSources.add(sourceId);

  const type = resolveAdapterType(layer.dataset_geometry_type, layer.style_config, layer.paint);
  const adapter = getAdapter(type);

  // GeoJSON-Z branch: 3D small datasets use GeoJSON source instead of MVT
  const isGeoJsonZ = layer.is_3d && layer.feature_count != null && layer.feature_count <= 5000;
  if (isGeoJsonZ && geojsonDataMap?.has(layer.id)) {
    const geojsonData = geojsonDataMap.get(layer.id)!;
    adapterInput.sourceType = 'geojson';
    if (!map.getSource(sourceId)) {
      map.addSource(sourceId, { type: 'geojson', data: geojsonData });
      adapter.addLayers(map, adapterInput);
    } else {
      const src = map.getSource(sourceId);
      if (src && src.type === 'geojson') (src as GeoJSONSource).setData(geojsonData);
      adapter.syncPaint(map, adapterInput);
    }
    adapter.syncVisibility(map, adapterInput);
    return;
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

  // Per-layer zoom range from custom layout props (main + outline companion)
  const layerLayout = layer.layout ?? {};
  const layerMinzoom = (layerLayout['_minzoom'] as number) ?? 0;
  const layerMaxzoom = (layerLayout['_maxzoom'] as number) ?? 22;
  if (map.getLayer(layerId)) {
    map.setLayerZoomRange(layerId, layerMinzoom, layerMaxzoom);
  }
  const outlineLayerId = prefixed('outline', layer.id, prefix);
  if (map.getLayer(outlineLayerId)) {
    map.setLayerZoomRange(outlineLayerId, layerMinzoom, layerMaxzoom);
  }

  // Sync label layer (add/update/remove). Heatmap layers don't support labels.
  const labelId = prefixed('label', layer.id, prefix);
  const isHeatmap = type === 'heatmap';
  if (map.getSource(sourceId)) {
    if (layer.label_config?.column && !isHeatmap) {
      const lc = layer.label_config;
      const geomType = getLayerType(layer.dataset_geometry_type);
      const vis = layer.visible ? 'visible' : 'none';

      if (!map.getLayer(labelId)) {
        map.addLayer(buildLabelLayerSpec({ labelId, sourceId, sourceLayer, lc, geomType, visibility: vis }));
        if (layer.filter) map.setFilter(labelId, layer.filter);
      } else {
        syncLabelLayer(map, labelId, lc, geomType);
        map.setFilter(labelId, layer.filter ?? null);
      }
    } else if (map.getLayer(labelId)) {
      if (isHeatmap) {
        map.setLayoutProperty(labelId, 'visibility', 'none');
      } else {
        map.removeLayer(labelId);
      }
    }
  }

  adapter.syncVisibility(map, adapterInput);
  if (map.getLayer(labelId) && !isHeatmap) {
    const vis = layer.visible ? 'visible' : 'none';
    map.setLayoutProperty(labelId, 'visibility', vis);
  }
}

/** Remove map layers and sources that are no longer in the desired set. */
function removeStaleSourcesAndLayers(
  map: MaplibreMap,
  currentSources: Set<string>,
  desiredSources: Set<string>,
  sourcePrefix: string,
  prefix: string | undefined,
) {
  for (const sourceId of currentSources) {
    if (desiredSources.has(sourceId)) continue;
    const id = sourceId.replace(sourcePrefix, '');
    const layerId = prefixed('layer', id, prefix);
    const outlineId = prefixed('outline', id, prefix);
    const labelId = prefixed('label', id, prefix);
    const extrusionId = `${prefix ?? ''}layer-${id}-extrusion`;
    if (map.getLayer(labelId)) map.removeLayer(labelId);
    if (map.getLayer(extrusionId)) map.removeLayer(extrusionId);
    if (map.getLayer(outlineId)) map.removeLayer(outlineId);
    if (map.getLayer(layerId)) map.removeLayer(layerId);
    if (map.getSource(sourceId)) map.removeSource(sourceId);
  }
}

// ---------------------------------------------------------------------------

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
    try {
      const sourceId = prefixed('source', layer.id, prefix);
      const layerId = prefixed('layer', layer.id, prefix);
      const sourceLayer = `data.${layer.dataset_table_name}`;
      const token = tokenMap.get(layer.dataset_id) ?? null;

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
        tileUrl: '',
      };

      if (token?.kind === 'raster') {
        syncRasterLayer(map, adapterInput, token, desiredSources);
      } else {
        syncVectorLayer(map, layer, adapterInput, tileBaseUrl, token, desiredSources, geojsonDataMap, prefix);
      }
    } catch (err) {
      if (import.meta.env.DEV) console.error('[map-sync] layer sync failed', layer.id, err);
      toast.error(`Layer sync failed for "${layer.dataset_table_name}"`, { id: `sync-error-${layer.id}` });
    }
  }

  try {
    removeStaleSourcesAndLayers(map, currentSources, desiredSources, sourcePrefix, prefix);
    managedSourcesRef.current = desiredSources;
  } catch (err) {
    // On failure, keep managedSourcesRef at pre-removal value so next sync retries cleanup
    console.warn('[map-sync] removeStaleSourcesAndLayers failed', err);
  }

  // Only reorder when layer order actually changed (not on every paint/visibility sync).
  // Include total style layer count so basemap switches invalidate the key.
  const orderKey = layers.map((l) => l.id).join(',')
    + (options?.showBasemapLabels !== undefined ? `|${String(options.showBasemapLabels)}` : '')
    + `|${map.getStyle()?.layers?.length ?? 0}`;
  if (orderKey !== lastOrderKeyRef.current) {
    lastOrderKeyRef.current = orderKey;
    // Target z-order: data geometries → basemap labels → data labels
    reorderDataGeometry(map, layers, prefix);
    if (options?.showBasemapLabels !== undefined) {
      reorderBasemapLabels(map, options.showBasemapLabels, sourcePrefix);
    }
    reorderDataLabels(map, layers, prefix);
  }
}

/** Move data geometry layers (fill/line/circle + outlines) to the top of the stack.
 *  Reverse iterate so first-in-array (index 0) ends up topmost. */
function reorderDataGeometry(
  map: MaplibreMap,
  layers: Pick<SyncLayerInput, 'id'>[],
  idPrefix?: string,
) {
  for (let i = layers.length - 1; i >= 0; i--) {
    const lid = prefixed('layer',layers[i].id, idPrefix);
    const oid = prefixed('outline',layers[i].id, idPrefix);
    if (map.getLayer(lid)) map.moveLayer(lid);
    if (map.getLayer(oid)) map.moveLayer(oid);
  }
}

/** Move data label layers to the top of the stack (above everything else). */
function reorderDataLabels(
  map: MaplibreMap,
  layers: Pick<SyncLayerInput, 'id'>[],
  idPrefix?: string,
) {
  for (let i = layers.length - 1; i >= 0; i--) {
    const labelId = prefixed('label',layers[i].id, idPrefix);
    if (map.getLayer(labelId)) map.moveLayer(labelId);
  }
}

/** Convenience: reorder both geometry and labels in one call (no basemap interleave). */
export function reorderDataLayers(
  map: MaplibreMap,
  layers: Pick<SyncLayerInput, 'id'>[],
  idPrefix?: string,
) {
  reorderDataGeometry(map, layers, idPrefix);
  reorderDataLabels(map, layers, idPrefix);
}
