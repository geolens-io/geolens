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
import type { AdapterLayerInput, LayerAdapter, LayerSpec } from './layer-adapters/types';
import { FULL_ZOOM_RANGE } from './layer-adapters/builder-defaults';
import {
  adapterInputFor,
  describeLayers,
  type DescribedLayer,
  type Description,
  type RenderContext,
  type ZoomRange,
} from './layer-description';
import { clusterCircleLayerId, clusterCountLayerId, getClusterSourceOptions } from './layer-adapters/cluster-adapter';
import { mixedLinesLayerId, mixedPointsLayerId } from './layer-adapters/mixed-adapter';
import { getClusterSourceStrategy } from './cluster-source';
import { getCompanionLayerIds, COLOR_RELIEF_SUFFIX } from './companion-ids';
import { labelLayerId } from './label-layer-utils';

// Shared utilities — imported for local use and re-exported for backward compatibility
import {
  normalizeRasterBounds,
  setDynamicLayoutProperty,
  setDynamicPaintProperty,
} from './layer-adapters/shared';
// builder-audit #338 SYNC-01: re-export the SINGLE isTerrainCapableDemLayer predicate
// from map-stack so the legend, the delete-time terrain-clear check, AND the 3D
// mesh resolver (BuilderMap imports it from here) all consume one function. The
// previous local copy meant the mesh resolver used a different definition that
// could silently drift from the legend/stack copy.
export { isTerrainCapableDemLayer } from './map-stack';
// Re-export for backward compatibility with existing consumers
export {
  CUSTOM_PAINT_PROPS,
  getLayerType,
  resolveAdapterType,
  simplifyPaint,
  applyMasterOpacity,
  getExpressionSafeOpacity,
  stripCustomProps,
  filterPaintForLayerType,
} from './layer-adapters/shared';
export {
  getDataDrivenColumnsForLayer,
  getDataDrivenColumnsForSource,
  getSourceIdForLayer,
  isDemTerrainVisualSuppressed,
  type SourceIdLayer,
} from './layer-description';

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

export function normalizeTerrainExaggeration(value: number | null | undefined) {
  if (!Number.isFinite(value)) return 1;
  return Math.min(Math.max(value as number, TERRAIN_EXAGGERATION_MIN), TERRAIN_EXAGGERATION_MAX);
}

// builder-audit #338 ADAPT-01: normalizeRasterBounds now lives once in
// layer-adapters/shared.ts and is imported above; the verbatim copies in
// raster-adapter, hillshade-adapter, and this module collapse to one.

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
    /** fix(#1472 review): the backing DEM's required credit. Load-bearing on
     *  the BUILDER path only, and only because a terrain-mode DEM has no
     *  visible layer: `isDemTerrainVisualSuppressed` suppresses it, so nothing
     *  references the attributed raster-dem source the adapter created and
     *  MapLibre's `used` flag for it is false. This source is a different id
     *  (TERRAIN_SOURCE_ID) and is counted through `usedForTerrain`, so without
     *  the credit here a DEM used purely as terrain renders its relief
     *  uncredited — swissALTI3D, the example in #1472, is exactly that shape.
     *  The viewer passes nothing: it credits through customAttribution off its
     *  layer list, and in the one case that list misses (a share-token embed
     *  whose DEM row was filtered out, where terrain still seeds from the
     *  raster token) there is no layer object to read a credit from at all. */
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
      // fix(#1472 review): a changed credit replaces the source. Unlike the
      // GeoJSON case above there is no data to drop — this source carries only
      // a tile template — so the swap is cheap and keeps the terrain credit
      // live across an edit.
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
  /** Popup config — its visible_fields / title-template columns must be opted
   *  into the tile `cols=` set or they get stripped at z<10 (#350). */
  popup_config?: PopupConfig | null;
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
  /** MVT-05: per-dataset attribution string for the vector/raster source spec
   *  (rendered in the MapLibre attribution control). Optional — populated only
   *  when the dataset carries a credit/licensing string. */
  attribution?: string | null;
  /** MVT-04: dataset content/version stamp threaded into the tile URL's
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
  /** Phase 1051 UX-03: when 'top', move basemap fill/raster layers ABOVE data
   *  layers after the standard reorder pass. When 'bottom' (default + legacy),
   *  the standard reorder pipeline already produces data-above-basemap. */
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
    filter: layer.filter,
    label_config: layer.label_config ?? null,
    style_config: layer.style_config ?? null,
    popup_config: layer.popup_config ?? null,
    is_dem: layer.is_dem,
    is_3d: layer.is_3d,
    feature_count: layer.dataset_feature_count,
    layer_type: layer.layer_type,
    dataset_record_type: layer.dataset_record_type ?? null,
    // fix(#394) VT-02 (codex P2): without this the builder's `_v=` read below
    // always saw undefined — the cache-buster only flowed on the viewer path.
    tile_version: layer.tile_version,
    // fix(#1472 review): the builder's half of the attribution feature. It has
    // no explicit <AttributionControl> to hand `customAttribution` to (and
    // react-maplibre reads the <Map attributionControl> option once at mount),
    // so the builder credits through MapLibre's native source-level mechanism —
    // the field MVT-05 built here and left unfed. MapLibre recomputes the
    // control from sources whose `used` flag is live, so hiding every layer on
    // a source drops its credit without any code of ours running.
    //
    // Deliberately NOT mirrored in toViewerSyncInput: the viewer owns an
    // explicit control and passes customAttribution, and feeding both would be
    // two mechanisms answering one question.
    attribution: toMapLibreAttribution(layer.dataset_attribution),
    // MVT-06: surface the dataset spatial extent so the vector source can bound
    // tile fetching to the data footprint (the raster path already passes bounds).
    // fix(#1112): this is the RFC 7946 spec form now — `west > east` on an
    // antimeridian crossing — and it is passed through unconverted on purpose.
    // Every reader of `bounds` reaches a MapLibre source through
    // `normalizeRasterBounds` (layer-adapters/shared.ts), which spans it there,
    // at the one boundary that cannot express a crossing. Converting here would
    // be a second copy of that rule and would discard the seam before anything
    // downstream could use it.
    bounds: layer.dataset_extent_bbox ?? null,
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
    // builder-audit #338 DUP-02: shared basemap-owned predicate.
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
  // builder-audit #338 DUP-02: shared basemap-owned predicate.
  return style.layers.filter((layer) =>
    isBasemapOwnedLayer(layer, sourcePrefix),
  ) as StyleSpecification['layers'];
}

/** fix(#1778): what this module knows about one basemap-owned layer's paint.
 *
 *  applyBasemapConfigToMap feeds `map.getStyle()`, the LIVE and already-mutated
 *  style, into applyBasemapConfigToStyle, and the appearance helpers
 *  (applyLandWaterTone / applyBackgroundColor / applyReliefContrast) are no-ops
 *  on their default value. On a revert pass the "next" value was therefore the
 *  tint the previous pass wrote, compared equal, and nothing was written: the
 *  map stayed tinted for the rest of the session while React state, the stack
 *  row and the saved payload all said "default". Diffing against `pristine` is
 *  what makes "no override" a target state the writer can express. */
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
 * fix(#1778 codex round 5): per-key equality reconciliation cannot see a swap
 * whose new native value happens to equal the override the old style was
 * carrying (style A's water overridden to #d9dde0, style B's native water also
 * #d9dde0). Nothing has changed from the paint's point of view, so clearing the
 * override afterwards restored A's colour. A generation counter closes that,
 * and unlike a style-identity token it does not depend on fields that move for
 * unrelated reasons (`sprite` is rewritten by the symbol adapter's `addSprite`;
 * `layers` and `sources` change on every data-layer add).
 *
 * MUST be called from the map-creation path (BuilderMap and ViewerMap
 * `onLoad`), never lazily from an appearance pass. That is what makes this the
 * earliest-registered `style.load` listener, so it has already bumped the
 * counter by the time BuilderMap's own persistent handler triggers an
 * appearance pass on the new style. Registering it lazily would reproduce the
 * round-2 ordering bug exactly.
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
 * fix(#1778 codex round 2 P1): detect a style change SYNCHRONOUSLY, here, per
 * key, instead of clearing the cache from a `style.load` listener.
 *
 * The listener could never be right: BuilderMap registers its own persistent
 * `style.load` handler when the map mounts, and that handler calls
 * applyMapBasemapAppearance. Any listener this module attached was therefore
 * registered later and ran later, so on a swap between two styles that share
 * layer ids the appearance pass saw the OLD pristine values, wrote the previous
 * basemap's colours onto the new style, and the contaminated paint then became
 * the next pristine snapshot.
 *
 * fix(#1778 codex round 5): this is now the SECOND line of defence.
 * registerBasemapStyleGeneration drops the whole cache when the style
 * generation moves, which covers the one case equality cannot see: a new style
 * whose native value equals the override the old one was carrying. The
 * per-key comparison stays because it catches every OTHER writer, needs no
 * cooperation from the surface hosting the map, and keeps working on a surface
 * that never registered a counter.
 *
 * Per KEY rather than per layer on purpose: applySublayerOverrides runs
 * immediately after this helper and rewrites the `*-opacity` keys, so a
 * layer-level check would discard that layer's whole snapshot every pass and
 * re-baseline the tint as pristine. Those opacity keys are harmless to
 * re-snapshot because applyMasterOpacity writes them absolutely on every pass
 * and never consults their pristine value.
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
    // as basemap layers too. builder-audit #338 DUP-02: shared predicate.
    if (!isBasemapOwnedLayer(layer, sourcePrefix)) continue;
    if (!map.getLayer(layer.id)) continue;
    // Never lift the opaque base fills (background / land / water) above the
    // data layers — doing so paints them over the data and makes a
    // "labels only" basemap reveal its full imagery on reorder. Only the
    // reference detail layers (roads, buildings, boundaries, labels) should
    // float above the data when basemap_position === 'top'.
    if (isLandLayer(layer) || isWaterLayer(layer)) continue;
    // An imagery basemap is a raster layer (not a data-source layer, already skipped above).
    // Lifting it above data layers would occlude them — skip it.
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
  // fix(#1778): capture the pristine paint the FIRST time each basemap layer is
  // seen (before this call writes anything), then build `next` from pristine
  // rather than from the live style, so reverting an override is expressible.
  // fix(#1778 codex round 2): reconcile first, so a key the live style no longer
  // agrees with this module about is re-snapshotted before it is read.
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
    // The union is what makes a revert reachable: `next` alone misses a key the
    // OLD config stamped and this one does not set at all (text-halo-width from
    // label_mode 'subtle' is the canonical case). Keys are restricted to what
    // this function itself wrote, so applySublayerOverrides' writes and the
    // style's own paint are never clobbered.
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
  // builder-audit #338 SYNC-04: every companion id derived from one helper.
  const ids = getCompanionLayerIds(id, prefix);
  for (const candidate of [ids.label, ids.arrow, ids.extrusion, ids.outline, ids.clusterCount, ids.cluster, ids.mixedLines, ids.mixedPoints, layerId]) {
    if (map.getLayer(candidate)) map.removeLayer(candidate);
  }
}

/** Each layer's zoom range: the range its spec sets, else the saved layer's. */
function syncLayerZoomRange(map: MaplibreMap, layerIds: string[], zoom: ZoomRange, specs: readonly LayerSpec[]) {
  for (const id of layerIds) {
    if (!map.getLayer(id)) continue;
    const own = specs.find(({ layer }) => layer.id === id)?.layer;
    map.setLayerZoomRange(id, own?.minzoom ?? zoom.minzoom, own?.maxzoom ?? zoom.maxzoom);
  }
}

// builder-audit #338 SYNC-05: the cluster signature and the tile-url signature are
// kept in SEPARATE per-map WeakMaps. They were previously crammed into one Map
// (cluster key = sourceId, tile-url key = `${sourceId}::tileurl`), where a
// single `signatureMap.delete(sourceId)` in the non-cluster block risked wiping
// the tile-url guard if anyone "cleaned up" the deletes. With two typed stores
// the lifecycle rules are structural, not comment-enforced.
const clusterSourceSignatures = new WeakMap<MaplibreMap, Map<string, string>>();
const tileUrlSignatures = new WeakMap<MaplibreMap, Map<string, string>>();

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

function removeColorReliefCompanionLayer(map: MaplibreMap, layerId: string) {
  // builder-audit #338 SYNC-04: -colorrelief suffix lives in companion-ids.ts.
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
 * builder-audit #338 SYNC-03 + token-refresh: refresh a vector source's tiles ONLY
 * when the signed URL actually changed, honoring the per-source tile-url
 * signature. Both the in-pass sync (`syncVectorTiles`) and the BuilderMap
 * token-refresh effect call this, so a paint/visibility edit that does not
 * change the cols=/sig URL no longer re-issues setTiles (the flicker/refetch
 * guard that the standalone token-refresh effect previously bypassed). Returns
 * true when it actually re-tiled.
 */
export function refreshVectorSourceTiles(map: MaplibreMap, sourceId: string, tileUrl: string): boolean {
  const source = map.getSource(sourceId) as { type?: string; setTiles?: (tiles: string[]) => void } | undefined;
  if (!source || source.type !== 'vector' || typeof source.setTiles !== 'function') return false;
  const store = tileUrlSignatureStore(map);
  if (store.get(sourceId) === tileUrl) return false;
  source.setTiles([tileUrl]);
  store.set(sourceId, tileUrl);
  // fix(#584): maplibre 5.x silently drops setTiles' tile reload when the
  // source's TileManager is paused (any same-pass layer update pauses it):
  // the 'content' data event returns early without setting the
  // reload-on-resume flag, so loaded tiles keep serving the pre-edit cols=
  // payload until an unrelated re-tile. Re-issue the reload through the
  // public refreshTiles API — that path DOES set the resume flag, so the
  // refetch can no longer be lost. The refresh must wait until the source's
  // async load() has copied the new URL into `source.tiles` (fix(#586):
  // refreshing before adoption reloads the OLD url while the signature store
  // has already advanced, re-stranding the tiles), so poll for adoption with
  // a bounded retry that bails when the url is superseded by a newer edit or
  // the source is torn down.
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

// ---------------------------------------------------------------------------
// Sync sub-routines — extracted from syncLayersToMap for readability
// ---------------------------------------------------------------------------

/**
 * POLISH-02: Returns true when the given DEM layer is already consumed by the
 * active terrain source. In this state, starting a second raster-dem consumer
 * (for hillshade) causes MapLibre backfillBorder "dem dimension mismatch" errors.
 * Guard: terrain must be enabled AND the same dataset powers both consumers.
 *
 * Safety property: predicate is FALSE when terrainConfig.enabled=false (Map B),
 * so the primary hillshade path is completely unaffected on maps without terrain.
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

  // fix(HT-05): a terrain-bound hillshade always paints alongside the 3D mesh
  // on its own per-layer source (`source-${layer.id}` via getSourceIdForLayer,
  // NEVER the shared `terrain-dem` id, so the SF-04 teardown machinery does not
  // orphan it). The old shouldSkipHillshadeForTerrain tile-size-mismatch guard
  // (999.17 D-07) was dead code: terrain binding is same-dataset, so both
  // consumers derive tileSize from one raster token and can never mismatch.

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

/** Resolved per-layer source decisions — pure, no map side effects.
 *  builder-audit #338 SYNC-05: extracted from syncVectorLayer so the type/cluster
 *  resolution is testable and the gnarly source mutation lives separately. */
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
  // A clustered GeoJSON source is rebuilt when these options change; a cluster
  // tile source takes them in its URL, which refreshes in place.
  const desiredClusterSignature = canUseCluster
    ? `${getClusterSourceStrategy(layer).kind}:${clusterSourceSignature(adapterInput)}`
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

/** SYNC-05 unit 3 (syncVectorTiles): refresh the tiles of an EXISTING vector
 *  source through the guarded `refreshVectorSourceTiles` (one path for cluster
 *  and non-cluster), then advance the cluster signature for server clusters. */
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

/** SYNC-05 unit 2 (ensureVectorSource): create / recreate the described geojson
 *  or vector source and reconcile its tiles. Returns true when the geojson path
 *  fully handled visibility + zoom range (caller returns early). */
function ensureVectorSource(
  map: MaplibreMap,
  layer: SyncLayerInput,
  adapterInput: AdapterLayerInput,
  mode: VectorSourceMode,
  source: VectorSourceSpecification | GeoJSONSourceSpecification,
  zoom: ZoomRange,
  specs: readonly LayerSpec[],
  prefix: string | undefined,
): boolean {
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
    // Clear only the CLUSTER signature. The tile-url signature lives in its own
    // WeakMap (SYNC-05), so this per-pass cleanup can no longer wipe the flicker
    // guard — the lifecycle is structural, not comment-enforced.
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
      // fix(#1472 review): setData carries data only — MapLibre reads a GeoJSON
      // source's `attribution` at construction and exposes no setter, so an
      // attribution edited mid-session does not reach a source already on the
      // map. Accepted rather than engineered around: the alternative is
      // remove-and-re-add, which drops the rendered features and refetches, and
      // the credit is correct again on the next load of the builder. Every
      // PUBLISHED surface (viewer, share, embed, exported style) re-reads the
      // field per render or per request and is never stale.
      if (src && src.type === 'geojson') (src as GeoJSONSource).setData(source.data);
      // A second layer sharing this dataset's source (the SF-04 dedupe) hits this
      // branch even though its own layer was never added. syncPaint no-ops when the
      // layer is missing, so add it here instead. See #311.
      if (!map.getLayer(layerId)) adapter.addLayers(map, adapterInput);
      else adapter.syncPaint(map, adapterInput);
    }
    adapter.syncVisibility(map, adapterInput);
    syncLayerZoomRange(map, adapter.getLayerIds(layerId), zoom, specs);
    return true;
  }

  if (!map.getSource(sourceId)) {
    // lineMetrics is sticky per D-02 (255-CONTEXT.md): we only set it at source CREATE time.
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
    // A second layer sharing this dataset's source (the SF-04 dedupe) reaches this
    // branch with its own layer never added — the shared source was created by the
    // first layer. syncPaint no-ops when the layer is missing, so add it here. #311.
    if (!map.getLayer(layerId)) adapter.addLayers(map, adapterInput);
    else adapter.syncPaint(map, adapterInput);
  }
  return false;
}

/** Add or update a vector (MVT / GeoJSON) layer. Each labelled adapter's own
 *  `describe()` carries its label companion, so addLayers/syncPaint/
 *  syncVisibility already cover it — this orchestrates only source resolution
 *  and zoom range. */
function syncVectorLayer(
  map: MaplibreMap,
  layer: SyncLayerInput,
  described: DescribedLayer,
  source: VectorSourceSpecification | GeoJSONSourceSpecification,
  adapterInput: AdapterLayerInput,
  desiredSources: Set<string>,
  prefix: string | undefined,
) {
  const { sourceId, layerId } = adapterInput;
  desiredSources.add(sourceId);
  const zoom = described.zoom ?? FULL_ZOOM_RANGE;

  const mode = resolveVectorSourceMode(layer, adapterInput, described.drawsAs, source);
  const handledGeoJson = ensureVectorSource(map, layer, adapterInput, mode, source, zoom, described.specs, prefix);
  if (handledGeoJson) return;

  const outlineLayerId = prefixed('outline', layer.id, prefix);
  const extrusionLayerId = prefixed('extrusion', layer.id, prefix);
  const arrowLayerId = prefixed('arrow', layer.id, prefix);
  // fix(#430 codex r23): union with the adapter's own ids so mixed-geometry
  // sublayers (-lines/-points) honor the custom zoom range too.
  syncLayerZoomRange(
    map,
    [...new Set([...mode.adapter.getLayerIds(layerId), outlineLayerId, extrusionLayerId, arrowLayerId])],
    zoom,
    described.specs,
  );

  mode.adapter.syncVisibility(map, adapterInput);
}

/**
 * Remove a layer's label companion when the family it now draws as has no
 * label spec for it. A layer can switch into heatmap or symbol through a
 * state-only path (bulk style apply, restore) that never calls
 * `swapLayerOnMap`'s unconditional companion removal, and neither family's
 * own `syncPaint` calls `removeLabelCompanionIfCleared` (their `describe()`
 * never produces a label spec to begin with). Called once per layer here,
 * after `syncVectorLayer`, rather than from each adapter, so it covers every
 * drawsAs value uniformly.
 */
function removeOrphanedLabelCompanion(
  map: MaplibreMap,
  drawsAs: DescribedLayer['drawsAs'],
  adapterInput: AdapterLayerInput,
): void {
  const labelId = labelLayerId(adapterInput.layerId);
  if (!map.getLayer(labelId)) return;
  const hasLabelSpec = getAdapter(drawsAs).describe?.(adapterInput).specs.some((spec) => spec.layer.id === labelId) ?? false;
  if (!hasLabelSpec) map.removeLayer(labelId);
}

/** Remove every map layer whose `source` references `sourceId`. builder-audit
 *  SYNC-06: for a DEDUPED vector source the id derived from the source name is
 *  `data-${table}`, so the per-layer companion ids never match the real
 *  `layer-${layer.id}` ids — those orphan layers must be found structurally by
 *  walking the live style, not derived from the source key. */
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
    // EDITOR-DEM-05: color-relief companion has no own source (it reuses the
    // raster-dem source), so it is not found by the source-keyed loop and must
    // be removed explicitly here.
    removeColorReliefCompanionLayer(map, ids.layer);
    for (const candidate of [ids.label, ids.arrow, ids.extrusion, ids.outline, ids.clusterCount, ids.cluster, ids.mixedLines, ids.mixedPoints, ids.layer]) {
      if (map.getLayer(candidate)) map.removeLayer(candidate);
    }
    // builder-audit #338 SYNC-06: enumerate any remaining layers still referencing
    // this source (the deduped case where the derived ids above never matched)
    // and remove them BEFORE removeSource. Previously this relied on a sibling
    // path (removePerLayerCompanions) that early-returns mid-style-transition,
    // leaving orphan layers that made removeSource throw 'source ... in use'.
    removeLayersUsingSource(map, sourceId);
    if (map.getSource(sourceId)) map.removeSource(sourceId);
    clusterSourceSignatures.get(map)?.delete(sourceId);
    tileUrlSignatures.get(map)?.delete(sourceId);
  }
}

/** fix(#1778): remove managed data layers whose logical layer is gone even when
 *  their SOURCE is still wanted.
 *
 *  removeStaleSourcesAndLayers is keyed on the source, so under the SF-04
 *  dedupe (two layers on one dataset share `source-data-${table}`) deleting one
 *  of them leaves the source DESIRED and its layer rows are never reclaimed.
 *  The delete path's own cleanup (removePerLayerCompanions) is best-effort, so
 *  this walk is the backstop that closes the class rather than one instance.
 *
 *  Scoped on three conditions at once, so a basemap layer that happens to be
 *  named `layer-*` and anything a plugin added are left alone: the id starts
 *  with the managed `layer-` prefix, the layer sits on a data source (every
 *  managed layer does, including the label and color-relief companions), and
 *  the id is absent from the companion-id expansion of the desired set. */
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

// ---------------------------------------------------------------------------

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
  let description: Description;
  try {
    description = describeLayers(renderableLayers, syncRenderContext(tokenMap, tileBaseUrl, geojsonDataMap, options));
  } catch (err) {
    // Only an unresolved tenant prefix throws here, and every caller gates on it.
    for (const layer of renderableLayers) reportLayerSyncFailure(layer, err);
    return;
  }
  const describedById = new Map(description.layers.map((described) => [described.id, described]));

  for (const layer of renderableLayers) {
    try {
      const described = describedById.get(prefixed('layer', layer.id, prefix));
      const source = described && description.sources.get(described.sourceId);
      // Terrain-mode DEMs have no entry, and a raster without a tile URL no source.
      if (!described || !source) continue;

      const adapterInput: AdapterLayerInput = {
        ...adapterInputFor(layer, described),
        // fix(#1472 review): reaches the raster / raster-dem source specs.
        attribution: layer.attribution ?? null,
      };

      if (source.type === 'raster' || source.type === 'raster-dem') {
        syncRasterLayer(map, adapterInput, source, desiredSources);
        // A raster without a saved range keeps MapLibre's uncapped default,
        // which FULL_ZOOM_RANGE would cut off at z22.
        if (described.zoom) {
          syncLayerZoomRange(
            map,
            [described.id, getCompanionLayerIds(layer.id, prefix).colorRelief],
            described.zoom,
            described.specs,
          );
        }
      } else if (source.type === 'vector' || source.type === 'geojson') {
        syncVectorLayer(map, layer, described, source, adapterInput, desiredSources, prefix);
        removeOrphanedLabelCompanion(map, described.drawsAs, adapterInput);
      }
    } catch (err) {
      reportLayerSyncFailure(layer, err);
    }
  }

  try {
    // fix(#1778): layer-aware prune first, so an orphan on a still-shared
    // deduped source is reclaimed. Ordered before the source prune because the
    // source prune's removeLayersUsingSource depends on the layer set only for
    // sources it is about to drop.
    removeOrphanManagedLayers(map, renderableLayers.map((l) => l.id), sourcePrefix, prefix);
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
    const colorReliefId = `${lid}${COLOR_RELIEF_SUFFIX}`;
    const cid = clusterCircleLayerId(lid);
    const ccid = clusterCountLayerId(lid);
    // fix(#431 codex r1): mixed-geometry family sublayers move with their parent,
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
