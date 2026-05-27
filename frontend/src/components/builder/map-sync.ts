import type { Map as MaplibreMap, GeoJSONSource, StyleSpecification, VectorSourceSpecification } from 'maplibre-gl';
import type { FilterSpecification } from 'maplibre-gl';
import { toast } from 'sonner';
import type { MapBasemapConfig, MapLayerResponse, LabelConfig, StyleConfig } from '@/types/api';
import type { RasterTileToken, TileToken, VectorTileToken } from '@/api/tiles';
import i18n from '@/i18n/i18n';
import { buildClusterTileUrl, buildSignedTileUrl } from '@/lib/tile-utils';
import { applyBasemapConfigToStyle } from '@/lib/basemap-utils';
import { sanitizeNullableNumericFilter } from '@/lib/maplibre-filter-utils';
import { isFolderGroupLayer } from '@/lib/layer-capabilities';
import { getAdapter } from './layer-adapters/registry';
import type { AdapterLayerInput } from './layer-adapters/types';
import { buildLabelLayerSpec, syncLabelLayer } from './label-layer-utils';
import { clusterCircleLayerId, clusterCountLayerId, getClusterSourceOptions } from './layer-adapters/cluster-adapter';
import { getClusterSourceStrategy } from './cluster-source';

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
export const TERRAIN_EXAGGERATION_MIN = 0;
export const TERRAIN_EXAGGERATION_MAX = 3;
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

export function isDemTerrainVisualSuppressed(layer: {
  is_dem?: boolean | null;
  style_config?: Pick<StyleConfig, 'render_mode'> | null;
}) {
  return layer.is_dem === true
    && (layer.style_config as { render_mode?: unknown } | null | undefined)?.render_mode === 'terrain';
}

export function normalizeTerrainExaggeration(value: number | null | undefined) {
  if (!Number.isFinite(value)) return 1;
  return Math.min(Math.max(value as number, TERRAIN_EXAGGERATION_MIN), TERRAIN_EXAGGERATION_MAX);
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

export function clearTerrainForStyleSwap(
  map: Pick<MaplibreMap, 'setTerrain' | 'getSource' | 'removeSource'>,
  sourceId = TERRAIN_SOURCE_ID,
) {
  try {
    map.setTerrain(null);
  } catch {
    // Style swaps can run while MapLibre is between style states.
  }

  try {
    if (map.getSource(sourceId)) map.removeSource(sourceId);
  } catch {
    // If MapLibre still considers the source in use, the incoming style swap
    // will drop it and the terrain sync path will recreate it after load.
  }
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
  /** Source-id dedupe (Phase 1050 SF-04): consumed by `getSourceIdForLayer` to
   *  keep non-vector layers (raster/hillshade) on a per-layer source key. */
  layer_type?: string | null;
  dataset_record_type?: string | null;
  tile_url?: string | null;
  tile_size?: number | null;
  minzoom?: number | null;
  maxzoom?: number | null;
  bounds?: number[] | null;
  format?: string | null;
}

/** Options that vary between Builder and Viewer contexts. */
export interface SyncOptions {
  /** Prefix for generated source/layer IDs (default: no prefix, uses "source-"/"layer-" scheme) */
  idPrefix?: string;
  /** When provided, run basemap label reorder using this source prefix after layer order changes */
  showBasemapLabels?: boolean;
  /** Phase 1051 UX-03: when 'top', move basemap fill/raster layers ABOVE data
   *  layers after the standard reorder pass. When 'bottom' (default + legacy),
   *  the standard reorder pipeline already produces data-above-basemap. */
  basemapPosition?: 'top' | 'bottom';
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
    layer_type: layer.layer_type,
    dataset_record_type: layer.dataset_record_type ?? null,
  };
}

function isRasterLikeLayer(layer: SyncLayerInput) {
  return layer.is_dem === true
    || layer.layer_type === 'raster_geolens'
    || layer.dataset_record_type === 'raster_dataset'
    || layer.dataset_record_type === 'vrt_dataset';
}

function rasterTokenFromLayer(layer: SyncLayerInput): RasterTileToken | null {
  if (!isRasterLikeLayer(layer) || !layer.tile_url) return null;
  return {
    kind: 'raster',
    tile_url: layer.tile_url,
    bounds: layer.bounds ?? null,
    minzoom: layer.minzoom ?? 0,
    maxzoom: layer.maxzoom ?? 18,
    tile_size: layer.tile_size ?? 256,
    format: layer.format ?? 'png',
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

/** UX-03 (Phase 1051 Plan 06): when `basemap_position === 'top'`, move all
 *  basemap-loaded style layers (anything whose source DOES NOT start with the
 *  data sourcePrefix) ABOVE the data layers in the MapLibre stack. MapLibre
 *  renders layers in order — last-in-array is painted on top — so calling
 *  `map.moveLayer(id)` with NO `beforeId` moves the layer to the top of the
 *  rendering order.
 *
 *  When `basemap_position === 'bottom'` (default + legacy), do NOTHING — the
 *  existing `reorderDataGeometry` + `reorderDataLabels` already place data
 *  layers above the basemap. Calling this helper in the bottom case would
 *  silently undo that placement.
 *
 *  Idempotent — safe to call from the basemap effect on every render. */
export function reorderBasemapAboveData(
  map: MaplibreMap,
  position: 'top' | 'bottom' | undefined,
  sourcePrefix = 'source-',
) {
  if (position !== 'top') return;
  const style = map.getStyle();
  if (!style?.layers) return;
  for (const layer of style.layers) {
    // basemap layers do NOT have a source matching the data sourcePrefix.
    // 'source' may be undefined for some background-style layers — those count
    // as basemap layers too.
    const src = ('source' in layer) ? String(layer.source ?? '') : '';
    if (src.startsWith(sourcePrefix)) continue;
    if (!map.getLayer(layer.id)) continue;
    try {
      map.moveLayer(layer.id);
    } catch (err) {
      if (import.meta.env.DEV) console.warn('[map-sync] reorderBasemapAboveData moveLayer failed', layer.id, err);
    }
  }
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

const clusterSourceSignatures = new WeakMap<MaplibreMap, Map<string, string>>();

function clusterSourceSignature(input: AdapterLayerInput) {
  const options = getClusterSourceOptions(input);
  return `${options.clusterRadius}:${options.clusterMaxZoom}`;
}

function removeClusterCompanionLayers(map: MaplibreMap, layerId: string) {
  const clusterCountId = clusterCountLayerId(layerId);
  const clusterCircleId = clusterCircleLayerId(layerId);
  if (map.getLayer(clusterCountId)) map.removeLayer(clusterCountId);
  if (map.getLayer(clusterCircleId)) map.removeLayer(clusterCircleId);
}

function signatureStore(map: MaplibreMap) {
  let store = clusterSourceSignatures.get(map);
  if (!store) {
    store = new Map<string, string>();
    clusterSourceSignatures.set(map, store);
  }
  return store;
}

export function getSourceId(layerId: string) {
  return prefixed('source', layerId);
}

export function getLayerId(layerId: string) {
  return prefixed('layer', layerId);
}

/**
 * Derive the MapLibre source id for a given layer.
 *
 * Phase 1050 SF-04 dedupe contract:
 *   - Cluster layers (`getClusterSourceStrategy(layer).kind !== 'fallback'`)
 *     keep their per-layer source id (`source-${layer.id}`). Cluster radius
 *     and minPoints are per-layer settings, so two cluster layers on the
 *     SAME dataset still need separate sources. This preserves the existing
 *     `source-cluster-1` keying that `map-sync.cluster.test.ts` asserts —
 *     the test's layer id is literally `cluster-1`, so `source-${id}` already
 *     produces `source-cluster-1`.
 *   - Non-cluster VECTOR layers with a `dataset_table_name` share one
 *     deduped source per dataset (`source-data-${dataset_table_name}`).
 *     Multiple visual layers on the same dataset_table_name now reuse a
 *     single MapLibre source, eliminating the per-layer tile-request fanout
 *     observed in v1010.1 SF-04 (~80 requests collapse to ~M for M datasets).
 *   - Raster / hillshade / orphan layers (no dataset_table_name) fall back
 *     to the per-layer key (`source-${layer.id}`). Raster sources are
 *     already idempotency-guarded by signed-tile-URL shape and don't share
 *     across layers in practice.
 *
 * `prefix` is the optional Viewer/Embed prefix (e.g. `embed-`) used by
 * `syncLayersToMap`'s `idPrefix` option.
 */
/**
 * Minimal shape accepted by `getSourceIdForLayer`. Compatible with both
 * `SyncLayerInput` (builder/viewer sync) and `MapLayerResponse` (API). All
 * fields are optional except `id`, with `dataset_table_name` being the key
 * input for the dedupe path.
 */
export interface SourceIdLayer {
  id: string;
  dataset_table_name?: string | null;
  dataset_geometry_type?: string | null;
  dataset_record_type?: string | null;
  style_config?: Pick<StyleConfig, 'render_mode'> | null;
  feature_count?: number | null;
  dataset_feature_count?: number | null;
  is_dem?: boolean | null;
  layer_type?: string | null;
}

/** Extract column names a layer needs in MVT tiles to drive paint expressions.
 *
 * The tile server (Phase 269 H-23) projects no attribute columns at z<10 by
 * default, which breaks data-driven styling at zoomed-out views. Listing the
 * referenced columns here lets `buildSignedTileUrl` opt them into the tile
 * via the `cols=` query param so categorical / graduated / heatmap-weight /
 * height-extrusion expressions evaluate against real data at any zoom.
 *
 * Sources considered:
 *  - `style_config.column` — categorical / graduated styling
 *  - paint `_heatmap-weight-column` — heatmap weighting (custom builder prop)
 *  - paint `_height_column` — 3D fill-extrusion height (custom builder prop)
 *  - paint expressions of shape `["get", "<colname>"]` — generic catch-all
 */
export function getDataDrivenColumnsForLayer(
  layer: { style_config?: StyleConfig | null; paint?: Record<string, unknown> },
): string[] {
  const cols = new Set<string>();
  const styleCol = layer.style_config?.column;
  if (typeof styleCol === 'string' && styleCol) cols.add(styleCol);
  const paint = layer.paint ?? {};
  const heatmapWeight = paint['_heatmap-weight-column'];
  if (typeof heatmapWeight === 'string' && heatmapWeight) cols.add(heatmapWeight);
  const heightCol = paint['_height_column'];
  if (typeof heightCol === 'string' && heightCol) cols.add(heightCol);
  // Walk paint expressions for `["get", "<name>"]` references.
  // ["get", x] is the canonical MapLibre way to read a feature property.
  function walk(node: unknown): void {
    if (!Array.isArray(node) || node.length === 0) return;
    if (node[0] === 'get' && typeof node[1] === 'string') {
      cols.add(node[1]);
      return;
    }
    for (const child of node) walk(child);
  }
  for (const val of Object.values(paint)) walk(val);
  return Array.from(cols);
}

/** Union of data-driven columns across every layer sharing a source. */
export function getDataDrivenColumnsForSource(
  sourceId: string,
  layers: SourceIdLayer[],
  prefix?: string,
): string[] {
  const cols = new Set<string>();
  for (const layer of layers) {
    if (getSourceIdForLayer(layer, prefix) !== sourceId) continue;
    const layerWithStyle = layer as SourceIdLayer & {
      style_config?: StyleConfig | null;
      paint?: Record<string, unknown>;
    };
    for (const c of getDataDrivenColumnsForLayer(layerWithStyle)) cols.add(c);
  }
  return Array.from(cols);
}

export function getSourceIdForLayer(
  layer: SourceIdLayer,
  prefix?: string,
) {
  // Cluster layers stay per-layer — cluster radius/minPoints are per-layer
  // settings, so two cluster layers on the same dataset_table_name must
  // each get their own MapLibre source.
  if (getClusterSourceStrategy(layer).kind !== 'fallback') {
    return prefixed('source', layer.id, prefix);
  }
  // Raster / hillshade / DEM layers also stay per-layer. Their tile URL is
  // signed and per-dataset, and they can't share a MapLibre source with a
  // vector layer anyway.
  if (layer.is_dem === true || layer.layer_type === 'raster_geolens') {
    return prefixed('source', layer.id, prefix);
  }
  // Non-cluster VECTOR layers with a known dataset_table_name share one
  // source per dataset (the dedupe).
  if (
    typeof layer.dataset_table_name === 'string'
    && layer.dataset_table_name.length > 0
  ) {
    const p = prefix ?? '';
    return `${p}source-data-${layer.dataset_table_name}`;
  }
  // Fallback: per-layer key.
  return prefixed('source', layer.id, prefix);
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
 *  Phase 1050 SF-04 dedupe: this loop now matches multiple layers in the deduped
 *  case (two non-cluster vector layers on the same `dataset_table_name` share a
 *  source). The "any consumer needs it → emit on the shared source" semantics
 *  is exactly what the forward-compat note anticipated.
 */
function lineGradientNeededFor(
  sourceId: string,
  layers: SyncLayerInput[],
  idPrefix: string | undefined,
): boolean {
  for (const layer of layers) {
    if (getSourceIdForLayer(layer, idPrefix) !== sourceId) continue;
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
  const currentSourceSpec = currentSource ? sourceSpec(currentSource) : {};
  const desiredBounds = normalizeRasterBounds(token.bounds);
  const desiredTileUrl = absolutizeTileUrl(token.tile_url);
  const desiredTileSize = token.tile_size ?? 256;
  const desiredMinzoom = token.minzoom ?? 0;
  const desiredMaxzoom = token.maxzoom ?? 18;

  if (
    (currentLayer && currentLayer.type !== expectedLayerType) ||
    (currentSource && (
      currentSource.type !== expectedSourceType ||
      currentSourceSpec.tiles?.[0] !== desiredTileUrl ||
      currentSourceSpec.tileSize !== desiredTileSize ||
      currentSourceSpec.minzoom !== desiredMinzoom ||
      currentSourceSpec.maxzoom !== desiredMaxzoom ||
      !sameNumberArray(currentSourceSpec.bounds, desiredBounds)
    ))
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
  desiredSources.add(sourceId);

  const resolvedType = resolveAdapterType(layer.dataset_geometry_type, layer.style_config, layer.paint);
  const wantsCluster = resolvedType === 'cluster';
  const clusterStrategy = getClusterSourceStrategy(layer);
  const hasBoundedGeoJson = geojsonDataMap?.has(layer.id) === true;
  const canUseBoundedCluster = wantsCluster && clusterStrategy.kind === 'bounded-geojson' && hasBoundedGeoJson;
  const canUseServerCluster = wantsCluster && clusterStrategy.kind === 'server-tile';
  const canUseCluster = canUseBoundedCluster || canUseServerCluster;
  const type = wantsCluster && !canUseCluster ? 'circle' : resolvedType;
  const adapter = getAdapter(type);
  const filter = adapterInput.filter;
  const clusterOptions = getClusterSourceOptions(adapterInput);
  // Gather data-driven columns from every layer sharing this source. The
  // tile server's z<10 attribute budget would otherwise strip them, breaking
  // categorical / graduated / heatmap / 3D-extrusion paint at low zooms.
  const sharedSourceCols = canUseServerCluster
    ? null
    : getDataDrivenColumnsForSource(sourceId, allLayers, prefix);
  adapterInput.tileUrl = canUseServerCluster
    ? buildClusterTileUrl(layer.dataset_table_name, token, tileBaseUrl, undefined, clusterOptions)
    : buildSignedTileUrl(layer.dataset_table_name, token, tileBaseUrl, undefined, sharedSourceCols);

  // GeoJSON branch: 3D small datasets and eligible Cluster layers use GeoJSON
  // sources instead of the normal vector-tile path.
  // NOTE: GeoJSON sources also support a `lineMetrics` field, but Phase 255 only
  // wires the flag on the vector tile path. GeoJSON-Z line-gradient authoring is
  // Phase 256 scope (see .planning/phases/255-line-gradient-engine-foundation/255-CONTEXT.md).
  const isGeoJsonZ = layer.is_3d && layer.feature_count != null && layer.feature_count <= 5000;
  const useGeoJsonSource = (isGeoJsonZ || canUseBoundedCluster) && hasBoundedGeoJson;
  const desiredSourceType = useGeoJsonSource ? 'geojson' : 'vector';
  const currentSource = map.getSource(sourceId) as { type?: string } | undefined;
  const signatureMap = signatureStore(map);
  const desiredClusterSignature = canUseCluster
    ? `${clusterStrategy.kind}:${clusterSourceSignature(adapterInput)}:${adapterInput.tileUrl}`
    : null;
  const currentClusterSignature = signatureMap.get(sourceId);
  const geoJsonClusterSourceOptionsChanged = canUseBoundedCluster
    && currentSource?.type === 'geojson'
    && currentClusterSignature !== desiredClusterSignature;
  if (currentSource && (currentSource.type !== desiredSourceType || geoJsonClusterSourceOptionsChanged)) {
    removeKnownVectorLayers(map, layerId, layer.id, prefix);
    map.removeSource(sourceId);
    signatureMap.delete(sourceId);
  }
  if (!canUseCluster) {
    removeClusterCompanionLayers(map, layerId);
    signatureMap.delete(sourceId);
  }

  const layerLayout = layer.layout ?? {};
  const layerMinzoom = (layerLayout['_minzoom'] as number) ?? 0;
  const layerMaxzoom = (layerLayout['_maxzoom'] as number) ?? 22;

  if (useGeoJsonSource) {
    const geojsonData = geojsonDataMap.get(layer.id)!;
    adapterInput.sourceType = 'geojson';
    if (!map.getSource(sourceId)) {
      if (canUseBoundedCluster) {
        map.addSource(sourceId, {
          type: 'geojson',
          data: geojsonData,
          cluster: true,
          ...clusterOptions,
        });
        signatureMap.set(sourceId, desiredClusterSignature ?? '');
      } else {
        map.addSource(sourceId, { type: 'geojson', data: geojsonData });
        signatureMap.delete(sourceId);
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
    if (canUseServerCluster && desiredClusterSignature) {
      signatureMap.set(sourceId, desiredClusterSignature);
    } else {
      signatureMap.delete(sourceId);
    }
    adapter.addLayers(map, adapterInput);
  } else {
    adapterInput.sourceType = 'vector';
    if (canUseServerCluster && currentClusterSignature !== desiredClusterSignature) {
      const source = map.getSource(sourceId) as { type?: string; setTiles?: (tiles: string[]) => void } | undefined;
      if (source?.type === 'vector' && source.setTiles) {
        source.setTiles([adapterInput.tileUrl]);
      }
      if (desiredClusterSignature) signatureMap.set(sourceId, desiredClusterSignature);
    }
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
  const renderableLayers = layers.filter((layer) => !isFolderGroupLayer(layer));

  const currentSources = new Set(managedSourcesRef.current);
  const desiredSources = new Set<string>();

  for (const layer of renderableLayers) {
    try {
      if (isDemTerrainVisualSuppressed(layer)) {
        continue;
      }

      // SF-04 dedupe: non-cluster vector layers sharing a dataset_table_name
      // now resolve to one shared source id; cluster + raster/DEM layers stay
      // per-layer. Layer ids (per-layer paint/visibility) remain unchanged.
      const sourceId = getSourceIdForLayer(layer, prefix);
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

      const rasterToken = token?.kind === 'raster' ? token : rasterTokenFromLayer(layer);
      if (rasterToken) {
        syncRasterLayer(map, adapterInput, rasterToken, desiredSources);
      } else {
        const vectorToken = token?.kind === 'vector' ? token : null;
        syncVectorLayer(map, layer, renderableLayers, adapterInput, tileBaseUrl, vectorToken, desiredSources, geojsonDataMap, prefix);
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
  // UX-03 (Phase 1051 Plan 06): include basemap_position so dragging basemap
  // top↔bottom invalidates the orderKey and re-runs the reorder pipeline.
  const orderKey = renderableLayers.map((l) => l.id).join(',')
    + (options?.showBasemapLabels !== undefined ? `|${String(options.showBasemapLabels)}` : '')
    + (options?.basemapPosition !== undefined ? `|bp:${options.basemapPosition}` : '')
    + `|${map.getStyle()?.layers?.length ?? 0}`;
  if (orderKey !== lastOrderKeyRef.current) {
    lastOrderKeyRef.current = orderKey;
    // Target z-order: data geometries → basemap labels → data labels
    reorderDataGeometry(map, renderableLayers, prefix);
    if (options?.showBasemapLabels !== undefined) {
      reorderBasemapLabels(map, options.showBasemapLabels, sourcePrefix);
    }
    reorderDataLabels(map, renderableLayers, prefix);
    // UX-03: basemap-above-data inversion runs LAST so it overrides the
    // standard data-above-basemap stack ordering when position='top'.
    reorderBasemapAboveData(map, options?.basemapPosition, sourcePrefix);
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
