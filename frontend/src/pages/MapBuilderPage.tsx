import { lazy, Suspense, useState, useEffect, useRef, useCallback, useMemo, type ReactNode } from 'react';
import { useParams, Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { FileText, History, Sparkles, Info, FlaskConical, Loader2, LayoutDashboard } from 'lucide-react';
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
// Lazy so the map-vendor chunk loads only when the builder is about to render.
const BuilderMap = lazy(() =>
  import('@/components/builder/BuilderMap').then((m) => ({ default: m.BuilderMap }))
);
import { UnifiedStackPanel } from '@/components/builder/UnifiedStackPanel';
// Lazy so each editor scene ships in its own chunk, fetched on first open.
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
import { AttributeTableDrawer } from '@/components/builder/AttributeTableDrawer';
import { EphemeralBadge } from '@/components/builder/EphemeralBadge';
import { previewSaveMode } from '@/components/builder/ephemeral-preview';
// Lazy: it pulls in the import page's metadata form and is mounted only while
// open.
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
import { useMap, useAddLayer, useRemoveLayer, useLayersHiddenFromMapGroups } from '@/hooks/use-maps';
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
import { registerAnalysisAddToMap, useAnalysisJobStore } from '@/stores/analysis-job-store';
import { takeChatResult } from '@/lib/chat-result-handoff';
import { useBuilderEntryIntent } from '@/hooks/use-builder-entry-intent';

export function MapBuilderPage() {
  const { id } = useParams<{ id: string }>();
  // The intent is read once at mount, so useBuilderSave can defer the first
  // auto-capture until the layer-add effect has synced, whichever of the API
  // and the canvas init wins the race.
  const entryIntent = useBuilderEntryIntent();
  const pendingLayerAdd = entryIntent.addDatasetId !== undefined;
  const chatResultPendingRef = useRef(entryIntent.chatResult === true);
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
  // Saving a chat preview creates a dataset through POST /ingest/*, which
  // needs the caller's own `upload` capability; the map's edit rights say
  // nothing about it. can() is false while the query is in flight, so the
  // affordance appears only once the capability is known.
  //
  // `export` too: the snapshot is a caller-owned copy of source attributes the
  // caller may only be able to READ, which is why analysis materialize requires
  // both (router_analysis.py). Ingest asks only for `upload` because its file
  // comes from the caller's machine; this one's does not, so the client must
  // not offer a path around that boundary under a customized role matrix.
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
  // Chat run_analysis preview → Analysis panel handoff. The nonce remounts the
  // panel so successive handoffs re-apply the prefill.
  const [analysisPrefill, setAnalysisPrefill] = useState<
    (EphemeralAnalysisHandoff & { nonce: number }) | null
  >(null);
  const [dockNotes, setDockNotes] = useState('');
  const [localProjection, setLocalProjection] = useState<'mercator' | 'globe'>('mercator');
  const [showStyleJson, setShowStyleJson] = useState(false);
  const [showShortcuts, setShowShortcuts] = useState(false);
  // Session-local and deliberately not persisted to MapBasemapConfig (a new
  // backend field would hit the extra=forbid silent-422 class). Hiding renders
  // BLANK_BASEMAP_ID in the live map while the stack row's preset name still
  // derives from the real basemap style.
  const [basemapVisible, setBasemapVisible] = useState(true);
  const [viewport, setViewport] = useState<ViewportContext | undefined>(undefined);

  // One DndContext wraps both the sidebar stack and the Add Dataset modal so
  // catalog→stack drags work: @dnd-kit collision detection only fires within a
  // single DndContext.
  const [dragActiveId, setDragActiveId] = useState<string | null>(null);

  // Lifted here so handleDragStart can clear it (drag and multi-select are
  // mutually exclusive).
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const lastToggleAnchor = useRef<string | null>(null);
  // Selected rows the layer search hides are parked here rather than pruned,
  // and rejoin the selection when the search stops hiding them. Every explicit
  // selection interaction (Escape/outside click, drag-start, bulk actions,
  // cmd/shift clicks) clears it so stale rows cannot resurrect a selection the
  // user's gesture discarded.
  const searchHiddenSelectionRef = useRef<Set<string>>(new Set());
  // Lifted from UnifiedStackPanel so selectableRowIds can be derived from the
  // RENDERED row set: a shift-click range must never sweep rows the search
  // filtered out or that sit inside a collapsed group.
  const [layerSearch, setLayerSearch] = useState('');

  // Read by an sr-only aria-live region for keyboard/mouse catalog drag.
  const [dragAnnouncement, setDragAnnouncement] = useState('');
  const lastOverIdRef = useRef<string | null>(null);

  const announce = useCallback((text: string) => {
    // The zero-width space and timestamp make aria-live re-announce identical
    // consecutive messages.
    setDragAnnouncement(text + '\u200B' + Date.now());
  }, []);
  const dndSensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: {
        distance: 8, // px
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
      removeStorage(storageKeys.mapNotes(id ?? ''));
    } else {
      setDockNotes(readStorage(storageKeys.mapNotes(id ?? '')) ?? '');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- run once when mapData loads
  }, [mapData?.notes, id]);

  const dialogs = useBuilderDialogs();
  // Bridges useBuilderLayers to useBuilderSave, which is called after it.
  // useBuilderSave fills it with a function that registers a server-created
  // layer into the Save-diff baseline; the layer hook calls it after a
  // layer-create mutation so Save never re-diffs that layer as `added` and
  // PATCHes a duplicate. See use-builder-save.ts.
  const saveBaselineSyncRef = useRef<SaveBaselineSync>({ add: () => {}, remove: () => {} });
  const layers = useBuilderLayers(
    mapData,
    mapInstanceRef,
    id,
    addLayer,
    removeLayer,
    saveBaselineSyncRef,
    // Reactive counterpart of mapInstanceRef: lets the auto-zoom watcher retry
    // once a still-loading map is ready instead of losing an early zoom.
    mapInstance,
    entryIntent.addDatasetId,
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
    handleRenderAsChange,
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
  const handleToggleBasemapVisibility = useCallback(
    () => setBasemapVisible((v) => !v),
    [],
  );
  // String keys give the restore effect value-equality deps. mapData refetches
  // produce shape-equivalent but identity-different plugin arrays, so raw
  // `[mapData?.plugins, enabledPluginIds]` deps would reset the user's local
  // plugin toggles on every background refetch.
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
    // eslint-disable-next-line react-hooks/exhaustive-deps -- see the block comment above
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
    dashboard: layers.dashboard,
    savedDashboard: layers.savedDashboard,
    dashboardEdited: layers.dashboardEdited,
    onDashboardSave: layers.beginDashboardSave,
    mapInstanceRef,
    setHasUnsavedChanges: layers.setHasUnsavedChanges,
    hasUnsavedChanges: layers.hasUnsavedChanges,
    hasUnsavedEdits: layers.hasUnsavedEdits,
    hasThumbnail: !!mapData?.thumbnail_url,
    pendingLayerAdd,
    saveBaselineSyncRef,
    saveFence: layers.saveFence,
  });

  const handleMapRef = useCallback((map: MaplibreMap | null) => {
    mapInstanceRef.current = map;
    setMapInstance(map);
    if (map) save.maybeAutoCaptureThumbnail(map);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only the method reference matters, not the whole `save` object
  }, [save.maybeAutoCaptureThumbnail]);

  // DatasetChatPanel stashes its last spatial query result in sessionStorage
  // before navigating here; render it through the ephemeral-layer path. Gated
  // on mapInstance (not mapData) so it never fires against a null map ref.
  const handleChatQueryResult = layers.handleQueryResult;
  useEffect(() => {
    if (!mapInstance || !chatResultPendingRef.current) return;
    chatResultPendingRef.current = false;
    const result = takeChatResult();
    // Forward the completeness pair too: without it a clipped result reads as
    // complete and a save would persist it as the whole answer.
    if (result) {
      handleChatQueryResult(result.geojson, result.bbox, {
        ...(result.truncated ? { truncated: true } : {}),
        ...(result.totalCount != null ? { totalCount: result.totalCount } : {}),
        ...(result.prompt ? { prompt: result.prompt } : {}),
      });
    }
  }, [mapInstance, handleChatQueryResult]);

  const pluginCtx = useMemo(
    () => ({
      mapInstance,
      layers: layers.localLayers,
      mapId: id!,
      terrainConfig: layers.localTerrainConfig,
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

  // Viewport context for viewport-aware suggestion chips, updated on map idle
  // with a 500ms debounce.
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
    onRenderModeChange: handleRenderAsChange,
    onRemove: (layerId) => dispatchLayerAction({
      type: 'remove_layer',
      source: 'manual',
      layerId,
      persistence: 'server',
    }),
    // The revert re-marks the map dirty via the handlers above, so ask the
    // baseline owner to re-derive; it clears only when the WHOLE map is clean.
    onRevertToSaved: layers.requestCleanRecheck,
  }), [dispatchLayerAction, handleRenderAsChange, handleTabChange, layers.requestCleanRecheck]);

  // The dock's notes live in page state the layers hook cannot compare against
  // server data, so this is the OPAQUE marker. Controls whose fields the hook
  // does compare (name/description, basemap swap/remove) use plain markDirty.
  const handleMarkDirty = layers.markOpaqueDirty;

  // Plugin toggles live outside the layer state that drives hasUnsavedChanges,
  // so mark the map dirty here or the save indicator and unsaved-changes nav
  // guard miss plugin-only edits.
  const handleTogglePlugin = useCallback(
    (pluginId: string) => {
      togglePlugin(pluginId);
      layers.markOpaqueDirty();
    },
    [togglePlugin, layers],
  );

  // Persisted on basemap_config.projection; the basemap patch marks the map
  // dirty.
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

  // Keyed on the saved value so background refetches don't clobber an unsaved
  // local projection change.
  const savedProjection = mapData?.basemap_config?.projection ?? 'mercator';
  useEffect(() => {
    setLocalProjection(savedProjection);
  }, [savedProjection]);

  // Globe requires a loaded style, so gate on isStyleLoaded with an idle
  // fallback.
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

  // '?' opens the shortcut cheat-sheet, except while typing in a field or when
  // a dialog is already open (same guard as Ctrl/Cmd+S in use-builder-save.ts).
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

  const { data: basemaps = [] } = useBasemaps();

  // Derived from the canonical controller state, not runtime-only sublayer
  // state. A blank basemap ("No basemap") still returns a minimal group so the
  // stack keeps a "Basemap · No basemap" row: the preset-picker flyout is the
  // only way to choose a real basemap again, and an empty-sublayer group
  // renders cleanly there.
  const basemapGroup = useMemo(() => {
    if (!basemapState.hasVisibleBasemap) {
      return {
        id: 'basemap-group',
        presetName: t('basemapGroup.noBasemap', { defaultValue: 'No basemap' }),
        providerLabel: undefined,
        visible: basemapVisible,
        opacity: basemapState.config.opacity ?? 1,
        sublayers: [],
        // Compared semantically: the stored config is often a materialized
        // all-defaults object, so a non-null check would read every map as
        // customized.
        hasCustomAppearance: hasCustomBasemapAppearance(layers.basemapConfig, layers.showBasemapLabels),
      };
    }
    const presetId = basemapState.basemapStyle;
    const presetName = presetId
      .replace(/^(openfreemap-|carto-|mapbox-|maptiler-|esri-|stamen-|stadia-)/, '')
      .replace(/-/g, ' ')
      .replace(/\b\w/g, (c) => c.toUpperCase()) || t('search.basemap', { defaultValue: 'Basemap' });

    return {
      id: 'basemap-group',
      presetName,
      providerLabel: undefined,
      visible: basemapVisible,
      opacity: basemapState.config.opacity ?? 1,
      sublayers: basemapState.sublayers,
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

  // 'group' means the editor is closed, so LayerEditorPanel never renders for
  // it and its narrower editorScene prop type excludes it.
  const panelEditorScene: Exclude<BuilderEditorScene, 'group'> =
    editorScene === 'group' ? 'default' : editorScene;

  // Null when no layer is being edited, no filter is set, or the layer isn't
  // on the map yet. Drives the empty-state hint in LayerFilterEditor.
  const filteredFeatureCount = useFilteredFeatureCount(mapInstance, editingLayer ?? null);

  const isBasemapBoundaryId = useCallback((id: string): boolean => {
    if (!basemapGroup) return false;
    if (id === basemapGroup.id) return true;
    return basemapGroup.sublayers.some((s) => s.id === id);
  }, [basemapGroup]);

  // Ordered ids for shift-click ranges and Shift+Arrow, derived from the
  // RENDERED row set (shared helper with UnifiedStackPanel): the raw flat list
  // would let a range select children of collapsed groups and search-hidden
  // rows, so bulk actions would hit rows the user cannot see.
  const selectableRowIds = useMemo(
    (): string[] => computeSelectableRowIds(layers.localLayers, layers.groupMeta, layerSearch),
    [layers.localLayers, layers.groupMeta, layerSearch],
  );

  // Selection ids can outlive their rows (remove, delete/ungroup and the
  // empty-group prune leave selectedIds alone), so prune against the live layer
  // set or the bulk bar over-reports. Skipped while a bulk delete is in
  // flight: its optimistic removal must not eat the preserved-on-failure
  // selection (a full-failure rollback restores the rows in the same commit
  // that clears isDeleting).
  // Also intersect with selectableRowIds so rows hidden by the search or a
  // collapsed group leave the ACTIVE selection. Search-hidden rows are parked
  // and restored once selectable again (search cleared/edited AND not inside a
  // collapsed group); deleted rows are dropped. The park/restore bookkeeping
  // stays outside the updater, which must be idempotent (StrictMode
  // double-invokes updaters).
  useEffect(() => {
    if (layers.isDeleting) return;
    const liveIds = new Set(layers.localLayers.map((layer) => layer.id));
    const selectable = new Set(selectableRowIds);
    const parked = searchHiddenSelectionRef.current;
    // Park only rows the SEARCH itself hides: a child hidden by its collapsed
    // group stays pruned, since restoring it on a later expand would resurrect
    // a selection the collapse discarded. Recomputing the selectable set with
    // every group expanded isolates the search predicate: a live row absent
    // from THIS set fails the search; one present here but missing from
    // selectableRowIds is hidden by collapse alone.
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
    // A row stays parked only while it would be selectable the moment the
    // search cleared: the search must be what hides it AND its group must be
    // expanded under the REAL group state. A collapse discards the row
    // wherever it happens, even while the force-expanded searchHiddenIds still
    // lists it.
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
        // Add-only, so safe under a double-invoked updater.
        if (liveIds.has(rowId) && searchHiddenIds?.has(rowId)) parked.add(rowId);
      }
      for (const rowId of restored) {
        if (!next.has(rowId)) { next.add(rowId); changed = true; }
      }
      return changed ? next : prev;
    });
  }, [layers.localLayers, layers.groupMeta, layers.isDeleting, selectableRowIds, layerSearch]);

  // Plain, shift and cmd clicks share one anchor in `lastToggleAnchor`.
  const handleCmdClick = useCallback((id: string) => {
    if (isBasemapBoundaryId(id)) return;
    // The gesture supersedes search-parked rows; keeping them would resurrect
    // discarded rows once the search clears.
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
    // A range gesture replaces the selection, so parked rows must not outlive
    // it.
    searchHiddenSelectionRef.current.clear();
    setSelectedIds((prev) => {
      const { selection, anchor } = computeNextSelection(
        selectableRowIds,
        id,
        { shiftKey: true, metaKey: false, ctrlKey: false },
        prev,
        lastToggleAnchor.current,
      );
      // The range may include basemap-boundary ids if selectableRowIds drifts.
      const filtered = new Set<string>();
      for (const rid of selection) {
        if (!isBasemapBoundaryId(rid)) filtered.add(rid);
      }
      lastToggleAnchor.current = anchor;
      return filtered;
    });
  }, [isBasemapBoundaryId, selectableRowIds]);

  // A plain row click records the anchor so a later shift-click has a range
  // start, without disturbing handleSelectLayer's editor flow.
  const handlePlainSelectAnchor = useCallback((id: string | null) => {
    if (id && !isBasemapBoundaryId(id)) {
      lastToggleAnchor.current = id;
    }
  }, [isBasemapBoundaryId]);

  const handleCheckboxClick = useCallback((id: string) => {
    handleCmdClick(id);
  }, [handleCmdClick]);

  // Also drops search-parked rows so a dismissed selection doesn't resurrect
  // when the search clears.
  const resetMultiSelection = useCallback(() => {
    setSelectedIds(new Set());
    searchHiddenSelectionRef.current.clear();
  }, []);

  const handleClearSelection = useCallback(() => {
    resetMultiSelection();
    lastToggleAnchor.current = null;
  }, [resetMultiSelection]);

  // Deps are the specific stable callbacks, not the `layers` literal (new every
  // render): depending on `layers` would defeat React.memo() on BulkActionBar
  // and UnifiedStackPanel on every opacity-slider move (~60fps).
  const handleBulkVisibility = useCallback((ids: Set<string>) => {
    applyBulkVisibility(ids);
    resetMultiSelection();
  }, [applyBulkVisibility, resetMultiSelection]);

  const handleBulkOpacity = useCallback((ids: Set<string>, opacity: number) => {
    // The slider fires onValueChange continuously during a drag; clearing the
    // selection on the first event would empty it for the rest. The user
    // dismisses it via Escape or by clicking another row.
    applyBulkOpacity(ids, opacity);
  }, [applyBulkOpacity]);

  const handleBulkGroup = useCallback((ids: Set<string>) => {
    // An ineligible selection stays intact so the user can read the toast and
    // adjust instead of losing it silently.
    if (applyBulkGroup(ids)) resetMultiSelection();
  }, [applyBulkGroup, resetMultiSelection]);

  const handleBulkUngroup = useCallback((ids: Set<string>) => {
    applyBulkUngroup(ids);
    resetMultiSelection();
  }, [applyBulkUngroup, resetMultiSelection]);

  const handleBulkApplyStyle = useCallback((ids: Set<string>) => {
    applyBulkApplyStyle(ids);
    resetMultiSelection();
  }, [applyBulkApplyStyle, resetMultiSelection]);

  const handleBulkDelete = useCallback((ids: Set<string>) => {
    applyBulkDelete(ids)
      .then((ok) => {
        if (ok) resetMultiSelection();
        // On failure the selection is kept so the user can retry.
      })
      .catch(() => {
        // Already toasted by the bulk handler; this only stops an unhandled
        // rejection if invalidateQueries throws after allSettled.
      });
  }, [applyBulkDelete, resetMultiSelection]);

  const isMultiSelectionActive = selectedIds.size > 0;

  const handleToggleSublayerVisibility = useCallback((sublayerId: string) => {
    applyBasemapPatch(toggleBasemapSublayerVisibility(basemapState, sublayerId));
  }, [applyBasemapPatch, basemapState]);

  const handleSublayerOpacityChange = useCallback((sublayerId: string, opacity: number) => {
    applyBasemapPatch(setBasemapSublayerOpacity(basemapState, sublayerId, opacity));
  }, [applyBasemapPatch, basemapState]);

  // Merges one field into basemap_config.sublayer_overrides[sublayerId],
  // trimming the entry when every field becomes null/undefined.
  const updateSublayerOverride = useCallback(
    (sublayerId: string, field: keyof MapSublayerOverride, value: string | number | null) => {
      applyBasemapPatch(updateBasemapSublayerOverride(basemapState, sublayerId, field, value));
    },
    [applyBasemapPatch, basemapState],
  );

  const handleResetBasemapAppearance = useCallback(() => {
    applyBasemapPatch(resetBasemapAppearance());
  }, [applyBasemapPatch]);

  const existingFolderGroups = useMemo(() => {
    return layers.localLayers
      .filter(isFolderGroupLayer)
      .map((l) => ({ id: l.id, name: l.display_name ?? l.dataset_name ?? 'Group' }));
  }, [layers.localLayers]);

  // Materialize jobs are tracked globally (AnalysisJobWatcher in RootLayout
  // owns polling, the toast and cache invalidation) so the signal survives this
  // page unmounting. This page contributes only the "Add to map" capability.
  const setAnalysisJob = useAnalysisJobStore((s) => s.setJob);
  // The mobile rail buttons (<800px) need the same job signal as the desktop
  // rail.
  const analysisJobRunning = useAnalysisJobStore((s) => !!s.job);
  const handleAnalysisJobChange = useCallback(
    (jobId: string | null, title?: string) => {
      setAnalysisJob(jobId ? { jobId, title: title ?? '', mapId: id ?? null } : null);
    },
    [setAnalysisJob, id],
  );
  // Only a loaded map whose layers have hydrated can take the add, so the
  // loading and error screens below leave an open toast on "View dataset".
  const addAnalysisOutput =
    !error && mapData && layers.layersMapId === id
      ? (layers.chatLayerActions?.onAddDataset ?? null)
      : null;
  // No dep array: keeps the registered callback fresh on every render. The
  // clear runs only on unmount, so an open completion toast hears about this
  // builder arriving, leaving or switching maps, never about a re-render.
  useEffect(() => {
    registerAnalysisAddToMap(addAnalysisOutput, id ?? null);
  });
  useEffect(() => () => registerAnalysisAddToMap(null, null), []);

  // "Save as dataset" on the ephemeral preview: opens the Analysis panel
  // prefilled with the operation behind it.
  const ephemeralAnalysis = layers.ephemeralResult?.analysis;
  const handleSaveAnalysisPreview = useCallback(() => {
    if (!ephemeralAnalysis) return;
    setAnalysisPrefill({ ...ephemeralAnalysis, nonce: Date.now() });
    setRailPanel('analysis');
  }, [ephemeralAnalysis]);

  // Same affordance for a plain chat query result (no analysis behind it). The
  // draft snapshots the FeatureCollection when the dialog opens, so a new chat
  // turn or dismiss mid-dialog can't swap what gets saved.
  const [chatSaveDraft, setChatSaveDraft] = useState<{
    geojson: GeoJSON.FeatureCollection;
    prompt?: string;
  } | null>(null);
  const ephemeralResult = layers.ephemeralResult;
  const handleSaveChatPreview = useCallback(() => {
    if (!ephemeralResult) return;
    setChatSaveDraft({ geojson: ephemeralResult.geojson, prompt: ephemeralResult.prompt });
  }, [ephemeralResult]);

  // Memoized: a fresh object on the UnifiedStackPanel prop would defeat its
  // memo() on every render.
  const previewRowProps = useMemo(() => {
    const result = layers.ephemeralResult;
    if (!result) return null;
    const featureCount = result.geojson.features.length;
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

  // Uses the chat preview's handoff path, so the panel opens (or remounts via
  // the nonce) on exactly this layer even when the row isn't selected.
  const handleAnalyzeLayer = useCallback((layerId: string) => {
    setAnalysisPrefill({ layerId, operation: 'buffer', nonce: Date.now() });
    setRailPanel('analysis');
  }, []);

  // The open attribute-table drawer holds one layer id; opening another
  // layer's table replaces the current one, and a removed layer closes it.
  const [attributeTableLayerId, setAttributeTableLayerId] = useState<string | null>(null);
  const attributeTableLayer = useMemo(
    () => layers.localLayers.find((l) => l.id === attributeTableLayerId) ?? null,
    [layers.localLayers, attributeTableLayerId],
  );
  // What opened the table, so closing it returns focus there: the layer's
  // kebab trigger on the stack path, the editor's open-attribute-table button
  // on the editor path.
  const attributeTableOpenerRef = useRef<{ path: 'stack' | 'editor'; layerId: string } | null>(null);
  // One focus return per close, whether the ✕, a second activation of the
  // opener, or the layer's removal closed the table.
  const attributeTableWasOpenRef = useRef(false);
  useEffect(() => {
    const isOpen = attributeTableLayer !== null;
    if (!isOpen && attributeTableLayerId !== null) setAttributeTableLayerId(null);
    const wasOpen = attributeTableWasOpenRef.current;
    attributeTableWasOpenRef.current = isOpen;
    if (!wasOpen || isOpen) return;
    // Same pattern as handleCloseEditor: focus lands inside
    // requestAnimationFrame; the opener row may be gone (layer deleted while
    // open), where the first stack row keeps focus out of <body> — the same
    // known limit: zero remaining rows leaves focus on <body>.
    const opener = attributeTableOpenerRef.current;
    attributeTableOpenerRef.current = null;
    requestAnimationFrame(() => {
      const openerEl = opener
        ? opener.path === 'stack'
          // Below 1100px the rail replaces the stack rows.
          ? document
            .getElementById(`stack-row-${opener.layerId}`)
            ?.querySelector<HTMLElement>('[data-kebab-trigger]')
            ?? document.querySelector<HTMLElement>(`[data-rail-layer-id="${CSS.escape(opener.layerId)}"]`)
          : document.querySelector<HTMLElement>('[data-testid="layer-editor-open-attribute-table"]')
        : null;
      (openerEl ?? document.querySelector<HTMLElement>('[data-row-id]'))?.focus();
    });
  }, [attributeTableLayer, attributeTableLayerId]);

  const handleCloseAttributeTable = useCallback(() => {
    setAttributeTableLayerId(null);
  }, []);
  // A second activation of the same entry point closes the table; a different
  // layer's activation replaces it.
  const handleOpenAttributeTable = useCallback(
    (layerId: string, path: 'stack' | 'editor' = 'stack') => {
      if (attributeTableLayerId === layerId) {
        handleCloseAttributeTable();
        return;
      }
      attributeTableOpenerRef.current = { path, layerId };
      setAttributeTableLayerId(layerId);
    },
    [attributeTableLayerId, handleCloseAttributeTable],
  );

  // Clearing on any navigation away from the panel keeps a later ordinary
  // opening from remounting the form with stale handoff params.
  useEffect(() => {
    if (railPanel !== 'analysis' && analysisPrefill) setAnalysisPrefill(null);
  }, [railPanel, analysisPrefill]);

  const railProps = useMemo(() => ({
    activePanel: railPanel,
    onPanelChange: setRailPanel,
    aiAvailable: !!aiAvailable,
    notes: dockNotes,
    onNotesChange: setDockNotes,
    dashboard: layers.dashboard,
    onDashboardChange: layers.handleDashboardChange,
    map: mapInstance,
    mapId: id,
    layers: layers.localLayers,
    layersMapId: layers.layersMapId,
    // Lets the Analysis panel open on the selected row instead of the first
    // eligible layer.
    selectedLayerId: layers.expandedLayerId,
    layerActions: layers.chatLayerActions,
    onQueryResult: layers.handleQueryResult,
    mapInstanceRef,
    onClearPreview: layers.handleDismissEphemeral,
    hasPreview: !!layers.ephemeralResult,
    previewSource: layers.ephemeralResult?.source,
    analysisPrefill,
    onAnalysisJobChange: handleAnalysisJobChange,
    onMarkDirty: handleMarkDirty,
    viewport,
  }), [railPanel, aiAvailable, dockNotes, layers.dashboard, layers.handleDashboardChange, mapInstance, id, layers.localLayers, layers.layersMapId, layers.expandedLayerId, layers.chatLayerActions, layers.handleQueryResult, layers.handleDismissEphemeral, layers.ephemeralResult, analysisPrefill, mapInstanceRef, handleMarkDirty, viewport, handleAnalysisJobChange]);

  const mobileRailButtons = useMemo(() => [
    {
      id: 'notes' as const,
      icon: FileText,
      label: t('dock.notes', { defaultValue: 'Notes' }),
      disabled: false,
      unavailable: false,
    },
    {
      id: 'dashboard' as const,
      icon: LayoutDashboard,
      label: t('dock.dashboard'),
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

  const railSheetTitle = railPanel === 'dashboard'
    ? t('dock.dashboard')
    : railPanel === 'history'
    ? t('dock.history', { defaultValue: 'History' })
    : railPanel === 'analysis'
    ? t('analysisTools.title', { defaultValue: 'Analysis' })
    : railPanel === 'ai'
      ? aiAvailable
        ? t('dock.askAi', { defaultValue: 'Ask AI' })
        : t('rail.aiUnavailable', { defaultValue: 'AI unavailable' })
      : t('dock.notes', { defaultValue: 'Notes' });
  const railSheetDescription = railPanel === 'dashboard'
    ? t('dock.dashboardDescription')
    : railPanel === 'history'
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

  // The Add Data dialog stays open for repeated adds, so opening the editor on
  // the new layer is deferred (per-add it would stack the flyout behind the
  // dialog). The last added layer's id waits here until the dialog closes.
  const pendingEditorLayerIdRef = useRef<string | null>(null);

  const handleAddDataClick = useCallback(
    (initialQuery?: string) => {
      dialogs.setAddDataInitialQuery(initialQuery ?? '');
      // A stale id from an earlier session's mid-flight add must not leak into
      // this one's close.
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

  // Adapts `string | null` (null = deselect) to handleToggleExpand's string
  // ('' = toggle off), and records the row as the shift-click anchor.
  const handleSelectLayer = useCallback(
    (id: string | null) => {
      handlePlainSelectAnchor(id);
      layers.handleToggleExpand(id ?? '');
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps -- stable handlers
    [layers.handleToggleExpand, handlePlainSelectAnchor],
  );

  // The UnifiedStackPanel row handlers below are memoized, with the stable
  // callbacks from use-builder-layers as deps (not the per-render `layers`
  // literal), so the React.memo chain (UnifiedStackPanel → SortableStackRow →
  // StackRow) can skip rows.
  const handleRowToggleVisibility = useCallback((layerId: string) => {
    // A folder group row is synthetic, not a map layer: its eye toggle goes to
    // toggle_group_visibility so every child (and its companions) follows.
    // Group-ness comes from the hook's ref-backed isFolderGroupRow; a
    // localLayers.find() would re-create this callback (and every row) on the
    // frames the memoization targets.
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

  // handleToggleExpand already closes on the same id.
  const handlePanelSettingsClick = useCallback(() => {
    layers.handleToggleExpand('settings');
    // eslint-disable-next-line react-hooks/exhaustive-deps -- stable handlers
  }, [layers.handleToggleExpand]);

  const handleSwapBasemapClick = useCallback(() => {
    handleSelectLayer('basemap-group');
  }, [handleSelectLayer]);

  const handleDragStart = useCallback((event: DragStartEvent) => {
    setDragActiveId(String(event.active.id));
    handleSelectLayer(null);
    resetMultiSelection();
    lastToggleAnchor.current = null;
    document.documentElement.classList.add('dragging-active');
    lastOverIdRef.current = null;
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
    if (!over) {
      const data = active.data.current as { source?: string; name?: string } | undefined;
      if (data?.source === 'catalog') {
        announce(t('a11y.dragCancelled'));
      }
      return;
    }

    const data = active.data.current as
      | { source?: string; datasetId?: string; recordType?: string; name?: string }
      | undefined;

    if (data?.source === 'catalog') {
      const { datasetId, name: datasetName = '' } = data;
      if (!datasetId) return;
      const overId = String(over.id);

      // Basemap swaps go through the BasemapGroupEditorScene flyout, so a
      // catalog drop onto the basemap row is rejected.
      if (basemapGroup && overId === basemapGroup.id) {
        announce(t('a11y.dragCancelled'));
        return;
      }

      // Dropping onto a folder group makes the new layer join that group.
      const targetLayer = layers.localLayers.find((l) => l.id === overId);
      const parentGroupId = (targetLayer && isFolderGroupLayer(targetLayer)) ? overId : null;
      // Announce the REAL landing position: loose catalog drops PREPEND at the
      // top (position 1) and group drops land after the group's last child, so
      // the drop-target index would be wrong below row 1.
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
      // The announce runs in onSuccessCb, after the mutation succeeds; on error
      // the hook toasts instead, so screen readers never hear a contradiction.
      layers.handleAddDataset(datasetId, () => {
        announce(t('a11y.dragDropped', { name: datasetName, n: announcePosition }));
      }, parentGroupId, datasetName);
      return;
    }

    if (active.id === over.id) return;

    // The basemap is not in localLayers, so arrayMove can't reorder it. Its
    // position (MapBasemapConfig.basemap_position) is a two-way toggle: a drop
    // on any layer flips 'bottom' to 'top' and back.
    const currentLayers = layers.localLayers;
    if (basemapGroup && active.id === basemapGroup.id) {
      const currentPosition = basemapState.config.basemap_position ?? 'bottom';
      const nextPosition = currentPosition === 'top' ? 'bottom' : 'top';
      applyBasemapPatch(setBasemapPosition(basemapState, nextPosition));
      announce(t('a11y.basemapPositionChanged', {
        defaultValue: 'Basemap moved to {{position}}',
        position: nextPosition,
      }));
      return;
    }

    const oldIndex = currentLayers.findIndex((layer) => layer.id === active.id);
    const newIndex = currentLayers.findIndex((layer) => layer.id === over.id);
    if (oldIndex < 0 || newIndex < 0) return;

    // Dragging a folder group row moves the WHOLE block (row plus children), so
    // a single-row arrayMove can't split the group.
    const activeLayer = currentLayers[oldIndex];
    if (isFolderGroupLayer(activeLayer)) {
      const groupId = String(active.id);
      const block = currentLayers.filter(
        (l) =>
          l.id === groupId ||
          (l as { parent_group_id?: string | null }).parent_group_id === groupId,
      );
      const blockIds = new Set(block.map((l) => l.id));
      if (blockIds.has(String(over.id))) return;
      const remaining = currentLayers.filter((l) => !blockIds.has(l.id));
      const targetIdx = remaining.findIndex((l) => l.id === over.id);
      // Moving down inserts AFTER the drop target (like arrayMove), up before.
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

    // Group membership comes from the drop target: arrayMove alone leaves
    // parent_group_id untouched, and childrenByGroup renders by membership, so
    // a child dragged out of its group would snap back.
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
          // Leaving a group also clears the persisted folderGroupId, as
          // handleMoveLayerOutOfGroup does.
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

  // Catalog-drag position updates, only when the over-target changes.
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

  // dnd-kit's default announcements are English and built from the draggable
  // id ("Picked up draggable item <uuid>"), competing with the localized
  // announce() region. Announce translated layer names instead. Catalog drags
  // return undefined: they flow through announce(), whose drop fires only
  // after the add-dataset mutation resolves, which dnd-kit's synchronous
  // onDragEnd cannot honor.
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
    // Return focus to what opened the flyout: the settings cog button or the
    // layer's stack row.
    if (expandedId === 'settings') {
      requestAnimationFrame(() => {
        const cogEl = document.querySelector<HTMLElement>('[data-testid="settings-cog-btn"]');
        cogEl?.focus();
      });
    } else if (expandedId) {
      requestAnimationFrame(() => {
        // The row may be gone (layer deleted from the editor footer); falling
        // back to the first stack row keeps focus out of <body>.
        const rowEl = document.getElementById(`stack-row-${expandedId}`)
          ?? document.querySelector<HTMLElement>('[data-row-id]');
        rowEl?.focus();
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- stable refs
  }, [layers.handleToggleExpand, layers.expandedLayerId]);

  // groupId is not forwarded to the dialog yet.
  const handleAddLayerToFolderGroup = useCallback((_groupId: string) => {
    handleAddDataClick();
  }, [handleAddDataClick]);

  const onBreadcrumbClick = useCallback(() => {
    handleSelectLayer('basemap-group');
  }, [handleSelectLayer]);

  // Resolved the same way BuilderMap does: by source_dataset_id +
  // isTerrainCapableDemLayer, NOT render_mode === 'terrain', since a
  // hillshade-mode DEM drives the 3D mesh too.
  const boundTerrainLayer = useMemo(
    () => resolveTerrainSourceLayer(layers.localLayers, layers.localTerrainConfig),
    [layers.localLayers, layers.localTerrainConfig],
  );
  // Matches BuilderMap's effectiveTerrainEnabled: terrain only renders when the
  // bound DEM is visible.
  const isTerrainActive = Boolean(
    layers.localTerrainConfig?.enabled && boundTerrainLayer && boundTerrainLayer.visible !== false,
  );
  const boundLayerName = boundTerrainLayer
    ? (boundTerrainLayer.display_name ?? boundTerrainLayer.dataset_name ?? undefined)
    : undefined;

  // A DEM with its 2D relief overlay off (render_mode 'terrain') paints nothing
  // unless it is the ACTIVE 3D terrain source; flag those rows so an eye-on row
  // doesn't draw nothing silently. Already-hidden rows are skipped.
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

  const groupHiddenLayerIds = useLayersHiddenFromMapGroups(id, mapData?.visibility, mapData?.groups);

  let sceneContent: ReactNode = null;
  let sceneFooter: ReactNode = null;
  let breadcrumbPresetName: string | undefined = undefined;

  if (editorScene === 'basemap-group' && basemapGroup) {
    // The scene renders its own "No basemap" card; including 'blank' would
    // duplicate it.
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
            // onAddCustomBasemap is omitted so its button stays hidden.
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
      // Maps the UI routing id ('basemap:roads') to the bare key ('road') that
      // basemap_config.sublayer_overrides and applySublayerOverrides use.
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

  // Columns: sidebar (340px, or a 64px rail below 1100px), the 380px editor
  // flyout (only with a layer selected and viewport >= 800px), then the map.
  // Widths are fixed and breakpoint-driven by design: the budget keeps the map
  // at >=50% at 1280px, and a resizable panel would break the responsive
  // contract the e2e suite pins.
  const builderBodyGridClass = cn(
    'flex-1 min-h-0 grid',
    isRail ? 'grid-cols-[64px_1fr]' : 'grid-cols-[340px_1fr]',
    // Also covers basemap/settings scenes, which have no editingLayer.
    isEditorOpen && !isEditorHidden && (
      isRail ? 'grid-cols-[64px_380px_1fr]' : 'grid-cols-[340px_380px_1fr]'
    ),
  );

  return (
    // Fills the flex space <main> leaves (navbar, demo banner and footer
    // included), like PublicMapViewerPage.
    <div className="flex flex-col flex-1 min-h-0">
      {/* Root-level so screen readers in any panel can read drag announcements. */}
      <div
        className="sr-only"
        role="status"
        aria-live="polite"
        aria-atomic="true"
        data-testid="dnd-announcement"
      >
        {dragAnnouncement}
      </div>
      {/* The map name is an editable <input>, not a heading, so this sr-only <h1>
          anchors the outline. */}
      <h1 className="sr-only">
        {mapData?.name
          ? t('titleBar.builderHeading', { name: mapData.name, defaultValue: 'Map builder: {{name}}' })
          : t('common:pageTitle.mapBuilder')}
      </h1>
      {/* Below 768px the builder isn't a real editing surface; say so rather than
          present a broken-looking layout. */}
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
          // New tab, so this session and its unsaved-changes guard are untouched.
          onViewAsViewer: id
            ? () => window.open(`/maps/${id}?preview=viewer`, '_blank', 'noopener,noreferrer')
            : undefined,
        }}
      />

      {/* One DndContext wraps the sidebar and the Add Dataset modal so
          catalog→stack drags share a collision-detection scope. */}
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
          {/* A stack-panel render error must not take down the map and chat. */}
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
              // Drives the per-layer "hidden from public viewers" badge.
              mapVisibility={mapData?.visibility}
              drawsNothingLayerIds={drawsNothingLayerIds}
              groupHiddenLayerIds={groupHiddenLayerIds}
              selectedLayerId={layers.expandedLayerId}
              onSelectLayer={handleSelectLayer}
              onToggleVisibility={handleRowToggleVisibility}
              onReorder={handleRowReorder}
              onOpacityChange={handleRowOpacityChange}
              onRemove={handleRowRemove}
              onRename={layers.handleDisplayNameChange}
              onDuplicate={handleRowDuplicate}
              onZoomToLayer={layers.handleZoomToLayer}
              onAnalyzeLayer={handleAnalyzeLayer}
              onOpenAttributeTable={handleOpenAttributeTable}
              onCopyStyle={layers.handleCopyStyle}
              onPasteStyle={layers.handlePasteStyle}
              onBulkApplyStyle={handleBulkApplyStyle}
              copiedStyleGeometryClass={layers.copiedStyleGeometryClass}
              onKeyboardReorder={handleRowKeyboardReorder}
              // Keyboard reorder shares the pointer path's aria-live region.
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
              // Keeps selectableRowIds in step with what the panel renders.
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
              // A non-persisting row pinned above the sortable region; not in
              // `layers`, so it can't be reordered, styled, grouped or saved.
              preview={previewRowProps}
            />
          )}
          {/* Sidebar-placement plugins render below the layer stack. No built-in
              uses it, so this is inert, but it keeps the placement reachable
              for third-party plugins. */}
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
              // Closes the desktop flyout (the <800px Sheet gets Escape from
              // Radix). Nested Radix popovers/selects portal to <body>, so an
              // open picker's Escape never reaches this aside.
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
                onOpenAttributeTable={(layerId) => handleOpenAttributeTable(layerId, 'editor')}
                featureCount={filteredFeatureCount}
              />
              </Suspense>
            </LazyLoadErrorBoundary>
          </aside>
        )}

        {/* <800px drill-down — Sheet overlay when editor is hidden but a layer/scene is active */}
        {isEditorHidden && isEditorOpen && (
          <Sheet
            open={true}
            modal={false}
            onOpenChange={(open) => { if (!open) handleCloseEditor(); }}
          >
            <SheetContent
              side="right"
              overlay={false}
              showCloseButton={false}
              /* LayerEditorPanel owns the close button ("Close layer editor"), so
                 suppress the Sheet's built-in X. See
                 MapBuilderPage.sheet-close-button.test.tsx. */
              // The 48px top offset keeps the Sheet clear of the top-left
              // NavigationControl at <=800px.
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
                  onOpenAttributeTable={(layerId) => {
                    // This sheet would cover the features the table fits to,
                    // so the table replaces it and closing returns to the layer's rail button.
                    if (attributeTableLayerId !== layerId) handleCloseEditor();
                    handleOpenAttributeTable(layerId, 'stack');
                  }}
                  featureCount={filteredFeatureCount}
                />
                </Suspense>
              </LazyLoadErrorBoundary>
            </SheetContent>
          </Sheet>
        )}

        {/* Column 3 (or 2 when no editor): map canvas with the docked
            attribute table under it. The plain wrapper carries the map area's
            flex-1 sizing and hosts the map overlays; the boundary wraps the
            map alone, so a crash or a retry never touches the overlays; the
            table docks as the wrapper's following sibling. */}
        <div className="relative flex min-h-0 min-w-0 flex-col">
          <div className="relative min-h-0 flex-1">
            <MapErrorBoundary hasUnsavedChanges={layers.hasUnsavedChanges}>
              <Suspense fallback={<LoadingState />}>
                {/* Keyed by map so in-page navigation opens the next map the way a
                    fresh load does: at its saved view, or fitted to its layers. */}
                <BuilderMap
                  key={id}
                  layers={layers.localLayers}
                  // Hiding the basemap keeps data layers and drops the imagery.
                  basemapStyle={basemapVisible ? basemapState.basemapStyle : BLANK_BASEMAP_ID}
                  initialViewState={layers.initialViewState}
                  terrainConfig={basemapState.terrainConfig}
                  onMapRef={handleMapRef}
                  showBasemapLabels={basemapState.showBasemapLabels}
                  basemapConfig={basemapState.config}
                />
              </Suspense>
            </MapErrorBoundary>
            {/* The preview's surface is the stack row above — but the
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
                    // aria-label replaces the subtree, so the notes-presence state
                    // lives in the name rather than on the dot span.
                    aria-label={
                      btn.id === 'notes' && dockNotes.trim().length > 0
                        ? t('rail.notesButtonWithNotes', { defaultValue: 'Notes (map has notes)' })
                        : btn.label
                    }
                    aria-pressed={railPanel === btn.id}
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
                    {/* Mobile counterpart of BuilderRail's notes dot (the rail is
                        hidden at <800px). Decorative: the aria-label above carries
                        the state. */}
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

          {/* Read-only attribute table for one layer, docked under the map.
              Unmounts when the layer is removed, taking its highlight with it. */}
          {attributeTableLayer && (
            <AttributeTableDrawer
              layer={attributeTableLayer}
              open
              onClose={handleCloseAttributeTable}
              mapRef={mapInstanceRef}
              layers={layers.localLayers}
              onLayerChange={setAttributeTableLayerId}
            />
          )}
        </div>
      </div>

      {/* Right rail + panel */}
      {/* A HistoryPanel/Notes render error must not take down the builder. */}
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
            /* BuilderRail's panel owns the close button ("Close panel"), so
               suppress the Sheet's built-in X. */
            // The 48px top offset keeps the Sheet clear of the top-left
            // NavigationControl at <=800px.
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
            // Deferred editor-open: once per dialog session, on the last add.
            if (pendingEditorLayerIdRef.current) {
              handleSelectLayer(pendingEditorLayerIdRef.current);
              pendingEditorLayerIdRef.current = null;
            }
          }
        }}
        addDataInitialQuery={dialogs.addDataInitialQuery}
        // The dismissing click picks its own target; the deferred editor-open
        // would race it and toggle the editor shut.
        onAddDataPointerDownOutside={() => {
          pendingEditorLayerIdRef.current = null;
        }}
        onAddDataset={(datasetId: string) => {
          layers.handleAddDataset(datasetId, (newLayerId) => {
            // The dialog stays open for multi-add; the editor opens on close
            // (see onShowAddDataChange) instead of behind the dialog.
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
        // Per-row feedback; the global isAdding disables every Add button.
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

      </DndContext>

      {/* Mounted only while open: an always-mounted lazy component resolves its
          import on first paint and the split buys nothing. */}
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

      {/* Snapshots a chat query preview into a real dataset. Mounted only while
          open, like StyleJsonDialog above. */}
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

      {/* Not lazy-loaded: small, and needed on the first ? keypress. */}
      <KeyboardShortcutsSheet
        open={showShortcuts}
        onOpenChange={setShowShortcuts}
      />
    </div>
  );
}
