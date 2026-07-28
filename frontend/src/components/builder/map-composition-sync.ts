import type { Map as MaplibreMap } from 'maplibre-gl';
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

// feat(#845): one pending projection idle-retry per map instance, so a newer
// appearance application can cancel a stale one (Codex P2 on #848).
const pendingProjectionRetries = new WeakMap<MaplibreMap, () => void>();

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
  const staleRetry = pendingProjectionRetries.get(map);
  if (staleRetry) {
    map.off?.('style.load', staleRetry);
    pendingProjectionRetries.delete(map);
  }
  const applyProjection = () => {
    pendingProjectionRetries.delete(map);
    try {
      map.setProjection?.({ type: basemapConfig?.projection ?? 'mercator' });
    } catch {
      // Style not parsed yet — re-attempt as soon as it is. Partial map
      // mocks in tests lack `once`, hence the optional call.
      pendingProjectionRetries.set(map, applyProjection);
      map.once?.('style.load', applyProjection);
    }
  };
  applyProjection();

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
