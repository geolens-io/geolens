import { useState, useEffect, useLayoutEffect, useRef, useMemo, useCallback } from 'react';
import { useSearchParams } from 'react-router';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import type { Map as MaplibreMap } from 'maplibre-gl';
import { toFitBounds } from '@/lib/bbox';
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
// fix(#833): folder-group collapse dirties the save (its state is persisted
// on children); the basemap group's does not — the toggle needs to tell them apart.
import { isFolderGroupLayer } from '@/lib/layer-capabilities';
// STATE-02: cohesive handler clusters extracted into focused hooks. This hook
// composes them and keeps its return surface identical so MapBuilderPage is
// unchanged. PURE RELOCATION — see each hook for the verbatim handler bodies.
import { useFolderGroupLayers } from '@/components/builder/hooks/use-folder-group-layers';
import { useBulkLayerActions, restoreFailedLayers } from '@/components/builder/hooks/use-bulk-layer-actions';
import { useTerrainLayers } from '@/components/builder/hooks/use-terrain-layers';
import { useRenderModeLayers } from '@/components/builder/hooks/use-render-mode-layers';
import { useLayerStyleClipboard } from '@/components/builder/hooks/use-layer-style-clipboard';
import { useTileConfig } from '@/hooks/use-settings';
export { buildDuplicateRenderingInput } from '@/components/builder/hooks/builder-layer-mutations';

// True when a local text field and its saved value would persist identically.
// The save payload is `value.trim() || null`, and the field hydrates raw.
function sameSavedText(local: string | null | undefined, saved: string | null | undefined): boolean {
  const l = local ?? '';
  const r = saved ?? '';
  if (l === r) return true;
  return l.trim() === '' && r.trim() === '';
}

// fix(#913 review): the hydrated shape of mapData's folder-expansion state,
// mirroring the load path below (hydrated markers overlaid with group_meta).
function savedGroupMeta(mapData: MapResponse): Record<string, { expanded: boolean }> {
  return {
    ...hydrateFolderGroupLayers(mapData.layers ?? []).groupMeta,
    ...((mapData as { group_meta?: Record<string, { expanded: boolean }> }).group_meta ?? {}),
  };
}

// fix(#913): the hydrated shape of mapData.terrain_config, shared by the load
// path and the clean-state recheck so the two cannot drift.
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
  // fix(#392): populated by useBuilderSave (MapBuilderPage renders
  // useBuilderLayers before useBuilderSave, so a callback ref bridges the two).
  // Invoked by handleAddDataset/handleDuplicateRendering so the Save-diff
  // baseline learns about server-created layers immediately, instead of only
  // on a clean-state resync — see use-builder-save.ts for the full rationale.
  saveBaselineSyncRef: React.MutableRefObject<SaveBaselineSync>,
  // fix(#1863 P2): the REACTIVE counterpart of mapInstanceRef (MapBuilderPage
  // already tracks both — mapInstanceRef for imperative reads, this state for
  // effects that must re-run when the map becomes ready). mapInstanceRef.current
  // flipping non-null does NOT by itself re-run an effect (refs aren't
  // reactive), so the #1854 auto-zoom watcher below needs this to know when
  // to retry a pending zoom that arrived before the (lazy-loaded, possibly
  // still-suspended) map instance existed. Optional/trailing so every
  // existing call site compiles unchanged; omitting it only means a
  // cold-entry auto-zoom race is not retried, same as before this fix.
  mapInstance?: MaplibreMap | null,
) {
  const [searchParams, setSearchParams] = useSearchParams();
  const { t } = useTranslation('builder');
  const { data: tileConfig } = useTileConfig();
  const mvtSourceLayerPrefix = tileConfig?.mvt_source_layer_prefix;

  const initializedRef = useRef(false);
  const addDatasetProcessedRef = useRef(false);
  // fix(#1854): id of a just-added layer that still needs its one-time
  // auto-zoom (fresh map only — see the add_dataset effect below).
  const pendingAutoZoomLayerIdRef = useRef<string | null>(null);

  const [localLayers, setLocalLayers] = useState<MapLayerResponse[]>([]);
  // fix(#793 review): which map the CURRENT localLayers belong to. On direct
  // /maps/:id navigation this page stays mounted and the route id flips a
  // commit (or more) before the new map's layers hydrate — consumers that
  // initialize from layers at mount (AnalysisPanel) must wait until this
  // matches the route id, or they judge one map's remembered state against
  // another map's rows and overwrite it.
  const [layersMapId, setLayersMapId] = useState<string | null>(null);
  const layersMapIdRef = useRef<string | null>(null);
  const [localBasemap, setLocalBasemap] = useState<string>('openfreemap-positron');
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false);
  // fix(#1854): the live camera, sampled on moveend. Null until the map has
  // settled once, because a map that never moved cannot have changed the view
  // a save would store.
  const [liveCamera, setLiveCamera] = useState<BuilderCamera | null>(null);
  // fix(#913): dirt this hook cannot re-derive from server state — plugin
  // toggles and other page-owned edits that go through markDirty. recheckClean
  // refuses to clear the flag while it is set; every reset back to "saved"
  // clears it.
  const opaqueDirtyRef = useRef(false);
  const setHasUnsavedChangesTracked = useCallback(
    (next: React.SetStateAction<boolean>) => {
      if (next === false) opaqueDirtyRef.current = false;
      setHasUnsavedChanges(next);
    },
    [],
  );
  const [expandedLayerId, setExpandedLayerId] = useState<string | null>(null);
  const [activeEditorTab, setActiveEditorTab] = useState<'style' | 'filter' | 'labels' | 'popup' | null>(null);
  const [showBasemapLabels, setShowBasemapLabels] = useState(true);
  const [basemapConfig, _setBasemapConfigRaw] = useState<MapBasemapConfig | null>(null);
  // WR-02 (quick-260516-9g9 followup): wrap setBasemapConfig so external callers
  // get dirty-tracking for free — Option B's single-source-of-truth principle
  // means basemapConfig writes always imply user intent to persist. The raw
  // setter is reserved for the load path (line ~120) where the initial
  // hydration must NOT mark dirty.
  const setBasemapConfig = useCallback(
    (next: MapBasemapConfig | null | ((prev: MapBasemapConfig | null) => MapBasemapConfig | null)) => {
      _setBasemapConfigRaw(next);
      setHasUnsavedChanges(true);
    },
    [],
  );
  const [localTerrainConfig, setLocalTerrainConfig] = useState<MapTerrainConfig | null>(null);
  const [groupMeta, setGroupMeta] = useState<Record<string, { expanded: boolean }>>({});
  const [localName, setLocalName] = useState('');
  const [localDescription, setLocalDescription] = useState('');
  // ENH-06 (Phase 1201-06): map-level custom legend title. Null = no override.
  const [localLegendTitle, setLocalLegendTitle] = useState<string | null>(null);
  const [freshLayerId, setFreshLayerId] = useState<string | null>(null);
  const freshLayerTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const savedLayerBaselineRef = useRef<MapLayerResponse[]>([]);

  // Mirror current layers in a ref so stable callbacks can read fresh state
  // without invalidating on every layer mutation. Without this, each layer
  // edit would tear down React.memo() on StackRow (KISS-2 / PERF-N2).
  const layersRef = useRef(localLayers);
  useLayoutEffect(() => {
    layersRef.current = localLayers;
  }, [localLayers]);

  // Delegate ephemeral layer management
  const {
    ephemeralResult,
    handleQueryResult,
    handleDismissEphemeral,
  } = useEphemeralLayers(mapInstanceRef);

  // Delegate live map sync handlers
  const {
    handleToggleVisibility,
    handlePaintChange,
    handleStyleConfigChange,
    handleOpacityChange,
    handleLayoutChange,
    handleFilterChange,
    handleLabelChange,
    handlePopupChange,
    syncStyleConfigToMap,
  } = useLayerMapSync(
    localLayers,
    setLocalLayers,
    setHasUnsavedChanges,
    mapInstanceRef,
    mvtSourceLayerPrefix,
  );

  // STATE-02: per-row style clipboard (copy / paste). Owns the session clipboard
  // ref + geometry-class mirror; the bulk apply-style handler reads the same ref.
  const {
    copiedStyleRef,
    copiedStyleGeometryClass,
    handleCopyStyle,
    handlePasteStyle,
  } = useLayerStyleClipboard({ layersRef, handleStyleConfigChange });

  // STATE-02: bulk-operation handlers (apply-style / visibility / opacity /
  // group / ungroup / delete) + in-flight isDeleting state.
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
    syncStyleConfigToMap,
    mvtSourceLayerPrefix,
  });

  // STATE-02: folder-group handlers (create / rename / ungroup / toggle-vis /
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

  // STATE-02: DEM terrain bind / unbind / exaggeration handlers.
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

  // STATE-02: render-mode / layer-swap handlers.
  const {
    handleRenderAsChange,
    handleRenderModeChange,
  } = useRenderModeLayers({
    layersRef,
    setLocalLayers,
    setHasUnsavedChanges,
    mapInstanceRef,
    mvtSourceLayerPrefix,
  });

  // Initialize local state from API data (once).
  //
  // Phase 1051 UX-03: mapData.basemap_config may include the new
  // `basemap_position: 'top' | 'bottom'` field (jsonb additive, no migration).
  // We load it transparently via _setBasemapConfigRaw — downstream consumers
  // (UnifiedStackPanel `basemapPosition` prop, BuilderMap `reorderBasemapAboveData`
  // effect, MapBuilderPage `handleDragEnd` for basemap drag) read the field via
  // `basemapConfig?.basemap_position ?? 'bottom'` so legacy maps without the
  // field default to 'bottom' (the historical behaviour).
  // fix(#793 review): a direct /maps/:id navigation keeps this hook mounted,
  // so a DIFFERENT map identity must re-hydrate wholesale. The
  // !hasUnsavedChanges guard on the refetch sync below is for same-map
  // refetches — a discarded-edit exit ("Leave without saving") leaves the
  // flag true, which otherwise pins localLayers (and layersMapId, the
  // Analysis panel's mount gate) to the previous map forever. Declared
  // BEFORE the hydration effect so the same pass re-hydrates.
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
  }, [mapData]);

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

  // Cleanup freshLayerId timeout on unmount (T-1042-04-03 mitigation)
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

  // Handle ?add_dataset URL param: auto-add a dataset as a layer on map load.
  // Depends on mapData so the effect re-evaluates once initializedRef is set.
  useEffect(() => {
    if (!initializedRef.current || addDatasetProcessedRef.current) return;
    const datasetId = searchParams.get('add_dataset');
    if (!datasetId) return;
    addDatasetProcessedRef.current = true;
    // fix(#1854): a fresh map has no saved view of its own (center_lng/
    // center_lat are null — mirrors BuilderMap's hasSavedView check) and
    // opens at the world-view default, so the just-added dataset can land
    // off-screen. Record the new layer id for the one-time auto-zoom effect
    // below; a map with its own saved view is left alone (that framing was
    // chosen on purpose). Don't call handleZoomToLayer directly from this
    // callback — layersRef is only synced via the useLayoutEffect mirror on
    // commit (the same staleness #554 documented for the add-layer merge),
    // so it would still be missing the layer just created.
    const hasSavedView = mapData?.center_lng != null && mapData?.center_lat != null;
    handleAddDataset(
      datasetId,
      hasSavedView ? undefined : (newLayerId) => { pendingAutoZoomLayerIdRef.current = newLayerId; },
    );
    setSearchParams((prev) => {
      prev.delete('add_dataset');
      return prev;
    }, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- react to URL/map changes only; the applier is stable
  }, [searchParams, mapData]);

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
  // All handlers are wrapped in useCallback with stable deps so that
  // React.memo() on StackRow actually prevents re-renders on unrelated state
  // changes. Handlers that need to read the current layers list use
  // `layersRef.current` instead of `localLayers` to keep their dep lists
  // stable (KISS-2 / PERF-N2).

  // codex(#794): reports whether a move actually happened, so the keyboard
  // reorder announcement can stay silent at the stack boundaries instead of
  // confirming a move that did not occur.
  const handleMove = useCallback((layerId: string, direction: 'up' | 'down'): boolean => {
    const currentLayers = layersRef.current;
    // fix(HT-03): the stack no longer suppresses terrain-mode DEM rows, so the
    // rendered order IS the full layer order again (the #394 LM-05 filter is
    // obsolete — an arrow-move can never swap with an invisible row).
    const idx = currentLayers.findIndex((l) => l.id === layerId);
    if (idx < 0) return false;
    // codex(#794 round 3): the row's visible neighbor is its adjacent sibling
    // in the SAME container — the top level skips grouped children, and a
    // folder box lists only its own children — so the raw flat-array neighbor
    // can belong to another container. Swapping with that entry moves nothing
    // the user can see (while still dirtying the saved order) yet would be
    // announced as a move. Skip to the nearest same-container sibling; at the
    // container edge there is none, and that is a boundary, not a move.
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
  }, [mapInstanceRef]);

  const handleMoveUp = useCallback((layerId: string) => handleMove(layerId, 'up'), [handleMove]);
  const handleMoveDown = useCallback((layerId: string) => handleMove(layerId, 'down'), [handleMove]);

  const handleReorder = useCallback((reorderedLayers: MapLayerResponse[]) => {
    // fix(#767): dragging the last child out of a folder group empties it —
    // prune the childless group row so it does not linger in the UI only to
    // vanish on save+reload (it has no persisted carrier without children).
    const nextLayers = pruneEmptyFolderGroups(reorderedLayers)
      .map((l, i) => ({ ...l, sort_order: i }));
    setLocalLayers(nextLayers);

    // Imperatively reorder MapLibre layers so the visual change is immediate
    const map = mapInstanceRef.current;
    if (map && map.isStyleLoaded()) {
      reorderDataLayers(map, nextLayers);
    }

    setHasUnsavedChanges(true);
  }, [mapInstanceRef]);

  const handleDisplayNameChange = useCallback((layerId: string, newName: string | null) => {
    const normalized = newName?.trim() || null;
    setLocalLayers((prev) =>
      prev.map((l) => (l.id === layerId ? { ...l, display_name: normalized } : l)),
    );
    setHasUnsavedChanges(true);
  }, []);

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
    // fix(#833): folder-group collapse state IS persisted (the
    // folderGroupExpanded marker on each child's style_config), but a
    // collapse-only change never dirtied the save, so it only reached the
    // backend when another edit rode along and was lost on reload otherwise.
    // The basemap group stays UI-only — it has no persisted carrier, so
    // dirtying it would promise a save that stores nothing.
    if (layersRef.current.some((l) => l.id === groupId && isFolderGroupLayer(l))) {
      setHasUnsavedChanges(true);
    }
  }, []);

  const handleZoomToLayer = useCallback((layerId: string) => {
    const map = mapInstanceRef.current;
    if (!map) return;
    const layer = layersRef.current.find((l) => l.id === layerId);
    if (!layer?.dataset_extent_bbox) return;
    const bbox = layer.dataset_extent_bbox;
    // Validate bbox: must be 4 finite numbers with a non-inverted LATITUDE
    // range. Note: equal min/max (point geometries) is valid — fitBounds zooms
    // to maxZoom at that point.
    // fix(#903): `bbox[0] > bbox[2]` is no longer a rejection. That pair is the
    // RFC 7946 §5.2 spec form for an antimeridian-crossing extent, and
    // rejecting it made Zoom to Layer a silent no-op for exactly the layers a
    // user most needs it for. `toFitBounds` lets east run past 180, which
    // MapLibre normalizes.
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

  // fix(#1854): fires the pending auto-zoom (set by the ?add_dataset effect
  // above) once the new layer has actually committed to localLayers — by
  // then the useLayoutEffect mirror has already synced layersRef, so
  // handleZoomToLayer's lookup finds the layer and its dataset_extent_bbox.
  //
  // fix(#1863 P2): on a cold builder entry the add-layer POST can resolve
  // (landing the layer in localLayers) while BuilderMap is still lazy-loaded/
  // suspended or before its onLoad has populated mapInstanceRef — handleZoomToLayer
  // reads mapInstanceRef.current and silently no-ops when it is null. The old
  // version cleared pendingAutoZoomLayerIdRef unconditionally as soon as the
  // layer appeared, so nothing ever retried once the map became ready. Keep
  // the pending id until `mapInstance` (the reactive counterpart of the ref —
  // see the parameter above) is actually set, so this effect re-runs and
  // retries when the map finishes loading after the layer already landed.
  useEffect(() => {
    const pendingId = pendingAutoZoomLayerIdRef.current;
    if (!pendingId) return;
    if (!mapInstance) return;
    if (!localLayers.some((l) => l.id === pendingId)) return;
    pendingAutoZoomLayerIdRef.current = null;
    handleZoomToLayer(pendingId);
  }, [localLayers, mapInstance, handleZoomToLayer]);

  // ENH-06 (Phase 1201-06): set the map-level custom legend title. Empty/null
  // clears the override. Marks the map dirty so the save path persists it.
  const handleLegendTitleChange = useCallback((title: string | null) => {
    const next = title && title.trim() ? title.trim() : null;
    setLocalLegendTitle((prev) => {
      if (prev === next) return prev;
      setHasUnsavedChanges(true);
      return next;
    });
  }, [setHasUnsavedChanges]);

  // ENH-06 (Phase 1201-06): set a per-entry legend label override on a layer's
  // style_config.legendLabel. An empty string deletes the key (falls back to
  // the display/dataset name). Routes through handleStyleConfigChange — the
  // SAME atomic single-setLocalLayers write path used for every style mutation
  // — so no field-by-field clobber (applyLayerUpdate-stale-ref-clobber rule).
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

    // BUG-02 (Phase 1051-02): optimistic state update + rollback on error,
    // mirroring handleBulkDelete (lines 580-661). Without this, the user
    // clicks delete and nothing visibly happens — the API mutation fires
    // and onSuccess invalidates the map query, but the resync useEffect at
    // line 181-186 is gated by `!hasUnsavedChanges`, which is usually false
    // during the builder editing flow. The sidebar row then stays visible
    // until a full page reload.
    const previousLayers = layersRef.current;
    // fix(#767): removing a group's last child prunes the now-empty group row
    // in the same write; the error rollback below restores previousLayers, so
    // a failed delete brings the group back with its child.
    setLocalLayers((prev) =>
      pruneEmptyFolderGroups(prev.filter((l) => l.id !== layerId))
        .map((l, i) => ({ ...l, sort_order: i })),
    );

    // Phase 999.17 Fix 2 (D-05/A2): if this delete removes the last DEM layer
    // backing active 3D terrain, auto-clear terrain_config and surface a
    // non-blocking toast. Keys on dataset identity (shouldClearTerrainOnDelete),
    // so deleting an unrelated DEM/vector layer leaves terrain untouched.
    // HI-01 (999.17 gap-closure): snapshot the prior terrain_config alongside
    // previousLayers so the onError rollback can restore it. Without this, an
    // optimistic terrain clear that is followed by a failed delete leaves the DEM
    // layer restored but 3D terrain silently disabled (layers <-> terrain drift).
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

    // WR-01 (Phase 1050-rev): imperatively clean per-layer companions
    // BEFORE the mutation so the visual artifacts (outline/label/extrusion/
    // arrow/cluster glyphs) disappear in lockstep with the user action.
    // Deduped sources are left in place for the next syncFromState to prune
    // via the reference-count-aware desired-set logic.
    removePerLayerCompanions(mapInstanceRef.current, [layerId]);
    removeLayerMutation.mutate(
      { mapId, layerId },
      {
        onSuccess: () => {
          // Sync baseline so a subsequent React-Query refetch is not blocked
          // by a stale savedLayerBaselineRef (CR-01 from handleBulkDelete).
          savedLayerBaselineRef.current = savedLayerBaselineRef.current.filter(
            (l) => l.id !== layerId,
          );
          // fix(#1778): prune the SAVE-diff baseline too. It only refreshes
          // while the map is clean, so a delete on an already-dirty map used to
          // leave this id behind and the next save's diff.removed named a row
          // the server had already dropped, a 400 the client then misread.
          saveBaselineSyncRef.current?.remove([layerId]);
          toast.success(t('toasts.layerRemoved'));
        },
        onError: () => {
          // Rollback: re-insert the failed layer so the user sees it reappear.
          // fix(v1.6.0 audit B6): NOT a wholesale previousLayers write — a
          // concurrent edit (e.g. handleAddDataset onSuccess landing while the
          // DELETE was in flight) must survive the rollback, otherwise the next
          // save diff would ask the server to DELETE the just-added layer.
          setLocalLayers((current) =>
            restoreFailedLayers(current, previousLayers, new Set([layerId])),
          );
          // HI-01: also restore terrain_config if the optimistic delete cleared it,
          // so a failed delete does not leave terrain silently disabled.
          if (clearedTerrainOnRemove) {
            setLocalTerrainConfig(previousTerrainConfig);
          }
          toast.error(t('toasts.layerRemoveFailed'));
        },
      },
    );
  }, [mapId, mapInstanceRef, removeLayerMutation, localTerrainConfig, saveBaselineSyncRef, t]);

  const handleAddDataset = useCallback(
    (
      datasetId: string,
      onSuccessCb?: (newLayerId: string) => void,
      parentGroupId?: string | null,
      datasetName?: string,
    ) => {
      if (!mapId) return;
      // Per BSR-18 UI-SPEC §4b: new layers PREPEND at top of user stack (sort_order: 0).
      // The mutation onSuccess refresh (via React Query invalidation elsewhere) will
      // renumber existing layers as needed. Do NOT use layersRef.current.length here
      // (append) — that buries the new layer under existing ones and conflicts with
      // the auto-open flyout UX.
      addLayerMutation.mutate(
        { mapId, data: { dataset_id: datasetId, sort_order: 0 } },
        {
          onSuccess: (createdLayer) => {
            // P1-08: optimistically merge EVERY created layer into localLayers +
            // the saved baseline so it appears immediately, even while the map is
            // dirty — the API-refetch sync (apiLayers effect) is gated on
            // !hasUnsavedChanges, so a non-group add during dirty state otherwise
            // stayed hidden until save/reload and users retried → duplicates.
            // CR-02: dropping onto a folder group is the SAME single insertion,
            // just also stamping parent_group_id so the row renders inside the
            // group immediately.
            if (createdLayer?.id) {
              // fix(#545): the WR-02 dirty-flag below exists because prepending
              // renumbers EXISTING siblings locally (an unpersisted diff). On a
              // fresh map with no other layers there is nothing renumbered — the
              // POST-created layer alone IS the saved state — so marking dirty
              // falsely triggers the unsaved-changes prompt on every new
              // Add-to-Map / chat-created map.
              // fix(#554 codex P2): layersRef is committed via useLayoutEffect, so
              // when two add mutations resolve before React commits (e.g. AI
              // "Accept all" staging several add_layer actions) it is stale-empty
              // for BOTH onSuccess calls, yet the second add renumbers the first.
              // savedLayerBaselineRef is updated synchronously in this callback
              // (below), so it sees layers from earlier same-batch adds; check
              // both refs rather than side-effecting inside the setLocalLayers
              // updater (which must stay pure — StrictMode double-invokes it).
              const hadOtherLayers =
                layersRef.current.some((l) => l.id !== createdLayer.id) ||
                savedLayerBaselineRef.current.some((l) => l.id !== createdLayer.id);
              const insertedLayer: GroupedLayer = parentGroupId
                ? { ...createdLayer, parent_group_id: parentGroupId }
                : { ...createdLayer };
              setLocalLayers((prev) => {
                const existingIdx = prev.findIndex((l) => l.id === createdLayer.id);
                if (existingIdx >= 0) {
                  // Already present (e.g. a refetch landed first) — do not insert a
                  // duplicate. Only stamp group membership when this is a folder
                  // drop and it isn't already set.
                  if (!parentGroupId) return prev;
                  const existing = prev[existingIdx] as GroupedLayer;
                  if (existing.parent_group_id === parentGroupId) return prev;
                  const next = [...prev];
                  next[existingIdx] = { ...existing, parent_group_id: parentGroupId } as MapLayerResponse;
                  return next;
                }

                if (!parentGroupId) {
                  // Prepend at top of the user stack (sort_order 0) then renumber,
                  // matching the sort_order:0 add request above.
                  return [insertedLayer as MapLayerResponse, ...prev].map((l, i) => ({ ...l, sort_order: i }));
                }

                // fix(#392): insert adjacent to the group's
                // existing block instead of at array index 0. hydrateFolderGroupLayers
                // anchors the group row at the position of its FIRST child, so
                // prepending here would drag the whole group to the stack top after a
                // save/reload round-trip. Insert immediately after the group's LAST
                // existing child (or immediately after the group row itself when it
                // has no children yet) so the first child's position never moves. (audit B-004c/LM-03)
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
              // Keep the saved baseline in sync (mirrors handleDuplicateRendering)
              // so a later clean refetch is not blocked by a stale baseline. The
              // baseline carries the pure server layer (no parent_group_id, which
              // is unsaved frontend state). Unrelated dirty edits are untouched.
              if (!savedLayerBaselineRef.current.some((l) => l.id === createdLayer.id)) {
                savedLayerBaselineRef.current = [createdLayer, ...savedLayerBaselineRef.current];
              }
              // fix(#392): also register the pure server layer into the Save-diff baseline so
              // Save doesn't treat this just-created layer as diff.added and PATCH a duplicate.
              saveBaselineSyncRef.current?.add(createdLayer);
              // fix(#392): mark dirty whenever existing siblings were renumbered —
              // the non-grouped branch above renumbers every existing layer's
              // sort_order locally, but the backend does not renumber sibling rows
              // (maps/service_layers.py:106-120), so that renumber is an
              // unpersisted diff the apiLayers resync effect could otherwise
              // silently clobber before Save. Same defect class as CR-01
              // (handleDuplicateRendering). (audit WR-02)
              // fix(#545): skip when this is the ONLY layer (fresh map) and no
              // group membership was stamped — local state exactly mirrors the
              // server, so the map must stay clean.
              if (hadOtherLayers || parentGroupId) setHasUnsavedChanges(true);
              if (parentGroupId) {
                // Group membership is unsaved frontend state — mark dirty so the
                // save path persists it (and the refetch sync does not wipe it),
                // and auto-expand the group so the child is visible.
                setGroupMeta((prev) =>
                  prev[parentGroupId]?.expanded ? prev : { ...prev, [parentGroupId]: { expanded: true } },
                );
              }
            }
            // Phase 1040 POL-05: named toast when datasetName is provided; generic
            // fallback preserves backward-compat for callers that omit the name.
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
            // Phase 1042 POL-15: entry animation — set freshLayerId for 200ms so
            // StackRow can apply animate-in fade-in. Single-flight: clear any prior
            // timer before scheduling a new one (T-1042-04-03 mitigation).
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
            // fix(#833 codex P2): the analysis add-to-map guard settles in
            // useAddLayer's GLOBAL callbacks (see use-maps.ts) — per-call
            // callbacks here are dropped when a second add overlaps on the
            // shared mutation observer.
            toast.error(t('toasts.layerAddFailed'));
          },
        },
      );
    },
    [mapId, addLayerMutation, t, saveBaselineSyncRef],
  );

  // AI-specific remove: removes locally (persisted on Save).
  //
  // Phase 1050 SF-04: per-layer companion layers (label/outline/extrusion/
  // arrow + main layer-{id}) are still cleaned up imperatively because they
  // remain per-layer in the new keying scheme. Source teardown, however, is
  // delegated to the next `syncFromState` invocation's
  // `removeStaleSourcesAndLayers` desired-set prune — which is reference-
  // count-aware via `desiredSources.add(sourceId)` and will correctly leave
  // a deduped `source-data-${dataset_table_name}` in place while sibling
  // layers still reference it.
  const handleAiRemoveLayer = useCallback((layerId: string) => {
    // fix(#767): prune a group row emptied by this draft removal (same rule as
    // handleRemove — an empty group cannot survive save+reload).
    setLocalLayers((prev) => pruneEmptyFolderGroups(prev.filter((l) => l.id !== layerId)));
    // Clean up MapLibre per-layer companions imperatively. WR-01 (Phase
    // 1050-rev) factored this into removePerLayerCompanions so handleRemove
    // and handleBulkDelete now use the same helper. Sources are NOT
    // removed here — the deduped source may still be shared by sibling
    // layers, and the next syncFromState invocation's desired-set prune
    // correctly removes only truly-orphaned sources.
    removePerLayerCompanions(mapInstanceRef.current, [layerId]);
    setHasUnsavedChanges(true);
  }, [mapInstanceRef]);

  const handleToggleLegend = useCallback((layerId: string) => {
    setLocalLayers((prev) =>
      prev.map((l) =>
        l.id === layerId ? { ...l, show_in_legend: !l.show_in_legend } : l,
      ),
    );
    setHasUnsavedChanges(true);
  }, []);

  const handleDuplicateRendering = useCallback((layerId: string) => {
    if (!mapId) return;
    const layer = layersRef.current.find((candidate) => candidate.id === layerId);
    if (!layer) return;

    // fix(#451): the old D-04 guard that refused to duplicate a
    // render_mode:'terrain' DEM is gone. Under the composable model that mode
    // only means "overlay off" — terrain itself is a single map-level
    // terrain_config pointer, so duplicates can no longer accumulate terrain.

    const currentLayers = layersRef.current;
    const data = buildDuplicateRenderingInput(layer, currentLayers, {
      layerFallback: t('layerMutations.layerFallback', { defaultValue: 'Layer' }),
      duplicateName: (baseName) => t('layerMutations.duplicateName', { name: baseName, defaultValue: '{{name}} rendering' }),
    });
    // fix(#392): carry the source's frontend-only
    // parent_group_id so a duplicate of a grouped layer stays in the group
    // instead of escaping to the stack bottom. MapLayerInput/the API cannot
    // carry this field; it is stamped onto the LOCAL duplicate only. (audit B-004b/LM-02)
    const sourceParentGroupId = (layer as GroupedLayer).parent_group_id ?? null;

    addLayerMutation.mutate(
      { mapId, data },
      {
        onSuccess: (createdLayer) => {
          // STATE-05: the functional updater stays pure — no in-updater
          // `layersRef.current = next` side-write. The useLayoutEffect mirror
          // (lines ~101-103) syncs layersRef from committed state, which is the
          // single, StrictMode-safe place this hook updates the ref.
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
          // Baseline carries the PURE server layer (no parent_group_id, which
          // is unsaved frontend state) — mirrors the handleAddDataset drop path.
          savedLayerBaselineRef.current = [
            ...savedLayerBaselineRef.current.filter((candidate) => candidate.id !== createdLayer.id),
            createdLayer,
          ];
          // fix(#392): also register the pure server layer into the Save-diff baseline so
          // Save doesn't treat this just-created layer as diff.added and PATCH a duplicate.
          saveBaselineSyncRef.current?.add(createdLayer);
          // fix(#392): the splice above always renumbers the FULL local
          // array (adjacent-insert, not append) — this is a real, unpersisted
          // diff for grouped AND non-grouped duplicates alike. Mark dirty
          // unconditionally so the `!hasUnsavedChanges`-gated apiLayers resync
          // effect (triggered by addLayerMutation's own query invalidation)
          // cannot silently overwrite the adjacent placement with server order
          // before Save runs. (audit CR-01)
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
  }, [addLayerMutation, mapId, t, saveBaselineSyncRef]);

  const markDirty = useCallback(() => setHasUnsavedChanges(true), []);

  // fix(#913 review): the opaque flag is only for state this hook CANNOT compare
  // against server data — dock notes and plugin toggles live outside it. Marking
  // re-derivable edits (map name, description, basemap) opaque made the unsaved
  // indicator unclearable for the rest of the session once any of them was
  // touched, even after the value was put back.
  const markOpaqueDirty = useCallback(() => {
    opaqueDirtyRef.current = true;
    setHasUnsavedChanges(true);
  }, []);

  // fix(#913): a banner Revert restores the saved layer through the ordinary
  // mutation handlers, and every one of those marks the map dirty — so the
  // revert itself re-dirtied the map and nothing ever cleared the flag. Rather
  // than special-casing the revert path, recompute: clear the flag only when
  // every layer matches the saved baseline AND no map-level field diverges from
  // server state. Comparing the full layer objects (not just paint/layout/
  // style_config, which is all hasUnsavedStyleChanges covers) is what keeps an
  // outstanding opacity change, reorder, rename, visibility toggle, or layer
  // add/remove from reading as clean.
  const computeMapIsClean = useCallback((): boolean => {
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

    // fix(#913 review): compare the SAVE payload's normalization, not the raw
    // local strings — handleSave persists `localName || undefined`,
    // `localDescription.trim() || null`, and a trimmed-or-null legend title, so
    // an untrimmed local value would otherwise read as permanently dirty.
    if (localName && localName !== mapData.name) return false;
    // Text fields hydrate RAW but save trimmed-or-null, so neither a raw compare
    // nor a trimmed one is right on its own: a raw compare calls an untouched
    // server value with surrounding whitespace dirty forever, while a trimmed
    // compare calls a real user edit (removing that whitespace) clean. Dirty
    // means "saving would change the stored value": identical text is clean, and
    // so is any pair that both persist as null.
    if (!sameSavedText(localDescription, mapData.description)) return false;
    if (!sameSavedText(localLegendTitle, mapData.legend_title)) return false;
    if (localBasemap !== resolveBasemapId(mapData.basemap_style || 'positron')) return false;
    if (showBasemapLabels !== (mapData.show_basemap_labels ?? true)) return false;
    if (!deepEqual(basemapConfig, mapData.basemap_config ?? null)) return false;
    if (!deepEqual(localTerrainConfig, savedTerrainConfig(mapData))) return false;
    // fix(#1854): every save rewrites center/zoom/bearing/pitch from the live
    // map, so an unsaved pan is a real pending change to the stored view. Only
    // compared once the map has a stored view of its own: a map that has none
    // opens at the world default, which no save-time camera would match, and
    // every new map would read dirty before the user touched anything.
    if (liveCamera && hasSavedMapCamera(mapData)
      && !sameMapCamera(liveCamera, savedMapCamera(mapData))) return false;

    // fix(#913 review): folder expansion is persisted (prepareLayersForPersistence
    // reads groupMeta), and handleToggleGroupExpand marks the map dirty — without
    // this an expand-then-revert reported clean and the expansion was lost.
    // Compare ONLY persisted folder rows: the basemap row also writes a groupMeta
    // entry, deliberately without dirtying (it has no persisted carrier), so a
    // whole-object compare could never match and would pin the flag on.
    const savedMeta = savedGroupMeta(mapData);
    for (const layer of current) {
      if (!isFolderGroupLayer(layer)) continue;
      if ((groupMeta[layer.id]?.expanded ?? false) !== (savedMeta[layer.id]?.expanded ?? false)) return false;
    }

    return true;
  }, [
    mapData, localName, localDescription, localLegendTitle, localBasemap,
    showBasemapLabels, basemapConfig, localTerrainConfig, groupMeta, liveCamera,
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
  // fix(#913 review): a request stays pending until it actually finds the map
  // clean, and re-runs whenever the saved baselines it compares against change.
  // A save invalidates the map-detail query, so a revert racing the refetch used
  // to compare against stale server data, fail once, and never retry.
  useEffect(() => {
    if (recheckNonce === 0 || !recheckPendingRef.current) return;
    if (!computeMapIsClean()) return;
    recheckPendingRef.current = false;
    setHasUnsavedChanges(false);
  }, [recheckNonce, computeMapIsClean]);

  // fix(#1854): moveend is the canonical "the camera settled" signal. It fires
  // once per gesture rather than per frame, so no debounce of our own is
  // needed. Reads through the reactive mapInstance because a ref flipping
  // non-null does not re-run an effect.
  useEffect(() => {
    const map = mapInstance ?? mapInstanceRef.current;
    // Partial map doubles in sibling suites carry no event emitter; without a
    // moveend there is simply no camera signal, exactly as before this fix.
    if (!map || typeof map.on !== 'function') return;
    const handleMoveEnd = () => setLiveCamera(readMapCamera(map));
    map.on('moveend', handleMoveEnd);
    return () => { map.off?.('moveend', handleMoveEnd); };
  }, [mapInstance, mapInstanceRef]);

  // fix(#1854): a pan away from the stored view is unsaved work (the navigation
  // blocker and beforeunload both read hasUnsavedChanges); a pan back to it asks
  // for the ordinary recheck, which clears the flag only if nothing else is
  // outstanding.
  useEffect(() => {
    if (!liveCamera || !mapData || !hasSavedMapCamera(mapData)) return;
    if (sameMapCamera(liveCamera, savedMapCamera(mapData))) {
      requestCleanRecheck();
      return;
    }
    setHasUnsavedChanges(true);
  }, [liveCamera, mapData, requestCleanRecheck]);

  // fix(v1.6.0 audit D7): identity-stable "is this row a folder group?" lookup.
  // Reads through layersRef so callers (MapBuilderPage's memoized
  // onToggleVisibility) do not have to depend on localLayers — a naive
  // useCallback over localLayers re-creates on exactly the frames the row
  // memoization is meant to skip.
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

  // Atomic multi-field restore for chat undo. Restoring a snapshot field-by-field
  // through the individual dispatch handlers clobbered earlier restores: each
  // handler rebuilds the layer from `layersRef.current`, which only refreshes
  // between renders, so successive synchronous spreads re-stamp stale values and
  // silently drop the label/paint reverts (the undo-does-nothing bug). Replacing
  // every snapshotted layer wholesale in ONE setState avoids the clobber; the map
  // reconciles via BuilderMap's declarative syncLayersToMap effect (which adds /
  // updates / removes the companion label layer to match the restored state).
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
    onRestoreLayers: handleRestoreLayers,
  }), [dispatchLayerAction, handleRestoreLayers]);

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
    handleRenderModeChange,
    handleLayoutChange,
    handleZoomToLayer,
    // ENH-02/ENH-03 (Phase 1201-01): style clipboard
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
    // Bulk operation handlers (Phase 1041 Plan 03)
    handleBulkVisibility,
    handleBulkOpacity,
    handleBulkGroup,
    handleBulkUngroup,
    handleBulkDelete,
    // Phase 1047-04 (PERF-03): in-flight state for BulkActionBar spinner
    isDeleting,
    // fix(v1.6.0 audit A5): in-flight batch size for the BulkActionBar label
    deletingCount,
    // fix(v1.6.0 audit D7): stable ref-reading predicate so MapBuilderPage's
    // onToggleVisibility callback does not re-create on every layer change.
    isFolderGroupRow,
  };
}
