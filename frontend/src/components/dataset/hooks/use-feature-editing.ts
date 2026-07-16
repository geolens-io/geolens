/**
 * Hook that encapsulates all feature CRUD logic for the dataset map.
 *
 * Manages: create (with overlay), select, edit geometry, edit attributes,
 * delete, deselect, tile reload, and hide-filter lifecycle.
 */
import { useCallback, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { useDrawingStore } from '@/stores/drawing-store';
import { useCreateFeature, useUpdateFeature, useDeleteFeature } from '@/hooks/use-features';
import { getFeature } from '@/api/features';
import { getModeName, extractSingleGeometry, isMultiPartGeometry } from '@/components/drawing/hooks/use-terra-draw';
import { buildSignedTileUrl } from '@/lib/tile-utils';
import { formatMutationError } from '@/lib/error-map';
import { getEnvConfig } from '@/lib/env';
import type { Map as MaplibreMap } from 'maplibre-gl';
import type { Feature, Geometry } from 'geojson';

/** Vector tile layer IDs used for querying and filtering */
const VECTOR_TILE_LAYERS = ['vector-points', 'vector-lines', 'vector-fill', 'vector-outline', 'vector-extrusion'];

/** Empty GeoJSON FeatureCollection for overlay reset */
const EMPTY_FC: GeoJSON.FeatureCollection = { type: 'FeatureCollection', features: [] };

/** Hide a specific feature from vector tile layers by filtering on gid */
// fix(#430 codex r22): generic sketch datasets install per-family
// geometry-type filters at layer creation (use-map-layers). The editing gid
// filter must COMPOSE with those base filters, and clearing must RESTORE
// them — overwriting with the gid filter / null made polygon outlines bleed
// into the line renderer after any select/deselect on a generic dataset.
// Base filters are captured per map on first touch (they are static after
// layer creation).
const _baseFilters = new WeakMap<MaplibreMap, Map<string, unknown>>();

function _baseFilter(map: MaplibreMap, layerId: string): unknown {
  let perMap = _baseFilters.get(map);
  if (!perMap) {
    perMap = new Map();
    _baseFilters.set(map, perMap);
  }
  if (!perMap.has(layerId)) {
    perMap.set(layerId, map.getFilter(layerId) ?? null);
  }
  return perMap.get(layerId) ?? null;
}

function hideFeatureFromTiles(map: MaplibreMap, gid: number) {
  for (const layerId of VECTOR_TILE_LAYERS) {
    if (map.getLayer(layerId)) {
      const base = _baseFilter(map, layerId);
      const gidFilter = ['all', ['has', 'id'], ['!=', ['id'], gid]];
      map.setFilter(
        layerId,
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        (base ? ['all', base, gidFilter] : gidFilter) as any,
      );
    }
  }
}

/** Restore vector tile layers to their creation-time (base) filters */
export function showAllFeaturesInTiles(map: MaplibreMap) {
  for (const layerId of VECTOR_TILE_LAYERS) {
    if (map.getLayer(layerId)) {
      // Capture-on-first-touch also covers the cancel-before-any-hide path.
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      map.setFilter(layerId, _baseFilter(map, layerId) as any);
    }
  }
}

interface UseFeatureEditingOptions {
  mapRef: React.RefObject<MaplibreMap | null>;
  datasetId?: string;
  tableName: string | null;
  tileConfig: { cdn_base_url?: string | null } | null;
  tileToken: { sig: string; exp: number; scope: string } | null;
  /** TerraDraw methods */
  removeFeatures: (ids: (string | number)[]) => void;
  getSnapshotFeature: (id: string | number) => Feature | undefined;
  addFeatures: (features: Feature[]) => { id?: string | number; valid: boolean }[];
  selectFeature: (id: string) => void;
  clear: () => void;
}

export function useFeatureEditing({
  mapRef,
  datasetId,
  tableName,
  tileConfig,
  tileToken,
  removeFeatures,
  getSnapshotFeature,
  addFeatures,
  selectFeature: tdSelectFeature,
  clear,
}: UseFeatureEditingOptions) {
  const { t } = useTranslation('dataset');
  const createFeature = useCreateFeature();
  const updateFeatureMutation = useUpdateFeature();
  const deleteFeatureMutation = useDeleteFeature();

  const setSelectedFeature = useDrawingStore((s) => s.setSelectedFeature);
  const clearSelectedFeature = useDrawingStore((s) => s.clearSelectedFeature);
  const setEditDirty = useDrawingStore((s) => s.setEditDirty);

  const overlayFeaturesRef = useRef<GeoJSON.Feature[]>([]);
  const overlayCleanupRef = useRef<{ off: () => void; clearTimer: () => void } | null>(null);

  /** Swap tile URLs with a cache-busted version to force fresh tile fetches. */
  const reloadTiles = useCallback(() => {
    const map = mapRef.current;
    if (!map || !tableName) return;
    const source = map.getSource('vector-tile-source');
    if (source && 'setTiles' in source) {
      const tileBaseUrl = getEnvConfig().TILE_BASE_URL || tileConfig?.cdn_base_url;
      const freshUrl = buildSignedTileUrl(tableName, tileToken ?? null, tileBaseUrl, String(Date.now()));
      (source as maplibregl.VectorTileSource).setTiles([freshUrl]);
    }
  }, [mapRef, tableName, tileConfig?.cdn_base_url, tileToken]);

  /** Clean up overlay sourcedata listener. Call on unmount. */
  const cleanupOverlayListener = useCallback(() => {
    overlayCleanupRef.current?.off();
    overlayCleanupRef.current?.clearTimer();
    overlayCleanupRef.current = null;
  }, []);

  /** Create a new feature and refresh tiles. */
  const saveAndRefresh = useCallback(
    async (geometry: Geometry, properties: Record<string, unknown>) => {
      if (!datasetId || !tableName) return;
      const map = mapRef.current;

      // Overlay for instant visibility
      const overlayFeature: GeoJSON.Feature = { type: 'Feature', geometry, properties: properties ?? {} };
      overlayFeaturesRef.current = [...overlayFeaturesRef.current, overlayFeature];
      if (map) {
        const src = map.getSource('drawn-overlay') as maplibregl.GeoJSONSource | undefined;
        src?.setData({ type: 'FeatureCollection', features: overlayFeaturesRef.current });
      }

      try {
        await createFeature.mutateAsync({
          datasetId,
          geometry: geometry as Geometry,
          properties,
        });
        toast.success(t('map.featureSaved'));
        reloadTiles();

        // Clear overlay after tiles load
        if (map) {
          cleanupOverlayListener();
          const clearOverlay = () => {
            overlayFeaturesRef.current = [];
            const src = map.getSource('drawn-overlay') as maplibregl.GeoJSONSource | undefined;
            src?.setData(EMPTY_FC);
            overlayCleanupRef.current = null;
          };
          const onSourceData = (e: { sourceId?: string; isSourceLoaded?: boolean }) => {
            if (e.sourceId === 'vector-tile-source' && e.isSourceLoaded) {
              map.off('sourcedata', onSourceData);
              clearTimeout(fallbackTimer);
              clearOverlay();
            }
          };
          map.on('sourcedata', onSourceData);
          const fallbackTimer = setTimeout(() => {
            map.off('sourcedata', onSourceData);
            clearOverlay();
          }, 5000);
          overlayCleanupRef.current = {
            off: () => map.off('sourcedata', onSourceData),
            clearTimer: () => clearTimeout(fallbackTimer),
          };
        }
      } catch (err) {
        // fix(#458 E-36): surface the backend's reason (invalid geometry,
        // type mismatch) like the table path does, not a bare "failed".
        toast.error(formatMutationError('dataset:map.featureSaveFailed', err));
        overlayFeaturesRef.current = overlayFeaturesRef.current.filter((f) => f !== overlayFeature);
        if (map) {
          const src = map.getSource('drawn-overlay') as maplibregl.GeoJSONSource | undefined;
          src?.setData({ type: 'FeatureCollection', features: overlayFeaturesRef.current });
        }
      }
    },
    [datasetId, tableName, mapRef, createFeature, reloadTiles, cleanupOverlayListener, t],
  );

  /** Deselect the currently selected feature, restoring tile visibility. */
  const performDeselect = useCallback(() => {
    const sf = useDrawingStore.getState().selectedFeature;
    if (!sf) return;
    try { removeFeatures([sf.tdId]); } catch { /* already removed */ }
    const map = mapRef.current;
    if (map) showAllFeaturesInTiles(map);
    clearSelectedFeature();
  }, [mapRef, removeFeatures, clearSelectedFeature]);

  /** Save edited geometry for the selected feature. */
  const handleSaveEdit = useCallback(async () => {
    const sf = useDrawingStore.getState().selectedFeature;
    if (!sf || !datasetId || !tableName) return;

    const feature = getSnapshotFeature(sf.tdId);
    if (!feature) {
      toast.error(t('map.featureRetrieveFailed'));
      return;
    }

    try {
      await updateFeatureMutation.mutateAsync({
        datasetId,
        gid: sf.gid,
        geometry: feature.geometry as Geometry,
      });
      toast.success(t('map.featureUpdated'));
      try { removeFeatures([sf.tdId]); } catch { /* already removed */ }
      reloadTiles();
      const map = mapRef.current;
      if (map) showAllFeaturesInTiles(map);
      clearSelectedFeature();
    } catch (err) {
      // fix(#458 E-36): keep the backend detail.
      toast.error(formatMutationError('dataset:map.featureUpdateFailed', err));
    }
  }, [datasetId, tableName, mapRef, getSnapshotFeature, updateFeatureMutation, removeFeatures, clearSelectedFeature, reloadTiles, t]);

  /** Delete the selected feature. */
  const handleDeleteFeature = useCallback(async () => {
    const sf = useDrawingStore.getState().selectedFeature;
    if (!sf || !datasetId || !tableName) return;

    try {
      await deleteFeatureMutation.mutateAsync({ datasetId, gid: sf.gid });
      toast.success(t('map.featureDeleted'));
      try { removeFeatures([sf.tdId]); } catch { /* already removed */ }
      reloadTiles();
      const map = mapRef.current;
      if (map) showAllFeaturesInTiles(map);
      clearSelectedFeature();
    } catch (err) {
      // fix(#458 E-36): keep the backend detail.
      toast.error(formatMutationError('dataset:map.featureDeleteFailed', err));
    }
  }, [datasetId, tableName, mapRef, deleteFeatureMutation, removeFeatures, clearSelectedFeature, reloadTiles, t]);

  /** Update attributes of the selected feature. */
  const handleEditAttributeSubmit = useCallback(
    async (properties: Record<string, unknown>) => {
      const sf = useDrawingStore.getState().selectedFeature;
      if (!sf || !datasetId) return;
      try {
        await updateFeatureMutation.mutateAsync({ datasetId, gid: sf.gid, properties });
        toast.success(t('map.attributesUpdated'));
        setSelectedFeature({ ...sf, properties: { ...sf.properties, ...properties } });
        // BUG-042: the geometry handlers (handleSaveEdit/handleDeleteFeature)
        // reload tiles after a write; the attribute handler omitted it, so any
        // attribute-driven rendering kept stale values until a manual reload.
        // Cache-bust the vector tiles so the edited attributes render. Geometry
        // is unchanged, so the selection is intentionally kept.
        reloadTiles();
      } catch (err) {
        // fix(#458 E-36): keep the backend detail.
        toast.error(formatMutationError('dataset:map.attributesUpdateFailed', err));
      }
    },
    [datasetId, updateFeatureMutation, setSelectedFeature, reloadTiles, t],
  );

  /** Handle Terra Draw edit-finish (drag complete). */
  const handleEditFinish = useCallback(
    (_tdId: string, _feature: Feature) => {
      setEditDirty(true);
    },
    [setEditDirty],
  );

  /** Select a feature from the map by clicking on it. */
  const selectFeatureFromMap = useCallback(
    async (map: MaplibreMap, point: maplibregl.Point) => {
      if (useDrawingStore.getState().selectedFeature) return;
      if (!datasetId) return;

      const queryLayers = ['vector-points', 'vector-lines', 'vector-fill', 'vector-extrusion'].filter(
        (id) => map.getLayer(id),
      );
      if (queryLayers.length === 0) return;

      const features = map.queryRenderedFeatures(point, { layers: queryLayers });
      if (!features || features.length === 0) return;

      // MVT feature ID is stored in _vectorTileFeature.id by MapLibre,
      // promoted to feature.id via promoteId, or available as a property.
      const f0 = features[0] as typeof features[0] & { _vectorTileFeature?: { id?: number } };
      const gid = features[0].id ?? features[0].properties?.gid ?? f0._vectorTileFeature?.id;
      if (gid === undefined || gid === null) {
        toast.info(t('map.featureNotSelectable'));
        return;
      }

      try {
        const fullFeature = await getFeature(datasetId, gid);
        clear();

        if (!fullFeature.geometry) {
          toast.error(t('map.featureLoadFailed'));
          return;
        }

        if (isMultiPartGeometry(fullFeature.geometry)) {
          toast.info(t('map.multiPartNotEditable'));
          return;
        }

        const singleGeometry = extractSingleGeometry(fullFeature.geometry);
        const modeName = getModeName(singleGeometry.type);

        const result = addFeatures([{
          type: 'Feature',
          geometry: singleGeometry,
          properties: { mode: modeName },
        }]);

        if (result[0]?.valid && result[0].id !== undefined) {
          const tdId = String(result[0].id);
          setSelectedFeature({ gid, tdId, properties: fullFeature.properties });
          tdSelectFeature(tdId);
          hideFeatureFromTiles(map, gid);
        } else {
          toast.error(t('map.featureLoadFailed'));
        }
      } catch {
        toast.error(t('map.featureLoadFailed'));
      }
    },
    [datasetId, clear, addFeatures, setSelectedFeature, tdSelectFeature, t],
  );

  return {
    saveAndRefresh,
    performDeselect,
    handleSaveEdit,
    handleDeleteFeature,
    handleEditFinish,
    handleEditAttributeSubmit,
    selectFeatureFromMap,
    reloadTiles,
    cleanupOverlayListener,
  };
}
