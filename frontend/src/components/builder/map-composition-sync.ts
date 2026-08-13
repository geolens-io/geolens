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

// feat(#845): one pending root-style idle-retry per map instance, so a newer
// appearance application can cancel a stale one (Codex P2 on #848). Covers
// projection and, since feat(#1473), sky — both are root style state with the
// same "needs a parsed style" precondition.
const pendingRootStyleRetries = new WeakMap<MaplibreMap, () => void>();

// feat(#1473): atmosphere for globe maps, so the sphere reads as a planet
// instead of a flat disc. `atmosphere-blend` is the only sky property a globe
// actually shows: MapLibre draws the limb halo in a separate atmosphere pass
// scaled by this value, while the sky pass that consumes sky-color /
// horizon-color / sky-horizon-blend is multiplied out to fully transparent for
// as long as the projection is a globe.
//
// So the colors stay at their MapLibre defaults on purpose. A globe map zoomed
// past MapLibre's automatic globe-to-mercator handoff turns the sky pass back
// on, and a near-black sky-color would land there as a black band above the
// horizon on pitched views — the one place it is visible is the one place it
// would look wrong.
//
// The zoom ramp is upstream's own curve from their globe-with-atmosphere
// example: a full halo at world view, held through continental zoom, gone by
// the time the limb has left the frame.
const GLOBE_SKY: SkySpecification = {
  'atmosphere-blend': ['interpolate', ['linear'], ['zoom'], 0, 1, 5, 1, 7, 0],
};

// fix(#1474 Codex P2 round 1): a remote basemap style may ship its own `sky`
// block, and sanitizeMaplibreStyle() passes root properties through untouched.
// So the atmosphere is layered OVER whatever sky the style brought rather than
// replacing it, and mercator restores that sky instead of clearing it.
//
// `base` is the style's own sky and `applied` is what we last handed to
// setSky, read back from the map because maplibre skips the assignment when
// the new spec makes no difference. If the map is no longer holding `applied`,
// the style was reloaded underneath us and whatever it holds now is the new
// base to preserve.
type SkyState = { applied: SkySpecification | undefined; base: SkySpecification | undefined };
const skyStates = new WeakMap<MaplibreMap, SkyState>();

function applySky(map: MaplibreMap, isGlobe: boolean) {
  if (!map.setSky) return;
  const current = map.getSky?.();
  const tracked = skyStates.get(map);
  const base = tracked && current === tracked.applied ? tracked.base : current;
  const next = isGlobe ? { ...base, ...GLOBE_SKY } : base;
  // Passing `undefined` is the branch maplibre reads as "no sky at all", which
  // is the correct reset for a style that never had one. An empty object is a
  // silent no-op instead, because the diff it runs only walks the keys of the
  // spec you hand it. Map.setSky types the argument as required even though
  // the Style method behind it declares it optional, hence the cast.
  map.setSky(next as SkySpecification);
  skyStates.set(map, { applied: map.getSky?.(), base });
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
    basemapPosition: options?.basemapPosition ?? basemapConfig?.basemap_position,
  };
}

export interface ApplyMapBasemapAppearanceOptions {
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
  // builder-audit #338 CORR-01: pass master opacity so per-sublayer opacity overrides
  // COMPOSE with it (override * master) rather than clobbering the master-opacity
  // paint applyBasemapConfigToMap just wrote.
  const masterOpacity = basemapConfig?.opacity ?? 1;

  // feat(#845): projection is root style state persisted on
  // basemap_config.projection — apply it with the rest of the basemap
  // appearance so viewer/shared surfaces honor the saved value, not just the
  // builder. setProjection only needs the style PARSED (maplibre's
  // Style._checkLoaded), which is already true inside a `style.load`
  // callback, so attempt it immediately rather than gating on
  // isStyleLoaded()/idle — a slow tile source would otherwise leave a saved
  // globe map visibly in mercator (Codex P2 round 2 on #848). If the style
  // is not parsed yet the call throws; retry once on `style.load`, and
  // cancel any stale retry first so a projection change during the load
  // window can't be reverted by an old callback (Codex P2 round 1 on #848).
  const staleRetry = pendingRootStyleRetries.get(map);
  if (staleRetry) {
    map.off?.('style.load', staleRetry);
    pendingRootStyleRetries.delete(map);
  }
  const projection = basemapConfig?.projection ?? 'mercator';
  const applyRootStyle = () => {
    pendingRootStyleRetries.delete(map);
    try {
      map.setProjection?.({ type: projection });
      // feat(#1473): sky shares setProjection's parsed-style precondition, so
      // it rides the same retry and survives style/basemap reloads.
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
    return;
  }

  reorderBasemapLabels(map, showBasemapLabels, sourcePrefix);
  applyBasemapConfigToMap(map, basemapConfig, showBasemapLabels, sourcePrefix);
  applySublayerOverrides(map, basemapConfig?.sublayer_overrides ?? null, sourcePrefix, masterOpacity);

  if (reorderDataLayerIds) {
    reorderDataLayers(map, reorderDataLayerIds, idPrefix);
  }
  reorderBasemapAboveData(map, basemapConfig?.basemap_position, sourcePrefix);
}

export interface SyncMapCompositionOptions {
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
