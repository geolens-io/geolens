/**
 * Hook that encapsulates all feature CRUD logic for the dataset map.
 *
 * Manages: create (with overlay), select, edit geometry, edit attributes,
 * delete, deselect, tile reload, and hide-filter lifecycle.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { useDrawingStore } from '@/stores/drawing-store';
import { useCreateFeature, useUpdateFeature, useDeleteFeature } from '@/hooks/use-features';
import { getFeature } from '@/api/features';
import { ApiError } from '@/api/client';
import { getModeName, extractSingleGeometry, isMultiPartGeometry } from '@/components/drawing/hooks/use-terra-draw';
import { buildSignedTileUrl } from '@/lib/tile-utils';
import { formatMutationError } from '@/lib/error-map';
import { getEnvConfig } from '@/lib/env';
import { randomId } from '@/lib/random-id';
import {
  PREVIEW_FEATURE_LAYER_IDS,
  PREVIEW_LAYER_IDS,
  previewSourceId,
} from '@/components/maps/hooks/use-map-layers';
import type { Map as MaplibreMap, FilterSpecification, GeoJSONSource, MapGeoJSONFeature, Point, VectorTileSource } from 'maplibre-gl';
import type { Feature, Geometry } from 'geojson';

/**
 * One idempotency key per sketch, keyed on the geometry object the dataset map
 * holds until a create succeeds. Every attempt to save that sketch (automatic
 * save, Save, Skip) sends the same key and the next attempt number, so a create
 * that committed before its response was lost is not inserted twice, and the
 * server applies the body of the highest attempt it receives. A new sketch is
 * a new object and starts again at attempt 1.
 */
const createAttempts = new WeakMap<Geometry, { key: string; count: number }>();

function nextCreateAttempt(geometry: Geometry): { key: string; attempt: number } {
  const entry = createAttempts.get(geometry) ?? { key: randomId(), count: 0 };
  entry.count += 1;
  createAttempts.set(geometry, entry);
  return { key: entry.key, attempt: entry.count };
}

/**
 * The feature a sketch already created, and the table it was read from, once
 * a retry learns someone else has edited it. The sketch's next Save updates
 * that feature rather than creating.
 */
const createdFeatures = new WeakMap<Geometry, { gid: number; tableId?: string | null }>();

interface RefusedFeature {
  id?: number;
  table_id?: string | null;
  tile_cache_version?: number;
}

/**
 * The structured 409 a keyed create gets for a retry the server can't apply.
 * A feature_gone carries a tile_cache_version when the table was replaced.
 */
function createRefusal(err: unknown): {
  code: 'feature_changed' | 'feature_gone';
  feature?: RefusedFeature;
  tile_cache_version?: number;
} | null {
  if (!(err instanceof ApiError) || err.status !== 409) return null;
  const detail = err.body as { code?: string; feature?: RefusedFeature; tile_cache_version?: number } | undefined;
  if (detail?.code === 'feature_changed') return { code: 'feature_changed', feature: detail.feature };
  return detail?.code === 'feature_gone' ? { code: 'feature_gone', tile_cache_version: detail.tile_cache_version } : null;
}

/**
 * The 409 for a write sent with a table_id whose table a reupload or overwrite
 * has since replaced. Nothing was written.
 */
function datasetReplaced(err: unknown): { tile_cache_version?: number | null } | null {
  if (!(err instanceof ApiError) || err.status !== 409) return null;
  const detail = err.body as { code?: string; tile_cache_version?: number | null } | undefined;
  return detail?.code === 'dataset_replaced' ? { tile_cache_version: detail.tile_cache_version } : null;
}

/** Empty GeoJSON FeatureCollection for overlay reset */
const EMPTY_FC: GeoJSON.FeatureCollection = { type: 'FeatureCollection', features: [] };

/** Hide a specific feature from vector tile layers by filtering on gid */
// Generic sketch datasets install per-family geometry-type filters at layer
// creation (use-map-layers). The gid filter must COMPOSE with those base
// filters and clearing must RESTORE them; overwriting with the gid filter or
// null made polygon outlines bleed into the line renderer. Base filters are
// captured per map on first touch (they are static after layer creation).
const _baseFilters = new WeakMap<MaplibreMap, Map<string, FilterSpecification | null>>();

function _baseFilter(map: MaplibreMap, layerId: string): FilterSpecification | null {
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
  for (const layerId of PREVIEW_LAYER_IDS) {
    if (map.getLayer(layerId)) {
      const base = _baseFilter(map, layerId);
      const gidFilter: FilterSpecification = ['all', ['has', 'id'], ['!=', ['id'], gid]];
      map.setFilter(layerId, (base ? ['all', base, gidFilter] : gidFilter) as FilterSpecification);
    }
  }
}

/** Restore vector tile layers to their creation-time (base) filters */
export function showAllFeaturesInTiles(map: MaplibreMap) {
  for (const layerId of PREVIEW_LAYER_IDS) {
    if (map.getLayer(layerId)) {
      // Capture-on-first-touch also covers the cancel-before-any-hide path.
      map.setFilter(layerId, _baseFilter(map, layerId));
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
  /** Reset the undo ring once a pending edit settles
   *  (save, cancel, or deselection) — NOT on every drag/vertex finish. */
  resetHistory: () => void;
}

/** A request belongs to one identity and drawing session, even after returning to a dataset. */
function isStale(
  epoch: number,
  targetDatasetId: string | null,
  generation: number,
  currentGeneration: number,
): boolean {
  const state = useDrawingStore.getState();
  return generation !== currentGeneration
    || state.sessionEpoch !== epoch || state.targetDatasetId !== targetDatasetId;
}

function isSelectionStale(
  epoch: number,
  targetDatasetId: string | null,
  selectedFeature: ReturnType<typeof useDrawingStore.getState>['selectedFeature'],
  generation: number,
  currentGeneration: number,
): boolean {
  return isStale(epoch, targetDatasetId, generation, currentGeneration)
    || useDrawingStore.getState().selectedFeature !== selectedFeature;
}

/**
 * A mutation entry point acts on whatever `selectedFeature` the global store
 * holds. A client-side navigation with nothing dirty (the unsaved guard allows
 * it) can leave that selection targeting a DIFFERENT dataset than this hook
 * instance is bound to: same identity, so no session epoch bump, and this
 * instance's generation counter starts fresh at 0, so neither staleness check
 * above fires. Refuse before the mutation goes out and end the mismatched
 * session so its selection can't be reused.
 *
 * `targetDatasetId === null` (nothing adopted a target) is not a mismatch: the
 * store's `setSelectedFeature` refuses to populate `selectedFeature` without a
 * target (drawing-store.ts), so a real session always has one.
 */
function refuseIfWrongDataset(datasetId: string | undefined): boolean {
  const state = useDrawingStore.getState();
  const { targetDatasetId } = state;
  if (targetDatasetId === null || targetDatasetId === (datasetId ?? null)) return false;
  state.clearDrawing();
  return true;
}

/**
 * MVT feature ID is stored in _vectorTileFeature.id by MapLibre, promoted to
 * feature.id via promoteId, or available as a property.
 */
export function renderedFeatureGid(
  feature: Pick<MapGeoJSONFeature, 'id' | 'properties'>,
): number | undefined {
  const f = feature as typeof feature & { _vectorTileFeature?: { id?: number } };
  return (f.id ?? f.properties?.gid ?? f._vectorTileFeature?.id) as number | undefined;
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

  // Each mutation hook's isPending follows only its latest call, so
  // overlapping writes are tracked here until every one has settled. A write
  // is filed under the session epoch it started in, so one left over from a
  // previous identity doesn't keep the current session busy.
  const sessionEpoch = useDrawingStore((s) => s.sessionEpoch);
  const [pendingWriteEpochs, setPendingWriteEpochs] = useState<number[]>([]);
  const beginWrite = useCallback(
    (epoch: number) => setPendingWriteEpochs((pending) => [...pending, epoch]),
    [],
  );
  const endWrite = useCallback(
    (epoch: number) => setPendingWriteEpochs((pending) => {
      const index = pending.indexOf(epoch);
      return pending.filter((_, i) => i !== index);
    }),
    [],
  );

  const drawingGenerationRef = useRef(0);
  useEffect(() => {
    // Subscribe synchronously so batched A→B→A transitions cannot look unchanged.
    const unsubscribe = useDrawingStore.subscribe((state, previous) => {
      if (state.targetDatasetId !== previous.targetDatasetId || state.isDrawing !== previous.isDrawing) {
        drawingGenerationRef.current += 1;
      }
    });
    return () => {
      unsubscribe();
      drawingGenerationRef.current += 1;
    };
  }, []);

  const overlayFeaturesRef = useRef<GeoJSON.Feature[]>([]);
  const overlayCleanupRef = useRef<{ off: () => void; clearTimer: () => void } | null>(null);

  /**
   * Swap tile URLs with a fresh version to force fresh tile fetches.
   *
   * `tileVersion` should be the dataset's tile_cache_version from the write
   * that triggered the reload: the tile routes treat it (or a record's
   * updated_at) as a freshness signal and force a stale API worker to re-read
   * the dataset, where a client timestamp is ignored. Without one (an older
   * server's response) it falls back to a timestamp, which still busts this
   * browser's tile cache.
   */
  const reloadTiles = useCallback((tileVersion?: number | null) => {
    const map = mapRef.current;
    if (!map || !tableName) return;
    const source = map.getSource(previewSourceId(tableName));
    if (source && 'setTiles' in source) {
      const tileBaseUrl = getEnvConfig().TILE_BASE_URL || tileConfig?.cdn_base_url;
      const freshUrl = buildSignedTileUrl(tableName, tileToken ?? null, tileBaseUrl, tileVersion ?? Date.now());
      (source as VectorTileSource).setTiles([freshUrl]);
    }
  }, [mapRef, tableName, tileConfig?.cdn_base_url, tileToken]);

  /** Clean up overlay sourcedata listener. Call on unmount. */
  const cleanupOverlayListener = useCallback(() => {
    overlayCleanupRef.current?.off();
    overlayCleanupRef.current?.clearTimer();
    overlayCleanupRef.current = null;
  }, []);

  // Empties the overlay ref and the drawn-overlay source immediately, for the
  // identity-change cleanup (DatasetMap's finishDrawingSession, keyed on
  // sessionEpoch), so a drawn-but-uncommitted shape from the previous identity
  // doesn't sit on the map for the next one. Also cancels the pending
  // sourcedata/timeout listener, which holds a reference to the stale overlay
  // feature.
  const resetOverlay = useCallback(() => {
    cleanupOverlayListener();
    overlayFeaturesRef.current = [];
    const map = mapRef.current;
    if (map) {
      const src = map.getSource('drawn-overlay') as GeoJSONSource | undefined;
      src?.setData(EMPTY_FC);
    }
  }, [cleanupOverlayListener, mapRef]);

  /** Create a new feature and refresh tiles. `refused` marks a failed write for the current session. */
  const saveAndRefresh = useCallback(
    async (geometry: Geometry, properties: Record<string, unknown>): Promise<{ saved: boolean; refused?: boolean }> => {
      if (!datasetId || !tableName) return { saved: false };
      const map = mapRef.current;

      // Captured before the mutation's await: clearOverlay() below must not
      // erase a NEWER identity's overlay.
      const session = useDrawingStore.getState();
      const epoch = session.sessionEpoch;
      const targetDatasetId = session.targetDatasetId;
      const generation = drawingGenerationRef.current;

      // Overlay for instant visibility
      const overlayFeature: GeoJSON.Feature = { type: 'Feature', geometry, properties: properties ?? {} };
      overlayFeaturesRef.current = [...overlayFeaturesRef.current, overlayFeature];
      if (map) {
        const src = map.getSource('drawn-overlay') as GeoJSONSource | undefined;
        src?.setData({ type: 'FeatureCollection', features: overlayFeaturesRef.current });
      }

      let existing: { gid: number; tableId?: string | null } | undefined;
      beginWrite(epoch);
      try {
        existing = createdFeatures.get(geometry);
        let created;
        if (existing !== undefined) {
          created = await updateFeatureMutation.mutateAsync({
            datasetId,
            gid: existing.gid,
            geometry: geometry as Geometry,
            properties,
            tableId: existing.tableId,
          });
          createdFeatures.delete(geometry);
        } else {
          const { key, attempt } = nextCreateAttempt(geometry);
          created = await createFeature.mutateAsync({
            datasetId,
            geometry: geometry as Geometry,
            properties,
            idempotencyKey: key,
            attempt,
          });
        }
        // If the identity changed while the request was in flight, the
        // identity-change cleanup already emptied the overlay (resetOverlay via
        // finishDrawingSession); reporting success and reloading tiles would
        // be feedback for an identity no longer looking.
        if (isStale(epoch, targetDatasetId, generation, drawingGenerationRef.current)) return { saved: false };
        toast.success(t('map.featureSaved'));
        reloadTiles(created.tile_cache_version);

        // Clear overlay after tiles load
        if (map) {
          cleanupOverlayListener();
          const clearOverlay = () => {
            // Re-checked at fire time: the identity can change again before the
            // tile-load event (or the 5s fallback) fires, and a second identity
            // may have started their own overlay by then.
            if (isStale(epoch, targetDatasetId, generation, drawingGenerationRef.current)) return;
            overlayFeaturesRef.current = [];
            const src = map.getSource('drawn-overlay') as GeoJSONSource | undefined;
            src?.setData(EMPTY_FC);
            overlayCleanupRef.current = null;
          };
          const sourceId = previewSourceId(tableName);
          const onSourceData = (e: { sourceId?: string; isSourceLoaded?: boolean }) => {
            if (e.sourceId === sourceId && e.isSourceLoaded) {
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
        return { saved: true };
      } catch (err) {
        // The toast is feedback for whoever issued this request; reject it as
        // the success branch does, or a failed create surfaces A's backend
        // error to B. The overlay-ref filtering below stays unconditional (see
        // its comment).
        const stale = isStale(epoch, targetDatasetId, generation, drawingGenerationRef.current);
        const refusal = createRefusal(err);
        const updateTargetGone = existing !== undefined && err instanceof ApiError && err.status === 404;
        // The feature the sketch created was in a table that is gone, so the
        // sketch is created afresh under a new key.
        const replaced = existing !== undefined ? datasetReplaced(err) : null;
        if (refusal?.code === 'feature_gone' || updateTargetGone || replaced) {
          createAttempts.delete(geometry);
          createdFeatures.delete(geometry);
        }
        if (refusal?.code === 'feature_changed' && refusal.feature?.id !== undefined) {
          createdFeatures.set(geometry, { gid: refusal.feature.id, tableId: refusal.feature.table_id });
        }
        if (!stale && refusal?.code === 'feature_changed') {
          toast.warning(t('map.featureSavedThenChanged'));
          reloadTiles(refusal.feature?.tile_cache_version);
        } else if (!stale && (refusal?.code === 'feature_gone' || updateTargetGone)) {
          toast.error(t('map.featureSavedThenRemoved'));
          if (refusal?.tile_cache_version !== undefined) reloadTiles(refusal.tile_cache_version);
        } else if (!stale && replaced) {
          toast.error(t('map.featureSavedThenReplaced'));
          reloadTiles(replaced.tile_cache_version);
        } else if (!stale) {
          // Surface the backend's reason (invalid geometry, type mismatch) as
          // the table path does, not a bare "failed".
          toast.error(formatMutationError('dataset:map.featureSaveFailed', err));
        }
        // Not epoch-gated: this filters OUT the one feature this call added, by
        // object identity, so it is safe even if a second identity added their
        // own overlay feature to the same ref.
        overlayFeaturesRef.current = overlayFeaturesRef.current.filter((f) => f !== overlayFeature);
        if (map) {
          const src = map.getSource('drawn-overlay') as GeoJSONSource | undefined;
          src?.setData({ type: 'FeatureCollection', features: overlayFeaturesRef.current });
        }
        return stale ? { saved: false } : { saved: false, refused: true };
      } finally {
        endWrite(epoch);
      }
    },
    [datasetId, tableName, mapRef, createFeature, updateFeatureMutation, reloadTiles, cleanupOverlayListener, beginWrite, endWrite, t],
  );

  /** Deselect the currently selected feature, restoring tile visibility. */
  const performDeselect = useCallback(() => {
    const sf = useDrawingStore.getState().selectedFeature;
    if (!sf) return;
    try { removeFeatures([sf.tdId]); } catch { /* already removed */ }
    const map = mapRef.current;
    if (map) showAllFeaturesInTiles(map);
    clearSelectedFeature();
    // Deselection (also used for Cancel, see DatasetMap's handleDeselect)
    // discards the pending, unsaved undo history of the abandoned edit.
    resetHistory();
  }, [mapRef, removeFeatures, clearSelectedFeature, resetHistory]);

  /**
   * End an edit whose write was refused because the dataset's table was
   * replaced. The selected gid may now name another row, so the edit can't be
   * saved; nothing was written, and the toast says so.
   */
  const closeReplacedEdit = useCallback((tileVersion?: number | null) => {
    toast.error(t('map.featureDatasetReplaced'));
    performDeselect();
    reloadTiles(tileVersion);
  }, [performDeselect, reloadTiles, t]);

  /** Save edited geometry for the selected feature. */
  const handleSaveEdit = useCallback(async () => {
    const sf = useDrawingStore.getState().selectedFeature;
    if (!sf || !datasetId || !tableName) return;
    if (refuseIfWrongDataset(datasetId)) return;

    const feature = getSnapshotFeature(sf.tdId);
    if (!feature) {
      toast.error(t('map.featureRetrieveFailed'));
      return;
    }

    // Captured before the mutation's await; see handleDeleteFeature below.
    const session = useDrawingStore.getState();
    const epoch = session.sessionEpoch;
    const targetDatasetId = session.targetDatasetId;
    const generation = drawingGenerationRef.current;
    beginWrite(epoch);
    try {
      const updated = await updateFeatureMutation.mutateAsync({
        datasetId,
        gid: sf.gid,
        geometry: feature.geometry as Geometry,
        tableId: sf.tableId,
      });
      // If the identity changed while the request was in flight, a second
      // identity may have adopted their own selection. Cleaning up here would
      // remove THEIR terra draw feature by a colliding tdId, restore tile
      // filters from under them and clear THEIR selectedFeature. The write
      // already landed server-side, which is as far as a stale caller's
      // responsibility goes.
      if (isSelectionStale(epoch, targetDatasetId, sf, generation, drawingGenerationRef.current)) return;
      toast.success(t('map.featureUpdated'));
      try { removeFeatures([sf.tdId]); } catch { /* already removed */ }
      reloadTiles(updated.tile_cache_version);
      const map = mapRef.current;
      if (map) showAllFeaturesInTiles(map);
      clearSelectedFeature();
      // The edit landed server-side, so its pending undo history is moot.
      resetHistory();
    } catch (err) {
      // Mirror the success branch's recheck: a failed update is feedback for
      // whoever issued it, not whoever is signed in when it rejects.
      if (isSelectionStale(epoch, targetDatasetId, sf, generation, drawingGenerationRef.current)) return;
      const replaced = datasetReplaced(err);
      if (replaced) {
        closeReplacedEdit(replaced.tile_cache_version);
        return;
      }
      // Keep the backend detail.
      toast.error(formatMutationError('dataset:map.featureUpdateFailed', err));
    } finally {
      endWrite(epoch);
    }
  }, [datasetId, tableName, mapRef, getSnapshotFeature, updateFeatureMutation, removeFeatures, clearSelectedFeature, reloadTiles, resetHistory, closeReplacedEdit, beginWrite, endWrite, t]);

  /** Delete the selected feature. */
  const handleDeleteFeature = useCallback(async () => {
    const sf = useDrawingStore.getState().selectedFeature;
    if (!sf || !datasetId || !tableName) return;
    if (refuseIfWrongDataset(datasetId)) return;

    // Captured before the mutation's await. A second identity can adopt their
    // own selection while this delete is in flight; cleaning up then would
    // remove THEIR terra draw feature by a colliding tdId, restore tile
    // filters from under them and clear THEIR selectedFeature.
    const session = useDrawingStore.getState();
    const epoch = session.sessionEpoch;
    const targetDatasetId = session.targetDatasetId;
    const generation = drawingGenerationRef.current;
    beginWrite(epoch);
    try {
      const deleted = await deleteFeatureMutation.mutateAsync({ datasetId, gid: sf.gid, tableId: sf.tableId });
      if (isSelectionStale(epoch, targetDatasetId, sf, generation, drawingGenerationRef.current)) return;
      toast.success(t('map.featureDeleted'));
      try { removeFeatures([sf.tdId]); } catch { /* already removed */ }
      // Optional: an older server's delete has no body at all (a bare 204),
      // so `deleted` itself, not just its field, can be undefined here.
      reloadTiles(deleted?.tile_cache_version);
      const map = mapRef.current;
      if (map) showAllFeaturesInTiles(map);
      clearSelectedFeature();
      // The deleted feature no longer exists, so its pending undo history
      // (which would restore it as a client-side ghost) is moot. Same point as
      // handleSaveEdit.
      resetHistory();
    } catch (err) {
      // Mirror the success branch's recheck: a failed delete is feedback for
      // whoever issued it, not whoever is signed in when it rejects.
      if (isSelectionStale(epoch, targetDatasetId, sf, generation, drawingGenerationRef.current)) return;
      const replaced = datasetReplaced(err);
      if (replaced) {
        closeReplacedEdit(replaced.tile_cache_version);
        return;
      }
      // Keep the backend detail.
      toast.error(formatMutationError('dataset:map.featureDeleteFailed', err));
    } finally {
      endWrite(epoch);
    }
  }, [datasetId, tableName, mapRef, deleteFeatureMutation, removeFeatures, clearSelectedFeature, reloadTiles, resetHistory, closeReplacedEdit, beginWrite, endWrite, t]);

  /**
   * Update attributes of the selected feature. `applied` says whether the
   * caller may treat the submission as settled: false only for a stale
   * request, whose dialog may now belong to a different identity's own edit.
   * A failed write still resolves `applied: true` and adds `refused: true`.
   */
  const handleEditAttributeSubmit = useCallback(
    async (properties: Record<string, unknown>): Promise<{ applied: boolean; refused?: boolean }> => {
      const sf = useDrawingStore.getState().selectedFeature;
      if (!sf || !datasetId) return { applied: true };
      if (refuseIfWrongDataset(datasetId)) return { applied: true };
      // Captured BEFORE the mutation's await, not re-read afterward: a second
      // identity may have adopted a new target by then, whose fresh epoch would
      // make this stale write look current. See setSelectedFeature in
      // drawing-store.ts.
      const session = useDrawingStore.getState();
      const epoch = session.sessionEpoch;
      const targetDatasetId = session.targetDatasetId;
      const generation = drawingGenerationRef.current;
      beginWrite(epoch);
      try {
        const updated = await updateFeatureMutation.mutateAsync({ datasetId, gid: sf.gid, properties, tableId: sf.tableId });
        // Recheck immediately after the await, before reporting success,
        // writing to the store or reloading tiles. setSelectedFeature's own
        // epoch check refuses the store write, but this validates BEFORE those
        // other effects and reports it via the return value.
        if (isSelectionStale(epoch, targetDatasetId, sf, generation, drawingGenerationRef.current)) return { applied: false };
        toast.success(t('map.attributesUpdated'));
        setSelectedFeature({ ...sf, properties: { ...sf.properties, ...properties } }, epoch);
        // Cache-bust the vector tiles so edited attributes render, as the
        // geometry handlers (handleSaveEdit/handleDeleteFeature) do after a
        // write. Geometry is unchanged, so the selection is kept.
        reloadTiles(updated.tile_cache_version);
        return { applied: true };
      } catch (err) {
        // Mirror the success path's recheck. If the identity changed while the
        // request was in flight, the failure is A's, not whoever is looking now
        // (possibly B, with their own editor open): an error toast and a
        // close-the-dialog result would be the same collateral damage the
        // success path guards against.
        if (isSelectionStale(epoch, targetDatasetId, sf, generation, drawingGenerationRef.current)) return { applied: false };
        const replaced = datasetReplaced(err);
        if (replaced) {
          closeReplacedEdit(replaced.tile_cache_version);
          return { applied: true, refused: true };
        }
        // Keep the backend detail.
        toast.error(formatMutationError('dataset:map.attributesUpdateFailed', err));
        return { applied: true, refused: true };
      } finally {
        endWrite(epoch);
      }
    },
    [datasetId, updateFeatureMutation, setSelectedFeature, reloadTiles, closeReplacedEdit, beginWrite, endWrite, t],
  );

  /** Handle Terra Draw edit-finish (drag complete). */
  const handleEditFinish = useCallback(
    (_tdId: string, _feature: Feature) => {
      setEditDirty(true);
    },
    [setEditDirty],
  );

  /**
   * Terra Draw's undo() popped the ring back to its earliest snapshot, so the
   * displayed geometry is what it was when the ring started and there is no
   * pending edit to confirm away on Cancel/Done/mode-switch. A later drag or
   * vertex edit re-dirties via handleEditFinish above.
   */
  const handleHistoryBaseline = useCallback(() => {
    setEditDirty(false);
  }, [setEditDirty]);

  /**
   * Undo restored a snapshot without the feature that was selected, so Terra
   * Draw has nothing left to re-select. Clear our selection store to agree
   * (a stale selection would keep showing the action bar for a feature no
   * longer on the canvas). Guarded on the CURRENT selection matching the id
   * this fired for, in case a newer selection has replaced it.
   */
  const handleSelectionLost = useCallback(
    (id: string | number) => {
      const sf = useDrawingStore.getState().selectedFeature;
      if (sf && sf.tdId === String(id)) {
        clearSelectedFeature();
      }
    },
    [clearSelectedFeature],
  );

  /** Select a feature from the map by clicking on it. */
  const selectFeatureFromMap = useCallback(
    async (map: MaplibreMap, point: Point) => {
      if (useDrawingStore.getState().selectedFeature) return;
      if (!datasetId) return;

      const queryLayers = PREVIEW_FEATURE_LAYER_IDS.filter((id) => map.getLayer(id));
      if (queryLayers.length === 0) return;

      const features = map.queryRenderedFeatures(point, { layers: queryLayers });
      if (!features || features.length === 0) return;

      // MVT feature ID is stored in _vectorTileFeature.id by MapLibre,
      // promoted to feature.id via promoteId, or available as a property.
      const gid = renderedFeatureGid(features[0]);
      if (gid === undefined || gid === null) {
        toast.info(t('map.featureNotSelectable'));
        return;
      }

      // Captured BEFORE the fetch's await, as in handleEditAttributeSubmit: a
      // stale resolution must not be accepted just because someone else's fresh
      // target makes the live epoch look unchanged.
      const session = useDrawingStore.getState();
      const epoch = session.sessionEpoch;
      const targetDatasetId = session.targetDatasetId;
      const generation = drawingGenerationRef.current;
      try {
        const fullFeature = await getFeature(datasetId, gid);
        // Recheck IMMEDIATELY after the await, before ANY map mutation.
        // setSelectedFeature's epoch check refuses the STORE write, but clear()
        // and addFeatures() below would already have installed the stale
        // geometry, and the rest of this block would select it and hide its tile.
        if (isSelectionStale(epoch, targetDatasetId, null, generation, drawingGenerationRef.current)) return;
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
          setSelectedFeature({ gid, tdId, properties: fullFeature.properties, tableId: fullFeature.table_id }, epoch);
          tdSelectFeature(tdId);
          hideFeatureFromTiles(map, gid);
        } else {
          toast.error(t('map.featureLoadFailed'));
        }
      } catch {
        // Mirror the success branch's recheck: a failed fetch is feedback for
        // whoever clicked the feature, not whoever is signed in (or anonymous)
        // when getFeature() rejects.
        if (isSelectionStale(epoch, targetDatasetId, null, generation, drawingGenerationRef.current)) return;
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
    handleSelectionLost,
    handleEditAttributeSubmit,
    selectFeatureFromMap,
    reloadTiles,
    cleanupOverlayListener,
    resetOverlay,
    isFeatureMutationPending: pendingWriteEpochs.includes(sessionEpoch),
  };
}
