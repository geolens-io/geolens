import { lazy, Suspense, useState, useEffect, useRef, useCallback, useMemo, type ReactNode } from 'react';
import { useParams, Link, useSearchParams } from 'react-router';
import { useTranslation } from 'react-i18next';
import { FileText, History, Sparkles, Info, FlaskConical, Loader2 } from 'lucide-react';
import type { Map as MaplibreMap } from 'maplibre-gl';
import { ApiError } from '@/api/client';
import {
  closestCenter,
  pointerWithin,
  DndContext,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
} from '@dnd-kit/core';
import type {
  Active,
  Announcements,
  DragEndEvent,
  DragOverEvent,
  DragStartEvent,
  ScreenReaderInstructions,
} from '@dnd-kit/core';
import { arrayMove, sortableKeyboardCoordinates } from '@dnd-kit/sortable';
// PERF-06 (Phase 274): lazy-load BuilderMap so map-vendor chunk loads
// only when the builder is about to render (post-data-fetch).
const BuilderMap = lazy(() =>
  import('@/components/builder/BuilderMap').then((m) => ({ default: m.BuilderMap }))
);
import { UnifiedStackPanel } from '@/components/builder/UnifiedStackPanel';
// PERF-05 (Phase 1047 Plan 02): lazy-load editor scenes so they only ship in their own
// chunks and are fetched only when the user opens the corresponding scene panel.
const DEMEditorScene = lazy(() =>
  import('@/components/builder/DEMEditorScene').then((m) => ({ default: m.DEMEditorScene }))
);
const SettingsEditorScene = lazy(() =>
  import('@/components/builder/SettingsEditorScene').then((m) => ({ default: m.SettingsEditorScene }))
);
const BasemapGroupEditorScene = lazy(() =>
  import('@/components/builder/BasemapGroupEditorScene').then((m) => ({ default: m.BasemapGroupEditorScene }))
);
const BasemapGroupEditorFooter = lazy(() =>
  import('@/components/builder/BasemapGroupEditorScene').then((m) => ({ default: m.BasemapGroupEditorFooter }))
);
const BasemapSublayerEditorScene = lazy(() =>
  import('@/components/builder/BasemapSublayerEditorScene').then((m) => ({ default: m.BasemapSublayerEditorScene }))
);
const BasemapSublayerEditorFooter = lazy(() =>
  import('@/components/builder/BasemapSublayerEditorScene').then((m) => ({ default: m.BasemapSublayerEditorFooter }))
);
import { useBasemaps } from '@/hooks/use-settings';
import {
  basemapThumbnail,
  BLANK_BASEMAP_ID,
} from '@/lib/basemap-utils';
import type { MapLayerResponse, MapSublayerOverride } from '@/types/api';
import { isFolderGroupLayer } from '@/lib/layer-capabilities';
import { clearPersistedFolderGroup, getParentGroupId, resolveDropGroupMembership } from '@/components/builder/folder-groups';
import { SidebarRail } from '@/components/builder/SidebarRail';
import { LayerEditorPanel, type LayerEditorHandlers } from '@/components/builder/LayerEditorPanel';
import { EphemeralBadge } from '@/components/builder/EphemeralBadge';
import { previewSaveMode } from '@/components/builder/ephemeral-preview';
// feat(#1241): only mounted while the save dialog is open, and it pulls in the
// import page's metadata form — lazy so the builder's initial chunk is unchanged.
const SaveChatPreviewDialog = lazy(() =>
  import('@/components/builder/SaveChatPreviewDialog').then((m) => ({ default: m.SaveChatPreviewDialog }))
);
import { MapToolbar } from '@/components/builder/MapToolbar';
import { MapTitleBar } from '@/components/builder/MapTitleBar';
import { BuilderRail, type RailPanel } from '@/components/builder/BuilderRail';
import { BuilderDialogs } from '@/components/builder/BuilderDialogs';
const StyleJsonDialog = lazy(() =>
  import('@/components/builder/StyleJsonDialog').then((m) => ({ default: m.StyleJsonDialog }))
);
import { KeyboardShortcutsSheet } from '@/components/builder/KeyboardShortcutsSheet';
import { ActiveFilterChips } from '@/components/builder/ActiveFilterChips';
import { computeNextSelection, computeSelectableRowIds } from '@/components/builder/selection-utils';
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from '@/components/ui/sheet';
import { cn } from '@/lib/utils';
import { MAP_COLORS } from '@/lib/map-colors';
import { SceneSpinnerFallback } from '@/components/builder/SceneSpinnerFallback';
import { LoadingState } from '@/components/layout/LoadingState';
import { ErrorState } from '@/components/layout/ErrorState';
import { MapErrorBoundary, PanelErrorBoundary } from '@/components/error';
import { LazyLoadErrorBoundary } from '@/components/error/LazyLoadErrorBoundary';
import { useMap, useAddLayer, useRemoveLayer } from '@/hooks/use-maps';
import { useAIAvailability } from '@/hooks/use-ai-availability';
import { usePermissions } from '@/hooks/use-permissions';
import { useDocumentTitle } from '@/hooks/use-document-title';
import { useEnabledPlugins } from '@/hooks/use-settings';
import { useBuilderLayout } from '@/components/builder/hooks/use-builder-layout';
import { useBuilderDialogs } from '@/components/builder/hooks/use-builder-dialogs';
import { useBuilderEditorScene, type BuilderEditorScene } from '@/components/builder/hooks/use-builder-editor-scene';
import { useFilteredFeatureCount } from '@/components/builder/hooks/use-filtered-feature-count';
import { useBuilderLayers } from '@/components/builder/hooks/use-builder-layers';
import { useBuilderSave, type SaveBaselineSync } from '@/components/builder/hooks/use-builder-save';
import { TERRAIN_SOURCE_ID, normalizeTerrainExaggeration, isHillshadeTerrainBound } from '@/components/builder/map-sync';
import { resolveTerrainSourceLayer } from '@/components/builder/map-stack';
import { effectiveDemRenderMode } from '@/lib/dem-render-mode';
import {
  createBuilderBasemapState,
  hasCustomBasemapAppearance,
  removeBasemap as removeBasemapFromState,
  resetBasemapAppearance,
  resetBasemapSublayer,
  setBasemapBackgroundColor,
  setBasemapMasterOpacity,
  setBasemapPosition,
  setBasemapProjection,
  setBasemapSublayerOpacity,
  SUBLAYER_ID_OVERRIDE_KEY,
  swapBasemapPreset,
  toggleBasemapSublayerVisibility,
  updateBasemapSublayerOverride,
  type BuilderBasemapPatch,
} from '@/components/builder/basemap-state-controller';
import { PluginHost, PluginSidebar, getDefaultPluginIds, resolveAvailablePluginIds, usePartitionedPlugins } from '@/components/map-plugins';
import { usePluginStore } from '@/stores/map-plugin-store';
import type { ViewportContext } from '@/components/builder/chat-suggestions';
import type { EphemeralAnalysisHandoff } from '@/components/builder/hooks/use-ephemeral-layers';
import { readStorage, removeStorage, storageKeys } from '@/lib/storage';
import { analysisAddToMap, useAnalysisJobStore } from '@/stores/analysis-job-store';
import { takeChatResult } from '@/lib/chat-result-handoff';

export function MapBuilderPage() {
  const { id } = useParams<{ id: string }>();
  // POLISH-01 (Phase 1233-01): detect the ?add_dataset path so useBuilderSave
  // can defer the first auto-capture until the layer-add effect has synced.
  // use-builder-layers DELETES the param once processed, so reading it
  // reactively can flip to false before the capture path runs (WR-01). Freeze
  // the mount-time value in a ref so the deferred path is honored regardless of
  // whether the API or the canvas init wins the race.
  const [searchParams, setSearchParams] = useSearchParams();
  const pendingLayerAddRef = useRef(searchParams.has('add_dataset'));
  const pendingLayerAdd = pendingLayerAddRef.current;
  const { t } = useTranslation('builder');
  const { data: mapData, isLoading, error } = useMap(id, { refetchOnWindowFocus: false });
  const enabledPluginsQuery = useEnabledPlugins();
  const enabledPluginIds = useMemo(
    () => enabledPluginsQuery.data ?? (enabledPluginsQuery.isLoading ? [] : null),
    [enabledPluginsQuery.data, enabledPluginsQuery.isLoading],
  );
  const addLayer = useAddLayer();
  const removeLayer = useRemoveLayer();

  const { isAIAvailable: aiAvailable } = useAIAvailability();
  // feat(#1241): saving a chat preview creates a dataset through POST
  // /ingest/*, which needs the caller's own `upload` capability. The map's edit
  // rights say nothing about it. can() is false while the query is in flight,
  // which is the safe way round: the affordance appears once the capability is
  // known rather than 403ing after the user has named a dataset.
  //
  // feat(#1241 codex r2): `export` as well. The snapshot hands the caller a
  // durable, caller-owned copy of source attributes they may only be able to
  // READ, which is exactly why analysis materialize requires both (fix(#692),
  // `require_permission("upload", "export")` in
  // backend/app/modules/catalog/datasets/api/router_analysis.py). The ingest
  // endpoints ask only for `upload` because their file normally comes from the
  // caller's own machine; this one's does not, so the client must not offer a
  // path around that boundary under a customized role matrix.
  const { can } = usePermissions();
  const canSaveDataset = can('upload') && can('export');
  useDocumentTitle(mapData?.name ?? t('common:pageTitle.mapBuilder'));

  // Three-column layout: isRail (sidebar→64px at <1100px), isEditorHidden (flyout hidden at <800px)
  const { isRail, isEditorHidden, isMobile } = useBuilderLayout();

  const mapInstanceRef = useRef<MaplibreMap | null>(null);
  // mapInstance state duplicates the ref — needed to trigger re-renders for
  // pluginCtx useMemo. The ref provides stable imperative access without re-renders.
  const [mapInstance, setMapInstance] = useState<MaplibreMap | null>(null);
  const [railPanel, setRailPanel] = useState<RailPanel>(null);
  // feat(#675): chat run_analysis preview → Analysis panel handoff. The nonce
  // keys a panel remount so successive handoffs re-apply the prefill.
  const [analysisPrefill, setAnalysisPrefill] = useState<
    (EphemeralAnalysisHandoff & { nonce: number }) | null
  >(null);
  const [dockNotes, setDockNotes] = useState('');
  // Projection (Mercator/Globe). Persisted on basemap_config.projection; seeded from
  // the saved map on load and applied to the live map once it's ready (effects below).
  const [localProjection, setLocalProjection] = useState<'mercator' | 'globe'>('mercator');
  const [showStyleJson, setShowStyleJson] = useState(false);
  const [showShortcuts, setShowShortcuts] = useState(false);
  // Phase 1199 STACK-02: session-local basemap visibility toggle. Client-only and
  // intentionally NOT persisted to MapBasemapConfig — a backend field is deferred to
  // GUARD-02/Phase 1203 to avoid the extra=forbid silent-422 class. Hiding is applied
  // by rendering BLANK_BASEMAP_ID in the live map (BuilderMap's isBlank branch) while
  // the stack row's preset name still derives from the real basemap style.
  const [basemapVisible, setBasemapVisible] = useState(true);
  // Phase 1135 AI-05: debounced viewport context for viewport-aware suggestion chips.
  // Updated on map idle (500ms debounce) and when the selected layer changes.
  const [viewport, setViewport] = useState<ViewportContext | undefined>(undefined);

  // Phase 1040: Lifted DnD state — single DndContext wraps both the sidebar stack
  // (UnifiedStackPanel) and the Add Dataset modal (BuilderDialogs) so catalog→stack
  // cross-panel drag is possible. Without this, @dnd-kit collision detection only
  // fires within one DndContext and cross-panel isOver events never fire.
  const [dragActiveId, setDragActiveId] = useState<string | null>(null);

  // Phase 1041: Multi-selection state lifted to MapBuilderPage so handleDragStart
  // can clear it directly (drag + multi-select are mutually exclusive). This mirrors
  // the Phase 1040 lift-DndContext architecture decision.
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const lastToggleAnchor = useRef<string | null>(null);
  // fix(#833): selected rows the layer search hides are parked here instead of
  // being pruned outright, and rejoin the selection when the search stops
  // hiding them. Cleared on every explicit selection interaction — Escape/
  // outside click, drag-start, bulk actions, and (codex round 2) cmd/shift
  // clicks, which replace the selection — so stale parked rows cannot
  // resurrect a selection the user's gesture already discarded.
  const searchHiddenSelectionRef = useRef<Set<string>>(new Set());
  // fix(#771): the layer-search query is lifted here (hybrid-controlled on
  // UnifiedStackPanel) so selectableRowIds below can be derived from the
  // RENDERED row set — a shift-click range must never sweep rows the search
  // has filtered out or that live inside a collapsed group.
  const [layerSearch, setLayerSearch] = useState('');

  // Phase 1040 Plan 04: aria-live announcement for keyboard/mouse catalog drag (T-1040-10 / POL-05).
  // A sr-only region reads these strings to screen-reader users. We append a zero-width-space
  // + timestamp suffix to force aria-live re-fire when the same message is announced twice
  // (e.g. two consecutive "Drop cancelled." calls without an intermediate different message).
  const [dragAnnouncement, setDragAnnouncement] = useState('');
  const lastOverIdRef = useRef<string | null>(null);

  const announce = useCallback((text: string) => {
    // appends zero-width space to forces aria-live re-fire for identical consecutive strings
    setDragAnnouncement(text + '\u200B' + Date.now());
  }, []);
  const dndSensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: {
        distance: 8, // px — drag only after moving >= 8px from pointerdown origin (T-1040-01)
      },
    }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    }),
  );

  // Initialize notes from server data, falling back to localStorage only for
  // legacy responses that predate the server-backed notes field.
  useEffect(() => {
    if (!mapData) return;
    const hasServerNotes = Object.prototype.hasOwnProperty.call(mapData, 'notes') && mapData.notes !== undefined;
    if (hasServerNotes) {
      setDockNotes(mapData.notes ?? '');
      // fix(#438): ARC-06 — key + access via the typed storage helper.
      removeStorage(storageKeys.mapNotes(id ?? ''));
    } else {
      setDockNotes(readStorage(storageKeys.mapNotes(id ?? '')) ?? '');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- run once when mapData loads
  }, [mapData?.notes, id]);

  // Composed hooks
  const dialogs = useBuilderDialogs();
  // fix(#392): callback ref bridging useBuilderLayers (rendered first, below)
  // to useBuilderSave (rendered after it, at ~line 281+7). useBuilderSave
  // populates this with a function that registers a server-created layer into
  // the Save-diff baseline; useBuilderLayers' handleAddDataset /
  // handleDuplicateRendering invoke it right after a layer-create mutation
  // succeeds, so Save never re-diffs that layer as `added` and PATCHes a
  // duplicate. See use-builder-save.ts for the full rationale.
  const saveBaselineSyncRef = useRef<SaveBaselineSync>({ add: () => {}, remove: () => {} });
  const layers = useBuilderLayers(
    mapData,
    mapInstanceRef,
    id,
    addLayer,
    removeLayer,
    saveBaselineSyncRef,
  );
  const {
    handleBulkVisibility: applyBulkVisibility,
    handleBulkOpacity: applyBulkOpacity,
    handleBulkGroup: applyBulkGroup,
    handleBulkUngroup: applyBulkUngroup,
    handleBulkDelete: applyBulkDelete,
    handleBulkApplyStyle: applyBulkApplyStyle,
    setLocalBasemap,
    setShowBasemapLabels,
    setBasemapConfig,
    setLocalTerrainConfig,
    dispatchLayerAction,
    handleTabChange,
    handleRenderModeChange,
  } = layers;
  const basemapState = useMemo(
    () => createBuilderBasemapState({
      basemapStyle: layers.localBasemap,
      showBasemapLabels: layers.showBasemapLabels,
      basemapConfig: layers.basemapConfig,
      terrainConfig: layers.localTerrainConfig,
    }, t),
    [layers.localBasemap, layers.showBasemapLabels, layers.basemapConfig, layers.localTerrainConfig, t],
  );
  const applyBasemapPatch = useCallback(
    (patch: BuilderBasemapPatch) => {
      if (patch.basemapStyle !== undefined) setLocalBasemap(patch.basemapStyle);
      if (patch.showBasemapLabels !== undefined) setShowBasemapLabels(patch.showBasemapLabels);
      if (patch.basemapConfig !== undefined) setBasemapConfig(patch.basemapConfig);
      if (patch.terrainConfig !== undefined) setLocalTerrainConfig(patch.terrainConfig);
    },
    [setBasemapConfig, setLocalBasemap, setLocalTerrainConfig, setShowBasemapLabels],
  );
  // Phase 1199 STACK-02: session-local show/hide of the basemap. Toggles the live
  // map between the real basemap style and BLANK_BASEMAP_ID; not persisted.
  const handleToggleBasemapVisibility = useCallback(
    () => setBasemapVisible((v) => !v),
    [],
  );
  // Phase 276 CODE-12: hand-rolled string keys are intentional value-equality
  // dependencies. mapData refetches (TanStack Query refetchOnReconnect /
  // refetchOnMount / window-focus invalidations) produce shape-equivalent
  // but identity-different plugin arrays — declaring `[mapData?.plugins,
  // enabledPluginIds]` directly as deps would reset the user's local plugin
  // toggles on every background refetch. Coercing the deps to stable JSON
  // strings (savedPluginKey) and a NUL-joined ID list (enabledPluginKey)
  // gives the useEffect value-equality semantics, which is what we actually
  // want for "restore plugins when the saved set or admin allowlist
  // changes".
  //
  // If a future author "simplifies" this back to raw object/array deps,
  // local plugin toggle state will silently regress on every refetch.
  // Verify with the map-builder UAT in Plan 276-05: open builder, toggle a
  // plugin OFF, trigger a refetch (Cmd-R / window focus / queryClient
  // invalidateQueries), confirm the toggle stays OFF.
  const savedPluginKey = mapData ? `${mapData.id}:${JSON.stringify(mapData.plugins ?? null)}` : '';
  const enabledPluginKey = enabledPluginIds == null ? '__all__' : enabledPluginIds.join('\0');

  // Restore active plugins from the saved map payload. `null` means client defaults,
  // `[]` means no plugins, and unknown or admin-disabled IDs are ignored.
  useEffect(() => {
    if (!mapData) return;
    const nextPlugins = mapData.plugins == null
      ? getDefaultPluginIds(enabledPluginIds)
      : resolveAvailablePluginIds(mapData.plugins, enabledPluginIds);
    usePluginStore.getState().replace(nextPlugins);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- see Phase 276 CODE-12 block comment above
  }, [savedPluginKey, enabledPluginKey]);

  const save = useBuilderSave({
    mapId: id,
    localLayers: layers.localLayers,
    groupMeta: layers.groupMeta,
    localBasemap: basemapState.basemapStyle,
    showBasemapLabels: basemapState.showBasemapLabels,
    basemapConfig: basemapState.config,
    terrainConfig: basemapState.terrainConfig,
    localName: layers.localName,
    localDescription: layers.localDescription,
    legendTitle: layers.localLegendTitle,
    dockNotes,
    mapInstanceRef,
    setHasUnsavedChanges: layers.setHasUnsavedChanges,
    hasUnsavedChanges: layers.hasUnsavedChanges,
    hasThumbnail: !!mapData?.thumbnail_url,
    pendingLayerAdd,
    saveBaselineSyncRef,
  });

  const handleMapRef = useCallback((map: MaplibreMap | null) => {
    mapInstanceRef.current = map;
    setMapInstance(map);
    if (map) save.maybeAutoCaptureThumbnail(map);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only the method reference matters, not the whole `save` object
  }, [save.maybeAutoCaptureThumbnail]);

  // feat(#531 follow-up): ?chat_result=1 — DatasetChatPanel stashed its last
  // spatial query result in sessionStorage before navigating here; render it
  // through the ephemeral-layer path. Gated on mapInstance (not mapData) so
  // the ephemeral effect never fires against a null map ref.
  const handleChatQueryResult = layers.handleQueryResult;
  useEffect(() => {
    if (!mapInstance || !searchParams.has('chat_result')) return;
    setSearchParams((prev) => {
      prev.delete('chat_result');
      return prev;
    }, { replace: true });
    const result = takeChatResult();
    // feat(#1241 codex r1): forward everything the stash carries, not just the
    // geometry. Without the completeness pair a clipped carried result reads as
    // a complete one here, and the save this issue adds would persist it as the
    // whole answer.
    if (result) {
      handleChatQueryResult(result.geojson, result.bbox, {
        ...(result.truncated ? { truncated: true } : {}),
        ...(result.totalCount != null ? { totalCount: result.totalCount } : {}),
        ...(result.prompt ? { prompt: result.prompt } : {}),
      });
    }
  }, [mapInstance, searchParams, setSearchParams, handleChatQueryResult]);

  const pluginCtx = useMemo(
    () => ({
      mapInstance,
      layers: layers.localLayers,
      mapId: id!,
      terrainConfig: layers.localTerrainConfig,
      // ENH-06: map-level legend title + persistence callbacks for the
      // LegendPlugin edit affordance.
      legendTitle: layers.localLegendTitle,
      onLegendTitleChange: layers.handleLegendTitleChange,
      onLegendLabelChange: layers.handleLegendLabelChange,
    }),
    [
      mapInstance,
      layers.localLayers,
      id,
      layers.localTerrainConfig,
      layers.localLegendTitle,
      layers.handleLegendTitleChange,
      layers.handleLegendLabelChange,
    ],
  );

  // Phase 1135 AI-05: subscribe to map idle events with 500ms debounce to update
  // viewport context for suggestion chips. Unsubscribes when mapInstance changes.
  useEffect(() => {
    if (!mapInstance) return;
    let debounceTimer: ReturnType<typeof setTimeout> | null = null;
    const handler = () => {
      if (debounceTimer !== null) clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => {
        const zoom = mapInstance.getZoom();
        const bounds = mapInstance.getBounds();
        setViewport((prev) => ({
          zoom,
          bounds: [bounds.getWest(), bounds.getSouth(), bounds.getEast(), bounds.getNorth()],
          selectedLayerName: prev?.selectedLayerName,
        }));
      }, 500);
    };
    mapInstance.on('idle', handler);
    return () => {
      if (debounceTimer !== null) clearTimeout(debounceTimer);
      mapInstance.off('idle', handler);
    };
  }, [mapInstance]);

  // Phase 1135 AI-05: sync selectedLayerName from expandedLayerId into viewport context.
  useEffect(() => {
    setViewport((prev) => {
      const expanded = layers.expandedLayerId;
      if (!expanded) {
        if (!prev) return prev;
        return { ...prev, selectedLayerName: undefined };
      }
      const layer = layers.localLayers.find((l) => l.id === expanded);
      const name = layer ? (layer.display_name ?? layer.dataset_name) : undefined;
      if (!prev) {
        // Camera state not yet settled — skip; the idle handler will fold this in next idle.
        return prev;
      }
      if (prev.selectedLayerName === name) return prev;
      return { ...prev, selectedLayerName: name };
    });
  }, [layers.expandedLayerId, layers.localLayers]);

  const { byAnchor, sidebar: sidebarPlugins } = usePartitionedPlugins();
  // activePlugins for Settings panel plugin toggles (Phase 1036)
  const activePlugins = usePluginStore((state) => state.activePlugins);
  const togglePlugin = usePluginStore((state) => state.toggle);

  const layerEditorHandlers = useMemo((): LayerEditorHandlers => ({
    onTabChange: handleTabChange,
    onPaintChange: (layerId, paint) => dispatchLayerAction({
      type: 'set_paint',
      source: 'manual',
      layerId,
      paint,
    }),
    onOpacityChange: (layerId, opacity) => dispatchLayerAction({
      type: 'set_opacity',
      source: 'manual',
      layerId,
      opacity,
    }),
    onFilterChange: (layerId, expression) => dispatchLayerAction({
      type: 'set_filter',
      source: 'manual',
      layerId,
      expression,
    }),
    onLabelChange: (layerId, config) => dispatchLayerAction({
      type: 'set_label',
      source: 'manual',
      layerId,
      config,
    }),
    onPopupChange: (layerId, config) => dispatchLayerAction({
      type: 'set_popup',
      source: 'manual',
      layerId,
      config,
    }),
    onStyleConfigChange: (layerId, config, paint, opts) => dispatchLayerAction({
      type: 'set_style_config',
      source: 'manual',
      layerId,
      config,
      paint,
      replace: opts?.replace,
    }),
    onLayoutChange: (layerId, layout) => dispatchLayerAction({
      type: 'set_layout',
      source: 'manual',
      layerId,
      layout,
    }),
    onRenderModeChange: handleRenderModeChange,
    onRemove: (layerId) => dispatchLayerAction({
      type: 'remove_layer',
      source: 'manual',
      layerId,
      persistence: 'server',
    }),
    // fix(#913): the revert routes through the mutation handlers above, so the
    // map is re-marked dirty on the way back to its saved state. Ask the
    // baseline owner to re-derive; it clears only when the WHOLE map is clean.
    onRevertToSaved: layers.requestCleanRecheck,
  }), [dispatchLayerAction, handleRenderModeChange, handleTabChange, layers.requestCleanRecheck]);

  // fix(#913 review): the dock's notes live in page state the layers hook cannot
  // compare against server data, so this is the OPAQUE marker. Controls whose
  // fields the hook does compare (map name/description via MapTitleBar, basemap
  // swap/remove) use the plain markDirty instead.
  const handleMarkDirty = layers.markOpaqueDirty;

  // Plugin toggles live in a store outside the layer state that drives
  // hasUnsavedChanges, so wrap the toggle to mark the map dirty — otherwise the
  // save indicator + unsaved-changes nav guard miss plugin-only edits. The save
  // payload already reads the store at save time (resolvePluginsPayload).
  const handleTogglePlugin = useCallback(
    (pluginId: string) => {
      togglePlugin(pluginId);
      // Plugin state lives in its own store — not re-derivable here.
      layers.markOpaqueDirty();
    },
    [togglePlugin, layers],
  );

  // Projection persists on basemap_config.projection. Route through the basemap
  // patch (which marks the map dirty), update local state, and apply to the live
  // map. setProjection is guarded for test envs / older maplibre.
  const handleSetProjection = useCallback(
    (proj: 'mercator' | 'globe') => {
      setLocalProjection(proj);
      applyBasemapPatch(setBasemapProjection(basemapState, proj));
      try {
        mapInstanceRef.current?.setProjection?.({ type: proj });
      } catch {
        // setProjection may not exist in test envs / older maplibre — swallow safely
      }
    },
    [applyBasemapPatch, basemapState],
  );

  // Seed projection from the saved map. Keyed on the saved value so background
  // refetches don't clobber an unsaved local projection change (the value only
  // changes when the persisted projection does).
  const savedProjection = mapData?.basemap_config?.projection ?? 'mercator';
  useEffect(() => {
    setLocalProjection(savedProjection);
  }, [savedProjection]);

  // Apply projection to the live map once it's ready (and on map swap). Globe
  // requires a loaded style, so gate on isStyleLoaded with an idle fallback.
  useEffect(() => {
    if (!mapInstance) return;
    const apply = () => {
      try {
        mapInstance.setProjection?.({ type: localProjection });
      } catch {
        // older maplibre / test env — swallow safely
      }
    };
    if (mapInstance.isStyleLoaded?.()) apply();
    else mapInstance.once?.('idle', apply);
  }, [mapInstance, localProjection]);

  // A11Y-05 (Phase 1204-03): '?' hotkey opens the keyboard shortcut cheat-sheet.
  // Guarded so it does not fire while the user is typing in an input/textarea/select
  // or a contenteditable field — mirrors the Ctrl/Cmd+S guard in use-builder-save.ts.
  // Also no-ops when a Radix dialog/sheet is already open (same guard pattern).
  useEffect(() => {
    function handleShortcutKeyDown(e: KeyboardEvent) {
      if (e.key !== '?') return;
      const target = e.target as HTMLElement | null;
      if (target) {
        const tag = target.tagName;
        if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
        if (target.isContentEditable) return;
      }
      const dialogOpen = document.querySelector('[role="dialog"][data-state="open"]');
      if (dialogOpen) return;
      setShowShortcuts(true);
    }
    window.addEventListener('keydown', handleShortcutKeyDown);
    return () => window.removeEventListener('keydown', handleShortcutKeyDown);
  }, []);

  // Phase 1035: basemaps data for the BasemapGroupEditorScene preset grid
  // (placed early for useMemo/useState hooks — actual wiring happens after handleSelectLayer)
  const { data: basemaps = [] } = useBasemaps();

  // Phase 1119: basemap group display object derived from the canonical
  // controller state, not runtime-only sublayer state.
  //
  // Bugbash fix: when the basemap is blank ("No basemap"), still return a
  // minimal non-null group so the stack renders a "Basemap · No basemap" row.
  // Without it the row disappears entirely and the preset-picker flyout (which
  // is the only way to choose a real basemap again after the Add-Data Basemap
  // tab was removed) becomes unreachable. The flyout already excludes BLANK from
  // its preset list and its SUBLAYERS section already hides itself when
  // sublayers is empty (BasemapGroupEditorScene WR-02), so an empty-sublayer
  // group renders cleanly and lets the user pick a real preset.
  const basemapGroup = useMemo(() => {
    if (!basemapState.hasVisibleBasemap) {
      return {
        id: 'basemap-group',
        presetName: t('basemapGroup.noBasemap', { defaultValue: 'No basemap' }),
        providerLabel: undefined,
        // Phase 1199 STACK-02: session-local visibility (was hardcoded true).
        visible: basemapVisible,
        opacity: basemapState.config.opacity ?? 1,
        sublayers: [],
        // fix(#585): semantic comparison against the default appearance — the
        // stored config is often a materialized all-defaults object, so a
        // non-null check would read every map as customized.
        hasCustomAppearance: hasCustomBasemapAppearance(layers.basemapConfig, layers.showBasemapLabels),
      };
    }
    // Derive preset name from the basemap id (label portion after last dash, capitalized)
    const presetId = basemapState.basemapStyle;
    const presetName = presetId
      .replace(/^(openfreemap-|carto-|mapbox-|maptiler-|esri-|stamen-|stadia-)/, '')
      .replace(/-/g, ' ')
      .replace(/\b\w/g, (c) => c.toUpperCase()) || t('search.basemap', { defaultValue: 'Basemap' });

    return {
      id: 'basemap-group',
      presetName,
      providerLabel: undefined,
      // Phase 1199 STACK-02: session-local visibility (was hardcoded true).
      visible: basemapVisible,
      opacity: basemapState.config.opacity ?? 1,
      sublayers: basemapState.sublayers,
      // fix(#585): see the no-basemap branch above.
      hasCustomAppearance: hasCustomBasemapAppearance(layers.basemapConfig, layers.showBasemapLabels),
    };
  }, [basemapState, basemapVisible, layers.basemapConfig, layers.showBasemapLabels, t]);

  const isBasemapExpanded = layers.groupMeta?.['basemap-group']?.expanded ?? false;

  const {
    editingLayer,
    editingSavedLayer,
    editorLayer,
    editorScene,
    isEditorOpen,
  } = useBuilderEditorScene({
    expandedLayerId: layers.expandedLayerId,
    localLayers: layers.localLayers,
    savedLayerBaseline: layers.savedLayerBaseline,
    basemapGroup,
    labels: {
      settingsName: t('unifiedStack.settings', { defaultValue: 'Settings' }),
      sublayerFallback: t('basemapSublayer.sublayerFallback', { defaultValue: 'Sublayer' }),
      untitledFallback: t('basemapSublayer.breadcrumbUntitled', { defaultValue: 'Untitled' }),
      basemapGroupName: (presetName) => t('basemapGroup.rowName', { name: presetName, defaultValue: 'Basemap · {{name}}' }),
    },
  });

  // fix(#392): 'group' means the editor is closed (LayerEditorPanel never
  // renders for it — see isEditorOpen above), so LayerEditorPanel's narrower
  // editorScene prop type intentionally excludes it. Derive a panel-safe
  // scene once rather than widening the panel's contract.
  const panelEditorScene: Exclude<BuilderEditorScene, 'group'> =
    editorScene === 'group' ? 'default' : editorScene;

  // EASY-18 (Phase 1138-03): rendered-feature count for the active editing layer.
  // Returns null when no layer is being edited, when no filter is set, or when
  // the layer isn't yet on the map. Used to drive the empty-state hint inside
  // LayerFilterEditor.
  const filteredFeatureCount = useFilteredFeatureCount(mapInstance, editingLayer ?? null);

  // Phase 1041: Boundary guard — true when id belongs to basemap group or its sublayers
  const isBasemapBoundaryId = useCallback((id: string): boolean => {
    if (!basemapGroup) return false;
    if (id === basemapGroup.id) return true;
    return basemapGroup.sublayers.some((s) => s.id === id);
  }, [basemapGroup]);

  // Phase 1041: derive selectable row ids (ordered list, basemap excluded)
  // Used by handleShiftClick for range computation and by the Shift+Arrow keyboard handler.
  // fix(#771): derived from the RENDERED row set (shared helper with
  // UnifiedStackPanel) instead of the raw flat array — the raw list let a
  // shift-click range select children of collapsed groups and rows hidden by
  // the layer search, so bulk delete/visibility/opacity acted on rows the
  // user could not see.
  // fix(HT-03): terrain-mode DEM rows render in the stack again, so they are
  // range-selectable like any other row (the BLDR-03 skip is obsolete).
  const selectableRowIds = useMemo(
    (): string[] => computeSelectableRowIds(layers.localLayers, layers.groupMeta, layerSearch),
    [layers.localLayers, layers.groupMeta, layerSearch],
  );

  // fix(#771): selection ids can outlive their rows — handleRemove,
  // handleDeleteGroup, handleUngroup, and the #767 empty-group prune all
  // remove rows without touching selectedIds, so the bulk bar kept
  // over-reporting counts it could not perform. Prune against the live layer
  // set. Skipped while a bulk delete is in flight: its optimistic removal
  // must not eat the preserved-on-failure selection (a full-failure rollback
  // restores the rows in the same commit that clears isDeleting).
  // fix(v1.6.0 audit B7): also intersect with selectableRowIds — a row hidden
  // by the layer search or a collapsed group must leave the selection, or the
  // bulk bar keeps acting on rows the user can no longer see.
  // fix(#833): rows hidden by the layer search leave the ACTIVE selection (B7
  // stands: the bulk bar must not act on rows the user cannot see) but are
  // parked and rejoin it when they become visible again — hiding used to
  // prune them permanently. Parked rows are restored only once selectable
  // again (search cleared/edited AND not inside a collapsed group); deleted
  // rows are dropped for good. The park/restore bookkeeping lives outside the
  // updater where it must be idempotent (StrictMode double-invokes updaters).
  useEffect(() => {
    if (layers.isDeleting) return;
    const liveIds = new Set(layers.localLayers.map((layer) => layer.id));
    const selectable = new Set(selectableRowIds);
    const parked = searchHiddenSelectionRef.current;
    // fix(#833 codex round 3): park only rows the SEARCH itself hides, not any
    // unselectable row while a search happens to be active — a child hidden by
    // its collapsed group must stay pruned (restoring it on a later expand
    // would resurrect a selection the collapse discarded). Recomputing the
    // selectable set with every group forced expanded isolates the search
    // predicate (computeSelectableRowIds stays the single source of truth):
    // a live row absent from THIS set fails the search; one present here but
    // missing from selectableRowIds is hidden by collapse alone.
    let searchHiddenIds: Set<string> | null = null;
    if (layerSearch.trim() !== '') {
      const allExpanded: Record<string, { expanded: boolean }> = {};
      for (const layer of layers.localLayers) {
        if (isFolderGroupLayer(layer)) allExpanded[layer.id] = { expanded: true };
      }
      const matching = new Set(
        computeSelectableRowIds(layers.localLayers, allExpanded, layerSearch),
      );
      searchHiddenIds = new Set(
        layers.localLayers.filter((layer) => !matching.has(layer.id)).map((layer) => layer.id),
      );
    }
    // fix(#833 codex rounds 5+6): a row stays parked only while it would be
    // selectable the moment the search cleared — the search must be what
    // hides it AND its group must be expanded under the REAL group state. A
    // collapse is a discarding gesture wherever it happens: after parking,
    // while the search is active (even though the force-expanded
    // searchHiddenIds still lists the row), or ordered the other way.
    const selectableWithoutSearch = new Set(
      computeSelectableRowIds(layers.localLayers, layers.groupMeta, ''),
    );
    const restored: string[] = [];
    for (const rowId of Array.from(parked)) {
      if (!liveIds.has(rowId)) { parked.delete(rowId); continue; }
      if (selectable.has(rowId)) { parked.delete(rowId); restored.push(rowId); continue; }
      if (!searchHiddenIds?.has(rowId) || !selectableWithoutSearch.has(rowId)) {
        parked.delete(rowId);
      }
    }
    setSelectedIds((prev) => {
      if (prev.size === 0 && restored.length === 0) return prev;
      let changed = false;
      const next = new Set<string>();
      for (const rowId of prev) {
        if (liveIds.has(rowId) && selectable.has(rowId)) { next.add(rowId); continue; }
        changed = true;
        // Park only live, search-hidden rows (an add-only mutation, safe under
        // a double-invoked updater); rows removed from the map or swallowed by
        // a collapsed group stay pruned for good.
        if (liveIds.has(rowId) && searchHiddenIds?.has(rowId)) parked.add(rowId);
      }
      for (const rowId of restored) {
        if (!next.has(rowId)) { next.add(rowId); changed = true; }
      }
      return changed ? next : prev;
    });
  }, [layers.localLayers, layers.groupMeta, layers.isDeleting, selectableRowIds, layerSearch]);

  // Phase 1041 + SP-04 (Phase 1045): multi-selection handlers driven by the
  // `computeNextSelection` pure helper. Anchor lives in `lastToggleAnchor` ref
  // so plain/shift/cmd clicks all coordinate from the same authoritative source.
  const handleCmdClick = useCallback((id: string) => {
    if (isBasemapBoundaryId(id)) return;
    // fix(#833 codex round 2): an explicit selection gesture supersedes any
    // search-parked rows — keeping them would resurrect rows the gesture
    // discarded once the search clears (and a later bulk op would hit them).
    searchHiddenSelectionRef.current.clear();
    setSelectedIds((prev) => {
      const { selection, anchor } = computeNextSelection(
        selectableRowIds,
        id,
        { shiftKey: false, metaKey: true, ctrlKey: false },
        prev,
        lastToggleAnchor.current,
      );
      lastToggleAnchor.current = anchor;
      return selection;
    });
  }, [isBasemapBoundaryId, selectableRowIds]);

  const handleShiftClick = useCallback((id: string) => {
    if (isBasemapBoundaryId(id)) return;
    // fix(#833 codex round 2): same as handleCmdClick — a range gesture
    // replaces the selection, so parked rows must not outlive it.
    searchHiddenSelectionRef.current.clear();
    setSelectedIds((prev) => {
      const { selection, anchor } = computeNextSelection(
        selectableRowIds,
        id,
        { shiftKey: true, metaKey: false, ctrlKey: false },
        prev,
        lastToggleAnchor.current,
      );
      // Phase 20260526-builder-audit #338 BLD-20260526-11: treat the helper's return as immutable. Range may include
      // basemap-boundary ids if selectableRowIds drifts; build a fresh Set.
      const filtered = new Set<string>();
      for (const rid of selection) {
        if (!isBasemapBoundaryId(rid)) filtered.add(rid);
      }
      lastToggleAnchor.current = anchor;
      return filtered;
    });
  }, [isBasemapBoundaryId, selectableRowIds]);

  // SP-04: plain row click must record the anchor so a subsequent shift-click
  // has somewhere to range from. handleSelectLayer below opens the editor;
  // this is the side-channel anchor capture without disturbing that flow.
  const handlePlainSelectAnchor = useCallback((id: string | null) => {
    if (id && !isBasemapBoundaryId(id)) {
      lastToggleAnchor.current = id;
    }
  }, [isBasemapBoundaryId]);

  const handleCheckboxClick = useCallback((id: string) => {
    handleCmdClick(id);
  }, [handleCmdClick]);

  // fix(#833): every explicit selection reset also drops the search-parked
  // rows — a dismissed selection must not resurrect when the search clears.
  const resetMultiSelection = useCallback(() => {
    setSelectedIds(new Set());
    searchHiddenSelectionRef.current.clear();
  }, []);

  // Phase 1041-02: clear-selection handler (used by UnifiedStackPanel's Escape/outside-click)
  const handleClearSelection = useCallback(() => {
    resetMultiSelection();
    lastToggleAnchor.current = null;
  }, [resetMultiSelection]);

  // Phase 1041-03: real bulk handlers — wired to use-builder-layers bulk ops.
  // Each dep is the specific stable useCallback from use-builder-layers, NOT the
  // entire `layers` object (which is a plain literal re-created on every render).
  // Depending on `layers` defeats React.memo() on BulkActionBar / UnifiedStackPanel
  // on every opacity-slider move, which fires at ~60fps (Phase 20260526-builder-audit #338 BLD-20260526-11).
  const handleBulkVisibility = useCallback((ids: Set<string>) => {
    applyBulkVisibility(ids);
    resetMultiSelection();
  }, [applyBulkVisibility, resetMultiSelection]);

  const handleBulkOpacity = useCallback((ids: Set<string>, opacity: number) => {
    // NOTE: Opacity slider fires onValueChange continuously during drag.
    // Clearing selection on each intermediate event would break subsequent
    // drag events (selection would be empty). Selection is preserved during
    // drag; user dismisses via Escape or by clicking another row. This is
    // documented in the Plan 03 SUMMARY as a deliberate UX decision.
    applyBulkOpacity(ids, opacity);
  }, [applyBulkOpacity]);

  const handleBulkGroup = useCallback((ids: Set<string>) => {
    // fix(#392): only clear the selection when a group was
    // actually created; an ineligible selection must stay intact so the user
    // can see it, read the toast, and adjust instead of losing it silently. (audit B-004d/LM-04)
    if (applyBulkGroup(ids)) resetMultiSelection();
  }, [applyBulkGroup, resetMultiSelection]);

  const handleBulkUngroup = useCallback((ids: Set<string>) => {
    applyBulkUngroup(ids);
    resetMultiSelection();
  }, [applyBulkUngroup, resetMultiSelection]);

  // Phase 1201-01 ENH-03: apply one selected/copied style to compatible peers,
  // then clear the multi-selection (mirrors group/ungroup wrappers).
  const handleBulkApplyStyle = useCallback((ids: Set<string>) => {
    applyBulkApplyStyle(ids);
    resetMultiSelection();
  }, [applyBulkApplyStyle, resetMultiSelection]);

  const handleBulkDelete = useCallback((ids: Set<string>) => {
    applyBulkDelete(ids)
      .then((ok) => {
        if (ok) resetMultiSelection();
        // on failure: selection preserved so user can retry
      })
      .catch(() => {
        // Error already toasted inside handleBulkDelete; swallow here to prevent
        // unhandled rejection if invalidateQueries throws after allSettled.
      });
  }, [applyBulkDelete, resetMultiSelection]);

  // Derived: any row in selectedIds
  const isMultiSelectionActive = selectedIds.size > 0;

  // Phase 1119: sublayer visibility/opacity handlers route through the
  // controller-backed persisted basemap_config fields.
  const handleToggleSublayerVisibility = useCallback((sublayerId: string) => {
    applyBasemapPatch(toggleBasemapSublayerVisibility(basemapState, sublayerId));
  }, [applyBasemapPatch, basemapState]);

  const handleSublayerOpacityChange = useCallback((sublayerId: string, opacity: number) => {
    applyBasemapPatch(setBasemapSublayerOpacity(basemapState, sublayerId, opacity));
  }, [applyBasemapPatch, basemapState]);

  // Phase 1059 BSE-01: helper that merges a single field into basemap_config.sublayer_overrides[sublayerId].
  // Trims the entry if every field becomes null/undefined (no-op state).
  // Uses setBasemapConfig which auto-marks dirty (Phase 20260526-builder-audit #338 BLD-20260526-11).
  const updateSublayerOverride = useCallback(
    (sublayerId: string, field: keyof MapSublayerOverride, value: string | number | null) => {
      applyBasemapPatch(updateBasemapSublayerOverride(basemapState, sublayerId, field, value));
    },
    [applyBasemapPatch, basemapState],
  );

  const handleResetBasemapAppearance = useCallback(() => {
    applyBasemapPatch(resetBasemapAppearance());
  }, [applyBasemapPatch]);

  // Phase 1035: existing folder groups list for StackRow "Add to group…" sub-flow
  const existingFolderGroups = useMemo(() => {
    return layers.localLayers
      .filter(isFolderGroupLayer)
      .map((l) => ({ id: l.id, name: l.display_name ?? l.dataset_name ?? 'Group' }));
  }, [layers.localLayers]);

  // Analysis materialize jobs are tracked globally (AnalysisJobWatcher in
  // RootLayout owns polling, the completion toast, and cache invalidation) so
  // the signal survives this page unmounting. This page contributes only the
  // "Add to map" capability, which needs its layer actions.
  const setAnalysisJob = useAnalysisJobStore((s) => s.setJob);
  // fix(#760): the mobile rail buttons need the same ambient job signal the
  // desktop rail shows (feat(#682)) — <800px was the only surface with no
  // indication at all that a materialize is still running.
  const analysisJobRunning = useAnalysisJobStore((s) => !!s.job);
  const handleAnalysisJobChange = useCallback(
    (jobId: string | null, title?: string) => {
      setAnalysisJob(jobId ? { jobId, title: title ?? '', mapId: id ?? null } : null);
    },
    [setAnalysisJob, id],
  );
  // No dep array: keeps the registered callback fresh on every render; the
  // cleanup is what matters, so the watcher falls back to "View dataset" once
  // this builder is gone.
  useEffect(() => {
    analysisAddToMap.current = layers.chatLayerActions?.onAddDataset ?? null;
    analysisAddToMap.mapId = id ?? null;
    return () => {
      analysisAddToMap.current = null;
      analysisAddToMap.mapId = null;
    };
  });

  // feat(#675): "Save as dataset" on the ephemeral preview — open the Analysis
  // panel prefilled with the operation behind the chat preview.
  const ephemeralAnalysis = layers.ephemeralResult?.analysis;
  const handleSaveAnalysisPreview = useCallback(() => {
    if (!ephemeralAnalysis) return;
    setAnalysisPrefill({ ...ephemeralAnalysis, nonce: Date.now() });
    setRailPanel('analysis');
  }, [ephemeralAnalysis]);

  // feat(#1241): the same affordance for a preview with no analysis behind it —
  // a plain chat query result, which until now could only be dismissed. The
  // draft snapshots the FeatureCollection at the moment the dialog opens, so a
  // new chat turn (or a dismiss) landing mid-dialog can't swap what gets saved
  // out from under the name the user is typing.
  const [chatSaveDraft, setChatSaveDraft] = useState<{
    geojson: GeoJSON.FeatureCollection;
    prompt?: string;
  } | null>(null);
  const ephemeralResult = layers.ephemeralResult;
  const handleSaveChatPreview = useCallback(() => {
    if (!ephemeralResult) return;
    setChatSaveDraft({ geojson: ephemeralResult.geojson, prompt: ephemeralResult.prompt });
  }, [ephemeralResult]);

  // fix(#1009): the preview's stack-row props. Memoized because a fresh object
  // literal on the UnifiedStackPanel prop would defeat its memo() on every
  // render of this (very large) page.
  const previewRowProps = useMemo(() => {
    const result = layers.ephemeralResult;
    if (!result) return null;
    const featureCount = result.geojson.features.length;
    // feat(#1241): which save (if any) this preview earns — the truncation
    // guard and the upload-capability gate both live in previewSaveMode.
    const saveMode = previewSaveMode({ ...result, featureCount }, canSaveDataset);
    return {
      featureCount,
      truncated: result.truncated,
      totalCount: result.totalCount,
      viewportScoped: result.viewportScoped,
      onDismiss: layers.handleDismissEphemeral,
      onSaveAsDataset:
        saveMode === 'analysis'
          ? handleSaveAnalysisPreview
          : saveMode === 'snapshot'
          ? handleSaveChatPreview
          : undefined,
      saveDisabledReason: saveMode === 'truncated' ? ('truncated' as const) : undefined,
    };
  }, [layers.ephemeralResult, layers.handleDismissEphemeral, canSaveDataset, handleSaveAnalysisPreview, handleSaveChatPreview]);

  // ux(#772): stack-row kebab "Analyze this layer" — the same handoff path the
  // chat preview uses, so the panel opens (or remounts, via the prefill nonce
  // key) targeting exactly this layer even when the row isn't selected.
  const handleAnalyzeLayer = useCallback((layerId: string) => {
    setAnalysisPrefill({ layerId, operation: 'buffer', nonce: Date.now() });
    setRailPanel('analysis');
  }, []);

  // fix(#679 review P2): the prefill lives only for the handoff opening it
  // triggered. Clearing it on any navigation away from the panel (rail close,
  // panel switch, mobile sheet dismiss) keeps a later ordinary opening from
  // remounting the form with stale handoff params.
  useEffect(() => {
    if (railPanel !== 'analysis' && analysisPrefill) setAnalysisPrefill(null);
  }, [railPanel, analysisPrefill]);

  const railProps = useMemo(() => ({
    activePanel: railPanel,
    onPanelChange: setRailPanel,
    aiAvailable: !!aiAvailable,
    notes: dockNotes,
    onNotesChange: setDockNotes,
    mapId: id,
    layers: layers.localLayers,
    layersMapId: layers.layersMapId,
    // ux(#772): the stack's selected row, so the Analysis panel can open
    // targeting it instead of the first eligible layer.
    selectedLayerId: layers.expandedLayerId,
    layerActions: layers.chatLayerActions,
    onQueryResult: layers.handleQueryResult,
    mapInstanceRef,
    onClearPreview: layers.handleDismissEphemeral,
    hasPreview: !!layers.ephemeralResult,
    previewSource: layers.ephemeralResult?.source,
    analysisPrefill,
    // setState identity is stable — safe to pass without a memo dep.
    onAnalysisJobChange: handleAnalysisJobChange,
    onMarkDirty: handleMarkDirty,
    viewport,
  }), [railPanel, aiAvailable, dockNotes, id, layers.localLayers, layers.layersMapId, layers.expandedLayerId, layers.chatLayerActions, layers.handleQueryResult, layers.handleDismissEphemeral, layers.ephemeralResult, analysisPrefill, mapInstanceRef, handleMarkDirty, viewport, handleAnalysisJobChange]);

  const mobileRailButtons = useMemo(() => [
    {
      id: 'notes' as const,
      icon: FileText,
      label: t('dock.notes', { defaultValue: 'Notes' }),
      disabled: false,
      unavailable: false,
    },
    {
      id: 'history' as const,
      icon: History,
      label: t('dock.history', { defaultValue: 'History' }),
      disabled: false,
      unavailable: false,
    },
    {
      id: 'analysis' as const,
      icon: FlaskConical,
      label: t('analysisTools.title', { defaultValue: 'Analysis' }),
      disabled: false,
      unavailable: false,
    },
    {
      id: 'ai' as const,
      icon: Sparkles,
      label: aiAvailable
        ? t('dock.askAi', { defaultValue: 'Ask AI' })
        : t('rail.aiUnavailable', { defaultValue: 'AI unavailable' }),
      disabled: false,
      unavailable: !aiAvailable,
    },
  ], [aiAvailable, t]);

  const railSheetTitle = railPanel === 'history'
    ? t('dock.history', { defaultValue: 'History' })
    : railPanel === 'analysis'
    ? t('analysisTools.title', { defaultValue: 'Analysis' })
    : railPanel === 'ai'
      ? aiAvailable
        ? t('dock.askAi', { defaultValue: 'Ask AI' })
        : t('rail.aiUnavailable', { defaultValue: 'AI unavailable' })
      : t('dock.notes', { defaultValue: 'Notes' });
  const railSheetDescription = railPanel === 'history'
    ? t('history.timelineLabel', { defaultValue: 'Map edit history' })
    : railPanel === 'analysis'
    ? t('analysisTools.description', { defaultValue: 'Run buffer, centroid, and clip operations on a layer' })
    : railPanel === 'ai'
      ? aiAvailable
        ? t('dock.askAi', { defaultValue: 'Ask AI' })
        : t('rail.aiUnavailableDescription', {
          defaultValue: 'An administrator needs to enable an AI provider before Ask AI can be used in this builder.',
        })
      : t('dock.notesPlaceholder', { defaultValue: 'Add notes about this map...' });

  // ux(#776): the Add Data dialog stays open for repeated adds, so the
  // "open the editor on the new layer" step is DEFERRED — opening it per-add
  // would stack the flyout behind the still-open dialog. The last added
  // layer's id waits here until the dialog closes.
  const pendingEditorLayerIdRef = useRef<string | null>(null);

  const handleAddDataClick = useCallback(
    (initialQuery?: string) => {
      dialogs.setAddDataInitialQuery(initialQuery ?? '');
      // A pending id from a previous session's mid-flight add must not leak
      // into this one's close.
      pendingEditorLayerIdRef.current = null;
      dialogs.setShowAddData(true);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps -- stable setters from useBuilderDialogs
    [dialogs.setAddDataInitialQuery, dialogs.setShowAddData],
  );

  const handleClearFilter = useCallback(
    (layerId: string) => dispatchLayerAction({
      type: 'set_filter',
      source: 'manual',
      layerId,
      expression: null,
    }),
    [dispatchLayerAction],
  );

  // Adapter: UnifiedStackPanel/SidebarRail pass `string | null` (null = deselect);
  // handleToggleExpand accepts only string ('' = toggle off).
  // SP-04 (Phase 1045): record the row id as the shift-click anchor on every
  // plain selection so a subsequent shift-click range-extends from this row.
  const handleSelectLayer = useCallback(
    (id: string | null) => {
      handlePlainSelectAnchor(id);
      layers.handleToggleExpand(id ?? '');
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps -- stable handlers
    [layers.handleToggleExpand, handlePlainSelectAnchor],
  );

  // fix(v1.6.0 audit D7): the UnifiedStackPanel props below were inline lambdas
  // re-created on every MapBuilderPage render, so the React.memo chain
  // (UnifiedStackPanel → SortableStackRow → StackRow) never skipped a row
  // render. dispatchLayerAction and the other deps here are the stable
  // useCallbacks from use-builder-layers — NOT the per-render `layers` literal.
  const handleRowToggleVisibility = useCallback((layerId: string) => {
    // P1-09: a folder group row is a synthetic row, not a map layer. Route its
    // eye toggle to toggle_group_visibility so every child (and its
    // companions) follows; loose/child rows use set_visibility.
    // fix(v1.6.0 audit D7): group-ness is read through the hook's ref-backed
    // isFolderGroupRow predicate — a localLayers.find() here would force this
    // callback (and every row) to re-create on exactly the frames the
    // memoization targets.
    if (layers.isFolderGroupRow(layerId)) {
      layers.dispatchLayerAction({
        type: 'toggle_group_visibility',
        source: 'manual',
        groupId: layerId,
      });
    } else {
      layers.dispatchLayerAction({
        type: 'set_visibility',
        source: 'manual',
        layerId,
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- stable handlers
  }, [layers.isFolderGroupRow, layers.dispatchLayerAction]);

  const handleRowReorder = useCallback((reorderedLayers: MapLayerResponse[]) => {
    layers.dispatchLayerAction({
      type: 'reorder_layers',
      source: 'manual',
      layers: reorderedLayers,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- stable handlers
  }, [layers.dispatchLayerAction]);

  const handleRowOpacityChange = useCallback((layerId: string, opacity: number) => {
    layers.dispatchLayerAction({
      type: 'set_opacity',
      source: 'manual',
      layerId,
      opacity,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- stable handlers
  }, [layers.dispatchLayerAction]);

  const handleRowRemove = useCallback((layerId: string) => {
    layers.dispatchLayerAction({
      type: 'remove_layer',
      source: 'manual',
      layerId,
      persistence: 'server',
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- stable handlers
  }, [layers.dispatchLayerAction]);

  const handleRowDuplicate = useCallback((layerId: string) => {
    layers.dispatchLayerAction({
      type: 'duplicate_rendering',
      source: 'manual',
      layerId,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- stable handlers
  }, [layers.dispatchLayerAction]);

  const handleRowKeyboardReorder = useCallback(
    (layerId: string, direction: 'up' | 'down') =>
      direction === 'up'
        ? layers.handleMoveUp(layerId)
        : layers.handleMoveDown(layerId),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- stable handlers
    [layers.handleMoveUp, layers.handleMoveDown],
  );

  const handlePanelAddDataset = useCallback((datasetId: string) => {
    layers.handleAddDataset(datasetId, (newLayerId) => {
      handleSelectLayer(newLayerId);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- stable handlers
  }, [layers.handleAddDataset, handleSelectLayer]);

  // handleToggleExpand already toggles-on-same-id (prev === id → close), so the
  // old `expandedLayerId === 'settings' ? '' : 'settings'` ternary was
  // redundant AND made the lambda depend on expandedLayerId.
  const handlePanelSettingsClick = useCallback(() => {
    layers.handleToggleExpand('settings');
    // eslint-disable-next-line react-hooks/exhaustive-deps -- stable handlers
  }, [layers.handleToggleExpand]);

  const handleSwapBasemapClick = useCallback(() => {
    handleSelectLayer('basemap-group');
  }, [handleSelectLayer]);

  // Phase 1040: DnD handlers hoisted from UnifiedStackPanel — same behavior,
  // lifted to MapBuilderPage so BuilderDialogs (catalog modal) shares the context.
  // T-1040-01: preserve activationConstraint distance:8 and closestCenter verbatim.
  const handleDragStart = useCallback((event: DragStartEvent) => {
    setDragActiveId(String(event.active.id));
    handleSelectLayer(null);
    // Phase 1041 POL-10: drag + multi-select are mutually exclusive. Clear selection at drag-start.
    resetMultiSelection();
    lastToggleAnchor.current = null;
    document.documentElement.classList.add('dragging-active');
    lastOverIdRef.current = null;
    // Announce pick-up for catalog drags (POL-05 / T-1040-10)
    const data = event.active.data.current as { source?: string; name?: string } | undefined;
    if (data?.source === 'catalog' && data.name) {
      announce(t('a11y.dragPickup', { name: data.name }));
    }
  }, [handleSelectLayer, announce, t, resetMultiSelection]);

  const handleDragEnd = useCallback((event: DragEndEvent) => {
    setDragActiveId(null);
    document.documentElement.classList.remove('dragging-active');
    lastOverIdRef.current = null;
    const { active, over } = event;
    // If dropped outside any droppable, cancel cleanly with no action.
    if (!over) {
      const data = active.data.current as { source?: string; name?: string } | undefined;
      if (data?.source === 'catalog') {
        announce(t('a11y.dragCancelled'));
      }
      return;
    }

    // --- Catalog drop (cross-context: from Add Dataset modal) ---
    const data = active.data.current as
      | { source?: string; datasetId?: string; recordType?: string; name?: string }
      | undefined;

    if (data?.source === 'catalog') {
      const { datasetId, name: datasetName = '' } = data;
      if (!datasetId) return;
      const overId = String(over.id);

      // Case 3: non-basemap row dropped onto the basemap group row → silent reject (UI-SPEC §3d).
      // (Basemaps are no longer draggable from the catalog; basemap swaps go through the
      // left-pane BasemapGroupEditorScene flyout instead.)
      if (basemapGroup && overId === basemapGroup.id) {
        announce(t('a11y.dragCancelled'));
        return;
      }

      // Cases 4 & 5: non-basemap row dropped onto a folder-group (POL-03) or loose row (POL-01).
      // When target is a folder group, parentGroupId is set so the new layer joins the group.
      const targetLayer = layers.localLayers.find((l) => l.id === overId);
      const parentGroupId = (targetLayer && isFolderGroupLayer(targetLayer)) ? overId : null;
      // fix(#394) LM-03: announce the REAL landing position — loose catalog
      // drops always PREPEND at top (position 1, BSR-18), and group drops land
      // after the group's last existing child; the drop-target index the SR
      // heard before was a lie for every drop below row 1.
      let announcePosition = 1;
      if (parentGroupId) {
        const stack = layers.localLayers;
        const groupIdx = stack.findIndex((l) => l.id === parentGroupId);
        let lastChildIdx = -1;
        for (let i = stack.length - 1; i >= 0; i--) {
          if ((stack[i] as { parent_group_id?: string | null }).parent_group_id === parentGroupId) {
            lastChildIdx = i;
            break;
          }
        }
        announcePosition = (lastChildIdx >= 0 ? lastChildIdx + 1 : groupIdx + 1) + 1;
      }
      // Phase 20260526-builder-audit #338 BLD-20260526-11: announce fires inside onSuccessCb — only after the async mutation resolves
      // successfully. If the mutation errors, the hook fires toast.error and the announce
      // is never called, avoiding contradictory screen-reader output.
      // Modal stays open per POL-05 — onSuccessCb is not used to auto-select the layer.
      layers.handleAddDataset(datasetId, () => {
        announce(t('a11y.dragDropped', { name: datasetName, n: announcePosition }));
      }, parentGroupId, datasetName);
      return;
    }

    // --- Intra-stack reorder (unchanged from Plan 01) ---
    if (active.id === over.id) return;

    // UX-03 (Phase 1051 Plan 06): basemap row drag — encode position in
    // MapBasemapConfig.basemap_position. Basemap is not in localLayers, so the
    // standard arrayMove path below cannot reorder it. Determine the new
    // position by comparing the drop target's index to the basemap's current
    // position:
    //   - basemap dragged onto ANY layer when currently 'bottom' → 'top'
    //   - basemap dragged onto ANY layer when currently 'top' → 'bottom'
    // This 2-position toggle matches the design contract; for visual feedback
    // the basemap row jumps to the opposite end of the stack on drop.
    const currentLayers = layers.localLayers;
    if (basemapGroup && active.id === basemapGroup.id) {
      // Sliding the basemap onto itself is a no-op (early-returned by the
      // active.id === over.id check above), so here we know `over.id` is some
      // other row id.
      const currentPosition = basemapState.config.basemap_position ?? 'bottom';
      const nextPosition = currentPosition === 'top' ? 'bottom' : 'top';
      applyBasemapPatch(setBasemapPosition(basemapState, nextPosition));
      announce(t('a11y.basemapPositionChanged', {
        defaultValue: 'Basemap moved to {{position}}',
        position: nextPosition,
      }));
      return;
    }

    // Standard intra-stack reorder for non-basemap drags.
    const oldIndex = currentLayers.findIndex((layer) => layer.id === active.id);
    const newIndex = currentLayers.findIndex((layer) => layer.id === over.id);
    if (oldIndex < 0 || newIndex < 0) return;

    // P2-07: dragging a folder group row moves the WHOLE group block (the row +
    // all its child layers) atomically, so a single-row arrayMove can never
    // split the group by leaving its children behind. Loose/child row drags are
    // unchanged (the simple arrayMove below).
    const activeLayer = currentLayers[oldIndex];
    if (isFolderGroupLayer(activeLayer)) {
      const groupId = String(active.id);
      const block = currentLayers.filter(
        (l) =>
          l.id === groupId ||
          (l as { parent_group_id?: string | null }).parent_group_id === groupId,
      );
      const blockIds = new Set(block.map((l) => l.id));
      // Dropping a group onto itself or one of its own children is a no-op.
      if (blockIds.has(String(over.id))) return;
      const remaining = currentLayers.filter((l) => !blockIds.has(l.id));
      const targetIdx = remaining.findIndex((l) => l.id === over.id);
      // Moving downward inserts the block AFTER the drop target (matching the
      // single-row arrayMove feel); moving upward inserts before it.
      const insertIdx =
        targetIdx < 0
          ? remaining.length
          : newIndex > oldIndex
            ? targetIdx + 1
            : targetIdx;
      const next = [
        ...remaining.slice(0, insertIdx),
        ...block,
        ...remaining.slice(insertIdx),
      ];
      dispatchLayerAction({ type: 'reorder_layers', source: 'manual', layers: next });
      return;
    }

    // fix(#525 B-040): derive group membership from the drop target — the
    // bare arrayMove never touched parent_group_id, so dragging a child out
    // of its group was a silent no-op (childrenByGroup renders by membership,
    // not array position, so the row snapped back) and a loose layer dropped
    // between group children never joined the group.
    const overLayer = currentLayers[newIndex];
    const currentGroupId = getParentGroupId(activeLayer);
    const targetGroupId = resolveDropGroupMembership(activeLayer, overLayer);
    let moved = arrayMove(currentLayers, oldIndex, newIndex);
    if (targetGroupId !== currentGroupId) {
      moved = moved.map((l) => {
        if (l.id !== activeLayer.id) return l;
        return {
          ...l,
          parent_group_id: targetGroupId,
          // Leaving a group also clears the persisted folderGroupId — mirrors
          // handleMoveLayerOutOfGroup (fix(#392) CR-01).
          ...(targetGroupId === null
            ? { style_config: clearPersistedFolderGroup(l.style_config) }
            : {}),
        } as MapLayerResponse;
      });
    }
    dispatchLayerAction({
      type: 'reorder_layers',
      source: 'manual',
      layers: moved,
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps -- layers.localLayers + dispatchLayerAction + handleAddDataset captured; basemapGroup is stable derived value; announce is stable
  }, [layers.localLayers, dispatchLayerAction, layers.handleAddDataset, layers.markDirty, basemapGroup, t, announce, applyBasemapPatch, basemapState]);

  const handleDragCancel = useCallback(() => {
    setDragActiveId(null);
    document.documentElement.classList.remove('dragging-active');
    lastOverIdRef.current = null;
    announce(t('a11y.dragCancelled'));
  }, [announce, t]);

  // Phase 1040 Plan 04: announce position updates during catalog drag (best-effort).
  // Only fires when the over-target changes (via lastOverIdRef) to avoid excessive spam.
  const handleDragOver = useCallback((event: DragOverEvent) => {
    const data = event.active.data.current as { source?: string } | undefined;
    if (data?.source !== 'catalog') return;
    const overId = event.over ? String(event.over.id) : null;
    if (overId === lastOverIdRef.current) return;
    lastOverIdRef.current = overId;
    if (!overId) return;
    const index = layers.localLayers.findIndex((l) => l.id === overId);
    if (index < 0) return;
    announce(t('a11y.dragPosition', { n: index + 1, total: layers.localLayers.length }));
  }, [layers.localLayers, announce, t]);

  // fix(#785): dnd-kit's DEFAULT announcements are hardcoded English built
  // from the draggable id — every drag emitted "Picked up draggable item
  // <uuid>…" into dnd-kit's own live region, in English regardless of locale,
  // competing with the app's localized announce() region. Announce translated,
  // human layer names instead. Catalog drags return undefined: their pickup /
  // position / drop already flow through announce() above (the drop
  // deliberately fires only AFTER the add-dataset mutation resolves — see
  // handleDragEnd — which dnd-kit's synchronous onDragEnd cannot honor).
  const dndAccessibility = useMemo(() => {
    const isCatalogDrag = (active: Active) =>
      (active.data.current as { source?: string } | undefined)?.source === 'catalog';
    const itemName = (active: Active): string => {
      const data = active.data.current as { name?: string } | undefined;
      if (data?.name) return data.name;
      if (basemapGroup && String(active.id) === basemapGroup.id) {
        return basemapGroup.presetName;
      }
      const layer = layers.localLayers.find((l) => l.id === String(active.id));
      return layer ? (layer.display_name ?? layer.dataset_name) : String(active.id);
    };
    const overPosition = (over: { id: string | number } | null): number | null => {
      if (!over) return null;
      const index = layers.localLayers.findIndex((l) => l.id === String(over.id));
      return index >= 0 ? index + 1 : null;
    };
    const announcements: Announcements = {
      onDragStart({ active }) {
        if (isCatalogDrag(active)) return undefined;
        return t('a11y.dragPickup', { name: itemName(active) });
      },
      onDragOver({ active, over }) {
        if (isCatalogDrag(active)) return undefined;
        const n = overPosition(over);
        if (n == null) return undefined;
        return t('a11y.dragPosition', { n, total: layers.localLayers.length });
      },
      onDragEnd({ active, over }) {
        if (isCatalogDrag(active)) return undefined;
        if (!over) return t('a11y.dragCancelled');
        return t('a11y.dragDropped', { name: itemName(active), n: overPosition(over) ?? 1 });
      },
      onDragCancel({ active }) {
        if (isCatalogDrag(active)) return undefined;
        return t('a11y.dragCancelled');
      },
    };
    const screenReaderInstructions: ScreenReaderInstructions = {
      draggable: t('a11y.dragInstructions', {
        defaultValue:
          'To reorder a layer, press Enter or Space on its drag handle, use the arrow keys to move it, then press Enter, Space, or Escape to finish.',
      }),
    };
    return { announcements, screenReaderInstructions };
  }, [layers.localLayers, basemapGroup, t]);

  const handleCloseEditor = useCallback(() => {
    const expandedId = layers.expandedLayerId;
    layers.handleToggleExpand('');
    // Return focus to the element that triggered the flyout.
    // - Settings panel: return focus to the cog button (data-testid="settings-cog-btn")
    // - Layer editor: return focus to the row (stack-row-{id})
    if (expandedId === 'settings') {
      requestAnimationFrame(() => {
        const cogEl = document.querySelector<HTMLElement>('[data-testid="settings-cog-btn"]');
        cogEl?.focus();
      });
    } else if (expandedId) {
      requestAnimationFrame(() => {
        // fix(HT-18): the row can be gone by the time focus returns (e.g. the
        // layer was deleted from the editor footer). Falling back to the first
        // stack row keeps keyboard focus in the panel instead of dropping it
        // on <body>.
        const rowEl = document.getElementById(`stack-row-${expandedId}`)
          ?? document.querySelector<HTMLElement>('[data-row-id]');
        rowEl?.focus();
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- stable refs
  }, [layers.handleToggleExpand, layers.expandedLayerId]);

  // Phase 1035: open Add Data modal for "Add layer" in folder group (Plan 1037 will pass groupId)
  const handleAddLayerToFolderGroup = useCallback((_groupId: string) => {
    handleAddDataClick();
  }, [handleAddDataClick]);

  // Phase 1035: breadcrumb click — navigate editor from Scene C → Scene B
  const onBreadcrumbClick = useCallback(() => {
    handleSelectLayer('basemap-group');
  }, [handleSelectLayer]);

  // Resolve the bound terrain DEM the SAME way the map renderer (BuilderMap)
  // does: by source_dataset_id + isTerrainCapableDemLayer, NOT by
  // render_mode === 'terrain'. A hillshade-mode DEM drives the 3D mesh too, so
  // requiring terrain mode here made the settings report "No terrain layer is
  // active" while the map was actively rendering terrain from it.
  const boundTerrainLayer = useMemo(
    () => resolveTerrainSourceLayer(layers.localLayers, layers.localTerrainConfig),
    [layers.localLayers, layers.localTerrainConfig],
  );
  // Match the map's effectiveTerrainEnabled: terrain only renders when the bound
  // DEM is also visible (BuilderMap sets terrain to null for a hidden DEM).
  const isTerrainActive = Boolean(
    layers.localTerrainConfig?.enabled && boundTerrainLayer && boundTerrainLayer.visible !== false,
  );
  const boundLayerName = boundTerrainLayer
    ? (boundTerrainLayer.display_name ?? boundTerrainLayer.dataset_name ?? undefined)
    : undefined;

  // codex(#451): a DEM whose 2D relief overlay is off (render_mode 'terrain')
  // paints nothing unless it is the ACTIVE 3D terrain source. When it isn't, the
  // stack row would show a normal eye-on layer that draws nothing — flag those
  // so the row stays honest. Skip already-hidden rows (their eye is off, which
  // already reads as "not shown").
  const drawsNothingLayerIds = useMemo(() => {
    const ids = new Set<string>();
    const activeMeshId = isTerrainActive ? boundTerrainLayer?.id : undefined;
    for (const layer of layers.localLayers) {
      if (layer.is_dem !== true || layer.visible === false) continue;
      if (effectiveDemRenderMode(layer.style_config, layer.is_dem) !== 'terrain') continue;
      if (layer.id === activeMeshId) continue;
      ids.add(layer.id);
    }
    return ids;
  }, [layers.localLayers, isTerrainActive, boundTerrainLayer?.id]);

  // Phase 1035+1036: scene-specific content + footer for LayerEditorPanel
  // Computed after handleSelectLayer and handleAddDataClick are in scope
  let sceneContent: ReactNode = null;
  let sceneFooter: ReactNode = null;
  let breadcrumbPresetName: string | undefined = undefined;

  if (editorScene === 'basemap-group' && basemapGroup) {
    // IN-02 fix: exclude BLANK_BASEMAP_ID from the presets list — the component renders
    // a dedicated "No basemap" card before the presets loop; including 'blank' in both
    // would produce a duplicate card if an admin ever adds it to the basemaps catalog.
    const presets = basemaps
      .filter((b) => b.id !== BLANK_BASEMAP_ID)
      .map((b) => ({
        id: b.id,
        name: b.label,
        provider: '',
        thumbnailUrl: basemapThumbnail(b.id),
      }));
    sceneContent = (
      <LazyLoadErrorBoundary>
        <Suspense fallback={<SceneSpinnerFallback />}>
          <BasemapGroupEditorScene
            activePresetId={basemapState.basemapStyle}
            presets={presets}
            sublayers={basemapGroup.sublayers}
            masterOpacity={basemapGroup.opacity}
            onSwapBasemap={(presetId) => {
              applyBasemapPatch(swapBasemapPreset(basemapState, presetId));
              layers.markDirty();
            }}
            // onAddCustomBasemap intentionally omitted — custom-basemap support is a Plan
            // 1037 follow-up. With the prop optional, the button stays hidden until a real
            // handler is wired up here (was a visible no-op stub; B-015).
            onSublayerVisibilityChange={handleToggleSublayerVisibility}
            onSublayerOpacityChange={handleSublayerOpacityChange}
            onMasterOpacityChange={(opacity) => {
              applyBasemapPatch(setBasemapMasterOpacity(basemapState, opacity));
            }}
          />
        </Suspense>
      </LazyLoadErrorBoundary>
    );
    sceneFooter = (
      <LazyLoadErrorBoundary>
        <Suspense fallback={<SceneSpinnerFallback />}>
          <BasemapGroupEditorFooter
            onResetAppearance={handleResetBasemapAppearance}
            onRemoveBasemap={() => {
              applyBasemapPatch(removeBasemapFromState(basemapState));
              layers.markDirty();
              handleSelectLayer(null);
            }}
          />
        </Suspense>
      </LazyLoadErrorBoundary>
    );
  } else if (editorScene === 'basemap-sublayer' && basemapGroup) {
    const sublayer = basemapGroup.sublayers.find((s) => s.id === layers.expandedLayerId);
    breadcrumbPresetName = basemapGroup.presetName;
    if (sublayer) {
      // Phase 20260526-builder-audit #338 BLD-20260526-11: translate the UI routing ID (e.g. 'basemap:roads') to the bare semantic
      // key ('road') used in basemap_config.sublayer_overrides so reads and writes are
      // consistent with what applySublayerOverrides expects from SUBLAYER_CLASSIFIERS.
      const overrideKey = SUBLAYER_ID_OVERRIDE_KEY[sublayer.id] ?? sublayer.id;
      sceneContent = (
        <LazyLoadErrorBoundary>
          <Suspense fallback={<SceneSpinnerFallback />}>
            <BasemapSublayerEditorScene
              sublayerId={sublayer.id}
              sublayerName={sublayer.name}
              opacity={sublayer.opacity}
              strokeColor={basemapState.config.sublayer_overrides?.[overrideKey]?.stroke_color ?? MAP_COLORS.basemapSublayer.stroke}
              strokeWidth={basemapState.config.sublayer_overrides?.[overrideKey]?.stroke_width ?? 1}
              casingColor={basemapState.config.sublayer_overrides?.[overrideKey]?.casing_color ?? MAP_COLORS.basemapSublayer.casing}
              casingWidth={basemapState.config.sublayer_overrides?.[overrideKey]?.casing_width ?? 0.5}
              minZoom={basemapState.config.sublayer_overrides?.[overrideKey]?.min_zoom ?? 0}
              maxZoom={basemapState.config.sublayer_overrides?.[overrideKey]?.max_zoom ?? 22}
              onOpacityChange={(o) => handleSublayerOpacityChange(sublayer.id, o)}
              onStrokeColorChange={(hex) => updateSublayerOverride(sublayer.id, 'stroke_color', hex)}
              onStrokeWidthChange={(w) => updateSublayerOverride(sublayer.id, 'stroke_width', w)}
              onCasingColorChange={(hex) => updateSublayerOverride(sublayer.id, 'casing_color', hex)}
              onCasingWidthChange={(w) => updateSublayerOverride(sublayer.id, 'casing_width', w)}
              onMinZoomChange={(z) => updateSublayerOverride(sublayer.id, 'min_zoom', z)}
              onMaxZoomChange={(z) => updateSublayerOverride(sublayer.id, 'max_zoom', z)}
              onResetSublayer={() => {
                applyBasemapPatch(resetBasemapSublayer(basemapState, sublayer.id));
              }}
            />
          </Suspense>
        </LazyLoadErrorBoundary>
      );
      sceneFooter = (
        <LazyLoadErrorBoundary>
          <Suspense fallback={<SceneSpinnerFallback />}>
            <BasemapSublayerEditorFooter
              onBackToBasemap={() => handleSelectLayer('basemap-group')}
            />
          </Suspense>
        </LazyLoadErrorBoundary>
      );
    }
  } else if (editorScene === 'dem' && editingLayer) {
    sceneContent = (
      <LazyLoadErrorBoundary>
        <Suspense fallback={<SceneSpinnerFallback />}>
          <DEMEditorScene
            layer={editingLayer}
            onPaintChange={(paint) => layers.dispatchLayerAction({
              type: 'set_paint',
              source: 'manual',
              layerId: editingLayer.id,
              paint,
            })}
            onStyleConfigChange={(config, paint) => layers.dispatchLayerAction({
              type: 'set_style_config',
              source: 'manual',
              layerId: editingLayer.id,
              config,
              paint,
            })}
            onOpacityChange={(opacity) => layers.dispatchLayerAction({
              type: 'set_opacity',
              source: 'manual',
              layerId: editingLayer.id,
              opacity,
            })}
            onZoomChange={(min, max) => layers.dispatchLayerAction({
              type: 'set_layout',
              source: 'manual',
              layerId: editingLayer.id,
              layout: { ...editingLayer.layout, _minzoom: min, _maxzoom: max },
            })}
            onTerrainBind={(layerId) => layers.dispatchLayerAction({
              type: 'bind_dem_terrain',
              source: 'manual',
              layerId,
            })}
            onTerrainUnbind={(layerId) => layers.dispatchLayerAction({
              type: 'unbind_dem_terrain',
              source: 'manual',
              layerId,
            })}
            terrainExaggeration={
              layers.localTerrainConfig?.source_dataset_id === editingLayer.dataset_id
                ? layers.localTerrainConfig.exaggeration ?? 1
                : 1
            }
            onTerrainExaggerationChange={(layerId, exaggeration) => {
              const nextExaggeration = normalizeTerrainExaggeration(exaggeration);
              layers.dispatchLayerAction({
                type: 'set_dem_terrain_exaggeration',
                source: 'manual',
                layerId,
                exaggeration: nextExaggeration,
              });
              try {
                if (mapInstanceRef.current?.getSource(TERRAIN_SOURCE_ID)) {
                  mapInstanceRef.current.setTerrain({
                    source: TERRAIN_SOURCE_ID,
                    exaggeration: nextExaggeration,
                  });
                  mapInstanceRef.current.triggerRepaint();
                }
              } catch {
                // BuilderMap reapplies the layer-owned terrain config once the
                // DEM terrain source exists after style or token refreshes.
              }
            }}
            onRemove={(layerId) => layers.dispatchLayerAction({
              type: 'remove_layer',
              source: 'manual',
              layerId,
              persistence: 'server',
            })}
            isTerrainBound={isHillshadeTerrainBound(
              { dataset_id: editingLayer.dataset_id, is_dem: editingLayer.is_dem },
              layers.localTerrainConfig,
            )}
          />
        </Suspense>
      </LazyLoadErrorBoundary>
    );
    // DEMEditorScene renders its own footer (Delete layer inline confirm)
  } else if (editorScene === 'settings') {
    sceneContent = (
      <LazyLoadErrorBoundary>
        <Suspense fallback={<SceneSpinnerFallback />}>
          <SettingsEditorScene
            terrainConfig={layers.localTerrainConfig}
            isTerrainActive={isTerrainActive}
            boundLayerName={boundLayerName}
            onOpenBoundLayer={
              boundTerrainLayer
                ? () => handleSelectLayer(boundTerrainLayer.id)
                : undefined
            }
            enabledPluginIds={enabledPluginIds}
            activePluginIds={activePlugins}
            onTogglePlugin={handleTogglePlugin}
            backgroundColor={basemapState.config.background_color ?? null}
            onBackgroundColorChange={(color) => {
              applyBasemapPatch(setBasemapBackgroundColor(basemapState, color));
            }}
            onBackgroundColorReset={() => {
              applyBasemapPatch(setBasemapBackgroundColor(basemapState, null));
            }}
            projection={localProjection}
            onSetProjection={handleSetProjection}
          />
        </Suspense>
      </LazyLoadErrorBoundary>
    );
    sceneFooter = undefined;
    breadcrumbPresetName = undefined;
  }

  if (isLoading) {
    return (
      <div className="flex flex-1 min-h-0 items-center justify-center">
        <LoadingState message={t('loadingMap')} />
      </div>
    );
  }

  if (error || !mapData) {
    const msg = error instanceof ApiError && error.status === 403
      ? t('common:errors.accessDenied', { defaultValue: 'Access denied' })
      : error instanceof ApiError && error.status === 404
        ? t('common:errors.mapNotFound')
        : error
          ? t('common:errors.loadFailed', { defaultValue: 'Failed to load map' })
          : t('common:errors.mapNotFound');
    return (
      <div className="flex flex-1 min-h-0 items-center justify-center">
        <div className="text-center space-y-4">
          <ErrorState message={msg} />
          <Link to="/maps" className="text-sm text-primary hover:underline">
            {t('backToMaps')}
          </Link>
        </div>
      </div>
    );
  }

  // Three-column grid classes for the builder body.
  // Column 1: sidebar (340px full or 64px rail at <1100px)
  // Column 2: LayerEditorPanel flyout (380px, only when layer selected AND viewport >= 800px)
  // Column 3 (or 2 when no editor): map canvas (1fr)
  //
  // fix(#394) UX-05 (decision record): sidebar/editor widths are fixed and
  // breakpoint-driven BY DESIGN — no user drag-resize, no persisted width.
  // The three-column budget is tuned per breakpoint (340/380px columns keep
  // the map ≥50% at 1280px) and a resizable panel would invalidate the
  // responsive contract the e2e suite pins. Revisit only with a product ask.
  const builderBodyGridClass = cn(
    'flex-1 min-h-0 grid',
    // Base: no editor open
    isRail ? 'grid-cols-[64px_1fr]' : 'grid-cols-[340px_1fr]',
    // Editor open and not hidden (also for basemap group/sublayer/settings scenes which have no editingLayer)
    isEditorOpen && !isEditorHidden && (
      isRail ? 'grid-cols-[64px_380px_1fr]' : 'grid-cols-[340px_380px_1fr]'
    ),
  );

  return (
    // Fill the flex space <main> leaves (navbar + demo banner + footer), rather
    // than a hardcoded 100vh-navbar calc that ignored the demo banner and made
    // the whole page scroll. Matches PublicMapViewerPage's flex-1/min-h-0 layout.
    <div className="flex flex-col flex-1 min-h-0">
      {/* Phase 1040 Plan 04: sr-only aria-live region for keyboard/mouse catalog drag announcements.
          Renders at root of the builder so screen readers in any panel can read it.
          Zero-width-space + timestamp suffix in dragAnnouncement forces aria-live re-fire on
          identical consecutive messages (e.g. two "Drop cancelled." announcements). */}
      <div
        className="sr-only"
        role="status"
        aria-live="polite"
        aria-atomic="true"
        data-testid="dnd-announcement"
      >
        {dragAnnouncement}
      </div>
      {/* fix(#438): A11Y-03 — the builder's heading outline started at <h2>. The
          map name is an editable <input>, not a heading, so this sr-only <h1>
          anchors the outline without altering the visible title bar. */}
      <h1 className="sr-only">
        {mapData?.name
          ? t('titleBar.builderHeading', { name: mapData.name, defaultValue: 'Map builder: {{name}}' })
          : t('common:pageTitle.mapBuilder')}
      </h1>
      {/* fix(#438): UX-06 / LIVE-03 — below 768px the top bar cramps and the
          builder isn't a real editing surface; tell the user rather than
          presenting a broken-looking layout. */}
      {isMobile && (
        <div
          role="status"
          className="flex items-center gap-2 border-b border-warning/30 bg-warning/10 px-3 py-1.5 text-mini text-warning"
        >
          <Info className="size-3.5 shrink-0" aria-hidden="true" />
          <span>{t('builder:mobileNotice', { defaultValue: 'The map builder works best on a larger screen. Some controls are limited here.' })}</span>
        </div>
      )}
      {/* Breadcrumb header bar — title + save status + actions */}
      <MapTitleBar
        name={layers.localName}
        onNameChange={layers.setLocalName}
        description={layers.localDescription}
        onDescriptionChange={layers.setLocalDescription}
        onMarkDirty={layers.markDirty}
        hasUnsavedChanges={layers.hasUnsavedChanges}
        isSaving={save.isSaving}
        saveStatus={save.saveStatus}
        isSaveRetryable={save.isSaveRetryable}
        onSave={save.handleSave}
        onShare={id ? () => dialogs.setShowShare(true) : undefined}
        overflow={{
          onExportPNG: save.handleExportPNG,
          onShowInfo: () => dialogs.setShowInfo(true),
          onFork: save.handleFork,
          isForkPending: save.isForkPending,
          // fix(#430 V-15): new tab so the editor's in-progress builder session
          // (and any unsaved-changes nav guard) is untouched.
          onViewAsViewer: id
            ? () => window.open(`/maps/${id}?preview=viewer`, '_blank', 'noopener,noreferrer')
            : undefined,
        }}
      />

      {/* Phase 1040: single DndContext wraps sidebar (UnifiedStackPanel) and
          BuilderDialogs (Add Dataset modal) so catalog→stack drag shares one
          collision-detection scope. T-1040-02: sensors declared via useSensors
          at MapBuilderPage level so identity is stable across renders. */}
      <DndContext
        sensors={dndSensors}
        accessibility={dndAccessibility}
        collisionDetection={(args) =>
          pointerWithin(args).length > 0 ? pointerWithin(args) : closestCenter(args)
        }
        onDragStart={handleDragStart}
        onDragOver={handleDragOver}
        onDragEnd={handleDragEnd}
        onDragCancel={handleDragCancel}
      >

      <div className="flex flex-1 min-h-0">

      {/* Three-column builder body grid */}
      <div
        className={builderBodyGridClass}
        data-builder-editor-open={isEditorOpen}
      >
        {/* Column 1: sidebar (340px full or 64px rail at <1100px) */}
        <aside
          data-testid="builder-sidebar"
          aria-label={t('layers.title')}
          className="border-e bg-background flex flex-col overflow-hidden"
        >
          {/* fix(#394) UX-01/B-027: recoverable boundary — a stack-panel render
              error must not take down the whole builder (map + chat stay up). */}
          <PanelErrorBoundary panelId="builder-sidebar">
          {isRail ? (
            <SidebarRail
              layers={layers.localLayers}
              selectedLayerId={layers.expandedLayerId}
              onSelectLayer={handleSelectLayer}
              onAddDataClick={handleAddDataClick}
              onSettingsClick={() => {
                layers.handleToggleExpand(
                  layers.expandedLayerId === 'settings' ? '' : 'settings',
                );
              }}
              isSettingsOpen={editorScene === 'settings'}
              basemapGroup={basemapGroup ? { id: 'basemap-group' } : null}
            />
          ) : (
            <UnifiedStackPanel
              layers={layers.localLayers}
              // fix(#430 V-17): drives the per-layer "hidden from public viewers"
              // badge — mapData is undefined only during initial load, before
              // the stack panel has anything to render anyway.
              mapVisibility={mapData?.visibility}
              drawsNothingLayerIds={drawsNothingLayerIds}
              selectedLayerId={layers.expandedLayerId}
              onSelectLayer={handleSelectLayer}
              // fix(v1.6.0 audit D7): the row handlers here are memoized
              // useCallbacks (defined next to handleSelectLayer) — the previous
              // inline lambdas re-created every render and defeated the
              // UnifiedStackPanel → StackRow memo chain.
              onToggleVisibility={handleRowToggleVisibility}
              onReorder={handleRowReorder}
              onOpacityChange={handleRowOpacityChange}
              onRemove={handleRowRemove}
              onRename={layers.handleDisplayNameChange}
              onDuplicate={handleRowDuplicate}
              onZoomToLayer={layers.handleZoomToLayer}
              onAnalyzeLayer={handleAnalyzeLayer}
              onCopyStyle={layers.handleCopyStyle}
              onPasteStyle={layers.handlePasteStyle}
              onBulkApplyStyle={handleBulkApplyStyle}
              copiedStyleGeometryClass={layers.copiedStyleGeometryClass}
              onKeyboardReorder={handleRowKeyboardReorder}
              // fix(#759): the keyboard reorder mode shares the pointer
              // path's aria-live region instead of staying silent.
              onAnnounce={announce}
              onAddDataClick={handleAddDataClick}
              onAddDataset={handlePanelAddDataset}
              onSettingsClick={handlePanelSettingsClick}
              isSettingsOpen={editorScene === 'settings'}
              activeDragId={dragActiveId}
              groupMeta={layers.groupMeta}
              onToggleGroupExpand={layers.handleToggleGroupExpand}
              basemapGroup={basemapGroup}
              isBasemapExpanded={isBasemapExpanded}
              onToggleSublayerVisibility={handleToggleSublayerVisibility}
              onSublayerOpacityChange={handleSublayerOpacityChange}
              onToggleBasemapVisibility={handleToggleBasemapVisibility}
              onSwapBasemap={handleSwapBasemapClick}
              onResetBasemapAppearance={handleResetBasemapAppearance}
              onRenameGroup={layers.handleRenameGroup}
              onAddLayerToGroup={handleAddLayerToFolderGroup}
              onUngroup={layers.handleUngroup}
              onDeleteGroup={layers.handleDeleteGroup}
              onAddLayerToExistingGroup={layers.handleAddLayerToExistingGroup}
              onCreateGroupWithLayer={layers.handleCreateGroupWithLayer}
              onMoveLayerOutOfGroup={layers.handleMoveLayerOutOfGroup}
              existingFolderGroups={existingFolderGroups}
              selectedIds={selectedIds}
              isMultiSelectionActive={isMultiSelectionActive}
              selectableRowIds={selectableRowIds}
              // fix(#771): hybrid-controlled search so selectableRowIds above
              // tracks exactly what the panel renders.
              layerSearch={layerSearch}
              onLayerSearchChange={setLayerSearch}
              onCmdClick={handleCmdClick}
              onShiftClick={handleShiftClick}
              onCheckboxClick={handleCheckboxClick}
              onClearSelection={handleClearSelection}
              onBulkVisibility={handleBulkVisibility}
              onBulkOpacity={handleBulkOpacity}
              onBulkGroup={handleBulkGroup}
              onBulkUngroup={handleBulkUngroup}
              onBulkDelete={handleBulkDelete}
              isDeleting={layers.isDeleting}
              deletingCount={layers.deletingCount}
              freshLayerId={layers.freshLayerId}
              basemapPosition={basemapState.config.basemap_position ?? 'bottom'}
              // fix(#1009): the ephemeral preview as a non-persisting row pinned
              // above the sortable region. Not a member of `layers`, so it can
              // never be reordered, styled, grouped, or saved into the map.
              preview={previewRowProps}
            />
          )}
          {/* Sidebar-placement plugins render below the layer stack. No built-in
              uses { mode: 'sidebar' } today, so PluginSidebar returns null and
              this is inert — but it keeps the declared sidebar placement mode
              actually reachable for third-party plugins (plugin-audit finding). */}
          {!isRail && <PluginSidebar plugins={sidebarPlugins} ctx={pluginCtx} />}
          </PanelErrorBoundary>
        </aside>

        {/* Column 2: LayerEditorPanel flyout (380px) — when layer selected or basemap/settings scene active; viewport >= 800px */}
        {isEditorOpen && !isEditorHidden && (
          // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions -- container-level Escape shortcut for keystrokes bubbling from the panel's own interactive children; the aside itself stays non-interactive
          <aside
            data-testid="builder-layer-editor"
            aria-label={t('layerEditor.tabsLabel')}
            className="border-e bg-background flex flex-col overflow-hidden"
            onKeyDown={(e) => {
              // fix(#394) UX-02/B-015: Escape closes the desktop editor flyout —
              // the <800px Sheet gets this from Radix for free. Only fires when
              // focus is inside the flyout; nested Radix popovers/selects portal
              // to <body>, so an open picker's Escape never reaches this aside.
              if (e.key === 'Escape' && !e.defaultPrevented) {
                e.stopPropagation();
                handleCloseEditor();
              }
            }}
          >
            <LazyLoadErrorBoundary>
              <Suspense fallback={<SceneSpinnerFallback />}>
              <LayerEditorPanel
                key={layers.expandedLayerId ?? 'no-layer'}
                layer={editorLayer!}
                savedLayer={editingSavedLayer}
                onClose={handleCloseEditor}
                isDrillDown={false}
                handlers={layerEditorHandlers}
                activeTab={layers.activeEditorTab}
                editorScene={panelEditorScene}
                sceneContent={sceneContent ?? undefined}
                sceneFooter={sceneFooter ?? undefined}
                breadcrumbPresetName={breadcrumbPresetName}
                onBreadcrumbClick={onBreadcrumbClick}
                featureCount={filteredFeatureCount}
              />
              </Suspense>
            </LazyLoadErrorBoundary>
          </aside>
        )}

        {/* BSR-13: <800px drill-down — Sheet overlay when editor is hidden but a layer/scene is active */}
        {isEditorHidden && isEditorOpen && (
          <Sheet
            open={true}
            onOpenChange={(open) => { if (!open) handleCloseEditor(); }}
          >
            <SheetContent
              side="right"
              showCloseButton={false}
              /* RESP-03 (Phase 1051 Plan 10): suppress shadcn Sheet's
                 built-in auto-close X. The wrapped LayerEditorPanel already
                 owns its canonical close affordance (header X at
                 LayerEditorPanel.tsx:316-325 with aria-label
                 "Close layer editor"). Pre-fix this overlay rendered TWO
                 close buttons. See regression test
                 MapBuilderPage.sheet-close-button.test.tsx. */
              // MAP-07: 48px top offset clears the MapTitleBar so the right-sidebar Sheet does not
              // visually overlap the top-left NavigationControl at ≤800px. NavigationControl stays
              // `top-left` per Pitfall #10; this is the sidebar-side fix.
              className="mt-12 h-[calc(100%-3rem)] w-full max-w-[380px] p-0 flex flex-col"
            >
              <SheetHeader className="sr-only">
                <SheetTitle>
                  {editorLayer?.display_name ?? editorLayer?.dataset_name ?? t('layerEditor.close', { defaultValue: 'Close layer editor' })}
                </SheetTitle>
                <SheetDescription>
                  {t('layerEditor.section.appearance', { defaultValue: 'Appearance' })}
                </SheetDescription>
              </SheetHeader>
              <LazyLoadErrorBoundary>
                <Suspense fallback={<SceneSpinnerFallback />}>
                <LayerEditorPanel
                  key={layers.expandedLayerId ?? 'no-layer'}
                  layer={editorLayer!}
                  savedLayer={editingSavedLayer}
                  onClose={handleCloseEditor}
                  isDrillDown={true}
                  handlers={layerEditorHandlers}
                  activeTab={layers.activeEditorTab}
                  editorScene={panelEditorScene}
                  sceneContent={sceneContent ?? undefined}
                  sceneFooter={sceneFooter ?? undefined}
                  breadcrumbPresetName={breadcrumbPresetName}
                  onBreadcrumbClick={onBreadcrumbClick}
                  featureCount={filteredFeatureCount}
                />
                </Suspense>
              </LazyLoadErrorBoundary>
            </SheetContent>
          </Sheet>
        )}

        {/* Column 3 (or 2 when no editor): map canvas */}
        <div className="relative min-h-0 min-w-0">
          <MapErrorBoundary hasUnsavedChanges={layers.hasUnsavedChanges}>
            <Suspense fallback={<LoadingState />}>
              <BuilderMap
                layers={layers.localLayers}
                // Phase 1199 STACK-02: when the basemap is toggled off (session-local),
                // render the blank basemap so imagery disappears while data layers remain.
                basemapStyle={basemapVisible ? basemapState.basemapStyle : BLANK_BASEMAP_ID}
                initialViewState={layers.initialViewState}
                terrainConfig={basemapState.terrainConfig}
                onMapRef={handleMapRef}
                showBasemapLabels={basemapState.showBasemapLabels}
                basemapConfig={basemapState.config}
              />
            </Suspense>
          </MapErrorBoundary>
          {/* fix(#1009): the preview's surface is the stack row above — but the
              stack panel only exists at ≥1100px; below that the sidebar
              collapses to SidebarRail, which has no rows. Keep the badge for
              exactly that case, so the narrow layout doesn't lose the count,
              the dismiss, and the #675 hand-off altogether. Still one surface
              at a time, never both. */}
          {isRail && previewRowProps && (
            <EphemeralBadge
              featureCount={previewRowProps.featureCount}
              onDismiss={previewRowProps.onDismiss}
              truncated={previewRowProps.truncated}
              totalCount={previewRowProps.totalCount}
              viewportScoped={previewRowProps.viewportScoped}
              onSaveAsDataset={previewRowProps.onSaveAsDataset}
              saveDisabledReason={previewRowProps.saveDisabledReason}
            />
          )}

          {/* Centered toolbar */}
          <MapToolbar
            onStyleJsonClick={() => setShowStyleJson(true)}
            onShortcutsClick={() => setShowShortcuts(true)}
          />
          {isEditorHidden && (
            <div className="absolute end-2 top-16 z-30 flex flex-col gap-1 rounded-md border bg-background/95 p-1 shadow-md backdrop-blur-sm">
              {mobileRailButtons.map((btn) => (
                <button
                  key={btn.id}
                  type="button"
                  onClick={btn.disabled ? undefined : () => setRailPanel(btn.id)}
                  disabled={btn.disabled}
                  data-unavailable={btn.unavailable || undefined}
                  title={btn.label}
                  // MAP-22 rework: notes-presence folds into the button's own
                  // accessible name (aria-label replaces the subtree, so a
                  // label on the dot span was never exposed).
                  aria-label={
                    btn.id === 'notes' && dockNotes.trim().length > 0
                      ? t('rail.notesButtonWithNotes', { defaultValue: 'Notes (map has notes)' })
                      : btn.label
                  }
                  aria-pressed={railPanel === btn.id}
                  // fix(#760): mirrors BuilderRail's feat(#682) job signal.
                  aria-busy={btn.id === 'analysis' && analysisJobRunning}
                  className={cn(
                    'relative flex h-11 w-11 items-center justify-center rounded-md transition-colors',
                    btn.disabled
                      ? 'cursor-not-allowed text-muted-foreground/40'
                      : railPanel === btn.id
                        ? 'bg-accent text-primary'
                        : 'text-muted-foreground hover:bg-accent hover:text-foreground',
                  )}
                >
                  {btn.id === 'analysis' && analysisJobRunning ? (
                    <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                  ) : (
                    <btn.icon className="h-4 w-4" aria-hidden="true" />
                  )}
                  {/* MAP-22: presence dot on mobile Notes button — mirrors the
                      BuilderRail rail-button dot (search for MAP-22 there).
                      BuilderRail is hidden at <800px (isEditorHidden); this dot keeps
                      MAP-22 parity at 414×896. Decorative: the state is announced via
                      the button's conditional aria-label above. */}
                  {btn.id === 'notes' && dockNotes.trim().length > 0 && (
                    <span
                      aria-hidden="true"
                      className="absolute -top-0.5 -end-0.5 size-1.5 rounded-full bg-primary"
                    />
                  )}
                </button>
              ))}
            </div>
          )}

          <PluginHost
            byAnchor={byAnchor}
            ctx={pluginCtx}
            topLeftSlot={
              <ActiveFilterChips
                layers={layers.localLayers}
                onClearFilter={handleClearFilter}
              />
            }
          />
        </div>
      </div>

      {/* Right rail + panel */}
      {/* fix(#527 B-054/U-08): boundary parity with the sidebar/map — a
          HistoryPanel/Notes render error must not take down the builder. */}
      {!isEditorHidden && (
        <PanelErrorBoundary panelId="builder-rail">
          <BuilderRail {...railProps} />
        </PanelErrorBoundary>
      )}

      {/* Mobile rail as Sheet overlay */}
      {isEditorHidden && railPanel && (
        <Sheet open={!!railPanel} onOpenChange={(open) => { if (!open) setRailPanel(null); }}>
          <SheetContent
            side="right"
            showCloseButton={false}
            /* RESP-03 (Phase 1051 Plan 10): suppress shadcn Sheet's
               built-in auto-close X. The wrapped BuilderRail expanded panel
               already owns its canonical close affordance (ChevronRight at
               BuilderRail.tsx:125-132 with aria-label "Close panel"). */
            // MAP-07: 48px top offset clears the MapTitleBar so the right-sidebar Sheet does not
            // visually overlap the top-left NavigationControl at ≤800px. NavigationControl stays
            // `top-left` per Pitfall #10; this is the sidebar-side fix.
            className="mt-12 h-[calc(100%-3rem)] w-[22rem] max-w-[calc(100vw-5rem)] p-0 flex flex-col"
          >
            <SheetHeader className="sr-only">
              <SheetTitle>{railSheetTitle}</SheetTitle>
              <SheetDescription>{railSheetDescription}</SheetDescription>
            </SheetHeader>
            <PanelErrorBoundary panelId="builder-rail-sheet">
              <BuilderRail {...railProps} showRail={false} />
            </PanelErrorBoundary>
          </SheetContent>
        </Sheet>
      )}

      </div>{/* close flex flex-1 min-h-0 wrapper */}

      <BuilderDialogs
        mapId={id}
        mapData={mapData}
        showAddData={dialogs.showAddData}
        onShowAddDataChange={(open: boolean) => {
          dialogs.setShowAddData(open);
          if (!open) {
            dialogs.setAddDataInitialQuery('');
            // ux(#776): the deferred editor-open — once per dialog session,
            // on the most recently added layer.
            if (pendingEditorLayerIdRef.current) {
              handleSelectLayer(pendingEditorLayerIdRef.current);
              pendingEditorLayerIdRef.current = null;
            }
          }
        }}
        addDataInitialQuery={dialogs.addDataInitialQuery}
        onAddDataset={(datasetId: string) => {
          layers.handleAddDataset(datasetId, (newLayerId) => {
            // ux(#776): keep the dialog open for multi-add — the row flips to
            // "Added ✓" and Escape/backdrop/X still close it. The editor
            // opens on close (see onShowAddDataChange above) instead of
            // landing behind the dialog.
            pendingEditorLayerIdRef.current = newLayerId;
          });
        }}
        onDuplicateRendering={(layerId) => layers.dispatchLayerAction({
          type: 'duplicate_rendering',
          source: 'manual',
          layerId,
        })}
        layers={layers.localLayers}
        isAdding={addLayer.isPending}
        // fix(#526 B-050): which dataset is in flight — the global isAdding
        // flag disabled every Add button with no per-row feedback, so the user
        // couldn't tell whether their click registered.
        addingDatasetId={addLayer.isPending ? (addLayer.variables?.data?.dataset_id ?? null) : null}
        showShare={dialogs.showShare}
        onShowShareChange={dialogs.setShowShare}
        hasUnsavedChanges={layers.hasUnsavedChanges}
        saveStatus={save.saveStatus}
        showInfo={dialogs.showInfo}
        onShowInfoChange={dialogs.setShowInfo}
        blockerState={save.blocker.state}
        onBlockerReset={save.blocker.reset}
        onBlockerProceed={save.blocker.proceed}
      />

      </DndContext>{/* close Phase 1040 DndContext */}

      {/* SF-03 (Phase 1049): gate the StyleJsonDialog mount on `showStyleJson`,
          not just on `id`. The previous form always mounted the dialog (it just
          returned null when closed), which made React.lazy() resolve the import
          on initial builder paint — defeating the whole PB-05 lazy-load split. */}
      {id && showStyleJson && (
        <LazyLoadErrorBoundary>
          <Suspense fallback={null}>
            <StyleJsonDialog
              mapId={id}
              mapName={layers.localName}
              open={showStyleJson}
              onOpenChange={setShowStyleJson}
            />
          </Suspense>
        </LazyLoadErrorBoundary>
      )}

      {/* feat(#1241): snapshot a chat query preview into a real dataset.
          Mounted only while open, for the same reason StyleJsonDialog above is
          — an always-mounted lazy component resolves its import on first paint
          and the split buys nothing. */}
      {chatSaveDraft && (
        <LazyLoadErrorBoundary>
          <Suspense fallback={null}>
            <SaveChatPreviewDialog
              open
              onOpenChange={(open) => { if (!open) setChatSaveDraft(null); }}
              geojson={chatSaveDraft.geojson}
              prompt={chatSaveDraft.prompt}
            />
          </Suspense>
        </LazyLoadErrorBoundary>
      )}

      {/* A11Y-05 (Phase 1204-03): keyboard shortcut cheat-sheet overlay.
          Not lazy-loaded — component is small and needed on first ? keypress. */}
      <KeyboardShortcutsSheet
        open={showShortcuts}
        onOpenChange={setShowShortcuts}
      />
    </div>
  );
}
