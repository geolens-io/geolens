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

  if (!map.isStyleLoaded()) {
    applySublayerOverrides(map, basemapConfig?.sublayer_overrides ?? null, sourcePrefix);
    return;
  }

  reorderBasemapLabels(map, showBasemapLabels, sourcePrefix);
  applyBasemapConfigToMap(map, basemapConfig, showBasemapLabels, sourcePrefix);
  applySublayerOverrides(map, basemapConfig?.sublayer_overrides ?? null, sourcePrefix);

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
