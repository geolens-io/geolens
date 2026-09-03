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
import type { Map as MaplibreMap, GeoJSONSource, Point, VectorTileSource } from 'maplibre-gl';
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
  /** fix(round1 #1795): reset the undo ring once a pending edit settles
   *  (save, cancel, or deselection) — NOT on every drag/vertex finish. */
  resetHistory: () => void;
}

/**
 * fix(#1761 review round 7): shared by every mutation's success AND failure
 * path — round 5/6 found catch blocks that skipped the same epoch recheck
 * their own success path already did, so a request that FAILED after an
 * identity change still surfaced its error toast (and, for create, its
 * failed-write UI feedback) to whoever is signed in now. One helper used in
 * all six places (three successes, three failures) instead of six
 * hand-rolled comparisons, so a seventh mutation added later has an
 * unmissable pattern to copy.
 */
function isStale(epoch: number): boolean {
  return useDrawingStore.getState().sessionEpoch !== epoch;
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
  resetHistory,
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
      (source as VectorTileSource).setTiles([freshUrl]);
    }
  }, [mapRef, tableName, tileConfig?.cdn_base_url, tileToken]);

  /** Clean up overlay sourcedata listener. Call on unmount. */
  const cleanupOverlayListener = useCallback(() => {
    overlayCleanupRef.current?.off();
    overlayCleanupRef.current?.clearTimer();
    overlayCleanupRef.current = null;
  }, []);

  // fix(#1761 review round 4): empties the overlay ref and the map's
  // drawn-overlay source immediately — used by the identity-change cleanup
  // (DatasetMap's finishDrawingSession, keyed on sessionEpoch) so a shape
  // drawn-but-not-yet-committed under the previous identity does not sit
  // on the map for whoever is signed in next. Cancels the pending
  // sourcedata/timeout listener too, since it would otherwise still be
  // holding a reference to the (about to be stale) overlay feature.
  const resetOverlay = useCallback(() => {
    cleanupOverlayListener();
    overlayFeaturesRef.current = [];
    const map = mapRef.current;
    if (map) {
      const src = map.getSource('drawn-overlay') as GeoJSONSource | undefined;
      src?.setData(EMPTY_FC);
    }
  }, [cleanupOverlayListener, mapRef]);

  /** Create a new feature and refresh tiles. */
  const saveAndRefresh = useCallback(
    async (geometry: Geometry, properties: Record<string, unknown>) => {
      if (!datasetId || !tableName) return;
      const map = mapRef.current;

      // fix(#1761 review round 4): captured before the mutation's await —
      // clearOverlay() below must not erase a NEWER identity's own overlay
      // if this request's identity has since changed.
      const epoch = useDrawingStore.getState().sessionEpoch;

      // Overlay for instant visibility
      const overlayFeature: GeoJSON.Feature = { type: 'Feature', geometry, properties: properties ?? {} };
      overlayFeaturesRef.current = [...overlayFeaturesRef.current, overlayFeature];
      if (map) {
        const src = map.getSource('drawn-overlay') as GeoJSONSource | undefined;
        src?.setData({ type: 'FeatureCollection', features: overlayFeaturesRef.current });
      }

      try {
        await createFeature.mutateAsync({
          datasetId,
          geometry: geometry as Geometry,
          properties,
        });
        // fix(#1761 review round 4): if the identity changed while this
        // request was in flight, the identity-change cleanup already
        // emptied the overlay ref/source (resetOverlay, via
        // finishDrawingSession). Reporting success and reloading tiles
        // here would only be feedback for an identity that is no longer
        // looking, and re-arming the listener below would have nothing
        // useful left to clear.
        if (isStale(epoch)) return;
        toast.success(t('map.featureSaved'));
        reloadTiles();

        // Clear overlay after tiles load
        if (map) {
          cleanupOverlayListener();
          const clearOverlay = () => {
            // fix(#1761 review round 4): re-checked at fire time, not just
            // at the mutation's resolution above — the identity can change
            // again in the gap before the tile-load event (or the 5s
            // fallback) fires, and a second identity may have started
            // their own overlay by then.
            if (isStale(epoch)) return;
            overlayFeaturesRef.current = [];
            const src = map.getSource('drawn-overlay') as GeoJSONSource | undefined;
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
        // fix(#1761 review round 7): the toast is feedback for whoever
        // issued this request — reject it the same way the success branch
        // above already does, or a failed create surfaces A's backend
        // error to B. The overlay-ref filtering below stays unconditional:
        // see its own comment for why it's already safe either way.
        if (!isStale(epoch)) {
          // fix(#458 E-36): surface the backend's reason (invalid geometry,
          // type mismatch) like the table path does, not a bare "failed".
          toast.error(formatMutationError('dataset:map.featureSaveFailed', err));
        }
        // Not epoch-gated: this filters OUT the one feature this specific
        // call added, by object identity, rather than clearing the ref —
        // safe even if a second identity has since added their own
        // overlay feature to the same ref, because that entry survives
        // the filter untouched.
        overlayFeaturesRef.current = overlayFeaturesRef.current.filter((f) => f !== overlayFeature);
        if (map) {
          const src = map.getSource('drawn-overlay') as GeoJSONSource | undefined;
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
    // fix(round1 #1795): deselection (also used for Cancel — see
    // DatasetMap's handleDeselect) discards any pending, un-saved undo
    // history for the edit just abandoned.
    resetHistory();
  }, [mapRef, removeFeatures, clearSelectedFeature, resetHistory]);

  /** Save edited geometry for the selected feature. */
  const handleSaveEdit = useCallback(async () => {
    const sf = useDrawingStore.getState().selectedFeature;
    if (!sf || !datasetId || !tableName) return;

    const feature = getSnapshotFeature(sf.tdId);
    if (!feature) {
      toast.error(t('map.featureRetrieveFailed'));
      return;
    }

    // fix(#1761 review round 3 P2): captured before the mutation's
    // await — see handleDeleteFeature below for the shared rationale.
    const epoch = useDrawingStore.getState().sessionEpoch;
    try {
      await updateFeatureMutation.mutateAsync({
        datasetId,
        gid: sf.gid,
        geometry: feature.geometry as Geometry,
      });
      // fix(#1761 review round 3 P2): if the identity changed while this
      // request was in flight, a second identity may have adopted their
      // own selection by now. Applying this success's cleanup here would
      // remove THEIR terra draw feature by a colliding tdId, restore tile
      // filters out from under them, and clear THEIR selectedFeature. The
      // write already landed server-side, which is as far as a stale
      // caller's responsibility goes — skip the rest.
      if (isStale(epoch)) return;
      toast.success(t('map.featureUpdated'));
      try { removeFeatures([sf.tdId]); } catch { /* already removed */ }
      reloadTiles();
      const map = mapRef.current;
      if (map) showAllFeaturesInTiles(map);
      clearSelectedFeature();
      // fix(round1 #1795): the edit just landed server-side — the pending
      // undo history it belonged to is no longer meaningful.
      resetHistory();
    } catch (err) {
      // fix(#1761 review round 7): mirror the success branch's recheck —
      // a failed update is feedback for whoever issued it, not whoever is
      // signed in by the time it rejects.
      if (isStale(epoch)) return;
      // fix(#458 E-36): keep the backend detail.
      toast.error(formatMutationError('dataset:map.featureUpdateFailed', err));
    }
  }, [datasetId, tableName, mapRef, getSnapshotFeature, updateFeatureMutation, removeFeatures, clearSelectedFeature, reloadTiles, resetHistory, t]);

  /** Delete the selected feature. */
  const handleDeleteFeature = useCallback(async () => {
    const sf = useDrawingStore.getState().selectedFeature;
    if (!sf || !datasetId || !tableName) return;

    // fix(#1761 review round 3 P2): captured before the mutation's
    // await. A second identity can adopt their own selection while this
    // delete is in flight; applying this success's cleanup then would
    // remove THEIR terra draw feature by a colliding tdId, restore tile
    // filters out from under them, and clear THEIR selectedFeature.
    const epoch = useDrawingStore.getState().sessionEpoch;
    try {
      await deleteFeatureMutation.mutateAsync({ datasetId, gid: sf.gid });
      if (isStale(epoch)) return;
      toast.success(t('map.featureDeleted'));
      try { removeFeatures([sf.tdId]); } catch { /* already removed */ }
      reloadTiles();
      const map = mapRef.current;
      if (map) showAllFeaturesInTiles(map);
      clearSelectedFeature();
      // fix(round2 #1795): the deleted feature no longer exists — its
      // pending undo history (which would restore it as a client-side
      // ghost) is no longer meaningful. Same point handleSaveEdit resets at.
      resetHistory();
    } catch (err) {
      // fix(#1761 review round 7): mirror the success branch's recheck —
      // a failed delete is feedback for whoever issued it, not whoever is
      // signed in by the time it rejects.
      if (isStale(epoch)) return;
      // fix(#458 E-36): keep the backend detail.
      toast.error(formatMutationError('dataset:map.featureDeleteFailed', err));
    }
  }, [datasetId, tableName, mapRef, deleteFeatureMutation, removeFeatures, clearSelectedFeature, reloadTiles, resetHistory, t]);

  /** Update attributes of the selected feature. */
  // fix(#1761 review round 4): returns whether the caller may treat this
  // submission as settled. DatasetMap's AttributeForm onSubmit closes the
  // dialog unconditionally once this resolves — for a stale request that
  // discards a SECOND identity's own now-open editor for their feature.
  // `applied: false` ONLY for that stale-epoch case, so the caller keeps
  // the dialog open; a real failure still resolves `applied: true`,
  // preserving the pre-existing behavior of closing on error.
  const handleEditAttributeSubmit = useCallback(
    async (properties: Record<string, unknown>): Promise<{ applied: boolean }> => {
      const sf = useDrawingStore.getState().selectedFeature;
      if (!sf || !datasetId) return { applied: true };
      // fix(#1761 review round 2 P1): captured BEFORE the mutation's await,
      // not re-read afterward — by the time this resolves, a second
      // identity may have adopted its own new target, whose fresh epoch
      // would otherwise make this stale write look current. See
      // drawing-store.ts's setSelectedFeature doc comment.
      const epoch = useDrawingStore.getState().sessionEpoch;
      try {
        await updateFeatureMutation.mutateAsync({ datasetId, gid: sf.gid, properties });
        // fix(#1761 review round 4): recheck immediately after the await,
        // before reporting success, writing to the store, or reloading
        // tiles. setSelectedFeature's own epoch check already refuses the
        // store write on its own, but this validates it BEFORE those other
        // effects run and reports it to the caller via the return value.
        if (isStale(epoch)) return { applied: false };
        toast.success(t('map.attributesUpdated'));
        setSelectedFeature({ ...sf, properties: { ...sf.properties, ...properties } }, epoch);
        // BUG-042: the geometry handlers (handleSaveEdit/handleDeleteFeature)
        // reload tiles after a write; the attribute handler omitted it, so any
        // attribute-driven rendering kept stale values until a manual reload.
        // Cache-bust the vector tiles so the edited attributes render. Geometry
        // is unchanged, so the selection is intentionally kept.
        reloadTiles();
        return { applied: true };
      } catch (err) {
        // fix(#1761 review round 5): mirror the success path's recheck. If
        // the identity changed while this request was in flight, the
        // failure is A's, not whoever is looking now (possibly B, with
        // their own editor open for their own feature) — reporting it as
        // an error toast and telling the caller to close would be exactly
        // the same collateral damage the success path already guards
        // against, just via the rejection branch instead of the resolve one.
        if (isStale(epoch)) return { applied: false };
        // fix(#458 E-36): keep the backend detail.
        toast.error(formatMutationError('dataset:map.attributesUpdateFailed', err));
        return { applied: true };
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

  /**
   * fix(round2 #1795): Terra Draw's undo() popped the ring back to its
   * earliest recorded snapshot — the displayed geometry is once again
   * whatever was there when the ring started, so there is no longer a
   * pending edit to confirm away on Cancel/Done/mode-switch. A subsequent
   * drag/vertex edit re-dirties normally via handleEditFinish above.
   */
  const handleHistoryBaseline = useCallback(() => {
    setEditDirty(false);
  }, [setEditDirty]);

  /** Select a feature from the map by clicking on it. */
  const selectFeatureFromMap = useCallback(
    async (map: MaplibreMap, point: Point) => {
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

      // fix(#1761 review round 2 P1): captured BEFORE the fetch's await, for
      // the same reason as handleEditAttributeSubmit above — a stale
      // resolution here must not be accepted just because someone else's
      // fresh target happens to make the live epoch look unchanged.
      const epoch = useDrawingStore.getState().sessionEpoch;
      try {
        const fullFeature = await getFeature(datasetId, gid);
        // fix(#1761 review round 3 P1): recheck IMMEDIATELY after the
        // await, before ANY map mutation. setSelectedFeature's own epoch
        // check refuses the STORE write, but by then clear() and
        // addFeatures() below would already have installed the stale
        // geometry on the map, and the rest of this block would go on to
        // select it and hide its tile.
        if (isStale(epoch)) return;
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
          setSelectedFeature({ gid, tdId, properties: fullFeature.properties }, epoch);
          tdSelectFeature(tdId);
          hideFeatureFromTiles(map, gid);
        } else {
          toast.error(t('map.featureLoadFailed'));
        }
      } catch {
        // fix(#1761 review round 8): mirror the success branch's recheck —
        // a failed fetch is feedback for whoever clicked the feature, not
        // whoever is signed in (or anonymous) by the time getFeature()
        // rejects.
        if (isStale(epoch)) return;
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
    handleHistoryBaseline,
    handleEditAttributeSubmit,
    selectFeatureFromMap,
    reloadTiles,
    cleanupOverlayListener,
    resetOverlay,
  };
}
