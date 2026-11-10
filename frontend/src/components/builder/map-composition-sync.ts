import { latest as styleSpec } from '@maplibre/maplibre-gl-style-spec';
import type { Map as MaplibreMap, SkySpecification } from 'maplibre-gl';
import type { TileToken } from '@/api/tiles';
import type { MapBasemapConfig } from '@/types/api';
import { applySublayerOverrides } from '@/lib/builder/basemap-style-mutation';
import {
  applyBasemapConfigToMap,
  reorderBasemapAboveData,
  reorderBasemapLabels,
  reorderDataLayers,
  syncLayersToMap,
  type SyncLayerInput,
  type SyncOptions,
} from './map-sync';

type RefBox<T> = { current: T };

// One pending root-style idle-retry per map instance, so a newer appearance
// application can cancel a stale one. Covers projection and sky: both are root
// style state needing a parsed style.
const pendingRootStyleRetries = new WeakMap<MaplibreMap, () => void>();

// Atmosphere for globe maps, so the sphere reads as a planet instead of a flat
// disc. `atmosphere-blend` is the only sky property a globe shows: MapLibre
// draws the limb halo in a separate atmosphere pass scaled by it, while the sky
// pass that consumes sky-color / horizon-color / sky-horizon-blend is
// multiplied out to fully transparent for as long as the projection is a globe.
//
// So the colors stay at their MapLibre defaults on purpose: a globe map zoomed
// past MapLibre's automatic globe-to-mercator handoff turns the sky pass back
// on, and a near-black sky-color would land there as a black band above the
// horizon on pitched views.
//
// The zoom ramp is upstream's curve from their globe-with-atmosphere example: a
// full halo at world view, held through continental zoom, gone by the time the
// limb has left the frame.
const GLOBE_SKY: SkySpecification = {
  'atmosphere-blend': ['interpolate', ['linear'], ['zoom'], 0, 1, 5, 1, 7, 0],
};

// A remote basemap style may ship its own `sky` block, and
// sanitizeMaplibreStyle() passes root properties through untouched. So the
// atmosphere is layered OVER whatever sky the style brought rather than
// replacing it, and mercator restores that sky instead of clearing it.
//
// `base` is the style's own sky and `applied` is what we last handed to setSky,
// read back from the map because maplibre skips the assignment when the new
// spec makes no difference. If the map no longer holds `applied`, the style was
// reloaded underneath us and whatever it holds now is the new base to preserve.
type SkyState = { applied: SkySpecification | undefined; base: SkySpecification | undefined };
const skyStates = new WeakMap<MaplibreMap, SkyState>();

// Handing back a `base` that never mentioned atmosphere-blend does not remove
// ours: setSky's diff walks only the keys of the spec you pass, so every key
// compares equal and the write is dropped with our override still in the live
// style. Naming the property explicitly forces the write, using the value a
// fresh load of `base` would evaluate to, read off the style spec so it cannot
// drift.
const DEFAULT_ATMOSPHERE_BLEND = styleSpec.sky['atmosphere-blend'].default as number;

function restoreSky(base: SkySpecification | undefined) {
  if (!base || base['atmosphere-blend'] !== undefined) return base;
  return { ...base, 'atmosphere-blend': DEFAULT_ATMOSPHERE_BLEND };
}

function applySky(map: MaplibreMap, isGlobe: boolean) {
  if (!map.setSky) return;
  const current = map.getSky?.();
  const tracked = skyStates.get(map);
  const base = tracked && current === tracked.applied ? tracked.base : current;
  const next = isGlobe ? { ...base, ...GLOBE_SKY } : restoreSky(base);
  // Passing `undefined` is the branch maplibre reads as "no sky at all", the
  // correct reset for a style that never had one. An empty object is a silent
  // no-op, because the diff only walks the keys of the spec you hand it.
  // Map.setSky types the argument as required though the Style method behind it
  // declares it optional, hence the cast.
  map.setSky(next as SkySpecification);
  skyStates.set(map, { applied: map.getSky?.(), base });
}

// The void behind the sphere, which no sky value can reach: the atmosphere pass
// returns alpha 0 for rays that miss the planet, the canvas clears transparent,
// and the style's `background` layer is drawn per tile so it stays clipped to
// the sphere. What shows through is the page behind the canvas, so the
// treatment is a background on the map container, with the color in `index.css`
// keyed on this marker.
//
// A dedicated attribute rather than container.style.backgroundColor keeps the
// value out of the component (DESIGN-GUIDE) and means we add and remove exactly
// the one attribute we own, so reverting cannot clobber a background that
// belongs to someone else.
const GLOBE_SPACE_ATTR = 'data-globe-space';

function applySpaceBackdrop(map: MaplibreMap, isGlobe: boolean) {
  // Partial map mocks in tests lack `getContainer`, hence the optional call.
  const container = map.getContainer?.();
  if (!container) return;
  if (isGlobe) container.setAttribute(GLOBE_SPACE_ATTR, 'true');
  else container.removeAttribute(GLOBE_SPACE_ATTR);
}

/**
 * Whether `map` is currently showing the globe space backdrop. Image captures
 * have to paint the same void the screen does, and asking the container what it
 * was marked with, rather than re-deriving globeness from projection state,
 * keeps a capture from disagreeing with the pixels it is capturing.
 */
export function hasGlobeSpaceBackdrop(map: MaplibreMap): boolean {
  return map.getContainer?.()?.hasAttribute(GLOBE_SPACE_ATTR) ?? false;
}

function sourcePrefixFor(idPrefix: string | undefined) {
  return idPrefix ? `${idPrefix}source-` : 'source-';
}

function compositionSyncOptions(
  options: SyncOptions | undefined,
  basemapConfig: MapBasemapConfig | null | undefined,
  showBasemapLabels: boolean,
): SyncOptions {
  return {
    ...options,
    showBasemapLabels,
    basemapPosition: options?.basemapPosition ?? basemapConfig?.basemap_position ?? undefined,
  };
}

interface ApplyMapBasemapAppearanceOptions {
  map: MaplibreMap;
  basemapConfig?: MapBasemapConfig | null;
  showBasemapLabels?: boolean;
  idPrefix?: string;
  reorderDataLayerIds?: Pick<SyncLayerInput, 'id'>[];
}

export function applyMapBasemapAppearance({
  map,
  basemapConfig,
  showBasemapLabels = true,
  idPrefix,
  reorderDataLayerIds,
}: ApplyMapBasemapAppearanceOptions) {
  const sourcePrefix = sourcePrefixFor(idPrefix);
  // Pass master opacity so per-sublayer opacity overrides COMPOSE with it
  // (override * master) rather than clobbering the master-opacity paint
  // applyBasemapConfigToMap just wrote.
  const masterOpacity = basemapConfig?.opacity ?? 1;

  // Projection is root style state persisted on basemap_config.projection;
  // apply it with the rest of the basemap appearance so viewer/shared surfaces
  // honor the saved value. setProjection only needs the style PARSED
  // (maplibre's Style._checkLoaded), which already holds inside a `style.load`
  // callback, so attempt it immediately rather than gating on
  // isStyleLoaded()/idle: a slow tile source would otherwise leave a saved
  // globe map in mercator. If the style is not parsed yet the call throws;
  // retry once on `style.load`, cancelling any stale retry first so a
  // projection change during the load window can't be reverted by an old
  // callback.
  const staleRetry = pendingRootStyleRetries.get(map);
  if (staleRetry) {
    map.off?.('style.load', staleRetry);
    pendingRootStyleRetries.delete(map);
  }
  const projection = basemapConfig?.projection ?? 'mercator';
  // The backdrop is DOM state, not style state, so it doesn't share
  // setProjection's parsed-style precondition and is applied outside the retry
  // below. Inside it, a throw from either maplibre call would strand the
  // backdrop out of step with the projection until `style.load`, permanently if
  // the throw came from anything other than an unparsed style.
  applySpaceBackdrop(map, projection === 'globe');
  const applyRootStyle = () => {
    pendingRootStyleRetries.delete(map);
    try {
      map.setProjection?.({ type: projection });
      // Sky shares setProjection's parsed-style precondition, so it rides the
      // same retry and survives style/basemap reloads.
      applySky(map, projection === 'globe');
    } catch {
      // Style not parsed yet — re-attempt as soon as it is. Partial map
      // mocks in tests lack `once`, hence the optional call.
      pendingRootStyleRetries.set(map, applyRootStyle);
      map.once?.('style.load', applyRootStyle);
    }
  };
  applyRootStyle();

  if (!map.isStyleLoaded()) {
    applySublayerOverrides(map, basemapConfig?.sublayer_overrides ?? null, sourcePrefix, masterOpacity);
  } else {
    reorderBasemapLabels(map, showBasemapLabels, sourcePrefix);
    applyBasemapConfigToMap(map, basemapConfig, showBasemapLabels, sourcePrefix);
    applySublayerOverrides(map, basemapConfig?.sublayer_overrides ?? null, sourcePrefix, masterOpacity);

    if (reorderDataLayerIds) {
      reorderDataLayers(map, reorderDataLayerIds, idPrefix);
    }
    reorderBasemapAboveData(map, basemapConfig?.basemap_position ?? undefined, sourcePrefix);
  }
  // Data composition can move layers above selection while sources are still pending.
  for (const id of ['attribute-table-highlight-line', 'attribute-table-highlight-point']) {
    if (map.getLayer(id)) map.moveLayer(id);
  }
}

interface SyncMapCompositionOptions {
  map: MaplibreMap;
  layers: SyncLayerInput[];
  tokenMap: Map<string, TileToken>;
  tileBaseUrl?: string;
  managedSourcesRef: RefBox<Set<string>>;
  orderKeyRef: RefBox<string>;
  geojsonDataMap?: Map<string, GeoJSON.FeatureCollection>;
  syncOptions?: SyncOptions;
  basemapConfig?: MapBasemapConfig | null;
  showBasemapLabels?: boolean;
  reorderDataLayerIds?: Pick<SyncLayerInput, 'id'>[];
  afterSync?: () => void;
}

export function syncMapComposition({
  map,
  layers,
  tokenMap,
  tileBaseUrl,
  managedSourcesRef,
  orderKeyRef,
  geojsonDataMap,
  syncOptions,
  basemapConfig,
  showBasemapLabels = true,
  reorderDataLayerIds = layers,
  afterSync,
}: SyncMapCompositionOptions) {
  const effectiveSyncOptions = compositionSyncOptions(syncOptions, basemapConfig, showBasemapLabels);
  syncLayersToMap(
    map,
    layers,
    tokenMap,
    tileBaseUrl,
    managedSourcesRef,
    orderKeyRef,
    geojsonDataMap,
    effectiveSyncOptions,
  );
  applyMapBasemapAppearance({
    map,
    basemapConfig,
    showBasemapLabels,
    idPrefix: syncOptions?.idPrefix,
    reorderDataLayerIds,
  });
  afterSync?.();
}
