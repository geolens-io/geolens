import type { Map as MaplibreMap, GeoJSONSource, StyleSpecification, VectorSourceSpecification } from 'maplibre-gl';
import type { FilterSpecification } from 'maplibre-gl';
import { toast } from 'sonner';
import type { MapBasemapConfig, MapLayerResponse, LabelConfig, StyleConfig } from '@/types/api';
import type { RasterTileToken, TileToken, VectorTileToken } from '@/api/tiles';
import i18n from '@/i18n/i18n';
import { buildSignedTileUrl } from '@/lib/tile-utils';
import { applyBasemapConfigToStyle } from '@/lib/basemap-utils';
import { sanitizeNullableNumericFilter } from '@/lib/maplibre-filter-utils';
import { getAdapter } from './layer-adapters/registry';
import type { AdapterLayerInput } from './layer-adapters/types';
import { buildLabelLayerSpec, syncLabelLayer } from './label-layer-utils';
import { clusterCircleLayerId, clusterCountLayerId, getClusterSourceOptions } from './layer-adapters/cluster-adapter';

// Shared utilities — imported for local use and re-exported for backward compatibility
import { getLayerType, resolveAdapterType } from './layer-adapters/shared';
// Re-export for backward compatibility with existing consumers
export {
  CUSTOM_PAINT_PROPS,
  getLayerType,
  resolveAdapterType,
  simplifyPaint,
  getCompoundOpacity,
  getExpressionSafeOpacity,
  stripCustomProps,
  filterPaintForLayerType,
} from './layer-adapters/shared';

export const TERRAIN_SOURCE_ID = 'terrain-dem';
export const MAP_STACK_Z_ORDER_POLICY = [
  'surface terrain',
  'basemap relief and detail',
  'user data geometry',
  'basemap labels',
  'user data labels',
] as const;

export function isTerrainCapableDemLayer(layer: {
  is_dem?: boolean | null;
  dataset_record_type?: string | null;
}) {
  return layer.is_dem === true
    && (layer.dataset_record_type === 'raster_dataset' || layer.dataset_record_type === 'vrt_dataset');
}

export function normalizeTerrainExaggeration(value: number | null | undefined) {
  if (!Number.isFinite(value)) return 1;
  return Math.min(Math.max(value as number, 0), 10);
}

type RasterBounds = [number, number, number, number];

function normalizeRasterBounds(bounds: number[] | null | undefined): RasterBounds | undefined {
  if (!Array.isArray(bounds) || bounds.length !== 4) return undefined;
  if (!bounds.every((value) => Number.isFinite(value))) return undefined;
  return [bounds[0], bounds[1], bounds[2], bounds[3]];
}

function absolutizeTileUrl(tileUrl: string) {
  if (tileUrl.startsWith('http')) return tileUrl;
  const origin = typeof window === 'undefined' ? '' : window.location.origin;
  return `${origin}${tileUrl}`;
}

function sourceSpec(source: unknown) {
  return (source as { serialize?: () => { tiles?: string[]; bounds?: number[]; tileSize?: number; minzoom?: number; maxzoom?: number } } | null)
    ?.serialize?.()
    ?? (source as { tiles?: string[]; bounds?: number[]; tileSize?: number; minzoom?: number; maxzoom?: number } | null)
    ?? {};
}

function sameNumberArray(left: number[] | undefined, right: number[] | undefined) {
  if (left == null && right == null) return true;
  if (!left || !right || left.length !== right.length) return false;
  return left.every((value, index) => value === right[index]);
}

export function ensureRasterDemTerrainSource(
  map: MaplibreMap,
  tileUrl: string,
  options: {
    sourceId?: string;
    tileSize?: number | null;
    minzoom?: number | null;
    maxzoom?: number | null;
    bounds?: number[] | null;
  } = {},
) {
  const sourceId = options.sourceId ?? TERRAIN_SOURCE_ID;
  const absoluteTileUrl = absolutizeTileUrl(tileUrl);
  const bounds = normalizeRasterBounds(options.bounds);
  const existing = map.getSource(sourceId) as { type?: string } | undefined;
  const existingSpec = existing ? sourceSpec(existing) : {};
  const existingTiles = Array.isArray(existingSpec.tiles) ? existingSpec.tiles : [];
  const shouldReplace = existing
    && (
      existing.type !== 'raster-dem'
      || existingTiles[0] !== absoluteTileUrl
      || !sameNumberArray(existingSpec.bounds, bounds)
      || existingSpec.tileSize !== (options.tileSize ?? 256)
      || existingSpec.minzoom !== (options.minzoom ?? 0)
      || existingSpec.maxzoom !== (options.maxzoom ?? 18)
    );

  if (shouldReplace) {
    map.setTerrain(null);
    map.removeSource(sourceId);
  }

  if (!map.getSource(sourceId)) {
    map.addSource(sourceId, {
      type: 'raster-dem',
      tiles: [absoluteTileUrl],
      tileSize: options.tileSize ?? 256,
      minzoom: options.minzoom ?? 0,
      maxzoom: options.maxzoom ?? 18,
      ...(bounds ? { bounds } : {}),
      encoding: 'mapbox',
    });
  }

  return sourceId;
}

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
  is_dem?: boolean | null;
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
    is_dem: layer.is_dem,
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

function basemapStyleLayers(style: StyleSpecification, sourcePrefix: string) {
  return style.layers.filter(
    (layer) => !('source' in layer) || !String(layer.source ?? '').startsWith(sourcePrefix),
  ) as StyleSpecification['layers'];
}

function changedPaintKeys(
  before: Record<string, unknown> | undefined,
  after: Record<string, unknown> | undefined,
) {
  if (!after) return [];
  return Object.keys(after).filter((key) => before?.[key] !== after[key]);
}

/** Apply curated basemap appearance controls to the loaded MapLibre style. */
export function applyBasemapConfigToMap(
  map: MaplibreMap,
  basemapConfig: MapBasemapConfig | null | undefined,
  showBasemapLabels = true,
  sourcePrefix = 'source-',
) {
  const style = map.getStyle() as StyleSpecification | undefined;
  if (!style?.layers) return;

  const basemapOnlyStyle: StyleSpecification = {
    ...style,
    layers: basemapStyleLayers(style, sourcePrefix),
  };
  const nextStyle = applyBasemapConfigToStyle(
    basemapOnlyStyle,
    basemapConfig,
    showBasemapLabels,
  );
  const nextById = new Map(nextStyle.layers.map((layer) => [layer.id, layer]));

  for (const current of basemapOnlyStyle.layers) {
    const next = nextById.get(current.id);
    if (!next || !map.getLayer(current.id)) continue;

    const currentLayout = 'layout' in current ? current.layout as Record<string, unknown> | undefined : undefined;
    const nextLayout = 'layout' in next ? next.layout as Record<string, unknown> | undefined : undefined;
    if (currentLayout?.visibility !== nextLayout?.visibility && nextLayout?.visibility != null) {
      try {
        map.setLayoutProperty(current.id, 'visibility', nextLayout.visibility);
      } catch (error) {
        if (import.meta.env.DEV) console.warn('[map-sync] basemap layout sync failed', current.id, error);
      }
    }

    const currentPaint = 'paint' in current ? current.paint as Record<string, unknown> | undefined : undefined;
    const nextPaint = 'paint' in next ? next.paint as Record<string, unknown> | undefined : undefined;
    for (const key of changedPaintKeys(currentPaint, nextPaint)) {
      try {
        map.setPaintProperty(current.id, key, nextPaint?.[key]);
      } catch (error) {
        if (import.meta.env.DEV) console.warn('[map-sync] basemap paint sync failed', current.id, key, error);
      }
    }
  }
}

export function prefixed(kind: 'source' | 'layer' | 'outline' | 'extrusion' | 'arrow' | 'label', id: string, prefix?: string) {
  const p = prefix ?? '';
  switch (kind) {
    case 'source':  return `${p}source-${id}`;
    case 'layer':   return `${p}layer-${id}`;
    case 'outline': return `${p}layer-${id}-outline`;
    case 'extrusion': return `${p}layer-${id}-extrusion`;
    case 'arrow': return `${p}layer-${id}-arrow`;
    case 'label':   return `${p}layer-${id}-label`;
  }
}

function removeKnownVectorLayers(map: MaplibreMap, layerId: string, id: string, prefix: string | undefined) {
  const labelId = prefixed('label', id, prefix);
  const arrowId = prefixed('arrow', id, prefix);
  const extrusionId = prefixed('extrusion', id, prefix);
  const outlineId = prefixed('outline', id, prefix);
  const clusterCountId = clusterCountLayerId(layerId);
  const clusterCircleId = clusterCircleLayerId(layerId);

  for (const candidate of [labelId, arrowId, extrusionId, outlineId, clusterCountId, clusterCircleId, layerId]) {
    if (map.getLayer(candidate)) map.removeLayer(candidate);
  }
}

function syncLayerZoomRange(map: MaplibreMap, layerIds: string[], minzoom: number, maxzoom: number) {
  for (const id of layerIds) {
    if (map.getLayer(id)) {
      map.setLayerZoomRange(id, minzoom, maxzoom);
    }
  }
}

export function getSourceId(layerId: string) {
  return prefixed('source', layerId);
}

export function getLayerId(layerId: string) {
  return prefixed('layer', layerId);
}

/** Detect whether any layer using this sourceId needs `lineMetrics: true`.
 *  A layer "needs" the flag when:
 *    - paint['line-gradient'] is set (any value — string, array expression, or object), OR
 *    - style_config.builder.lineGradient is a non-empty plain object (Phase 256 builder intent stub).
 *  Contract (locked): builder.lineGradient must be a plain object (NOT an array). Both this
 *  helper and the backend `_layer_uses_line_gradient` reject array-shaped intent. Phase 256
 *  builder UI must serialize stops as `{stops: [...]}` (or similar object wrapper), never as a
 *  bare array. Detection rule per .planning/phases/255-line-gradient-engine-foundation/255-CONTEXT.md D-01.
 *
 *  Implementation note: `lineGradientNeededFor` iterates the full layer list for structural
 *  symmetry with the backend `_layer_uses_line_gradient`. In the current frontend each layer
 *  has its own per-layer source-id (derived from layer.id), so this loop matches at most one
 *  layer in practice. The full-list iteration is intentional forward-compatibility for any
 *  future move to dataset-keyed sources. */
function lineGradientNeededFor(
  sourceId: string,
  layers: SyncLayerInput[],
  idPrefix: string | undefined,
): boolean {
  for (const layer of layers) {
    if (prefixed('source', layer.id, idPrefix) !== sourceId) continue;
    const paint = layer.paint ?? {};
    if (paint['line-gradient'] != null) return true;
    const builder = (layer.style_config as { builder?: { lineGradient?: unknown } } | null | undefined)?.builder;
    const intent = builder?.lineGradient;
    // Must be a non-null, non-array plain object with at least one key. Arrays are rejected
    // for parity with the backend (`isinstance(intent, dict)`); see CONTEXT D-01.
    if (
      intent != null
      && typeof intent === 'object'
      && !Array.isArray(intent)
      && Object.keys(intent as object).length > 0
    ) {
      return true;
    }
  }
  return false;
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
  adapterInput.bounds = token.bounds;
  const renderMode = adapterInput.style_config?.render_mode;
  const useHillshade = adapterInput.is_dem === true && renderMode === 'hillshade';
  const adapter = getAdapter(useHillshade ? 'hillshade' : 'raster');
  const expectedLayerType = useHillshade ? 'hillshade' : 'raster';
  const expectedSourceType = useHillshade ? 'raster-dem' : 'raster';
  const currentLayer = map.getLayer(adapterInput.layerId) as { type?: string } | undefined;
  const currentSource = map.getSource(adapterInput.sourceId) as { type?: string } | undefined;

  if (
    (currentLayer && currentLayer.type !== expectedLayerType) ||
    (currentSource && currentSource.type !== expectedSourceType)
  ) {
    if (map.getLayer(adapterInput.layerId)) map.removeLayer(adapterInput.layerId);
    if (map.getSource(adapterInput.sourceId)) map.removeSource(adapterInput.sourceId);
  }

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
  allLayers: SyncLayerInput[],
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

  const resolvedType = resolveAdapterType(layer.dataset_geometry_type, layer.style_config, layer.paint);
  const wantsCluster = resolvedType === 'cluster';
  const hasBoundedGeoJson = geojsonDataMap?.has(layer.id) === true;
  const canUseCluster = wantsCluster && hasBoundedGeoJson;
  const type = wantsCluster && !canUseCluster ? 'circle' : resolvedType;
  const adapter = getAdapter(type);
  const filter = adapterInput.filter;

  // GeoJSON branch: 3D small datasets and eligible Cluster layers use GeoJSON
  // sources instead of the normal vector-tile path.
  // NOTE: GeoJSON sources also support a `lineMetrics` field, but Phase 255 only
  // wires the flag on the vector tile path. GeoJSON-Z line-gradient authoring is
  // Phase 256 scope (see .planning/phases/255-line-gradient-engine-foundation/255-CONTEXT.md).
  const isGeoJsonZ = layer.is_3d && layer.feature_count != null && layer.feature_count <= 5000;
  const useGeoJsonSource = (isGeoJsonZ || canUseCluster) && hasBoundedGeoJson;
  const desiredSourceType = useGeoJsonSource ? 'geojson' : 'vector';
  const currentSource = map.getSource(sourceId) as { type?: string } | undefined;
  if (currentSource && currentSource.type !== desiredSourceType) {
    removeKnownVectorLayers(map, layerId, layer.id, prefix);
    map.removeSource(sourceId);
  }

  const layerLayout = layer.layout ?? {};
  const layerMinzoom = (layerLayout['_minzoom'] as number) ?? 0;
  const layerMaxzoom = (layerLayout['_maxzoom'] as number) ?? 22;

  if (useGeoJsonSource) {
    const geojsonData = geojsonDataMap.get(layer.id)!;
    adapterInput.sourceType = 'geojson';
    if (!map.getSource(sourceId)) {
      if (canUseCluster) {
        map.addSource(sourceId, {
          type: 'geojson',
          data: geojsonData,
          cluster: true,
          ...getClusterSourceOptions(adapterInput),
        });
      } else {
        map.addSource(sourceId, { type: 'geojson', data: geojsonData });
      }
      adapter.addLayers(map, adapterInput);
    } else {
      const src = map.getSource(sourceId);
      if (src && src.type === 'geojson') (src as GeoJSONSource).setData(geojsonData);
      adapter.syncPaint(map, adapterInput);
    }
    adapter.syncVisibility(map, adapterInput);
    syncLayerZoomRange(map, adapter.getLayerIds(layerId), layerMinzoom, layerMaxzoom);
    return;
  }

  if (!map.getSource(sourceId)) {
    const needsLineMetrics = lineGradientNeededFor(sourceId, allLayers, prefix);
    // lineMetrics is sticky per D-02 (255-CONTEXT.md): we only set it at source CREATE time.
    // Removing line-gradient mid-session does NOT tear down the source — the cost of leaving
    // the per-vertex distance computation on is small compared to the visual jank of recreation.
    const sourceSpec: VectorSourceSpecification = {
      type: 'vector',
      tiles: [adapterInput.tileUrl],
      minzoom: 1,
      maxzoom: 22,
      ...(needsLineMetrics && { lineMetrics: true }),
    };
    map.addSource(sourceId, sourceSpec);
    adapter.addLayers(map, adapterInput);
  } else {
    adapter.syncPaint(map, adapterInput);
  }

  // Per-layer zoom range from custom layout props (main + outline companion)
  const outlineLayerId = prefixed('outline', layer.id, prefix);
  const extrusionLayerId = prefixed('extrusion', layer.id, prefix);
  const arrowLayerId = prefixed('arrow', layer.id, prefix);
  syncLayerZoomRange(map, [layerId, outlineLayerId, extrusionLayerId, arrowLayerId], layerMinzoom, layerMaxzoom);

  // Sync companion label layer (add/update/remove). Heatmap layers don't support
  // labels, and symbol layers consolidate icon/text in the primary symbol layer.
  const labelId = prefixed('label', layer.id, prefix);
  const isHeatmap = type === 'heatmap';
  const isSymbol = type === 'symbol';
  if (map.getSource(sourceId)) {
    if (layer.label_config?.column && !isHeatmap && !isSymbol) {
      const lc = layer.label_config;
      const geomType = getLayerType(layer.dataset_geometry_type);
      const vis = layer.visible ? 'visible' : 'none';

      if (!map.getLayer(labelId)) {
        map.addLayer(buildLabelLayerSpec({ labelId, sourceId, sourceLayer, lc, geomType, visibility: vis }));
        if (filter) map.setFilter(labelId, filter);
      } else {
        syncLabelLayer(map, labelId, lc, geomType);
        map.setFilter(labelId, filter ?? null);
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
  if (map.getLayer(labelId) && !isHeatmap && !isSymbol) {
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
    const extrusionId = prefixed('extrusion', id, prefix);
    const arrowId = prefixed('arrow', id, prefix);
    const clusterCountId = clusterCountLayerId(layerId);
    const clusterCircleId = clusterCircleLayerId(layerId);
    if (map.getLayer(labelId)) map.removeLayer(labelId);
    if (map.getLayer(arrowId)) map.removeLayer(arrowId);
    if (map.getLayer(extrusionId)) map.removeLayer(extrusionId);
    if (map.getLayer(outlineId)) map.removeLayer(outlineId);
    if (map.getLayer(clusterCountId)) map.removeLayer(clusterCountId);
    if (map.getLayer(clusterCircleId)) map.removeLayer(clusterCircleId);
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

      const adapterInput: AdapterLayerInput & { style_config?: StyleConfig | null } = {
        id: layer.id,
        dataset_table_name: layer.dataset_table_name,
        dataset_geometry_type: layer.dataset_geometry_type,
        opacity: layer.opacity ?? 1,
        visible: layer.visible,
        paint: layer.paint ?? {},
        layout: layer.layout ?? {},
        filter: sanitizeNullableNumericFilter(layer.filter),
        label_config: layer.label_config,
        is_dem: layer.is_dem,
        sourceId,
        layerId,
        sourceLayer,
        tileUrl: '',
        style_config: layer.style_config ?? null,
      };

      if (token?.kind === 'raster') {
        syncRasterLayer(map, adapterInput, token, desiredSources);
      } else {
        syncVectorLayer(map, layer, layers, adapterInput, tileBaseUrl, token, desiredSources, geojsonDataMap, prefix);
      }
    } catch (err) {
      if (import.meta.env.DEV) console.error('[map-sync] layer sync failed', layer.id, err);
      toast.error(i18n.t('builder:toasts.layerSyncFailed', { name: layer.dataset_table_name }), { id: `sync-error-${layer.id}` });
    }
  }

  try {
    removeStaleSourcesAndLayers(map, currentSources, desiredSources, sourcePrefix, prefix);
    managedSourcesRef.current = desiredSources;
  } catch (err) {
    // On failure, keep managedSourcesRef at pre-removal value so next sync retries cleanup.
    // DEV-only diagnostic — silenced in production to keep the runtime console clean.
    if (import.meta.env.DEV) console.warn('[map-sync] removeStaleSourcesAndLayers failed', err);
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
    const lid = prefixed('layer', layers[i].id, idPrefix);
    const oid = prefixed('outline', layers[i].id, idPrefix);
    const eid = prefixed('extrusion', layers[i].id, idPrefix);
    const aid = prefixed('arrow', layers[i].id, idPrefix);
    const cid = clusterCircleLayerId(lid);
    const ccid = clusterCountLayerId(lid);
    if (map.getLayer(cid)) map.moveLayer(cid);
    if (map.getLayer(ccid)) map.moveLayer(ccid);
    if (map.getLayer(lid)) map.moveLayer(lid);
    if (map.getLayer(aid)) map.moveLayer(aid);
    if (map.getLayer(eid)) map.moveLayer(eid);
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
    const labelId = prefixed('label', layers[i].id, idPrefix);
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
