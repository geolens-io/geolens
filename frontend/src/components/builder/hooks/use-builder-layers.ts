import { useState, useEffect, useLayoutEffect, useRef, useMemo, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import type { Map as MaplibreMap } from 'maplibre-gl';
import { toFitBounds } from '@/lib/bbox';
import { getVisibleLayerBounds, clampMinZoomAfterFit } from '@/components/builder/builder-bounds';
import { normalizeTerrainExaggeration, reorderDataLayers } from '@/components/builder/map-sync';
import type { LayerActions } from '@/components/builder/ChatPanel';
import {
  dispatchBuilderLayerAction,
  type BuilderLayerAction,
} from '@/components/builder/builder-action-contract';
import { resolveBasemapId } from '@/lib/basemap-utils';
import {
  hasSavedMapCamera,
  readMapCamera,
  sameMapCamera,
  savedMapCamera,
  type BuilderCamera,
} from '@/components/builder/builder-camera';
import { deepEqual } from '@/components/builder/LayerStyleEditor/utils';
import type { MapBasemapConfig, MapLayerResponse, MapResponse, MapTerrainConfig, StyleConfig } from '@/types/api';
import type { useAddLayer, useRemoveLayer } from '@/hooks/use-maps';
import { useEphemeralLayers } from '@/components/builder/hooks/use-ephemeral-layers';
import { useLayerMapSync } from '@/components/builder/hooks/use-layer-map-sync';
import type { SaveBaselineSync } from '@/components/builder/hooks/use-builder-save';
import {
  buildDuplicateRenderingInput,
  removePerLayerCompanions,
  shouldClearTerrainOnDelete,
} from '@/components/builder/hooks/builder-layer-mutations';
import {
  getParentGroupId,
  hydrateFolderGroupLayers,
  pruneEmptyFolderGroups,
  type GroupedLayer,
} from '@/components/builder/folder-groups';
// Folder-group collapse dirties the save (its state is persisted on children);
// the basemap group's does not, so the toggle must tell them apart.
import { isFolderGroupLayer } from '@/lib/layer-capabilities';
// Cohesive handler clusters live in focused hooks; this hook composes them.
import { useFolderGroupLayers } from '@/components/builder/hooks/use-folder-group-layers';
import { useBulkLayerActions, restoreFailedLayers } from '@/components/builder/hooks/use-bulk-layer-actions';
import { useTerrainLayers } from '@/components/builder/hooks/use-terrain-layers';
import { useRenderModeLayers } from '@/components/builder/hooks/use-render-mode-layers';
import { useLayerStyleClipboard } from '@/components/builder/hooks/use-layer-style-clipboard';
import { useTileConfig } from '@/hooks/use-settings';
export { buildDuplicateRenderingInput } from '@/components/builder/hooks/builder-layer-mutations';

// A camera reading is only meaningful with the map it was read for.
interface CameraSample {
  mapId: string | null;
  camera: BuilderCamera;
}

// True when a local text field and its saved value would persist identically.
// The save payload is `value.trim() || null`, and the field hydrates raw.
function sameSavedText(local: string | null | undefined, saved: string | null | undefined): boolean {
  const l = local ?? '';
  const r = saved ?? '';
  if (l === r) return true;
  return l.trim() === '' && r.trim() === '';
}

// Hydrated shape of mapData's folder-expansion state, mirroring the load path.
function savedGroupMeta(mapData: MapResponse): Record<string, { expanded: boolean }> {
  return {
    ...hydrateFolderGroupLayers(mapData.layers ?? []).groupMeta,
    ...((mapData as { group_meta?: Record<string, { expanded: boolean }> }).group_meta ?? {}),
  };
}

// Hydrated shape of mapData.terrain_config, shared by the load path and the
// clean-state recheck so the two cannot drift.
function savedTerrainConfig(mapData: { terrain_config?: MapTerrainConfig | null }): MapTerrainConfig | null {
  if (!mapData.terrain_config) return null;
  return {
    ...mapData.terrain_config,
    exaggeration: normalizeTerrainExaggeration(mapData.terrain_config.exaggeration),
  };
}

export function useBuilderLayers(
  mapData: MapResponse | undefined,
  mapInstanceRef: React.RefObject<MaplibreMap | null>,
  mapId: string | undefined,
  addLayerMutation: ReturnType<typeof useAddLayer>,
  removeLayerMutation: ReturnType<typeof useRemoveLayer>,
  // Populated by useBuilderSave. MapBuilderPage renders useBuilderLayers first,
  // so a callback ref bridges the two. Invoked by handleAddDataset /
  // handleDuplicateRendering so the save-diff baseline learns about
  // server-created layers immediately (see use-builder-save.ts).
  saveBaselineSyncRef: React.MutableRefObject<SaveBaselineSync>,
  // Reactive counterpart of mapInstanceRef: a ref flipping non-null doesn't
  // re-run effects, so the auto-zoom watcher needs this to retry a pending
  // zoom that arrived before the lazy-loaded map instance existed. Optional:
  // omitting it leaves no signal for retrying a cold-entry auto-zoom.
  mapInstance?: MaplibreMap | null,
  // Dataset to add as a layer once the map has loaded (useBuilderEntryIntent).
  addDatasetId?: string,
) {
  const { t } = useTranslation('builder');
  const { data: tileConfig } = useTileConfig();
  const mvtSourceLayerPrefix = tileConfig?.mvt_source_layer_prefix;

  const initializedRef = useRef(false);
  const addDatasetProcessedRef = useRef(false);
  // Id of a just-added layer that still needs its one-time auto-zoom (fresh
  // map only; see the add_dataset effect below).
  const pendingAutoZoomLayerIdRef = useRef<string | null>(null);
  // True when the pending id needs a combined-bounds fit (cold-entry,
  // non-fresh map) rather than a single-layer zoom.
  const pendingCombinedFitRef = useRef(false);

  const [localLayers, setLocalLayers] = useState<MapLayerResponse[]>([]);
  // The map the current localLayers belong to. On direct /maps/:id navigation
  // this page stays mounted and the route id flips a commit before the new
  // map's layers hydrate; consumers that initialize from layers at mount
  // (AnalysisPanel) must wait until this matches the route id, or they judge
  // one map's remembered state against another map's rows.
  const [layersMapId, setLayersMapId] = useState<string | null>(null);
  const layersMapIdRef = useRef<string | null>(null);
  const [localBasemap, setLocalBasemap] = useState<string>('openfreemap-positron');
  // hasUnsavedChanges enables Save and includes a moved camera. hasUnsavedEdits
  // excludes a camera-only move and drives the leave prompt, so a pan alone
  // is saved when the author saves but doesn't ask before leaving.
  const [hasUnsavedChanges, setUnsavedFlag] = useState(false);
  const [hasUnsavedEdits, setHasUnsavedEdits] = useState(false);
  const setHasUnsavedChanges = useCallback((next: React.SetStateAction<boolean>) => {
    setUnsavedFlag(next);
    setHasUnsavedEdits(next);
  }, []);
  const hasUnsavedChangesRef = useRef(false);
  hasUnsavedChangesRef.current = hasUnsavedChanges;
  // Live camera sampled on moveend, tagged with the map it was taken on. Null
  // until the map has settled once, since a map that never moved can't have
  // changed the view a save would store. The tag matters because direct
  // /maps/:id navigation keeps this hook and the MapGL instance mounted, and a
  // sample from the previous map must not be judged against the next map's
  // saved view. The sample lives in a ref; state holds only whether it differs
  // from the saved view, so a pan that doesn't flip that answer doesn't
  // re-render the page.
  const liveCameraRef = useRef<CameraSample | null>(null);
  const mapDataRef = useRef(mapData);
  mapDataRef.current = mapData;
  const [cameraUnsaved, setCameraUnsaved] = useState<boolean | null>(null);
  // The camera the current map was entered on, until the camera leaves it: the
  // saved view on a fresh load, or the previous map's position after in-page
  // navigation (nothing repositions the shared instance). Not an edit.
  const cameraEntryRef = useRef<CameraSample | null>(null);
  // Dirt this hook can't re-derive from server state: plugin toggles and other
  // page-owned edits through markDirty. recheckClean refuses to clear the flag
  // while it is set; every reset to "saved" clears it.
  const opaqueDirtyRef = useRef(false);
  const setHasUnsavedChangesTracked = useCallback(
    (next: React.SetStateAction<boolean>) => {
      if (next === false) opaqueDirtyRef.current = false;
      setHasUnsavedChanges(next);
    },
    [setHasUnsavedChanges],
  );
  const [expandedLayerId, setExpandedLayerId] = useState<string | null>(null);
  const [activeEditorTab, setActiveEditorTab] = useState<'style' | 'filter' | 'labels' | 'popup' | null>(null);
  const [showBasemapLabels, setShowBasemapLabels] = useState(true);
  const [basemapConfig, _setBasemapConfigRaw] = useState<MapBasemapConfig | null>(null);
  // Wrap setBasemapConfig so external callers get dirty-tracking. The raw
  // setter is reserved for the load path, where hydration must not mark dirty.
  const setBasemapConfig = useCallback(
    (next: MapBasemapConfig | null | ((prev: MapBasemapConfig | null) => MapBasemapConfig | null)) => {
      _setBasemapConfigRaw(next);
      setHasUnsavedChanges(true);
    },
    [setHasUnsavedChanges],
  );
  const [localTerrainConfig, setLocalTerrainConfig] = useState<MapTerrainConfig | null>(null);
  const [groupMeta, setGroupMeta] = useState<Record<string, { expanded: boolean }>>({});
  const [localName, setLocalName] = useState('');
  const [localDescription, setLocalDescription] = useState('');
  // Map-level custom legend title. Null means no override.
  const [localLegendTitle, setLocalLegendTitle] = useState<string | null>(null);
  const [freshLayerId, setFreshLayerId] = useState<string | null>(null);
  const freshLayerTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const savedLayerBaselineRef = useRef<MapLayerResponse[]>([]);

  // Mirror current layers in a ref so stable callbacks read fresh state without
  // invalidating on every mutation, which would defeat React.memo() on StackRow.
  const layersRef = useRef(localLayers);
  useLayoutEffect(() => {
    layersRef.current = localLayers;
  }, [localLayers]);

  // Ephemeral layer management
  const {
    ephemeralResult,
    handleQueryResult,
    handleDismissEphemeral,
  } = useEphemeralLayers(mapInstanceRef);

  // Live map sync handlers
  const {
    handleToggleVisibility,
    handlePaintChange,
    handleStyleConfigChange,
    handleOpacityChange,
    handleLayoutChange,
    handleFilterChange,
    handleLabelChange,
    handlePopupChange,
  } = useLayerMapSync(
    localLayers,
    setLocalLayers,
    setHasUnsavedChanges,
    mapInstanceRef,
    layersRef,
  );

  // Per-row style clipboard: session clipboard ref + geometry-class mirror; the
  // bulk apply-style handler reads the same ref.
  const {
    copiedStyleRef,
    copiedStyleGeometryClass,
    handleCopyStyle,
    handlePasteStyle,
  } = useLayerStyleClipboard({ layersRef, handleStyleConfigChange });

  // Bulk-operation handlers (apply-style / visibility / opacity / group /
  // ungroup / delete) and in-flight isDeleting state.
  const {
    handleBulkApplyStyle,
    handleBulkVisibility,
    handleBulkOpacity,
    handleBulkGroup,
    handleBulkUngroup,
    handleBulkDelete,
    isDeleting,
    deletingCount,
  } = useBulkLayerActions({
    layersRef,
    setLocalLayers,
    setHasUnsavedChanges,
    setExpandedLayerId,
    setGroupMeta,
    mapInstanceRef,
    mapId,
    localTerrainConfig,
    setLocalTerrainConfig,
    savedLayerBaselineRef,
    saveBaselineSyncRef,
    copiedStyleRef,
  });

  // Folder-group handlers (create / rename / ungroup / toggle-vis /
  // delete / add-to-group / move-out).
  const {
    handleCreateGroupWithLayer,
    handleRenameGroup,
    handleUngroup,
    handleToggleGroupVisibility,
    handleDeleteGroup,
    handleAddLayerToExistingGroup,
    handleMoveLayerOutOfGroup,
  } = useFolderGroupLayers({
    layersRef,
    setLocalLayers,
    setGroupMeta,
    setHasUnsavedChanges,
    mapInstanceRef,
  });

  // DEM terrain bind, unbind, and exaggeration handlers.
  const {
    handleDEMTerrainBind,
    handleDEMTerrainUnbind,
    handleDEMTerrainExaggerationChange,
  } = useTerrainLayers({
    layersRef,
    localTerrainConfig,
    setLocalTerrainConfig,
    setHasUnsavedChanges,
  });

  // Render-mode and layer-swap handlers.
  const {
    handleRenderAsChange,
  } = useRenderModeLayers({
    layersRef,
    setLocalLayers,
    setHasUnsavedChanges,
    mapInstanceRef,
    mvtSourceLayerPrefix,
  });

  // Initialize local state from API data (once).
  //
  // mapData.basemap_config may carry `basemap_position: 'top' | 'bottom'`
  // (additive jsonb), loaded via _setBasemapConfigRaw. Consumers read
  // `basemapConfig?.basemap_position ?? 'bottom'`, so legacy maps default to
  // 'bottom'.
  //
  // A direct /maps/:id navigation keeps this hook mounted, so a different map
  // identity must re-hydrate wholesale. The !hasUnsavedChanges guard on the
  // refetch sync below is for same-map refetches; a discarded-edit exit
  // ("Leave without saving") leaves the flag true, which would otherwise pin
  // localLayers (and layersMapId, the Analysis panel's mount gate) to the
  // previous map. Declared before the hydration effect so the same pass
  // re-hydrates.
  useEffect(() => {
    if (
      mapData &&
      initializedRef.current &&
      layersMapIdRef.current !== null &&
      mapData.id !== layersMapIdRef.current
    ) {
      initializedRef.current = false;
      opaqueDirtyRef.current = false;
      setHasUnsavedChanges(false);
    }
  }, [mapData, setHasUnsavedChanges]);

  useEffect(() => {
    if (mapData && !initializedRef.current) {
      const hydrated = hydrateFolderGroupLayers(mapData.layers ?? []);
      setLocalLayers(hydrated.layers);
      layersMapIdRef.current = mapData.id;
      setLayersMapId(mapData.id);
      savedLayerBaselineRef.current = hydrated.layers;
      setLocalBasemap(resolveBasemapId(mapData.basemap_style || 'positron'));
      setShowBasemapLabels(mapData.show_basemap_labels ?? true);
      _setBasemapConfigRaw(mapData.basemap_config ?? null);
      setLocalTerrainConfig(savedTerrainConfig(mapData));
      setGroupMeta({
        ...hydrated.groupMeta,
        ...((mapData as { group_meta?: Record<string, { expanded: boolean }> }).group_meta ?? {}),
      });
      setLocalName(mapData.name);
      setLocalDescription(mapData.description ?? '');
      setLocalLegendTitle(mapData.legend_title ?? null);
      initializedRef.current = true;
    }
  }, [mapData]);

  // Clean up the freshLayerId timeout on unmount.
  useEffect(() => () => {
    if (freshLayerTimeoutRef.current) clearTimeout(freshLayerTimeoutRef.current);
  }, []);

  // Sync layers from API when they change (after add/remove mutations)
  const apiLayers = mapData?.layers;
  useEffect(() => {
    if (apiLayers && initializedRef.current && !hasUnsavedChanges) {
      const hydrated = hydrateFolderGroupLayers(apiLayers);
      setLocalLayers(hydrated.layers);
      layersMapIdRef.current = mapData?.id ?? null;
      setLayersMapId(mapData?.id ?? null);
      savedLayerBaselineRef.current = hydrated.layers;
      setGroupMeta({
        ...hydrated.groupMeta,
        ...((mapData as { group_meta?: Record<string, { expanded: boolean }> } | undefined)?.group_meta ?? {}),
      });
    }
  }, [apiLayers, hasUnsavedChanges, mapData]);

  // Compute initial view state only once
  const initialViewState = useMemo(() => {
    if (!mapData) return undefined;
    return {
      center_lng: mapData.center_lng,
      center_lat: mapData.center_lat,
      zoom: mapData.zoom,
      bearing: mapData.bearing,
      pitch: mapData.pitch,
    };
    // Only compute on first load
    // eslint-disable-next-line react-hooks/exhaustive-deps -- re-run only when the map identity changes
  }, [mapData?.id]);

  // --- Layer handlers ---
  //
  // Handlers use useCallback with stable deps so React.memo() on StackRow
  // holds across unrelated state changes; they read `layersRef.current`
  // instead of `localLayers` to keep dep lists stable.
  // Reports whether a move happened, so the keyboard reorder announcement
  // stays silent at the stack boundaries.
  const handleMove = useCallback((layerId: string, direction: 'up' | 'down'): boolean => {
    const currentLayers = layersRef.current;
    // The stack includes terrain-mode DEM rows, so the rendered order is the
    // full layer order.
    const idx = currentLayers.findIndex((l) => l.id === layerId);
    if (idx < 0) return false;
    // A row's visible neighbor is its adjacent sibling in the same container
    // (the top level skips grouped children; a folder box lists only its own
    // children), so the raw flat-array neighbor can belong to another
    // container. Swapping with it would dirty the saved order, move nothing
    // visible and still be announced as a move. Skip to the nearest
    // same-container sibling; none at the edge means a boundary, not a move.
    const container = getParentGroupId(currentLayers[idx]);
    const step = direction === 'up' ? -1 : 1;
    let swapIdx = idx + step;
    while (
      swapIdx >= 0 &&
      swapIdx < currentLayers.length &&
      getParentGroupId(currentLayers[swapIdx]) !== container
    ) {
      swapIdx += step;
    }
    if (swapIdx < 0 || swapIdx >= currentLayers.length) return false;

    const next = [...currentLayers];
    [next[idx], next[swapIdx]] = [next[swapIdx], next[idx]];
    const reordered = next.map((l, i) => ({ ...l, sort_order: i }));

    setLocalLayers(reordered);

    const map = mapInstanceRef.current;
    if (map && map.isStyleLoaded()) {
      reorderDataLayers(map, reordered);
    }

    setHasUnsavedChanges(true);
    return true;
  }, [mapInstanceRef, setHasUnsavedChanges]);

  const handleMoveUp = useCallback((layerId: string) => handleMove(layerId, 'up'), [handleMove]);
  const handleMoveDown = useCallback((layerId: string) => handleMove(layerId, 'down'), [handleMove]);

  const handleReorder = useCallback((reorderedLayers: MapLayerResponse[]) => {
    // Dragging the last child out of a folder group empties it; prune the
    // childless group row, which has no persisted carrier and would vanish on
    // save+reload.
    const nextLayers = pruneEmptyFolderGroups(reorderedLayers)
      .map((l, i) => ({ ...l, sort_order: i }));
    setLocalLayers(nextLayers);

    // Imperatively reorder MapLibre layers so the visual change is immediate
    const map = mapInstanceRef.current;
    if (map && map.isStyleLoaded()) {
      reorderDataLayers(map, nextLayers);
    }

    setHasUnsavedChanges(true);
  }, [mapInstanceRef, setHasUnsavedChanges]);

  const handleDisplayNameChange = useCallback((layerId: string, newName: string | null) => {
    const normalized = newName?.trim() || null;
    setLocalLayers((prev) =>
      prev.map((l) => (l.id === layerId ? { ...l, display_name: normalized } : l)),
    );
    setHasUnsavedChanges(true);
  }, [setHasUnsavedChanges]);

  const handleToggleExpand = useCallback((layerId: string) => {
    setExpandedLayerId((prev) => {
      if (!layerId) return null;
      const next = prev === layerId ? null : layerId;
      if (next !== null) setActiveEditorTab('style');
      return next;
    });
  }, []);

  const handleTabChange = useCallback((_layerId: string, tab: 'style' | 'filter' | 'labels' | 'popup') => {
    setActiveEditorTab((prev) => (prev === tab ? null : tab));
  }, []);

  const handleToggleGroupExpand = useCallback((groupId: string) => {
    if (!groupId) return;
    setGroupMeta((prev) => ({
      ...prev,
      [groupId]: { expanded: !(prev[groupId]?.expanded ?? false) },
    }));
    // Folder-group collapse state is persisted (the folderGroupExpanded marker
    // on each child's style_config), so a collapse-only change must dirty the
    // save. The basemap group stays UI-only: it has no persisted carrier.
    if (layersRef.current.some((l) => l.id === groupId && isFolderGroupLayer(l))) {
      setHasUnsavedChanges(true);
    }
  }, [setHasUnsavedChanges]);

  const handleZoomToLayer = useCallback((layerId: string) => {
    const map = mapInstanceRef.current;
    if (!map) return;
    const layer = layersRef.current.find((l) => l.id === layerId);
    if (!layer?.dataset_extent_bbox) return;
    const bbox = layer.dataset_extent_bbox;
    // Validate bbox: 4 finite numbers with a non-inverted latitude range. Equal
    // min/max (point geometries) is valid; fitBounds zooms to maxZoom there.
    // `bbox[0] > bbox[2]` is the RFC 7946 §5.2 form of an antimeridian-crossing
    // extent and must pass, or Zoom to Layer is a silent no-op for the layers
    // that need it most. `toFitBounds` lets east run past 180, which MapLibre
    // normalizes.
    if (
      bbox.length !== 4 ||
      bbox.some((v) => !Number.isFinite(v)) ||
      bbox[1] > bbox[3]
    ) return;
    try {
      map.fitBounds(
        toFitBounds([bbox[0], bbox[1], bbox[2], bbox[3]]),
        { padding: 40, maxZoom: 18 },
      );
    } catch {
      // Silently ignore invalid bounds (e.g. out-of-range coordinates)
    }
  }, [mapInstanceRef]);

  // Retain the pending id until both the new layer and reactive map instance
  // exist. The combined-fit branch shares this readiness gate and merges bounds
  // across every visible layer.
  useEffect(() => {
    const pendingId = pendingAutoZoomLayerIdRef.current;
    if (!pendingId) return;
    if (!mapInstance) return;
    if (!localLayers.some((l) => l.id === pendingId)) return;
    const wantsCombinedFit = pendingCombinedFitRef.current;
    pendingAutoZoomLayerIdRef.current = null;
    pendingCombinedFitRef.current = false;
    if (!wantsCombinedFit) {
      handleZoomToLayer(pendingId);
      return;
    }
    const map = mapInstanceRef.current;
    const bounds = getVisibleLayerBounds(layersRef.current);
    if (!map || !bounds) return;
    try {
      // duration: 0 settles fitBounds synchronously (as BuilderMap's own
      // auto-fit does); the zoom-2 clamp below must read the post-fit zoom.
      map.fitBounds(bounds, { padding: 40, maxZoom: 18, duration: 0 });
      clampMinZoomAfterFit(map);
    } catch {
      // Silently ignore invalid bounds (e.g. out-of-range coordinates)
    }
  }, [localLayers, mapInstance, handleZoomToLayer, mapInstanceRef]);

  // Set the map-level legend title; empty/null clears the override. Marks the
  // map dirty so the save path persists it.
  const handleLegendTitleChange = useCallback((title: string | null) => {
    const next = title && title.trim() ? title.trim() : null;
    setLocalLegendTitle((prev) => {
      if (prev === next) return prev;
      setHasUnsavedChanges(true);
      return next;
    });
  }, [setHasUnsavedChanges]);

  // Set a per-entry legend label override on style_config.legendLabel; an empty
  // string deletes the key (falls back to the display/dataset name). Routes
  // through handleStyleConfigChange, the single atomic setLocalLayers write
  // path, to avoid field-by-field clobbering.
  const handleLegendLabelChange = useCallback((layerId: string, label: string) => {
    const target = layersRef.current.find((l) => l.id === layerId);
    if (!target) return;
    const trimmed = label.trim();
    const current = target.style_config ?? null;
    const nextConfig = { ...(current ?? {}) } as StyleConfig;
    if (trimmed) {
      nextConfig.legendLabel = trimmed;
    } else {
      delete nextConfig.legendLabel;
    }
    const hasKeys = Object.keys(nextConfig).length > 0;
    handleStyleConfigChange(layerId, hasKeys ? nextConfig : null, target.paint);
  }, [handleStyleConfigChange]);

  const handleRemove = useCallback((layerId: string) => {
    if (!mapId) return;
    setExpandedLayerId((prev) => prev === layerId ? null : prev);

    // Optimistic state update with rollback on error, mirroring
    // handleBulkDelete. Without it nothing visibly happens: onSuccess only
    // invalidates the map query, and the resync effect is gated on
    // !hasUnsavedChanges, which is usually false while editing.
    const previousLayers = layersRef.current;
    // Removing a group's last child prunes the empty group row in the same
    // write; the error rollback restores previousLayers, bringing both back.
    setLocalLayers((prev) =>
      pruneEmptyFolderGroups(prev.filter((l) => l.id !== layerId))
        .map((l, i) => ({ ...l, sort_order: i })),
    );

    // If this delete removes the last DEM layer backing active 3D terrain,
    // auto-clear terrain_config and toast. Keys on dataset identity
    // (shouldClearTerrainOnDelete), so deleting an unrelated layer leaves
    // terrain untouched. The prior terrain_config is snapshotted so the onError
    // rollback restores it; otherwise a failed delete leaves the DEM layer back
    // but 3D terrain disabled.
    const previousTerrainConfig = localTerrainConfig;
    const remainingAfterRemove = previousLayers.filter((l) => l.id !== layerId);
    const clearedTerrainOnRemove = shouldClearTerrainOnDelete(remainingAfterRemove, localTerrainConfig);
    if (clearedTerrainOnRemove) {
      setLocalTerrainConfig((prev) => ({
        enabled: false,
        source_dataset_id: null,
        exaggeration: normalizeTerrainExaggeration(prev?.exaggeration),
      }));
      setHasUnsavedChanges(true);
      toast.success(t('toasts.terrainDisabledSourceRemoved'));
    }

    // Clean per-layer companions (outline/label/extrusion/arrow/cluster glyphs)
    // before the mutation so they disappear with the user action. Deduped
    // sources stay for the next syncFromState to prune by reference count.
    removePerLayerCompanions(mapInstanceRef.current, [layerId]);
    removeLayerMutation.mutate(
      { mapId, layerId },
      {
        onSuccess: () => {
          // Keep a stale savedLayerBaselineRef from blocking a React-Query refetch.
          savedLayerBaselineRef.current = savedLayerBaselineRef.current.filter(
            (l) => l.id !== layerId,
          );
          // Prune the save-diff baseline even while dirty so the next save
          // doesn't request removal of a row the server already dropped.
          saveBaselineSyncRef.current?.remove([layerId]);
          toast.success(t('toasts.layerRemoved'));
        },
        onError: () => {
          // Rollback: re-insert the failed layer. Not previousLayers wholesale:
          // a concurrent edit (e.g. handleAddDataset onSuccess landing while the
          // DELETE was in flight) must survive, or the next save diff would ask
          // the server to DELETE the just-added layer.
          setLocalLayers((current) =>
            restoreFailedLayers(current, previousLayers, new Set([layerId])),
          );
          // Restore terrain_config if the optimistic delete cleared it.
          if (clearedTerrainOnRemove) {
            setLocalTerrainConfig(previousTerrainConfig);
          }
          toast.error(t('toasts.layerRemoveFailed'));
        },
      },
    );
  }, [mapId, mapInstanceRef, removeLayerMutation, localTerrainConfig, saveBaselineSyncRef, t, setHasUnsavedChanges]);

  const handleAddDataset = useCallback(
    (
      datasetId: string,
      onSuccessCb?: (newLayerId: string) => void,
      parentGroupId?: string | null,
      datasetName?: string,
    ) => {
      if (!mapId) return;
      // New layers prepend at the top of the user stack with sort_order 0; the
      // mutation's invalidation renumbers existing layers. Appending would bury
      // the new layer and conflict with the auto-open flyout UX.
      addLayerMutation.mutate(
        { mapId, data: { dataset_id: datasetId, sort_order: 0 } },
        {
          onSuccess: (createdLayer) => {
            // Optimistically merge every created layer into localLayers and the
            // saved baseline so it appears immediately even while dirty (the
            // apiLayers sync is gated on !hasUnsavedChanges, so otherwise the
            // layer stayed hidden until save/reload and users retried,
            // duplicating). A folder-group drop is the same insertion, also
            // stamping parent_group_id.
            if (createdLayer?.id) {
              // Prepending renumbers existing siblings locally (an unpersisted
              // diff), which is what the dirty flag below is for. On a fresh map
              // the POST-created layer alone is the saved state, so marking
              // dirty would falsely trigger the unsaved-changes prompt.
              // layersRef is committed via useLayoutEffect, so when two add
              // mutations resolve before React commits (e.g. AI "Accept all"
              // staging several add_layer actions) it is stale-empty for both,
              // yet the second add renumbers the first. savedLayerBaselineRef is
              // updated synchronously below, so check both refs rather than
              // side-effect inside the setLocalLayers updater (which must stay
              // pure; StrictMode double-invokes it).
              const hadOtherLayers =
                layersRef.current.some((l) => l.id !== createdLayer.id) ||
                savedLayerBaselineRef.current.some((l) => l.id !== createdLayer.id);
              const insertedLayer: GroupedLayer = parentGroupId
                ? { ...createdLayer, parent_group_id: parentGroupId }
                : { ...createdLayer };
              setLocalLayers((prev) => {
                const existingIdx = prev.findIndex((l) => l.id === createdLayer.id);
                if (existingIdx >= 0) {
                  // Already present (e.g. a refetch landed first): don't
                  // duplicate. Only stamp group membership on a folder drop.
                  if (!parentGroupId) return prev;
                  const existing = prev[existingIdx] as GroupedLayer;
                  if (existing.parent_group_id === parentGroupId) return prev;
                  const next = [...prev];
                  next[existingIdx] = { ...existing, parent_group_id: parentGroupId } as MapLayerResponse;
                  return next;
                }

                if (!parentGroupId) {
                  // Prepend at the top (sort_order 0) and renumber, matching the add request.
                  return [insertedLayer as MapLayerResponse, ...prev].map((l, i) => ({ ...l, sort_order: i }));
                }

                // Insert adjacent to the group's existing block, not at index 0:
                // hydrateFolderGroupLayers anchors the group row at its first
                // child, so prepending would drag the group to the stack top after
                // a save/reload. Insert after the group's last child (or the group
                // row itself when empty) so the first child's position never moves.
                const groupIdx = prev.findIndex((l) => l.id === parentGroupId);
                let lastChildIdx = -1;
                for (let i = prev.length - 1; i >= 0; i--) {
                  if ((prev[i] as GroupedLayer).parent_group_id === parentGroupId) {
                    lastChildIdx = i;
                    break;
                  }
                }
                const insertIdx = lastChildIdx >= 0
                  ? lastChildIdx + 1
                  : (groupIdx >= 0 ? groupIdx + 1 : prev.length);
                const next = [...prev];
                next.splice(insertIdx, 0, insertedLayer as MapLayerResponse);
                return next.map((l, i) => ({ ...l, sort_order: i }));
              });
              // Keep the saved baseline in sync (as handleDuplicateRendering
              // does) so a clean refetch isn't blocked. It carries the pure
              // server layer: parent_group_id is unsaved frontend state.
              if (!savedLayerBaselineRef.current.some((l) => l.id === createdLayer.id)) {
                savedLayerBaselineRef.current = [createdLayer, ...savedLayerBaselineRef.current];
              }
              // Register the pure server layer in the save-diff baseline so Save
              // doesn't PATCH this just-created layer as a duplicate.
              saveBaselineSyncRef.current?.add(createdLayer);
              // Mark dirty when existing siblings were renumbered: the
              // non-grouped branch renumbers every sort_order locally but the
              // backend doesn't renumber sibling rows (maps/service_layers.py),
              // so it is an unpersisted diff the apiLayers resync could clobber
              // before Save. handleDuplicateRendering applies the same rule.
              // Skip for the only layer on a fresh map with no group stamped:
              // local state mirrors the server.
              if (hadOtherLayers || parentGroupId) setHasUnsavedChanges(true);
              if (parentGroupId) {
                // Group membership is unsaved frontend state: mark dirty so Save
                // persists it and the refetch sync doesn't wipe it, and
                // auto-expand the group so the child is visible.
                setGroupMeta((prev) =>
                  prev[parentGroupId]?.expanded ? prev : { ...prev, [parentGroupId]: { expanded: true } },
                );
              }
            }
            // Named toast when datasetName is provided; generic otherwise.
            if (datasetName) {
              toast.success(t('toasts.datasetAdded', { name: datasetName }), {
                id: `add-layer-${datasetId}`,
              });
            } else {
              toast.success(t('toasts.layerAdded'));
            }
            if (onSuccessCb && createdLayer?.id) {
              onSuccessCb(createdLayer.id);
            }
            // Set freshLayerId briefly so StackRow can animate in. Single-flight:
            // clear any prior timer first.
            if (createdLayer?.id) {
              if (freshLayerTimeoutRef.current) clearTimeout(freshLayerTimeoutRef.current);
              setFreshLayerId(createdLayer.id);
              freshLayerTimeoutRef.current = setTimeout(() => {
                setFreshLayerId(null);
                freshLayerTimeoutRef.current = null;
              }, 200);
            }
          },
          onError: () => {
            // The analysis add-to-map guard settles in useAddLayer's global
            // callbacks (use-maps.ts); per-call callbacks are dropped when a
            // second add overlaps on the shared mutation observer.
            toast.error(t('toasts.layerAddFailed'));
          },
        },
      );
    },
    [mapId, addLayerMutation, t, saveBaselineSyncRef, setHasUnsavedChanges],
  );
  // Adds the entry intent's dataset once. Depends on mapData so the effect
  // re-evaluates once initializedRef is set.
  useEffect(() => {
    if (!initializedRef.current || addDatasetProcessedRef.current) return;
    const datasetId = addDatasetId;
    if (!datasetId) return;
    addDatasetProcessedRef.current = true;
    // A fresh map has no saved view (center_lng/center_lat null, as in
    // BuilderMap's hasSavedView check) and opens at the world-view default, so
    // the added dataset can land off-screen. Record the new layer id for the
    // one-time auto-zoom effect above; a map with its own saved view keeps its
    // chosen framing. Not handleZoomToLayer directly: layersRef syncs only via
    // the useLayoutEffect mirror on commit, so it would miss the new layer.
    // "Fresh" also means no prior layers: a centerless map with layers keeps
    // BuilderMap's combined-bounds auto-fit, which a single-layer zoom would race.
    const hasSavedView = hasSavedMapCamera(mapData);
    const isFreshMap = !hasSavedView && (mapData?.layers?.length ?? 0) === 0;
    handleAddDataset(
      datasetId,
      hasSavedView
        ? undefined
        : (newLayerId) => {
            if (isFreshMap) {
              pendingAutoZoomLayerIdRef.current = newLayerId;
              return;
            }
            // BuilderMap seeds its auto-fit baseline from its first render, so a
            // cold mount (mapInstanceRef null) never sees this addition as a
            // change; take charge only then.
            if (!mapInstanceRef.current) {
              pendingAutoZoomLayerIdRef.current = newLayerId;
              pendingCombinedFitRef.current = true;
            }
          },
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps -- react to intent/map changes only; the applier is stable
  }, [addDatasetId, mapData]);


  // AI-specific remove: removes locally (persisted on Save).
  // Per-layer companions (label/outline/extrusion/arrow + main layer-{id})
  // are cleaned up imperatively. Source teardown is left to the next
  // `syncFromState` desired-set prune, which is reference-count-aware and keeps
  // a deduped `source-data-${dataset_table_name}` while sibling layers use it.
  const handleAiRemoveLayer = useCallback((layerId: string) => {
    // Prune a group row emptied by this removal, as handleRemove does.
    setLocalLayers((prev) => pruneEmptyFolderGroups(prev.filter((l) => l.id !== layerId)));
    // Clean up per-layer companions imperatively (shared with handleRemove and
    // handleBulkDelete). Sources are not removed here: a deduped source may
    // still be shared, and the next syncFromState prunes only orphans.
    removePerLayerCompanions(mapInstanceRef.current, [layerId]);
    setHasUnsavedChanges(true);
  }, [mapInstanceRef, setHasUnsavedChanges]);

  const handleToggleLegend = useCallback((layerId: string) => {
    setLocalLayers((prev) =>
      prev.map((l) =>
        l.id === layerId ? { ...l, show_in_legend: !l.show_in_legend } : l,
      ),
    );
    setHasUnsavedChanges(true);
  }, [setHasUnsavedChanges]);

  const handleDuplicateRendering = useCallback((layerId: string) => {
    if (!mapId) return;
    const layer = layersRef.current.find((candidate) => candidate.id === layerId);
    if (!layer) return;

    // render_mode:'terrain' only means "overlay off"; terrain itself is a
    // single map-level terrain_config pointer.

    const data = buildDuplicateRenderingInput(layer, {
      layerFallback: t('layerMutations.layerFallback', { defaultValue: 'Layer' }),
      duplicateName: (baseName) => t('layerMutations.duplicateName', { name: baseName, defaultValue: '{{name}} rendering' }),
    });
    // Carry the source's frontend-only parent_group_id so a duplicate of a
    // grouped layer stays in the group (MapLayerInput/the API can't carry it);
    // it is stamped onto the local duplicate only.
    const sourceParentGroupId = (layer as GroupedLayer).parent_group_id ?? null;

    addLayerMutation.mutate(
      { mapId, data },
      {
        onSuccess: (createdLayer) => {
          // The updater stays pure; the useLayoutEffect mirror syncs layersRef
          // from committed state, the one StrictMode-safe place the ref updates.
          setLocalLayers((prev) => {
            if (prev.some((candidate) => candidate.id === createdLayer.id)) return prev;
            const duplicate: GroupedLayer = sourceParentGroupId
              ? { ...createdLayer, parent_group_id: sourceParentGroupId }
              : { ...createdLayer };
            const sourceIdx = prev.findIndex((candidate) => candidate.id === layerId);
            const next = [...prev];
            if (sourceIdx >= 0) {
              // Splice adjacent to the source (inside the group block when
              // grouped) instead of appending at the array end.
              next.splice(sourceIdx + 1, 0, duplicate as MapLayerResponse);
            } else {
              next.push(duplicate as MapLayerResponse);
            }
            return next.map((candidate, index) => ({ ...candidate, sort_order: index }));
          });
          // Baseline carries the pure server layer (parent_group_id is unsaved
          // frontend state), as in the handleAddDataset drop path.
          savedLayerBaselineRef.current = [
            ...savedLayerBaselineRef.current.filter((candidate) => candidate.id !== createdLayer.id),
            createdLayer,
          ];
          // Register the pure server layer in the save-diff baseline so Save
          // doesn't PATCH this just-created layer as a duplicate.
          saveBaselineSyncRef.current?.add(createdLayer);
          // The splice above renumbers the full local array (adjacent insert),
          // an unpersisted diff for grouped and non-grouped duplicates alike.
          // Mark dirty unconditionally so the !hasUnsavedChanges-gated apiLayers
          // resync can't overwrite the adjacent placement with server order
          // before Save.
          setHasUnsavedChanges(true);
          if (createdLayer?.id) {
            setExpandedLayerId(createdLayer.id);
            setActiveEditorTab('style');
            if (freshLayerTimeoutRef.current) clearTimeout(freshLayerTimeoutRef.current);
            setFreshLayerId(createdLayer.id);
            freshLayerTimeoutRef.current = setTimeout(() => {
              setFreshLayerId(null);
              freshLayerTimeoutRef.current = null;
            }, 200);
          }
          toast.success(t('toasts.layerDuplicated'));
        },
        onError: () => {
          toast.error(t('toasts.layerAddFailed'));
        },
      },
    );
  }, [addLayerMutation, mapId, t, saveBaselineSyncRef, setHasUnsavedChanges]);

  const markDirty = useCallback(() => setHasUnsavedChanges(true), [setHasUnsavedChanges]);

  // For state this hook can't compare against server data (dock notes, plugin
  // toggles). Marking re-derivable edits (name, description, basemap) opaque
  // would leave the unsaved indicator unclearable even after the value is put back.
  const markOpaqueDirty = useCallback(() => {
    opaqueDirtyRef.current = true;
    setHasUnsavedChanges(true);
  }, [setHasUnsavedChanges]);

  // The live camera when it is an unsaved edit made on this map, else null. The
  // entry camera keeps an untouched map clean, so this applies to a map with no
  // stored view too: handleSave persists the camera either way.
  const unsavedCamera = useCallback((): BuilderCamera | null => {
    const liveCamera = liveCameraRef.current;
    if (!mapData || !liveCamera || liveCamera.mapId !== mapData.id) return null;
    const entry = cameraEntryRef.current;
    if (entry?.mapId === mapData.id && sameMapCamera(liveCamera.camera, entry.camera)) return null;
    if (sameMapCamera(liveCamera.camera, savedMapCamera(mapData))) return null;
    return liveCamera.camera;
  }, [mapData]);

  // Revert clears dirty state only after full layer objects and map-level state
  // match the saved baseline. The camera is checked separately by unsavedCamera.
  const computeEditsAreClean = useCallback((): boolean => {
    if (!mapData || opaqueDirtyRef.current) return false;

    const baseline = savedLayerBaselineRef.current;
    const current = layersRef.current;
    if (current.length !== baseline.length) return false;
    const savedById = new Map(baseline.map((l) => [l.id, l]));
    for (let i = 0; i < current.length; i += 1) {
      const saved = savedById.get(current[i].id);
      // Order matters (sort_order is persisted), so compare position too.
      if (!saved || saved.id !== baseline[i].id || !deepEqual(current[i], saved)) return false;
    }

    // Compare the save payload's normalization, not the raw local strings:
    // handleSave persists `localName || undefined`, `localDescription.trim() ||
    // null` and a trimmed-or-null legend title.
    if (localName && localName !== mapData.name) return false;
    // Text fields hydrate raw but save trimmed-or-null, so neither a raw nor a
    // trimmed compare is right alone: raw calls an untouched server value with
    // surrounding whitespace dirty forever; trimmed calls a real edit (removing
    // that whitespace) clean. Dirty means "saving would change the stored
    // value": identical text is clean, as is any pair that both persist as null.
    if (!sameSavedText(localDescription, mapData.description)) return false;
    if (!sameSavedText(localLegendTitle, mapData.legend_title)) return false;
    if (localBasemap !== resolveBasemapId(mapData.basemap_style || 'positron')) return false;
    if (showBasemapLabels !== (mapData.show_basemap_labels ?? true)) return false;
    if (!deepEqual(basemapConfig, mapData.basemap_config ?? null)) return false;
    if (!deepEqual(localTerrainConfig, savedTerrainConfig(mapData))) return false;

    // Folder expansion is persisted (prepareLayersForPersistence reads
    // groupMeta) and handleToggleGroupExpand dirties the map, so an
    // expand-then-revert must not report clean. Compare only persisted folder
    // rows: the basemap row also writes a groupMeta entry without dirtying, so
    // a whole-object compare could never match.
    const savedMeta = savedGroupMeta(mapData);
    for (const layer of current) {
      if (!isFolderGroupLayer(layer)) continue;
      if ((groupMeta[layer.id]?.expanded ?? false) !== (savedMeta[layer.id]?.expanded ?? false)) return false;
    }

    return true;
  }, [
    mapData, localName, localDescription, localLegendTitle, localBasemap,
    showBasemapLabels, basemapConfig, localTerrainConfig, groupMeta,
  ]);

  // The recheck must observe the reverted layers, so it runs in an effect after
  // commit rather than inline in the revert handler. The nonce and the layer
  // updates batch into the same render, so one request costs one pass.
  const [recheckNonce, setRecheckNonce] = useState(0);
  const recheckPendingRef = useRef(false);
  const requestCleanRecheck = useCallback(() => {
    recheckPendingRef.current = true;
    setRecheckNonce((n) => n + 1);
  }, []);
  // A request stays pending until it finds the map clean, and re-runs when the
  // saved baselines change: a save invalidates the map-detail query, and a
  // revert racing the refetch would otherwise compare stale server data once.
  // Every save rewrites center, zoom, bearing and pitch from the live map, so
  // once the edits are put back an unsaved pan still keeps Save enabled.
  useEffect(() => {
    if (recheckNonce === 0 || !recheckPendingRef.current) return;
    if (!computeEditsAreClean()) return;
    setHasUnsavedEdits(false);
    if (unsavedCamera()) return;
    recheckPendingRef.current = false;
    setUnsavedFlag(false);
  }, [recheckNonce, computeEditsAreClean, unsavedCamera]);

  // Camera a change of map identity starts from. Re-read on every identity
  // change: the shared MapGL instance isn't repositioned, so the screen still
  // shows the previous map's view.
  const currentMapId = mapData?.id ?? null;
  useEffect(() => {
    const map = mapInstance ?? mapInstanceRef.current;
    cameraEntryRef.current = { mapId: currentMapId, camera: readMapCamera(map) };
  }, [currentMapId, mapInstance, mapInstanceRef]);

  // moveend is the canonical camera-settled signal (once per gesture, so no
  // debounce). Read through the reactive mapInstance, since a ref flipping
  // non-null doesn't re-run an effect.
  useEffect(() => {
    const map = mapInstance ?? mapInstanceRef.current;
    // Partial map doubles in sibling suites carry no event emitter; without a
    // moveend there is no camera signal.
    if (!map || typeof map.on !== 'function') return;
    const handleMoveEnd = () => {
      const sample = { mapId: currentMapId, camera: readMapCamera(map) };
      const entry = cameraEntryRef.current;
      // The entry view excuses itself only until the camera leaves it. Coming
      // back to that position later is a choice the user made, and after a save
      // it is no longer what the server holds.
      if (entry?.mapId === currentMapId && !sameMapCamera(sample.camera, entry.camera)) {
        cameraEntryRef.current = null;
      }
      liveCameraRef.current = sample;
      const data = mapDataRef.current;
      const unsaved =
        !!data &&
        sample.mapId === data.id &&
        !(cameraEntryRef.current?.mapId === data.id && sameMapCamera(sample.camera, cameraEntryRef.current.camera)) &&
        !sameMapCamera(sample.camera, savedMapCamera(data));
      setCameraUnsaved(unsaved);
      // A save clears the flag while the camera stays unsaved-looking, so the
      // next pan has no flip to re-dirty it through.
      if (unsaved && !hasUnsavedChangesRef.current) setUnsavedFlag(true);
    };
    map.on('moveend', handleMoveEnd);
    return () => { map.off?.('moveend', handleMoveEnd); };
  }, [currentMapId, mapInstance, mapInstanceRef]);

  // An unsaved camera edit enables Save; anything else asks for the ordinary
  // recheck, which clears the flag only if nothing else is outstanding.
  useEffect(() => {
    if (cameraUnsaved === null) return;
    if (unsavedCamera()) {
      setUnsavedFlag(true);
      return;
    }
    requestCleanRecheck();
  }, [cameraUnsaved, unsavedCamera, requestCleanRecheck]);

  // Identity-stable "is this row a folder group?" lookup. Reads through
  // layersRef so MapBuilderPage's memoized onToggleVisibility needn't depend on
  // localLayers, which would re-create it on the frames row memoization skips.
  const isFolderGroupRow = useCallback((layerId: string): boolean => {
    const target = layersRef.current.find((l) => l.id === layerId);
    return (target as GroupedLayer | undefined)?.layer_type === 'group:folder';
  }, []);

  const dispatchLayerAction = useCallback((action: BuilderLayerAction) => {
    dispatchBuilderLayerAction(action, {
      setFilter: handleFilterChange,
      setPaint: handlePaintChange,
      setStyleConfig: handleStyleConfigChange,
      setLabel: handleLabelChange,
      setPopup: handlePopupChange,
      setLayout: handleLayoutChange,
      setVisibility: handleToggleVisibility,
      toggleGroupVisibility: handleToggleGroupVisibility,
      setOpacity: handleOpacityChange,
      addDataset: (datasetId) => handleAddDataset(datasetId),
      removePersistedLayer: handleRemove,
      removeDraftLayer: handleAiRemoveLayer,
      duplicateRendering: handleDuplicateRendering,
      reorderLayers: handleReorder,
      bindDemTerrain: handleDEMTerrainBind,
      unbindDemTerrain: handleDEMTerrainUnbind,
      setDemTerrainExaggeration: handleDEMTerrainExaggerationChange,
    });
  }, [
    handleAddDataset,
    handleAiRemoveLayer,
    handleDEMTerrainBind,
    handleDEMTerrainExaggerationChange,
    handleDEMTerrainUnbind,
    handleDuplicateRendering,
    handleFilterChange,
    handleLabelChange,
    handleLayoutChange,
    handleOpacityChange,
    handlePaintChange,
    handlePopupChange,
    handleRemove,
    handleReorder,
    handleStyleConfigChange,
    handleToggleVisibility,
    handleToggleGroupVisibility,
  ]);

  // Restore chat snapshots in one state update because sequential handlers read
  // the same ref snapshot. BuilderMap then reconciles the restored layers.
  const handleRestoreLayers = useCallback((restored: MapLayerResponse[]) => {
    if (restored.length === 0) return;
    const byId = new Map(restored.map((l) => [l.id, l]));
    setLocalLayers((prev) => prev.map((l) => byId.get(l.id) ?? l));
    setHasUnsavedChanges(true);
  }, [setLocalLayers, setHasUnsavedChanges]);

  const chatLayerActions: LayerActions = useMemo(() => ({
    onFilterChange: (layerId, expression) => dispatchLayerAction({
      type: 'set_filter',
      source: 'ai',
      layerId,
      expression,
    }),
    onPaintChange: (layerId, paint) => dispatchLayerAction({
      type: 'set_paint',
      source: 'ai',
      layerId,
      paint,
    }),
    onStyleConfigChange: (layerId, config, paint) => dispatchLayerAction({
      type: 'set_style_config',
      source: 'ai',
      layerId,
      config,
      paint,
    }),
    onLabelChange: (layerId, config) => dispatchLayerAction({
      type: 'set_label',
      source: 'ai',
      layerId,
      config,
    }),
    onToggleVisibility: (layerId, visible) => dispatchLayerAction({
      type: 'set_visibility',
      source: 'ai',
      layerId,
      visible,
    }),
    onAddDataset: (datasetId) => dispatchLayerAction({
      type: 'add_dataset',
      source: 'ai',
      datasetId,
    }),
    onRemove: (layerId) => dispatchLayerAction({
      type: 'remove_layer',
      source: 'ai',
      layerId,
      persistence: 'draft',
    }),
    onOpacityChange: (layerId, opacity) => dispatchLayerAction({
      type: 'set_opacity',
      source: 'ai',
      layerId,
      opacity,
    }),
    onRenderAsChange: handleRenderAsChange,
    getLayer: (layerId) => layersRef.current.find((l) => l.id === layerId),
    onRestoreLayers: handleRestoreLayers,
  }), [dispatchLayerAction, handleRenderAsChange, handleRestoreLayers]);

  return {
    localName, setLocalName,
    localDescription, setLocalDescription,
    localLegendTitle, setLocalLegendTitle,
    handleLegendTitleChange,
    handleLegendLabelChange,
    localLayers,
    layersMapId,
    freshLayerId,
    savedLayerBaseline: savedLayerBaselineRef.current,
    localBasemap, setLocalBasemap,
    hasUnsavedChanges, setHasUnsavedChanges: setHasUnsavedChangesTracked,
    hasUnsavedEdits,
    requestCleanRecheck,
    expandedLayerId,
    activeEditorTab,
    showBasemapLabels, setShowBasemapLabels,
    basemapConfig, setBasemapConfig,
    localTerrainConfig, setLocalTerrainConfig,
    groupMeta,
    ephemeralResult,
    initialViewState,
    handleToggleVisibility,
    handleMoveUp,
    handleMoveDown,
    handleReorder,
    handleDisplayNameChange,
    handleToggleExpand,
    handleToggleGroupExpand,
    handleTabChange,
    handleFilterChange,
    handleLabelChange,
    handlePopupChange,
    handleStyleConfigChange,
    handlePaintChange,
    handleOpacityChange,
    handleRenderAsChange,
    handleLayoutChange,
    handleZoomToLayer,
    // Style clipboard
    handleCopyStyle,
    handlePasteStyle,
    handleBulkApplyStyle,
    copiedStyleGeometryClass,
    handleRemove,
    handleDEMTerrainBind,
    handleDEMTerrainUnbind,
    handleDEMTerrainExaggerationChange,
    handleCreateGroupWithLayer,
    handleRenameGroup,
    handleUngroup,
    handleDeleteGroup,
    handleAddLayerToExistingGroup,
    handleMoveLayerOutOfGroup,
    handleAddDataset,
    handleDuplicateRendering,
    dispatchLayerAction,
    handleAiRemoveLayer,
    handleQueryResult,
    handleToggleLegend,
    handleDismissEphemeral,
    markDirty,
    markOpaqueDirty,
    chatLayerActions,
    // Bulk operation handlers
    handleBulkVisibility,
    handleBulkOpacity,
    handleBulkGroup,
    handleBulkUngroup,
    handleBulkDelete,
    // In-flight state for the BulkActionBar spinner
    isDeleting,
    // In-flight batch size for the BulkActionBar label
    deletingCount,
    // Stable ref-reading predicate so onToggleVisibility doesn't re-create per change.
    isFolderGroupRow,
  };
}
