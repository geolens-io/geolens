import type {
  Map as MaplibreMap,
  GeoJSONSource,
  GeoJSONSourceSpecification,
  RasterDEMSourceSpecification,
  RasterSourceSpecification,
  StyleSpecification,
  VectorSourceSpecification,
} from 'maplibre-gl';
import type { FilterSpecification } from 'maplibre-gl';
import { toast } from 'sonner';
import type { MapBasemapConfig, MapLayerResponse, LabelConfig, StyleConfig, MapTerrainConfig, PopupConfig } from '@/types/api';
import type { TileToken } from '@/api/tiles';
import i18n from '@/i18n/i18n';
import {
  applyBasemapConfigToStyle,
  isBasemapOwnedLayer,
  isLandLayer,
  isWaterLayer,
} from '@/lib/basemap-utils';
import { isFolderGroupLayer } from '@/lib/layer-capabilities';
import { toMapLibreAttribution } from '@/lib/attribution-safety';
import { normalizeDemStyleConfig } from '@/lib/dem-render-mode';
import { getAdapter } from './layer-adapters/registry';
import type { AdapterLayerInput, LayerAdapter } from './layer-adapters/types';
import {
  adapterInputFor,
  describeLayers,
  type DescribedLayer,
  type Description,
  type RenderContext,
} from './layer-description';
import { clusterCircleLayerId, clusterCountLayerId, getClusterSourceOptions } from './layer-adapters/cluster-adapter';
import { mixedLinesLayerId, mixedPointsLayerId } from './layer-adapters/mixed-adapter';
import { getClusterSourceStrategy } from './cluster-source';
import { getCompanionLayerIds, getDrawingLayerIds, COLOR_RELIEF_SUFFIX } from './companion-ids';
import { finishDescribedLayer } from './layer-writer';

import {
  filterSpec,
  normalizeRasterBounds,
  setDynamicLayoutProperty,
  setDynamicPaintProperty,
} from './layer-adapters/shared';
// Re-export the single isTerrainCapableDemLayer predicate from map-stack so the
// legend, the delete-time terrain-clear check and the 3D mesh resolver
// (BuilderMap imports it from here) share one definition.
export { isTerrainCapableDemLayer } from './map-stack';
export {
  CUSTOM_PAINT_PROPS,
  getLayerType,
  resolveAdapterType,
  simplifyPaint,
  getExpressionSafeOpacity,
  stripCustomProps,
} from './layer-adapters/shared';
export {
  getDataDrivenColumnsForLayer,
  getDataDrivenColumnsForSource,
  getSourceIdForLayer,
  isDemTerrainVisualSuppressed,
} from './layer-description';

export const TERRAIN_SOURCE_ID = 'terrain-dem';
export const TERRAIN_EXAGGERATION_MIN = 0;
export const TERRAIN_EXAGGERATION_MAX = 3;

export function normalizeTerrainExaggeration(value: number | null | undefined) {
  if (!Number.isFinite(value)) return 1;
  return Math.min(Math.max(value as number, TERRAIN_EXAGGERATION_MIN), TERRAIN_EXAGGERATION_MAX);
}

function absolutizeTileUrl(tileUrl: string) {
  if (tileUrl.startsWith('http')) return tileUrl;
  const origin = typeof window === 'undefined' ? '' : window.location.origin;
  return `${origin}${tileUrl}`;
}

function sourceSpec(source: unknown) {
  return (source as { serialize?: () => { tiles?: string[]; bounds?: number[]; tileSize?: number; minzoom?: number; maxzoom?: number; attribution?: string } } | null)
    ?.serialize?.()
    ?? (source as { tiles?: string[]; bounds?: number[]; tileSize?: number; minzoom?: number; maxzoom?: number; attribution?: string } | null)
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
    /**
     * The backing DEM's required credit. Load-bearing on the BUILDER path only,
     * because a terrain-mode DEM has no visible layer:
     * `isDemTerrainVisualSuppressed` suppresses it, so nothing references the
     * attributed raster-dem source the adapter created and MapLibre's `used`
     * flag for it is false. This source is a different id (TERRAIN_SOURCE_ID)
     * and is counted through `usedForTerrain`; without the credit here a DEM
     * used purely as terrain renders its relief uncredited. The viewer passes
     * nothing: it credits through customAttribution off its layer list, and
     * where that list misses (a share-token embed whose DEM row was filtered
     * out) there is no layer object to read a credit from.
     */
    attribution?: string | null;
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
      // A changed credit replaces the source. There is no data to drop (it
      // carries only a tile template), so the swap is cheap and keeps the
      // terrain credit live across an edit.
      || existingSpec.attribution !== (options.attribution ?? undefined)
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
      ...(options.attribution ? { attribution: options.attribution } : {}),
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
  filter?: FilterSpecification | null;
  label_config?: LabelConfig | null;
  style_config?: StyleConfig | null;
  /**
   * Popup config: its visible_fields / title-template columns must be opted
   * into the tile `cols=` set or they get stripped at z<10.
   */
  popup_config?: PopupConfig | null;
  is_dem?: boolean | null;
  is_3d?: boolean | null;
  feature_count?: number | null;
  /** Column types, so a server-clustered layer's filter is converted with typed literals. */
  dataset_column_info?: { name: string; type?: string | null }[] | null;
  /** Explicit tile attribute allowlist; null/absent permits all queryable columns. */
  dataset_tile_columns?: string[] | null;
  /** Source-id dedupe: consumed by `getSourceIdForLayer` to
   *  keep non-vector layers (raster/hillshade) on a per-layer source key. */
  layer_type?: string | null;
  dataset_record_type?: string | null;
  tile_url?: string | null;
  tile_size?: number | null;
  minzoom?: number | null;
  maxzoom?: number | null;
  bounds?: number[] | null;
  format?: string | null;
  /** Per-dataset attribution string for the vector/raster source spec
   *  (rendered in the MapLibre attribution control). Optional — populated only
   *  when the dataset carries a credit/licensing string. */
  attribution?: string | null;
  /** Dataset content/version stamp threaded into the tile URL's
   *  `_v=` cache-buster so a reupload/geometry edit busts client/CDN caches.
   *  Optional — only emitted when a content version is available. */
  tile_version?: string | number | null;
}

/** Options that vary between Builder and Viewer contexts. */
export interface SyncOptions {
  /** Prefix for generated source/layer IDs (default: no prefix, uses "source-"/"layer-" scheme) */
  idPrefix?: string;
  /** When provided, run basemap label reorder using this source prefix after layer order changes */
  showBasemapLabels?: boolean;
  /**
   * When 'top', move basemap fill/raster layers ABOVE data layers after the
   * standard reorder pass. When 'bottom' (default), the standard pipeline
   * already puts data above the basemap.
   */
  basemapPosition?: 'top' | 'bottom';
  /** Physical schema prefix emitted in MVT payload layer names. */
  mvtSourceLayerPrefix?: string | null;
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
    filter: layer.filter ?? null,
    label_config: layer.label_config ?? null,
    style_config: layer.style_config ?? null,
    popup_config: layer.popup_config ?? null,
    is_dem: layer.is_dem,
    is_3d: layer.is_3d,
    feature_count: layer.dataset_feature_count,
    dataset_column_info: layer.dataset_column_info,
    dataset_tile_columns: layer.dataset_tile_columns,
    layer_type: layer.layer_type,
    dataset_record_type: layer.dataset_record_type ?? null,
    tile_version: layer.tile_version,
    // The builder's half of the attribution feature. It has no explicit
    // <AttributionControl> to hand `customAttribution` to (react-maplibre reads
    // the <Map attributionControl> option once at mount), so the builder
    // credits through MapLibre's native source-level `attribution`. MapLibre
    // recomputes the control from sources whose `used` flag is live, so hiding
    // every layer on a source drops its credit without any code of ours
    // running.
    //
    // Deliberately NOT mirrored in toViewerSyncInput: the viewer owns an
    // explicit control and passes customAttribution; feeding both would be two
    // mechanisms answering one question.
    attribution: toMapLibreAttribution(layer.dataset_attribution),
    // Surface the dataset spatial extent so the vector source can bound tile
    // fetching to the data footprint (the raster path already passes bounds).
    // This is the RFC 7946 form (`west > east` on an antimeridian crossing),
    // passed through unconverted on purpose: every reader of `bounds` reaches a
    // MapLibre source through `normalizeRasterBounds`
    // (layer-adapters/shared.ts), which spans it at the one boundary that
    // cannot express a crossing. Converting here would duplicate that rule and
    // discard the seam.
    bounds: layer.dataset_extent_bbox ?? null,
  };
}

/** Move basemap symbol/label layers above data layers, or hide them. */
export function reorderBasemapLabels(map: MaplibreMap, show: boolean, sourcePrefix = 'source-') {
  const style = map.getStyle();
  if (!style?.layers) return;

  const basemapSymbolLayers = style.layers.filter(
    // Shared basemap-owned predicate.
    (l) => l.type === 'symbol' && isBasemapOwnedLayer(l, sourcePrefix),
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
  // Shared basemap-owned predicate.
  return style.layers.filter((layer) =>
    isBasemapOwnedLayer(layer, sourcePrefix),
  ) as StyleSpecification['layers'];
}

/**
 * What this module knows about one basemap-owned layer's paint.
 *
 * applyBasemapConfigToMap feeds `map.getStyle()`, the LIVE and already-mutated
 * style, into applyBasemapConfigToStyle, and the appearance helpers
 * (applyLandWaterTone / applyBackgroundColor / applyReliefContrast) are no-ops
 * on their default value. Without a snapshot, a revert pass would compare the
 * tint the previous pass wrote against itself and write nothing, leaving the
 * map tinted while React state, the stack row and the saved payload said
 * "default". Diffing against `pristine` lets "no override" be a target state
 * the writer can express.
 */
interface BasemapLayerPaintState {
  /** The layer's paint before this module overrode it. */
  pristine: Record<string, unknown>;
  /** The paint this module believes is live: `pristine` with everything it has
   *  since written on top. A live value that disagrees means somebody else
   *  wrote the key, and the most important somebody is a new style. */
  expected: Record<string, unknown>;
  /** Keys currently carrying an override, so a key the config stops setting can
   *  be restored without touching keys owned by applySublayerOverrides or by
   *  the style itself. */
  stamped: Set<string>;
}

/** The per-layer states, tagged with the style generation they describe. */
interface BasemapPaintCache {
  generation: number;
  states: Map<string, BasemapLayerPaintState>;
}

const basemapPaintStates = new WeakMap<MaplibreMap, BasemapPaintCache>();
const basemapStyleGenerations = new WeakMap<MaplibreMap, { value: number }>();
const generationListenerAttached = new WeakSet<MaplibreMap>();

/**
 * Start counting style generations for `map`.
 *
 * Per-key equality reconciliation cannot see a swap whose new native value
 * equals the override the old style was carrying (style A's water overridden to
 * #d9dde0, style B's native water also #d9dde0): nothing changed from the
 * paint's point of view, so clearing the override afterwards would restore A's
 * colour. A generation counter closes that gap, and unlike a style-identity
 * token it doesn't depend on fields that move for unrelated reasons (`sprite`
 * is rewritten by the symbol adapter's `addSprite`; `layers` and `sources`
 * change on every data-layer add).
 *
 * MUST be called from the map-creation path (BuilderMap and ViewerMap
 * `onLoad`), never lazily from an appearance pass, so it is the
 * earliest-registered `style.load` listener and has bumped the counter by the
 * time BuilderMap's persistent handler triggers an appearance pass on the new
 * style.
 *
 * Idempotent: a second call for the same map is a no-op, so a remount that
 * reuses the instance cannot double-count.
 */
export function registerBasemapStyleGeneration(map: MaplibreMap): void {
  if (generationListenerAttached.has(map)) return;
  generationListenerAttached.add(map);
  const counter = basemapStyleGenerations.get(map) ?? { value: 0 };
  basemapStyleGenerations.set(map, counter);
  // Partial map mocks in tests lack `on`, hence the optional call.
  map.on?.('style.load', () => {
    counter.value += 1;
  });
}

/** Zero when no counter is registered, so a surface that has not opted in
 *  degrades to the equality reconciliation alone rather than misbehaving. */
function currentBasemapStyleGeneration(map: MaplibreMap): number {
  return basemapStyleGenerations.get(map)?.value ?? 0;
}

function basemapPaintStateFor(map: MaplibreMap): Map<string, BasemapLayerPaintState> {
  const generation = currentBasemapStyleGeneration(map);
  const cache = basemapPaintStates.get(map);
  // A generation bump means a different style is loaded; everything cached
  // describes the previous one, so treat it as empty and re-snapshot.
  if (cache && cache.generation === generation) return cache.states;
  const states = new Map<string, BasemapLayerPaintState>();
  basemapPaintStates.set(map, { generation, states });
  return states;
}

/**
 * Detect a style change SYNCHRONOUSLY, per key, instead of clearing the cache
 * from a `style.load` listener.
 *
 * A listener here could never be right: BuilderMap registers its own persistent
 * `style.load` handler at mount, which calls applyMapBasemapAppearance, so any
 * listener this module attached ran later. On a swap between two styles sharing
 * layer ids the appearance pass then saw the OLD pristine values and wrote the
 * previous basemap's colours onto the new style, which became the next pristine
 * snapshot.
 *
 * This is the second line of defence. registerBasemapStyleGeneration drops the
 * whole cache when the style generation moves, which covers the case equality
 * cannot see. The per-key comparison stays because it catches every OTHER
 * writer, needs no cooperation from the host surface, and works where no
 * counter was registered.
 *
 * Per KEY rather than per layer on purpose: applySublayerOverrides runs right
 * after this helper and rewrites the `*-opacity` keys, so a layer-level check
 * would discard that layer's whole snapshot every pass and re-baseline the tint
 * as pristine. Those opacity keys are harmless to re-snapshot because
 * applyMasterOpacity writes them absolutely on every pass and never consults
 * their pristine value.
 */
function reconcileBasemapPaintState(
  state: BasemapLayerPaintState | undefined,
  livePaint: Record<string, unknown>,
): BasemapLayerPaintState {
  if (!state) {
    return { pristine: { ...livePaint }, expected: { ...livePaint }, stamped: new Set() };
  }
  for (const [key, live] of Object.entries(livePaint)) {
    if (key in state.expected && state.expected[key] === live) continue;
    state.pristine[key] = live;
    state.expected[key] = live;
    state.stamped.delete(key);
  }
  for (const key of Object.keys(state.expected)) {
    // maplibre omits a paint key whose value was set to undefined, so a key
    // that has left the serialized paint is one this module no longer knows.
    if (key in livePaint) continue;
    delete state.pristine[key];
    delete state.expected[key];
    state.stamped.delete(key);
  }
  return state;
}

/**
 * When `basemap_position === 'top'`, move all basemap-loaded style layers
 * (anything whose source does NOT start with the data sourcePrefix) ABOVE the
 * data layers. MapLibre paints last-in-array on top, so `map.moveLayer(id)`
 * with no `beforeId` moves a layer to the top.
 *
 * When 'bottom' (default), do nothing: `reorderDataGeometry` +
 * `reorderDataLabels` already place data above the basemap, and calling this
 * would undo that.
 *
 * Idempotent; safe to call from the basemap effect on every render.
 */
export function reorderBasemapAboveData(
  map: MaplibreMap,
  position: 'top' | 'bottom' | undefined,
  sourcePrefix = 'source-',
) {
  if (position !== 'top') return;
  const style = map.getStyle();
  if (!style?.layers) return;
  for (const layer of style.layers) {
    // Basemap layers do NOT have a source matching the data sourcePrefix;
    // 'source' may be undefined for some background-style layers, which count
    // as basemap layers too. Shared predicate.
    if (!isBasemapOwnedLayer(layer, sourcePrefix)) continue;
    if (!map.getLayer(layer.id)) continue;
    // Never lift the opaque base fills (background / land / water) above the
    // data layers: it would paint them over the data and make a "labels only"
    // basemap reveal its full imagery. Only reference detail layers (roads,
    // buildings, boundaries, labels) float above data when basemap_position ===
    // 'top'.
    if (isLandLayer(layer) || isWaterLayer(layer)) continue;
    // An imagery basemap is a raster layer (not a data-source layer, already
    // skipped above); lifting it above data would occlude them, so skip it.
    if (layer.type === 'raster') continue;
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
  // Capture the pristine paint the FIRST time each basemap layer is seen
  // (before this call writes anything), then build `next` from pristine rather
  // than from the live style, so reverting an override is expressible.
  // Reconcile first, so a key the live style no longer agrees with this module
  // about is re-snapshotted before it is read.
  const paintStates = basemapPaintStateFor(map);
  const pristineLayers = basemapOnlyStyle.layers.map((layer) => {
    const livePaint = ('paint' in layer
      ? (layer.paint as Record<string, unknown> | undefined)
      : undefined) ?? {};
    const state = reconcileBasemapPaintState(paintStates.get(layer.id), livePaint);
    paintStates.set(layer.id, state);
    return { ...layer, paint: { ...state.pristine } };
  }) as StyleSpecification['layers'];
  const nextStyle = applyBasemapConfigToStyle(
    { ...basemapOnlyStyle, layers: pristineLayers },
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
        setDynamicLayoutProperty(map, current.id, 'visibility', nextLayout.visibility);
      } catch (error) {
        if (import.meta.env.DEV) console.warn('[map-sync] basemap layout sync failed', current.id, error);
      }
    }

    const currentPaint = 'paint' in current ? current.paint as Record<string, unknown> | undefined : undefined;
    const nextPaint = 'paint' in next ? next.paint as Record<string, unknown> | undefined : undefined;
    const state = paintStates.get(current.id);
    const pristinePaint = state?.pristine ?? {};
    // The union makes a revert reachable: `next` alone misses a key the OLD
    // config stamped and this one doesn't set (text-halo-width from label_mode
    // 'subtle' is the canonical case). Keys are restricted to what this
    // function wrote, so applySublayerOverrides' writes and the style's own
    // paint are never clobbered.
    const keysToWrite = new Set<string>([
      ...Object.keys(nextPaint ?? {}),
      ...(state?.stamped ?? []),
    ]);
    const nowStamped = new Set<string>();
    for (const key of keysToWrite) {
      const target = nextPaint && key in nextPaint ? nextPaint[key] : pristinePaint[key];
      if (target !== pristinePaint[key]) nowStamped.add(key);
      if (target === currentPaint?.[key]) {
        if (state) state.expected[key] = target;
        continue;
      }
      try {
        setDynamicPaintProperty(map, current.id, key, target);
        // Recorded only on success: a throw leaves the live value untouched, so
        // the expectation must stay whatever it already was.
        if (state) state.expected[key] = target;
      } catch (error) {
        if (import.meta.env.DEV) console.warn('[map-sync] basemap paint sync failed', current.id, key, error);
      }
    }
    if (state) state.stamped = nowStamped;
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
  // Every companion id derived from one helper.
  const ids = getCompanionLayerIds(id, prefix);
  for (const candidate of [ids.label, ids.arrow, ids.extrusion, ids.outline, ids.clusterCount, ids.cluster, ids.mixedLines, ids.mixedPoints, layerId]) {
    if (map.getLayer(candidate)) map.removeLayer(candidate);
  }
}

// The cluster signature and the tile-url signature live in SEPARATE per-map
// WeakMaps, so deleting one can't wipe the other's guard.
const clusterSourceSignatures = new WeakMap<MaplibreMap, Map<string, string>>();
const tileUrlSignatures = new WeakMap<MaplibreMap, Map<string, string>>();

function clusterSourceSignature(input: AdapterLayerInput) {
  const options = getClusterSourceOptions(input);
  return `${options.clusterRadius}:${options.clusterMaxZoom}`;
}

/** A clustered GeoJSON source filters its points when it is built, so the filter belongs in its signature. */
function boundedClusterFilterKey(input: AdapterLayerInput) {
  return JSON.stringify(filterSpec(input.filter).filter ?? null);
}

function removeClusterCompanionLayers(map: MaplibreMap, layerId: string) {
  const clusterCountId = clusterCountLayerId(layerId);
  const clusterCircleId = clusterCircleLayerId(layerId);
  if (map.getLayer(clusterCountId)) map.removeLayer(clusterCountId);
  if (map.getLayer(clusterCircleId)) map.removeLayer(clusterCircleId);
}

function removeColorReliefCompanionLayer(map: MaplibreMap, layerId: string) {
  // The -colorrelief suffix lives in companion-ids.ts.
  const colorReliefId = `${layerId}${COLOR_RELIEF_SUFFIX}`;
  if (map.getLayer(colorReliefId)) map.removeLayer(colorReliefId);
}

function clusterSignatureStore(map: MaplibreMap) {
  let store = clusterSourceSignatures.get(map);
  if (!store) {
    store = new Map<string, string>();
    clusterSourceSignatures.set(map, store);
  }
  return store;
}

function tileUrlSignatureStore(map: MaplibreMap) {
  let store = tileUrlSignatures.get(map);
  if (!store) {
    store = new Map<string, string>();
    tileUrlSignatures.set(map, store);
  }
  return store;
}

/**
 * Refresh a vector source's tiles ONLY when the signed URL actually changed,
 * honoring the per-source tile-url signature. Both the in-pass sync
 * (`syncVectorTiles`) and the BuilderMap token-refresh effect call this, so a
 * paint/visibility edit that doesn't change the cols=/sig URL doesn't re-issue
 * setTiles (the flicker/refetch guard). Returns true when it actually re-tiled.
 */
export function refreshVectorSourceTiles(map: MaplibreMap, sourceId: string, tileUrl: string): boolean {
  const source = map.getSource(sourceId) as { type?: string; setTiles?: (tiles: string[]) => void } | undefined;
  if (!source || source.type !== 'vector' || typeof source.setTiles !== 'function') return false;
  const store = tileUrlSignatureStore(map);
  if (store.get(sourceId) === tileUrl) return false;
  source.setTiles([tileUrl]);
  store.set(sourceId, tileUrl);
  // MapLibre 5.x silently drops setTiles' tile reload when the source's
  // TileManager is paused (any same-pass layer update pauses it): the 'content'
  // data event returns early without setting the reload-on-resume flag, so
  // loaded tiles keep serving the pre-edit cols= payload. Re-issue the reload
  // through the public refreshTiles API, which DOES set the resume flag. The
  // refresh must wait until the source's async load() has copied the new URL
  // into `source.tiles` (refreshing earlier reloads the OLD url while the
  // signature store has already advanced, re-stranding the tiles), so poll for
  // adoption with a bounded retry that bails when the url is superseded by a
  // newer edit or the source is torn down.
  const awaitAdoptionThenRefresh = (attempt: number) => {
    if (store.get(sourceId) !== tileUrl) return; // superseded by a newer edit
    const src = map.getSource(sourceId) as { tiles?: string[] } | undefined;
    if (!src) return; // source removed
    if (src.tiles?.[0] === tileUrl) {
      try {
        (map as MaplibreMap & { refreshTiles?: (id: string) => void }).refreshTiles?.(sourceId);
      } catch {
        /* style torn down between the check and the refresh */
      }
      return;
    }
    if (attempt < 40) setTimeout(() => awaitAdoptionThenRefresh(attempt + 1), 100);
  };
  setTimeout(() => awaitAdoptionThenRefresh(0), 0);
  return true;
}

export function getLayerId(layerId: string) {
  return prefixed('layer', layerId);
}

/**
 * True when the given DEM layer is already consumed by the active terrain
 * source. A second raster-dem consumer (hillshade) on the same DEM causes
 * MapLibre backfillBorder "dem dimension mismatch" errors. Requires terrain
 * enabled AND the same dataset powering both consumers, so the predicate is
 * FALSE when terrainConfig.enabled=false and the primary hillshade path is
 * unaffected on maps without terrain.
 */
export function isHillshadeTerrainBound(
  layer: { dataset_id: string; is_dem?: boolean | null },
  terrainConfig: MapTerrainConfig | null | undefined,
): boolean {
  return (
    layer.is_dem === true &&
    terrainConfig?.enabled === true &&
    terrainConfig.source_dataset_id === layer.dataset_id
  );
}

/** Add or update a raster layer and its described source on the map. */
function syncRasterLayer(
  map: MaplibreMap,
  adapterInput: AdapterLayerInput,
  source: RasterSourceSpecification | RasterDEMSourceSpecification,
  desiredSources: Set<string>,
) {
  adapterInput.style_config = normalizeDemStyleConfig(adapterInput.style_config, adapterInput.is_dem);
  const useHillshade = source.type === 'raster-dem';

  // A terrain-bound hillshade always paints alongside the 3D mesh on its own
  // per-layer source (`source-${layer.id}` via getSourceIdForLayer, NEVER the
  // shared `terrain-dem` id, so the teardown machinery does not orphan it).
  // Terrain binding is same-dataset, so both consumers derive tileSize from one
  // raster token and cannot mismatch.

  const adapter = getAdapter(useHillshade ? 'hillshade' : 'raster');
  const expectedLayerType = useHillshade ? 'hillshade' : 'raster';
  const currentLayer = map.getLayer(adapterInput.layerId) as { type?: string } | undefined;
  const currentSource = map.getSource(adapterInput.sourceId) as { type?: string } | undefined;
  const currentSourceSpec = currentSource ? sourceSpec(currentSource) : {};

  if (
    (currentLayer && currentLayer.type !== expectedLayerType) ||
    (currentSource && (
      currentSource.type !== source.type ||
      currentSourceSpec.tiles?.[0] !== source.tiles?.[0] ||
      currentSourceSpec.tileSize !== source.tileSize ||
      currentSourceSpec.minzoom !== source.minzoom ||
      currentSourceSpec.maxzoom !== source.maxzoom ||
      !sameNumberArray(currentSourceSpec.bounds, source.bounds)
    ))
  ) {
    removeColorReliefCompanionLayer(map, adapterInput.layerId);
    if (map.getLayer(adapterInput.layerId)) map.removeLayer(adapterInput.layerId);
    if (map.getSource(adapterInput.sourceId)) map.removeSource(adapterInput.sourceId);
  }

  if (!map.getSource(adapterInput.sourceId)) {
    map.addSource(adapterInput.sourceId, source);
    adapter.addLayers(map, adapterInput);
  } else {
    adapter.syncPaint(map, adapterInput);
  }
  desiredSources.add(adapterInput.sourceId);
}

/**
 * Resolved per-layer source decisions: pure, no map side effects. Split from
 * syncVectorLayer so type/cluster resolution is testable.
 */
interface VectorSourceMode {
  adapter: LayerAdapter;
  /** Effective adapter type (cluster may downgrade to circle when ineligible). */
  type: string;
  canUseCluster: boolean;
  canUseServerCluster: boolean;
  canUseBoundedCluster: boolean;
  /** Composite signature for cluster sources (null for non-cluster). */
  desiredClusterSignature: string | null;
}

/** Cluster flags for the adapter and source the description chose. Sets `adapterInput.tileUrl`. */
function resolveVectorSourceMode(
  layer: SyncLayerInput,
  adapterInput: AdapterLayerInput,
  drawsAs: DescribedLayer['drawsAs'],
  source: VectorSourceSpecification | GeoJSONSourceSpecification,
): VectorSourceMode {
  // The description already turned a cluster it cannot draw into circles.
  const canUseCluster = drawsAs === 'cluster';
  const canUseBoundedCluster = canUseCluster && source.type === 'geojson';
  const canUseServerCluster = canUseCluster && source.type === 'vector';
  adapterInput.tileUrl = source.type === 'vector' ? source.tiles?.[0] ?? '' : '';
  // A clustered GeoJSON source is rebuilt when these options or its filter change; a cluster
  // tile source takes them in its URL, which refreshes in place.
  const desiredClusterSignature = canUseCluster
    ? `${getClusterSourceStrategy(layer).kind}:${clusterSourceSignature(adapterInput)}${
      source.type === 'geojson' ? `:${boundedClusterFilterKey(adapterInput)}` : ''}`
    : null;
  return {
    adapter: getAdapter(drawsAs),
    type: drawsAs,
    canUseCluster,
    canUseServerCluster,
    canUseBoundedCluster,
    desiredClusterSignature,
  };
}

/**
 * Refresh the tiles of an EXISTING vector source through the guarded
 * `refreshVectorSourceTiles` (one path for cluster and non-cluster), then
 * advance the cluster signature for server clusters.
 */
function syncVectorTiles(
  map: MaplibreMap,
  adapterInput: AdapterLayerInput,
  mode: VectorSourceMode,
  currentClusterSignature: string | undefined,
) {
  const { sourceId } = adapterInput;
  refreshVectorSourceTiles(map, sourceId, adapterInput.tileUrl);
  if (mode.canUseServerCluster
    && currentClusterSignature !== mode.desiredClusterSignature
    && mode.desiredClusterSignature) {
    clusterSignatureStore(map).set(sourceId, mode.desiredClusterSignature);
  }
}

/** Create or recreate the described geojson or vector source, reconcile its
 *  tiles, and add the layer's map layers or bring them in step. */
function ensureVectorSource(
  map: MaplibreMap,
  layer: SyncLayerInput,
  adapterInput: AdapterLayerInput,
  mode: VectorSourceMode,
  source: VectorSourceSpecification | GeoJSONSourceSpecification,
  prefix: string | undefined,
): void {
  const { sourceId, layerId } = adapterInput;
  const {
    adapter, canUseCluster, canUseServerCluster, canUseBoundedCluster, desiredClusterSignature,
  } = mode;
  const clusterStore = clusterSignatureStore(map);
  const tileStore = tileUrlSignatureStore(map);
  const currentSource = map.getSource(sourceId) as { type?: string } | undefined;
  const currentClusterSignature = clusterStore.get(sourceId);

  const geoJsonClusterSourceOptionsChanged = canUseBoundedCluster
    && currentSource?.type === 'geojson'
    && currentClusterSignature !== desiredClusterSignature;
  if (currentSource && (currentSource.type !== source.type || geoJsonClusterSourceOptionsChanged)) {
    removeKnownVectorLayers(map, layerId, layer.id, prefix);
    map.removeSource(sourceId);
    clusterStore.delete(sourceId);
    tileStore.delete(sourceId);
  }
  if (!canUseCluster) {
    removeClusterCompanionLayers(map, layerId);
    // Clear only the CLUSTER signature; the tile-url signature lives in its own
    // WeakMap, so this per-pass cleanup can't wipe the flicker guard.
    clusterStore.delete(sourceId);
  }

  if (source.type === 'geojson') {
    adapterInput.sourceType = 'geojson';
    if (!map.getSource(sourceId)) {
      map.addSource(sourceId, source);
      clusterStore.set(sourceId, desiredClusterSignature ?? '');
      adapter.addLayers(map, adapterInput);
    } else {
      const src = map.getSource(sourceId);
      // setData carries data only: MapLibre reads a GeoJSON source's
      // `attribution` at construction and exposes no setter, so an attribution
      // edited mid-session does not reach a source already on the map. Accepted
      // rather than engineered around: remove-and-re-add would drop the
      // rendered features and refetch, and the credit is correct on the next
      // builder load. Every PUBLISHED surface (viewer, share, embed, exported
      // style) re-reads the field per render or request and is never stale.
      if (src && src.type === 'geojson') (src as GeoJSONSource).setData(source.data);
      // A second layer sharing this dataset's source (the dedupe) hits this
      // branch though its own layer was never added. syncPaint no-ops when the
      // layer is missing, so add it here.
      if (!map.getLayer(layerId)) adapter.addLayers(map, adapterInput);
      else adapter.syncPaint(map, adapterInput);
    }
    return;
  }

  if (!map.getSource(sourceId)) {
    // lineMetrics is sticky: we only set it at source CREATE time.
    map.addSource(sourceId, source);
    if (canUseServerCluster && desiredClusterSignature) clusterStore.set(sourceId, desiredClusterSignature);
    else clusterStore.delete(sourceId);
    // Seed the tile-url signature so the first post-create sync (and the
    // token-refresh effect) do not redundantly re-fire setTiles.
    tileStore.set(sourceId, adapterInput.tileUrl);
    adapter.addLayers(map, adapterInput);
  } else {
    adapterInput.sourceType = 'vector';
    syncVectorTiles(map, adapterInput, mode, currentClusterSignature);
    // As above: the shared source was created by the first layer, so add this
    // layer here.
    if (!map.getLayer(layerId)) adapter.addLayers(map, adapterInput);
    else adapter.syncPaint(map, adapterInput);
  }
}

/** Add or update a vector (MVT or GeoJSON) layer's source and map layers. */
function syncVectorLayer(
  map: MaplibreMap,
  layer: SyncLayerInput,
  described: DescribedLayer,
  source: VectorSourceSpecification | GeoJSONSourceSpecification,
  adapterInput: AdapterLayerInput,
  desiredSources: Set<string>,
  prefix: string | undefined,
) {
  desiredSources.add(adapterInput.sourceId);
  removeReplacedLayer(map, layer, described, prefix);
  const mode = resolveVectorSourceMode(layer, adapterInput, described.drawsAs, source);
  ensureVectorSource(map, layer, adapterInput, mode, source, prefix);
}

/**
 * Remove a layer's map layers when the map draws its primary as another type, or
 * from another source, than the description does, so the source step adds them afresh.
 */
function removeReplacedLayer(map: MaplibreMap, layer: SyncLayerInput, described: DescribedLayer, prefix: string | undefined) {
  const drawn = map.getLayer(described.id);
  const primary = described.specs.find((spec) => spec.layer.id === described.id)?.layer;
  if (!drawn || !primary || (drawn.type === primary.type && drawn.source === primary.source)) return;
  removeKnownVectorLayers(map, described.id, layer.id, prefix);
}

/** Finish the described drawing after its source and paint have been reconciled. */
function syncDrawnLayer(
  map: MaplibreMap,
  described: DescribedLayer,
  adapterInput: AdapterLayerInput,
  prefix: string | undefined,
) {
  const drawing = getAdapter(described.drawsAs).describe?.(adapterInput) ?? described;
  finishDescribedLayer(map, drawing, getDrawingLayerIds(adapterInput.id, prefix), described.zoom);
}

/**
 * Remove every map layer whose `source` references `sourceId`. For a DEDUPED
 * vector source the id derived from the source name is `data-${table}`, so
 * per-layer companion ids never match the real `layer-${layer.id}` ids; those
 * orphans must be found by walking the live style.
 */
function removeLayersUsingSource(map: MaplibreMap, sourceId: string) {
  const style = map.getStyle();
  if (!style?.layers) return;
  for (const styleLayer of style.layers) {
    if ('source' in styleLayer && styleLayer.source === sourceId && map.getLayer(styleLayer.id)) {
      map.removeLayer(styleLayer.id);
    }
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
    const ids = getCompanionLayerIds(id, prefix);
    // The color-relief companion has no source of its own (it reuses the
    // raster-dem source), so the source-keyed loop doesn't find it; remove it
    // explicitly.
    removeColorReliefCompanionLayer(map, ids.layer);
    for (const candidate of [ids.label, ids.arrow, ids.extrusion, ids.outline, ids.clusterCount, ids.cluster, ids.mixedLines, ids.mixedPoints, ids.layer]) {
      // A layer redrawn on another source this pass keeps its id, and stays.
      if (map.getLayer(candidate)?.source === sourceId) map.removeLayer(candidate);
    }
    // Remove any remaining layers still referencing this source (the deduped
    // case where the derived ids above never matched) BEFORE removeSource,
    // which throws 'source ... in use' otherwise. removePerLayerCompanions
    // can't be relied on: it early-returns mid-style-transition.
    removeLayersUsingSource(map, sourceId);
    if (map.getSource(sourceId)) map.removeSource(sourceId);
    clusterSourceSignatures.get(map)?.delete(sourceId);
    tileUrlSignatures.get(map)?.delete(sourceId);
  }
}

/**
 * Remove managed data layers whose logical layer is gone even when their SOURCE
 * is still wanted.
 *
 * removeStaleSourcesAndLayers is keyed on the source, so under the dedupe (two
 * layers on one dataset share `source-data-${table}`) deleting one leaves the
 * source DESIRED and its layer rows never reclaimed. The delete path's own
 * cleanup (removePerLayerCompanions) is best-effort, so this walk is the
 * backstop.
 *
 * Scoped on three conditions at once, so a basemap layer that happens to be
 * named `layer-*` and anything a plugin added are left alone: the id starts
 * with the managed `layer-` prefix, the layer sits on a data source (every
 * managed layer does, including the label and color-relief companions), and the
 * id is absent from the companion-id expansion of the desired set.
 */
function removeOrphanManagedLayers(
  map: MaplibreMap,
  desiredLayerIds: Iterable<string>,
  sourcePrefix: string,
  prefix: string | undefined,
) {
  const style = map.getStyle();
  if (!style?.layers) return;
  const managedPrefix = `${prefix ?? ''}layer-`;
  const keep = new Set<string>();
  for (const id of desiredLayerIds) {
    const ids = getCompanionLayerIds(id, prefix);
    for (const companion of [
      ids.layer, ids.outline, ids.extrusion, ids.arrow, ids.label,
      ids.colorRelief, ids.cluster, ids.clusterCount, ids.mixedLines, ids.mixedPoints,
    ]) {
      keep.add(companion);
    }
  }
  for (const styleLayer of style.layers) {
    if (!styleLayer.id.startsWith(managedPrefix)) continue;
    if (isBasemapOwnedLayer(styleLayer, sourcePrefix)) continue;
    if (keep.has(styleLayer.id)) continue;
    if (map.getLayer(styleLayer.id)) map.removeLayer(styleLayer.id);
  }
}

/** The render context each map was last synced in, without its tokens. */
const drawnContexts = new WeakMap<MaplibreMap, RenderContext>();

/** Write one saved layer to the map layers a sync pass drew for it, as the pass would.
 *  It adds no source or whole layer, and leaves a layer the map draws as another type,
 *  or from another source, for the next pass to replace. */
export function writeLayerToMap(map: MaplibreMap, layer: SyncLayerInput): void {
  const context = drawnContexts.get(map);
  if (!context) return;
  const { layers: [described], sources } = describeLayers([layer], context);
  const primary = described?.specs.find((spec) => spec.layer.id === described.id)?.layer;
  const drawn = primary ? map.getLayer(primary.id) : undefined;
  if (!primary || !drawn || drawn.type !== primary.type || drawn.source !== primary.source) return;
  const adapterInput: AdapterLayerInput = {
    ...adapterInputFor(layer, described),
    sourceType: sources.get(described.sourceId)?.type === 'geojson' ? 'geojson' : 'vector',
  };
  getAdapter(described.drawsAs).syncPaint(map, adapterInput);
  syncDrawnLayer(map, described, adapterInput, context.idPrefix);
}

/** The render context syncLayersToMap describes its layers in. */
export function syncRenderContext(
  tokenMap: ReadonlyMap<string, TileToken>,
  tileBaseUrl: string | undefined,
  geojsonDataMap: ReadonlyMap<string, GeoJSON.FeatureCollection> | undefined,
  options: Pick<SyncOptions, 'idPrefix' | 'mvtSourceLayerPrefix'> | undefined,
): RenderContext {
  return {
    idPrefix: options?.idPrefix ?? '',
    origin: window.location.origin,
    tileBaseUrl,
    sourceLayerPrefix: options?.mvtSourceLayerPrefix,
    tokens: tokenMap,
    boundedGeoJson: geojsonDataMap ?? new Map(),
  };
}

function reportLayerSyncFailure(layer: SyncLayerInput, err: unknown) {
  if (import.meta.env.DEV) console.error('[map-sync] layer sync failed', layer.id, err);
  toast.error(i18n.t('builder:toasts.layerSyncFailed', { name: layer.dataset_table_name }), { id: `sync-error-${layer.id}` });
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
  const renderableLayers = layers.filter((layer) => !isFolderGroupLayer(layer));

  const currentSources = new Set(managedSourcesRef.current);
  const desiredSources = new Set<string>();
  const context = syncRenderContext(tokenMap, tileBaseUrl, geojsonDataMap, options);
  let description: Description;
  try {
    description = describeLayers(renderableLayers, context);
  } catch (err) {
    // Only an unresolved tenant prefix throws here, and every caller gates on it.
    for (const layer of renderableLayers) reportLayerSyncFailure(layer, err);
    return;
  }
  // A layer write adds no source, so it has no use for the tokens.
  drawnContexts.set(map, { ...context, tokens: new Map() });
  const describedById = new Map(description.layers.map((described) => [described.id, described]));

  for (const layer of renderableLayers) {
    try {
      const described = describedById.get(prefixed('layer', layer.id, prefix));
      const source = described && description.sources.get(described.sourceId);
      // Terrain-mode DEMs have no entry, and a raster without a tile URL no source.
      if (!described || !source) continue;

      const adapterInput: AdapterLayerInput = {
        ...adapterInputFor(layer, described),
        // Reaches the raster / raster-dem source specs.
        attribution: layer.attribution ?? null,
      };

      if (source.type === 'raster' || source.type === 'raster-dem') {
        syncRasterLayer(map, adapterInput, source, desiredSources);
      } else if (source.type === 'vector' || source.type === 'geojson') {
        syncVectorLayer(map, layer, described, source, adapterInput, desiredSources, prefix);
      }
      syncDrawnLayer(map, described, adapterInput, prefix);
    } catch (err) {
      reportLayerSyncFailure(layer, err);
    }
  }

  try {
    // Layer-aware prune first, so an orphan on a still-shared deduped source is
    // reclaimed; the source prune only covers sources it is about to drop.
    removeOrphanManagedLayers(map, renderableLayers.map((l) => l.id), sourcePrefix, prefix);
    removeStaleSourcesAndLayers(map, currentSources, desiredSources, sourcePrefix, prefix);
    managedSourcesRef.current = desiredSources;
  } catch (err) {
    // On failure, keep managedSourcesRef at pre-removal value so next sync retries cleanup.
    // DEV-only diagnostic — silenced in production to keep the runtime console clean.
    if (import.meta.env.DEV) console.warn('[map-sync] removeStaleSourcesAndLayers failed', err);
  }

  // Reorder only when the stack may be out of order: a new saved order or basemap
  // setting, or a style layer added, removed or replaced since. The key is read again
  // after the reorder, so the next pass over an unchanged map matches it.
  const orderKey = () => renderableLayers.map((l) => l.id).join(',')
    + (options?.showBasemapLabels !== undefined ? `|${String(options.showBasemapLabels)}` : '')
    + (options?.basemapPosition !== undefined ? `|bp:${options.basemapPosition}` : '')
    + `|${map.getStyle()?.layers?.map(({ id }) => id).join(',') ?? ''}`;
  if (orderKey() !== lastOrderKeyRef.current) {
    // Target z-order: data geometries → basemap labels → data labels
    reorderDataGeometry(map, renderableLayers, prefix);
    if (options?.showBasemapLabels !== undefined) {
      reorderBasemapLabels(map, options.showBasemapLabels, sourcePrefix);
    }
    reorderDataLabels(map, renderableLayers, prefix);
    // Basemap-above-data inversion runs LAST so it overrides the standard
    // data-above-basemap ordering when position='top'.
    reorderBasemapAboveData(map, options?.basemapPosition, sourcePrefix);
    lastOrderKeyRef.current = orderKey();
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
    const colorReliefId = `${lid}${COLOR_RELIEF_SUFFIX}`;
    const cid = clusterCircleLayerId(lid);
    const ccid = clusterCountLayerId(lid);
    // Mixed-geometry family sublayers move with their parent,
    // preserving the adapter's add order (fill < outline < lines < points).
    const mlid = mixedLinesLayerId(lid);
    const mpid = mixedPointsLayerId(lid);
    if (map.getLayer(cid)) map.moveLayer(cid);
    if (map.getLayer(ccid)) map.moveLayer(ccid);
    if (map.getLayer(colorReliefId)) map.moveLayer(colorReliefId);
    if (map.getLayer(lid)) map.moveLayer(lid);
    if (map.getLayer(aid)) map.moveLayer(aid);
    if (map.getLayer(eid)) map.moveLayer(eid);
    if (map.getLayer(oid)) map.moveLayer(oid);
    if (map.getLayer(mlid)) map.moveLayer(mlid);
    if (map.getLayer(mpid)) map.moveLayer(mpid);
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
