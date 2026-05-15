import { lazy, Suspense, useState, useEffect, useRef, useCallback, useMemo, type ReactNode } from 'react';
import { useParams, Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { FileText, History, Sparkles } from 'lucide-react';
import type { Map as MaplibreMap } from 'maplibre-gl';
import { ApiError } from '@/api/client';
import { toast } from 'sonner';
import {
  closestCenter,
  pointerWithin,
  DndContext,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
} from '@dnd-kit/core';
import type { DragEndEvent, DragOverEvent, DragStartEvent } from '@dnd-kit/core';
import { arrayMove, sortableKeyboardCoordinates } from '@dnd-kit/sortable';
// PERF-06 (Phase 274): lazy-load BuilderMap so map-vendor chunk loads
// only when the builder is about to render (post-data-fetch).
const BuilderMap = lazy(() =>
  import('@/components/builder/BuilderMap').then((m) => ({ default: m.BuilderMap }))
);
import { UnifiedStackPanel } from '@/components/builder/UnifiedStackPanel';
import { DEMEditorScene } from '@/components/builder/DEMEditorScene';
import { SettingsEditorScene } from '@/components/builder/SettingsEditorScene';
import { BasemapGroupEditorScene, BasemapGroupEditorFooter } from '@/components/builder/BasemapGroupEditorScene';
import { BasemapSublayerEditorScene, BasemapSublayerEditorFooter } from '@/components/builder/BasemapSublayerEditorScene';
import { useBasemaps } from '@/hooks/use-settings';
import { basemapThumbnail, normalizeBasemapConfig } from '@/lib/basemap-utils';
import { isFolderGroupLayer } from '@/lib/layer-capabilities';
import { SidebarRail } from '@/components/builder/SidebarRail';
import { LayerEditorPanel, type LayerEditorHandlers } from '@/components/builder/LayerEditorPanel';
import { EphemeralBadge } from '@/components/builder/EphemeralBadge';
import { MapToolbar } from '@/components/builder/MapToolbar';
import { MapTitleBar } from '@/components/builder/MapTitleBar';
import { BuilderRail, type RailPanel } from '@/components/builder/BuilderRail';
import { BuilderDialogs } from '@/components/builder/BuilderDialogs';
import { StyleJsonDialog } from '@/components/builder/StyleJsonDialog';
import { ActiveFilterChips } from '@/components/builder/ActiveFilterChips';
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from '@/components/ui/sheet';
import { cn } from '@/lib/utils';
import { LoadingState } from '@/components/layout/LoadingState';
import { ErrorState } from '@/components/layout/ErrorState';
import { MapErrorBoundary } from '@/components/error';
import { LazyLoadErrorBoundary } from '@/components/error/LazyLoadErrorBoundary';
import { useMap, useAddLayer, useRemoveLayer } from '@/hooks/use-maps';
import { useAIAvailability } from '@/hooks/use-ai-availability';
import { useDocumentTitle } from '@/hooks/use-document-title';
import { useEnabledWidgets } from '@/hooks/use-settings';
import { useBuilderLayout } from '@/components/builder/hooks/use-builder-layout';
import { useBuilderDialogs } from '@/components/builder/hooks/use-builder-dialogs';
import { useBuilderLayers } from '@/components/builder/hooks/use-builder-layers';
import { useBuilderSave } from '@/components/builder/hooks/use-builder-save';
import { WidgetHost, getDefaultWidgetIds, resolveAvailableWidgetIds, usePartitionedWidgets } from '@/components/map-widgets';
import { useWidgetStore } from '@/stores/map-widget-store';

export function MapBuilderPage() {
  const { id } = useParams<{ id: string }>();
  const { t } = useTranslation('builder');
  const { data: mapData, isLoading, error } = useMap(id, { refetchOnWindowFocus: false });
  const enabledWidgetsQuery = useEnabledWidgets();
  const enabledWidgetIds = useMemo(
    () => enabledWidgetsQuery.data ?? (enabledWidgetsQuery.isLoading ? [] : null),
    [enabledWidgetsQuery.data, enabledWidgetsQuery.isLoading],
  );
  const addLayer = useAddLayer();
  const removeLayer = useRemoveLayer();

  const { isAIAvailable: aiAvailable } = useAIAvailability();
  useDocumentTitle(mapData?.name ?? t('common:pageTitle.mapBuilder'));

  // Three-column layout: isRail (sidebar→64px at <1100px), isEditorHidden (flyout hidden at <800px)
  const { isRail, isEditorHidden } = useBuilderLayout();

  const mapInstanceRef = useRef<MaplibreMap | null>(null);
  // mapInstance state duplicates the ref — needed to trigger re-renders for
  // widgetCtx useMemo. The ref provides stable imperative access without re-renders.
  const [mapInstance, setMapInstance] = useState<MaplibreMap | null>(null);
  const [railPanel, setRailPanel] = useState<RailPanel>(null);
  const [dockNotes, setDockNotes] = useState('');
  // Runtime-only per Phase 1036 BSR-14 / UI-SPEC § Projection. Not persisted in v1.
  const [localProjection, setLocalProjection] = useState<'mercator' | 'globe'>('mercator');
  const [showStyleJson, setShowStyleJson] = useState(false);

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

  // Initialize notes from server data, falling back to localStorage for migration
  useEffect(() => {
    if (!mapData) return;
    if (mapData.notes) {
      setDockNotes(mapData.notes);
      try { localStorage.removeItem(`geolens-map-notes-${id}`); } catch { /* localStorage unavailable */ }
    } else {
      try {
        const local = localStorage.getItem(`geolens-map-notes-${id}`);
        if (local) setDockNotes(local);
      } catch { /* localStorage unavailable */ }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- run once when mapData loads
  }, [mapData?.notes, id]);

  // Composed hooks
  const dialogs = useBuilderDialogs(aiAvailable, isEditorHidden);
  const layers = useBuilderLayers(
    mapData,
    mapInstanceRef,
    id,
    addLayer,
    removeLayer,
  );
  // Phase 276 CODE-12: hand-rolled string keys are intentional value-equality
  // dependencies. mapData refetches (TanStack Query refetchOnReconnect /
  // refetchOnMount / window-focus invalidations) produce shape-equivalent
  // but identity-different widget arrays — declaring `[mapData?.widgets,
  // enabledWidgetIds]` directly as deps would reset the user's local widget
  // toggles on every background refetch. Coercing the deps to stable JSON
  // strings (savedWidgetKey) and a NUL-joined ID list (enabledWidgetKey)
  // gives the useEffect value-equality semantics, which is what we actually
  // want for "restore widgets when the saved set or admin allowlist
  // changes".
  //
  // If a future author "simplifies" this back to raw object/array deps,
  // local widget toggle state will silently regress on every refetch.
  // Verify with the map-builder UAT in Plan 276-05: open builder, toggle a
  // widget OFF, trigger a refetch (Cmd-R / window focus / queryClient
  // invalidateQueries), confirm the toggle stays OFF.
  const savedWidgetKey = mapData ? `${mapData.id}:${JSON.stringify(mapData.widgets ?? null)}` : '';
  const enabledWidgetKey = enabledWidgetIds == null ? '__all__' : enabledWidgetIds.join('\0');

  // Restore active widgets from the saved map payload. `null` means client defaults,
  // `[]` means no widgets, and unknown or admin-disabled IDs are ignored.
  useEffect(() => {
    if (!mapData) return;
    const nextWidgets = mapData.widgets == null
      ? getDefaultWidgetIds(enabledWidgetIds)
      : resolveAvailableWidgetIds(mapData.widgets, enabledWidgetIds);
    useWidgetStore.getState().replace(nextWidgets);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- see Phase 276 CODE-12 block comment above
  }, [savedWidgetKey, enabledWidgetKey]);

  const save = useBuilderSave({
    mapId: id,
    localLayers: layers.localLayers,
    localBasemap: layers.localBasemap,
    showBasemapLabels: layers.showBasemapLabels,
    basemapConfig: layers.basemapConfig,
    terrainConfig: layers.localTerrainConfig,
    localName: layers.localName,
    localDescription: layers.localDescription,
    dockNotes,
    mapInstanceRef,
    setHasUnsavedChanges: layers.setHasUnsavedChanges,
    hasUnsavedChanges: layers.hasUnsavedChanges,
    hasThumbnail: !!mapData?.thumbnail_url,
  });

  const handleMapRef = useCallback((map: MaplibreMap | null) => {
    mapInstanceRef.current = map;
    setMapInstance(map);
    if (map) save.maybeAutoCaptureThumbnail(map);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only the method reference matters, not the whole `save` object
  }, [save.maybeAutoCaptureThumbnail]);

  const widgetCtx = useMemo(
    () => ({ mapInstance, layers: layers.localLayers, mapId: id! }),
    [mapInstance, layers.localLayers, id],
  );

  const { byAnchor } = usePartitionedWidgets();
  // activeWidgets for Settings panel widget toggles (Phase 1036)
  const activeWidgets = useWidgetStore((state) => state.activeWidgets);
  const toggleWidget = useWidgetStore((state) => state.toggle);

  // selectedLayerId: the layer currently open in the flyout editor
  // Maps to existing expandedLayerId in use-builder-layers (same field, new semantic name)
  const editingLayer = useMemo(
    () => layers.expandedLayerId ? layers.localLayers.find((l) => l.id === layers.expandedLayerId) ?? null : null,
    [layers.expandedLayerId, layers.localLayers],
  );

  // SP-05 (Phase 1045): server-state baseline for the layer in the editor.
  // Used by LayerStyleEditor to gate the "Pending style preview" banner on a
  // real diff against persisted state instead of showing it unconditionally.
  // Looked up by id from savedLayerBaseline which use-builder-layers refreshes
  // after every successful save / fresh load (see savedLayerBaselineRef).
  const editingSavedLayer = useMemo(
    () => layers.expandedLayerId
      ? layers.savedLayerBaseline.find((l) => l.id === layers.expandedLayerId)
      : undefined,
    [layers.expandedLayerId, layers.savedLayerBaseline],
  );

  const layerEditorHandlers = useMemo((): LayerEditorHandlers => ({
    onTabChange: layers.handleTabChange,
    onPaintChange: layers.handlePaintChange,
    onOpacityChange: layers.handleOpacityChange,
    onFilterChange: layers.handleFilterChange,
    onLabelChange: layers.handleLabelChange,
    onPopupChange: layers.handlePopupChange,
    onStyleConfigChange: layers.handleStyleConfigChange,
    onLayoutChange: layers.handleLayoutChange,
    onRenderModeChange: layers.handleRenderModeChange,
    // onRemove wired to handleRemove; Plan 03 will use this for the footer Delete button
    onRemove: layers.handleRemove,
  }), [layers.handleTabChange, layers.handlePaintChange, layers.handleOpacityChange, layers.handleFilterChange, layers.handleLabelChange, layers.handlePopupChange, layers.handleStyleConfigChange, layers.handleLayoutChange, layers.handleRenderModeChange, layers.handleRemove]);

  const handleMarkDirty = useCallback(
    () => { layers.setHasUnsavedChanges(true); },
    [layers.setHasUnsavedChanges],
  );

  // Phase 1035: basemaps data for the BasemapGroupEditorScene preset grid
  // (placed early for useMemo/useState hooks — actual wiring happens after handleSelectLayer)
  const { data: basemaps = [] } = useBasemaps();

  // Phase 1035: in-memory sublayer state (persistence via basemap_config is a Phase 1038 follow-up)
  // TODO(Phase 1038): include sublayerState in the save payload via basemap_config round-trip.
  const [sublayerState, setSublayerState] = useState<Record<string, { visible: boolean; opacity: number }>>({});

  // Phase 1035: in-memory master opacity for the basemap group.
  // TODO(Phase 1038): persist masterOpacity via a dedicated basemap_config.opacity field (requires
  // backend schema addition to MapBasemapConfig). Spreading `opacity` directly into basemapConfig
  // bypasses the type system and the field is stripped on the next API round-trip.
  const [masterOpacity, setMasterOpacity] = useState(1);

  // Phase 1035: basemap group display object derived from localBasemap + showBasemapLabels
  const basemapGroup = useMemo(() => {
    if (!layers.localBasemap) return null;
    // Derive preset name from the basemap id (label portion after last dash, capitalized)
    const presetId = layers.localBasemap;
    const presetName = presetId
      .replace(/^(openfreemap-|carto-|mapbox-|maptiler-|esri-|stamen-|stadia-)/, '')
      .replace(/-/g, ' ')
      .replace(/\b\w/g, (c) => c.toUpperCase()) || 'Basemap';

    return {
      id: 'basemap-group',
      presetName,
      providerLabel: undefined,
      visible: true,
      opacity: masterOpacity,
      sublayers: [
        {
          id: 'basemap:roads',
          name: 'Roads',
          visible: sublayerState['basemap:roads']?.visible ?? true,
          opacity: sublayerState['basemap:roads']?.opacity ?? 1,
          kind: 'vector' as const,
        },
        {
          id: 'basemap:labels',
          name: 'Labels',
          // Labels sublayer wired to the persisted showBasemapLabels flag (BSR-06)
          visible: layers.showBasemapLabels,
          opacity: sublayerState['basemap:labels']?.opacity ?? 1,
          kind: 'vector' as const,
        },
        {
          id: 'basemap:buildings',
          name: 'Buildings',
          visible: sublayerState['basemap:buildings']?.visible ?? true,
          opacity: sublayerState['basemap:buildings']?.opacity ?? 1,
          kind: 'vector' as const,
        },
        {
          id: 'basemap:boundaries',
          name: 'Boundaries',
          visible: sublayerState['basemap:boundaries']?.visible ?? true,
          opacity: sublayerState['basemap:boundaries']?.opacity ?? 1,
          kind: 'vector' as const,
        },
        {
          id: 'basemap:land-water',
          name: 'Land-Water',
          visible: sublayerState['basemap:land-water']?.visible ?? true,
          opacity: sublayerState['basemap:land-water']?.opacity ?? 1,
          kind: 'vector' as const,
        },
      ],
    };
  }, [layers.localBasemap, layers.showBasemapLabels, sublayerState, masterOpacity]);

  const isBasemapExpanded = layers.groupMeta?.['basemap-group']?.expanded ?? false;

  // Phase 1041: Boundary guard — true when id belongs to basemap group or its sublayers
  const isBasemapBoundaryId = useCallback((id: string): boolean => {
    if (!basemapGroup) return false;
    if (id === basemapGroup.id) return true;
    return basemapGroup.sublayers.some((s) => s.id === id);
  }, [basemapGroup]);

  // Phase 1041: derive selectable row ids (ordered flat list, basemap excluded)
  // Used by handleShiftClick for range computation and by the Shift+Arrow keyboard handler
  const selectableRowIds = useMemo((): string[] => {
    const ids: string[] = [];
    for (const layer of layers.localLayers) {
      ids.push(layer.id);
    }
    return ids;
  }, [layers.localLayers]);

  // Phase 1041: multi-selection handlers (POL-06)
  const handleCmdClick = useCallback((id: string) => {
    if (isBasemapBoundaryId(id)) return;
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
    lastToggleAnchor.current = id;
  }, [isBasemapBoundaryId]);

  const handleShiftClick = useCallback((id: string) => {
    if (isBasemapBoundaryId(id)) return;
    const anchor = lastToggleAnchor.current;
    if (!anchor) {
      // No anchor — fall back to single toggle
      handleCmdClick(id);
      return;
    }
    const anchorIdx = selectableRowIds.indexOf(anchor);
    const targetIdx = selectableRowIds.indexOf(id);
    if (anchorIdx < 0 || targetIdx < 0) {
      handleCmdClick(id);
      return;
    }
    const lo = Math.min(anchorIdx, targetIdx);
    const hi = Math.max(anchorIdx, targetIdx);
    const rangeIds = selectableRowIds.slice(lo, hi + 1).filter((rid) => !isBasemapBoundaryId(rid));
    setSelectedIds((prev) => {
      const next = new Set(prev);
      for (const rid of rangeIds) next.add(rid);
      return next;
    });
  }, [isBasemapBoundaryId, selectableRowIds, handleCmdClick]);

  const handleCheckboxClick = useCallback((id: string) => {
    handleCmdClick(id);
  }, [handleCmdClick]);

  // Phase 1041-02: clear-selection handler (used by UnifiedStackPanel's Escape/outside-click)
  const handleClearSelection = useCallback(() => {
    setSelectedIds(new Set());
    lastToggleAnchor.current = null;
  }, []);

  // Phase 1041-03: real bulk handlers — wired to use-builder-layers bulk ops.
  // Each dep is the specific stable useCallback from use-builder-layers, NOT the
  // entire `layers` object (which is a plain literal re-created on every render).
  // Depending on `layers` defeats React.memo() on BulkActionBar / UnifiedStackPanel
  // on every opacity-slider move, which fires at ~60fps (WR-04).
  const handleBulkVisibility = useCallback((ids: Set<string>) => {
    layers.handleBulkVisibility(ids);
    setSelectedIds(new Set());
  }, [layers.handleBulkVisibility]);

  const handleBulkOpacity = useCallback((ids: Set<string>, opacity: number) => {
    // NOTE: Opacity slider fires onValueChange continuously during drag.
    // Clearing selection on each intermediate event would break subsequent
    // drag events (selection would be empty). Selection is preserved during
    // drag; user dismisses via Escape or by clicking another row. This is
    // documented in the Plan 03 SUMMARY as a deliberate UX decision.
    layers.handleBulkOpacity(ids, opacity);
  }, [layers.handleBulkOpacity]);

  const handleBulkGroup = useCallback((ids: Set<string>) => {
    layers.handleBulkGroup(ids);
    setSelectedIds(new Set());
  }, [layers.handleBulkGroup]);

  const handleBulkUngroup = useCallback((ids: Set<string>) => {
    layers.handleBulkUngroup(ids);
    setSelectedIds(new Set());
  }, [layers.handleBulkUngroup]);

  const handleBulkDelete = useCallback((ids: Set<string>) => {
    layers.handleBulkDelete(ids)
      .then((ok) => {
        if (ok) setSelectedIds(new Set());
        // on failure: selection preserved so user can retry
      })
      .catch(() => {
        // Error already toasted inside handleBulkDelete; swallow here to prevent
        // unhandled rejection if invalidateQueries throws after allSettled.
      });
  }, [layers.handleBulkDelete]);

  // Derived: any row in selectedIds
  const isMultiSelectionActive = selectedIds.size > 0;

  // Phase 1035: sublayer visibility/opacity handlers
  const handleToggleSublayerVisibility = useCallback((sublayerId: string) => {
    if (sublayerId === 'basemap:labels') {
      // Labels toggled via the persisted showBasemapLabels flag (BSR-06) — markDirty() fires
      // inside setShowBasemapLabels because this change IS saved.
      layers.setShowBasemapLabels(!layers.showBasemapLabels);
      return;
    }
    setSublayerState((prev) => ({
      ...prev,
      [sublayerId]: {
        visible: !(prev[sublayerId]?.visible ?? true),
        opacity: prev[sublayerId]?.opacity ?? 1,
      },
    }));
    // TODO(Phase 1038): call markDirty() here once sublayerState is included in the
    // save payload via basemap_config round-trip. Until then, omitting markDirty()
    // prevents the unsaved-changes badge from making a false promise to the user.
  }, [layers.setShowBasemapLabels, layers.showBasemapLabels]);

  const handleSublayerOpacityChange = useCallback((sublayerId: string, opacity: number) => {
    setSublayerState((prev) => ({
      ...prev,
      [sublayerId]: { visible: prev[sublayerId]?.visible ?? true, opacity },
    }));
    // TODO(Phase 1038): call markDirty() once sublayerState is persisted.
  }, []);

  const handleResetBasemapAppearance = useCallback(() => {
    layers.setBasemapConfig(null);
    setSublayerState({});
    setMasterOpacity(1);
    layers.markDirty(); // basemapConfig reset IS persisted (null → saved)
  }, [layers.setBasemapConfig, layers.markDirty]);

  // Phase 1035: existing folder groups list for StackRow "Add to group…" sub-flow
  const existingFolderGroups = useMemo(() => {
    return layers.localLayers
      .filter(isFolderGroupLayer)
      .map((l) => ({ id: l.id, name: l.display_name ?? l.dataset_name ?? 'Group' }));
  }, [layers.localLayers]);

  // Phase 1035+1036: editor scene selection based on current selection
  type EditorScene = 'default' | 'dem' | 'basemap-group' | 'basemap-sublayer' | 'settings';
  const editorScene = useMemo<EditorScene>(() => {
    const sel = layers.expandedLayerId;
    if (!sel) return 'default';
    if (sel === 'settings') return 'settings';
    if (sel === 'basemap-group') return 'basemap-group';
    if (sel.startsWith('basemap:')) return 'basemap-sublayer';
    if (editingLayer?.is_dem === true) return 'dem';
    return 'default';
  }, [layers.expandedLayerId, editingLayer]);

  const railProps = useMemo(() => ({
    activePanel: railPanel,
    onPanelChange: setRailPanel,
    aiAvailable: !!aiAvailable,
    notes: dockNotes,
    onNotesChange: setDockNotes,
    mapId: id,
    layers: layers.localLayers,
    layerActions: layers.chatLayerActions,
    onQueryResult: layers.handleQueryResult,
    onMarkDirty: handleMarkDirty,
  }), [railPanel, aiAvailable, dockNotes, id, layers.localLayers, layers.chatLayerActions, layers.handleQueryResult, handleMarkDirty]);

  const mobileRailButtons = useMemo(() => [
    {
      id: 'notes' as const,
      icon: FileText,
      label: t('dock.notes', { defaultValue: 'Notes' }),
      disabled: false,
    },
    {
      id: 'history' as const,
      icon: History,
      label: t('dock.history', { defaultValue: 'History' }),
      disabled: false,
    },
    {
      id: 'ai' as const,
      icon: Sparkles,
      label: aiAvailable
        ? t('dock.askAi', { defaultValue: 'Ask AI' })
        : t('rail.aiDisabled', { defaultValue: 'AI disabled by admin' }),
      disabled: !aiAvailable,
    },
  ], [aiAvailable, t]);

  const railSheetTitle = railPanel === 'history'
    ? t('dock.history', { defaultValue: 'History' })
    : railPanel === 'ai'
      ? t('dock.askAi', { defaultValue: 'Ask AI' })
      : t('dock.notes', { defaultValue: 'Notes' });
  const railSheetDescription = railPanel === 'history'
    ? t('history.timelineLabel', { defaultValue: 'Map edit history' })
    : railPanel === 'ai'
      ? t('dock.askAi', { defaultValue: 'Ask AI' })
      : t('dock.notesPlaceholder', { defaultValue: 'Add notes about this map...' });

  const handleAddDataClick = useCallback(
    (initialQuery?: string) => {
      dialogs.setAddDataInitialQuery(initialQuery ?? '');
      dialogs.setShowAddData(true);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps -- stable setters from useBuilderDialogs
    [dialogs.setAddDataInitialQuery, dialogs.setShowAddData],
  );

  const handleClearFilter = useCallback(
    (layerId: string) => layers.handleFilterChange(layerId, null),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- stable handler from useLayerMapSync
    [layers.handleFilterChange],
  );

  // Adapter: UnifiedStackPanel/SidebarRail pass `string | null` (null = deselect);
  // handleToggleExpand accepts only string ('' = toggle off).
  const handleSelectLayer = useCallback(
    (id: string | null) => layers.handleToggleExpand(id ?? ''),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- stable handler
    [layers.handleToggleExpand],
  );

  // Phase 1040: DnD handlers hoisted from UnifiedStackPanel — same behavior,
  // lifted to MapBuilderPage so BuilderDialogs (catalog modal) shares the context.
  // T-1040-01: preserve activationConstraint distance:8 and closestCenter verbatim.
  const handleDragStart = useCallback((event: DragStartEvent) => {
    setDragActiveId(String(event.active.id));
    handleSelectLayer(null);
    // Phase 1041 POL-10: drag + multi-select are mutually exclusive. Clear selection at drag-start.
    setSelectedIds(new Set());
    lastToggleAnchor.current = null;
    document.documentElement.classList.add('dragging-active');
    lastOverIdRef.current = null;
    // Announce pick-up for catalog drags (POL-05 / T-1040-10)
    const data = event.active.data.current as { source?: string; name?: string } | undefined;
    if (data?.source === 'catalog' && data.name) {
      announce(t('a11y.dragPickup', { name: data.name }));
    }
  }, [handleSelectLayer, announce, t]);

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
      const { datasetId, recordType, name: datasetName = '' } = data;
      if (!datasetId) return;
      const overId = String(over.id);

      // Case 1: basemap row dropped onto the basemap group row → swap basemap (POL-04).
      // Mirrors DatasetSearchPanel.handleBasemapSwap: four-step normalization.
      if (recordType === 'basemap' && basemapGroup && overId === basemapGroup.id) {
        const nextConfig = normalizeBasemapConfig(layers.basemapConfig, layers.showBasemapLabels);
        layers.setLocalBasemap(datasetId);
        layers.setShowBasemapLabels(nextConfig.label_mode !== 'hidden');
        layers.setBasemapConfig(nextConfig);
        layers.markDirty();
        toast.success(t('toasts.basemapChanged', { name: datasetName }), {
          id: `swap-basemap-${datasetId}`,
        });
        // WR-03: reuse the toast copy for the basemap swap announce — "Basemap changed to {name}."
        // is semantically correct; dragDropped copy ("added at position 1") is not.
        announce(t('toasts.basemapChanged', { name: datasetName }));
        return;
      }

      // Case 2: basemap row dropped onto a non-basemap target → silent reject (UI-SPEC §3d).
      if (recordType === 'basemap') {
        announce(t('a11y.dragCancelled'));
        return;
      }

      // Case 3: non-basemap row dropped onto the basemap group row → silent reject (UI-SPEC §3d).
      if (basemapGroup && overId === basemapGroup.id) {
        announce(t('a11y.dragCancelled'));
        return;
      }

      // Cases 4 & 5: non-basemap row dropped onto a folder-group (POL-03) or loose row (POL-01).
      // When target is a folder group, parentGroupId is set so the new layer joins the group.
      const targetLayer = layers.localLayers.find((l) => l.id === overId);
      const parentGroupId = (targetLayer && isFolderGroupLayer(targetLayer)) ? overId : null;
      const dropPosition = layers.localLayers.findIndex((l) => l.id === overId) + 1;
      const safePosition = dropPosition > 0 ? dropPosition : 1;
      // CR-01: announce fires inside onSuccessCb — only after the async mutation resolves
      // successfully. If the mutation errors, the hook fires toast.error and the announce
      // is never called, avoiding contradictory screen-reader output.
      // Modal stays open per POL-05 — onSuccessCb is not used to auto-select the layer.
      layers.handleAddDataset(datasetId, () => {
        announce(t('a11y.dragDropped', { name: datasetName, n: safePosition }));
      }, parentGroupId, datasetName);
      return;
    }

    // --- Intra-stack reorder (unchanged from Plan 01) ---
    if (active.id === over.id) return;
    const currentLayers = layers.localLayers;
    const oldIndex = currentLayers.findIndex((layer) => layer.id === active.id);
    const newIndex = currentLayers.findIndex((layer) => layer.id === over.id);
    if (oldIndex < 0 || newIndex < 0) return;
    layers.handleReorder(arrayMove(currentLayers, oldIndex, newIndex));
  // eslint-disable-next-line react-hooks/exhaustive-deps -- layers.localLayers + handleReorder + handleAddDataset captured; basemapGroup is stable derived value; announce is stable
  }, [layers.localLayers, layers.handleReorder, layers.handleAddDataset, layers.basemapConfig, layers.showBasemapLabels, layers.setLocalBasemap, layers.setShowBasemapLabels, layers.setBasemapConfig, layers.markDirty, basemapGroup, t, announce]);

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
  // eslint-disable-next-line react-hooks/exhaustive-deps -- layers.localLayers length read; announce is stable
  }, [layers.localLayers, announce, t]);

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
        const rowEl = document.getElementById(`stack-row-${expandedId}`);
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

  // Phase 1036: terrain active flag — true when localTerrainConfig.enabled is true,
  // meaning a DEM layer has been bound as the terrain source.
  const isTerrainActive = useMemo(
    () => Boolean(layers.localTerrainConfig?.enabled),
    [layers.localTerrainConfig],
  );

  // Phase 1036: name of the DEM layer currently bound as terrain source
  const boundLayerName = useMemo(() => {
    if (!layers.localTerrainConfig?.source_dataset_id) return undefined;
    const bound = layers.localLayers.find(
      (l) => l.dataset_id === layers.localTerrainConfig?.source_dataset_id,
    );
    return bound ? (bound.display_name ?? bound.dataset_name ?? undefined) : undefined;
  }, [layers.localLayers, layers.localTerrainConfig]);

  // Phase 1035+1036: scene-specific content + footer for LayerEditorPanel
  // Computed after handleSelectLayer and handleAddDataClick are in scope
  let sceneContent: ReactNode = null;
  let sceneFooter: ReactNode = null;
  let breadcrumbPresetName: string | undefined = undefined;

  if (editorScene === 'basemap-group' && basemapGroup) {
    const presets = basemaps.map((b) => ({
      id: b.id,
      name: b.label,
      provider: '',
      thumbnailUrl: basemapThumbnail(b.id),
    }));
    sceneContent = (
      <BasemapGroupEditorScene
        activePresetId={layers.localBasemap}
        presets={presets}
        sublayers={basemapGroup.sublayers}
        masterOpacity={basemapGroup.opacity}
        onSwapBasemap={(presetId) => { layers.setLocalBasemap(presetId); layers.markDirty(); }}
        onAddCustomBasemap={() => { /* Plan 1037 follow-up */ }}
        onSublayerVisibilityChange={handleToggleSublayerVisibility}
        onSublayerOpacityChange={handleSublayerOpacityChange}
        onMasterOpacityChange={(opacity) => {
          setMasterOpacity(opacity);
          // TODO(Phase 1038): persist masterOpacity via basemap_config.opacity field
          // (requires backend MapBasemapConfig schema addition). Spreading `opacity`
          // directly into basemapConfig bypasses the type system and is stripped on
          // the next API round-trip, so markDirty() is omitted until persistence is wired.
        }}
      />
    );
    sceneFooter = (
      <BasemapGroupEditorFooter
        onResetAppearance={handleResetBasemapAppearance}
        onRemoveBasemap={() => { layers.setLocalBasemap('openfreemap-positron'); layers.markDirty(); }}
      />
    );
  } else if (editorScene === 'basemap-sublayer' && basemapGroup) {
    const sublayer = basemapGroup.sublayers.find((s) => s.id === layers.expandedLayerId);
    breadcrumbPresetName = basemapGroup.presetName;
    if (sublayer) {
      sceneContent = (
        <BasemapSublayerEditorScene
          sublayerId={sublayer.id}
          sublayerName={sublayer.name}
          activeDetailLevel="default"
          isCustomized={false}
          strokeColor="#888888"
          strokeWidth={1}
          casingColor="#FFFFFF"
          casingWidth={0}
          opacity={sublayer.opacity}
          minZoom={0}
          maxZoom={22}
          onDetailLevelChange={() => { /* TODO(Phase 1038): markDirty() once sublayer styling is persisted */ }}
          onStrokeColorChange={() => { /* TODO(Phase 1038): markDirty() once sublayer styling is persisted */ }}
          onStrokeWidthChange={() => { /* TODO(Phase 1038): markDirty() once sublayer styling is persisted */ }}
          onCasingColorChange={() => { /* TODO(Phase 1038): markDirty() once sublayer styling is persisted */ }}
          onCasingWidthChange={() => { /* TODO(Phase 1038): markDirty() once sublayer styling is persisted */ }}
          onOpacityChange={(o) => handleSublayerOpacityChange(sublayer.id, o)}
          onZoomChange={() => { /* TODO(Phase 1038): markDirty() once sublayer zoom range is persisted */ }}
          onResetSublayer={() => {
            setSublayerState((prev) => {
              const next = { ...prev };
              delete next[sublayer.id];
              return next;
            });
            // TODO(Phase 1038): markDirty() once sublayerState is persisted
          }}
        />
      );
      sceneFooter = (
        <BasemapSublayerEditorFooter
          onBackToBasemap={() => handleSelectLayer('basemap-group')}
        />
      );
    }
  } else if (editorScene === 'dem' && editingLayer) {
    sceneContent = (
      <DEMEditorScene
        layer={editingLayer}
        onPaintChange={(p) => layers.handlePaintChange(editingLayer.id, p)}
        onStyleConfigChange={(cfg, paint) => layers.handleStyleConfigChange(editingLayer.id, cfg, paint)}
        onOpacityChange={(o) => layers.handleOpacityChange(editingLayer.id, o)}
        onZoomChange={(min, max) => layers.handleLayoutChange(editingLayer.id, { ...editingLayer.layout, _minzoom: min, _maxzoom: max })}
        onTerrainBind={layers.handleDEMTerrainBind}
        onRemove={(id) => layers.handleRemove(id)}
      />
    );
    // DEMEditorScene renders its own footer (Delete layer inline confirm)
  } else if (editorScene === 'settings') {
    sceneContent = (
      <SettingsEditorScene
        terrainConfig={layers.localTerrainConfig}
        isTerrainActive={isTerrainActive}
        boundLayerName={boundLayerName}
        onExaggerationChange={(v) => {
          layers.setLocalTerrainConfig((prev) =>
            prev ? { ...prev, exaggeration: v } : { enabled: false, source_dataset_id: null, exaggeration: v },
          );
          layers.setHasUnsavedChanges(true);
          if (
            mapInstanceRef.current &&
            layers.localTerrainConfig?.enabled &&
            layers.localTerrainConfig.source_dataset_id
          ) {
            mapInstanceRef.current.setTerrain({
              source: `dem-${layers.localTerrainConfig.source_dataset_id}`,
              exaggeration: v,
            });
          }
        }}
        activeWidgetIds={activeWidgets}
        onToggleWidget={toggleWidget}
        projection={localProjection}
        onSetProjection={(proj) => {
          setLocalProjection(proj);
          try {
            mapInstanceRef.current?.setProjection?.({ type: proj });
          } catch {
            // setProjection may not exist in test envs / older maplibre — swallow safely
          }
        }}
      />
    );
    sceneFooter = undefined;
    breadcrumbPresetName = undefined;
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-[calc(100vh-3.5rem)]">
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
      <div className="flex items-center justify-center h-[calc(100vh-3.5rem)]">
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
  const builderBodyGridClass = cn(
    'flex-1 min-h-0 grid',
    // Base: no editor open
    isRail ? 'grid-cols-[64px_1fr]' : 'grid-cols-[340px_1fr]',
    // Editor open and not hidden (also for basemap group/sublayer/settings scenes which have no editingLayer)
    (editingLayer || editorScene === 'basemap-group' || editorScene === 'basemap-sublayer' || editorScene === 'settings') && !isEditorHidden && (
      isRail ? 'grid-cols-[64px_380px_1fr]' : 'grid-cols-[340px_380px_1fr]'
    ),
  );

  return (
    <div className="flex flex-col h-[calc(100vh-3.5rem)]">
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
        }}
      />

      {/* Phase 1040: single DndContext wraps sidebar (UnifiedStackPanel) and
          BuilderDialogs (Add Dataset modal) so catalog→stack drag shares one
          collision-detection scope. T-1040-02: sensors declared via useSensors
          at MapBuilderPage level so identity is stable across renders. */}
      <DndContext
        sensors={dndSensors}
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
        data-builder-editor-open={!!editingLayer}
      >
        {/* Column 1: sidebar (340px full or 64px rail at <1100px) */}
        <aside
          data-testid="builder-sidebar"
          className="border-e bg-background flex flex-col overflow-hidden"
        >
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
              basemapGroup={layers.localBasemap ? { id: 'basemap-group' } : null}
            />
          ) : (
            <UnifiedStackPanel
              layers={layers.localLayers}
              selectedLayerId={layers.expandedLayerId}
              onSelectLayer={handleSelectLayer}
              onToggleVisibility={layers.handleToggleVisibility}
              onReorder={layers.handleReorder}
              onOpacityChange={layers.handleOpacityChange}
              onRemove={layers.handleRemove}
              onRename={layers.handleDisplayNameChange}
              onDuplicate={layers.handleDuplicateRendering}
              onAddDataClick={handleAddDataClick}
              onAddDataset={(datasetId: string) => {
                layers.handleAddDataset(datasetId, (newLayerId) => {
                  handleSelectLayer(newLayerId);
                });
              }}
              onSettingsClick={() => {
                layers.handleToggleExpand(
                  layers.expandedLayerId === 'settings' ? '' : 'settings',
                );
              }}
              isSettingsOpen={editorScene === 'settings'}
              activeDragId={dragActiveId}
              groupMeta={layers.groupMeta}
              onToggleGroupExpand={layers.handleToggleGroupExpand}
              basemapGroup={basemapGroup}
              isBasemapExpanded={isBasemapExpanded}
              onToggleSublayerVisibility={handleToggleSublayerVisibility}
              onSublayerOpacityChange={handleSublayerOpacityChange}
              onSwapBasemap={() => dialogs.setShowAddData(true)}
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
              onCmdClick={handleCmdClick}
              onShiftClick={handleShiftClick}
              onCheckboxClick={handleCheckboxClick}
              onClearSelection={handleClearSelection}
              onBulkVisibility={handleBulkVisibility}
              onBulkOpacity={handleBulkOpacity}
              onBulkGroup={handleBulkGroup}
              onBulkUngroup={handleBulkUngroup}
              onBulkDelete={handleBulkDelete}
              freshLayerId={layers.freshLayerId}
            />
          )}
        </aside>

        {/* Column 2: LayerEditorPanel flyout (380px) — when layer selected or basemap/settings scene active; viewport >= 800px */}
        {(editingLayer || editorScene === 'basemap-group' || editorScene === 'basemap-sublayer' || editorScene === 'settings') && !isEditorHidden && (
          <aside
            data-testid="builder-layer-editor"
            className="border-e bg-background flex flex-col overflow-hidden"
          >
            <LazyLoadErrorBoundary>
              <LayerEditorPanel
                key={layers.expandedLayerId ?? 'no-layer'}
                layer={editingLayer ?? {
                  // Synthetic placeholder for basemap group/sublayer/settings scenes (no real MapLayerResponse)
                  id: editorScene === 'settings' ? 'settings' : (layers.expandedLayerId ?? 'basemap-group'),
                  dataset_id: editorScene === 'settings' ? 'settings' : 'basemap',
                  dataset_name: editorScene === 'settings'
                    ? 'Settings'
                    : editorScene === 'basemap-sublayer'
                      ? (basemapGroup?.sublayers.find((s) => s.id === layers.expandedLayerId)?.name ?? 'Sublayer')
                      : `Basemap · ${basemapGroup?.presetName ?? 'Untitled'}`,
                  dataset_geometry_type: null,
                  dataset_table_name: editorScene === 'settings' ? 'settings' : 'basemap',
                  dataset_extent_bbox: null,
                  dataset_column_info: null,
                  dataset_feature_count: null,
                  dataset_sample_values: null,
                  display_name: editorScene === 'settings'
                    ? 'Settings'
                    : editorScene === 'basemap-sublayer'
                      ? (basemapGroup?.sublayers.find((s) => s.id === layers.expandedLayerId)?.name ?? 'Sublayer')
                      : `Basemap · ${basemapGroup?.presetName ?? 'Untitled'}`,
                  sort_order: -1, // synthetic placeholder — not a real layer; not persisted
                  visible: true,
                  opacity: 1,
                  paint: {},
                  layout: {},
                  filter: null,
                  label_config: null,
                  popup_config: null,
                  style_config: null,
                  layer_type: null,
                  dataset_record_type: 'vector_dataset',
                  show_in_legend: false,
                  is_dem: false,
                  dem_vertical_units: null,
                }}
                savedLayer={editingSavedLayer}
                onClose={handleCloseEditor}
                isDrillDown={false}
                handlers={layerEditorHandlers}
                activeTab={layers.activeEditorTab}
                enableLegacyTabs={false}
                editorScene={editorScene}
                sceneContent={sceneContent ?? undefined}
                sceneFooter={sceneFooter ?? undefined}
                breadcrumbPresetName={breadcrumbPresetName}
                onBreadcrumbClick={onBreadcrumbClick}
              />
            </LazyLoadErrorBoundary>
          </aside>
        )}

        {/* BSR-13: <800px drill-down — Sheet overlay when editor is hidden but a layer/scene is active */}
        {isEditorHidden && (editingLayer || editorScene === 'basemap-group' || editorScene === 'basemap-sublayer' || editorScene === 'settings') && (
          <Sheet
            open={true}
            onOpenChange={(open) => { if (!open) handleCloseEditor(); }}
          >
            <SheetContent
              side="right"
              className="w-full max-w-[380px] p-0 flex flex-col"
            >
              <SheetHeader className="sr-only">
                <SheetTitle>
                  {editingLayer?.display_name ?? editingLayer?.dataset_name ?? t('layerEditor.close', { defaultValue: 'Close layer editor' })}
                </SheetTitle>
                <SheetDescription>
                  {t('layerEditor.section.appearance', { defaultValue: 'Appearance' })}
                </SheetDescription>
              </SheetHeader>
              <LazyLoadErrorBoundary>
                <LayerEditorPanel
                  key={layers.expandedLayerId ?? 'no-layer'}
                  layer={editingLayer ?? {
                    id: editorScene === 'settings' ? 'settings' : (layers.expandedLayerId ?? 'basemap-group'),
                    dataset_id: editorScene === 'settings' ? 'settings' : 'basemap',
                    dataset_name: editorScene === 'settings'
                      ? 'Settings'
                      : editorScene === 'basemap-sublayer'
                        ? (basemapGroup?.sublayers.find((s) => s.id === layers.expandedLayerId)?.name ?? 'Sublayer')
                        : `Basemap · ${basemapGroup?.presetName ?? 'Untitled'}`,
                    dataset_geometry_type: null,
                    dataset_table_name: editorScene === 'settings' ? 'settings' : 'basemap',
                    dataset_extent_bbox: null,
                    dataset_column_info: null,
                    dataset_feature_count: null,
                    dataset_sample_values: null,
                    display_name: editorScene === 'settings'
                      ? 'Settings'
                      : editorScene === 'basemap-sublayer'
                        ? (basemapGroup?.sublayers.find((s) => s.id === layers.expandedLayerId)?.name ?? 'Sublayer')
                        : `Basemap · ${basemapGroup?.presetName ?? 'Untitled'}`,
                    sort_order: -1,
                    visible: true,
                    opacity: 1,
                    paint: {},
                    layout: {},
                    filter: null,
                    label_config: null,
                    popup_config: null,
                    style_config: null,
                    layer_type: null,
                    dataset_record_type: 'vector_dataset',
                    show_in_legend: false,
                    is_dem: false,
                    dem_vertical_units: null,
                  }}
                  savedLayer={editingSavedLayer}
                  onClose={handleCloseEditor}
                  isDrillDown={true}
                  handlers={layerEditorHandlers}
                  activeTab={layers.activeEditorTab}
                  enableLegacyTabs={false}
                  editorScene={editorScene}
                  sceneContent={sceneContent ?? undefined}
                  sceneFooter={sceneFooter ?? undefined}
                  breadcrumbPresetName={breadcrumbPresetName}
                  onBreadcrumbClick={onBreadcrumbClick}
                />
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
                basemapStyle={layers.localBasemap}
                initialViewState={layers.initialViewState}
                terrainConfig={layers.localTerrainConfig}
                onMapRef={handleMapRef}
                showBasemapLabels={layers.showBasemapLabels}
                basemapConfig={layers.basemapConfig}
              />
            </Suspense>
          </MapErrorBoundary>
          {layers.ephemeralResult && (
            <EphemeralBadge
              featureCount={layers.ephemeralResult.geojson.features.length}
              onDismiss={layers.handleDismissEphemeral}
            />
          )}

          {/* Centered toolbar */}
          <MapToolbar onStyleJsonClick={() => setShowStyleJson(true)} />
          {isEditorHidden && (
            <div className="absolute right-2 top-16 z-30 flex flex-col gap-1 rounded-md border bg-background/95 p-1 shadow-md backdrop-blur-sm">
              {mobileRailButtons.map((btn) => (
                <button
                  key={btn.id}
                  type="button"
                  onClick={btn.disabled ? undefined : () => setRailPanel(btn.id)}
                  disabled={btn.disabled}
                  title={btn.label}
                  aria-label={btn.label}
                  aria-pressed={!btn.disabled && railPanel === btn.id}
                  className={cn(
                    'flex h-11 w-11 items-center justify-center rounded-md transition-colors',
                    btn.disabled
                      ? 'cursor-not-allowed text-muted-foreground/40'
                      : railPanel === btn.id
                        ? 'bg-accent text-primary'
                        : 'text-muted-foreground hover:bg-accent hover:text-foreground',
                  )}
                >
                  <btn.icon className="h-4 w-4" aria-hidden="true" />
                </button>
              ))}
            </div>
          )}

          <WidgetHost
            byAnchor={byAnchor}
            ctx={widgetCtx}
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
      {!isEditorHidden && <BuilderRail {...railProps} />}

      {/* Mobile rail as Sheet overlay */}
      {isEditorHidden && railPanel && (
        <Sheet open={!!railPanel} onOpenChange={(open) => { if (!open) setRailPanel(null); }}>
          <SheetContent side="right" className="w-[22rem] max-w-[calc(100vw-5rem)] p-0 flex flex-col">
            <SheetHeader className="sr-only">
              <SheetTitle>{railSheetTitle}</SheetTitle>
              <SheetDescription>{railSheetDescription}</SheetDescription>
            </SheetHeader>
            <BuilderRail {...railProps} showRail={false} />
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
          }
        }}
        addDataInitialQuery={dialogs.addDataInitialQuery}
        onAddDataset={(datasetId: string) => {
          layers.handleAddDataset(datasetId, (newLayerId) => {
            dialogs.setShowAddData(false);
            dialogs.setAddDataInitialQuery('');
            handleSelectLayer(newLayerId);
          });
        }}
        onDuplicateRendering={layers.handleDuplicateRendering}
        layers={layers.localLayers}
        isAdding={addLayer.isPending}
        basemapStyle={layers.localBasemap}
        showBasemapLabels={layers.showBasemapLabels}
        basemapConfig={layers.basemapConfig}
        onBasemapChange={(key) => { layers.setLocalBasemap(key); layers.markDirty(); }}
        onBasemapLabelsChange={(show) => { layers.setShowBasemapLabels(show); layers.setHasUnsavedChanges(true); }}
        onBasemapConfigChange={(next) => {
          layers.setBasemapConfig(next);
          layers.setShowBasemapLabels(next.label_mode !== 'hidden');
          layers.markDirty();
        }}
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

      {id && (
        <StyleJsonDialog
          mapId={id}
          mapName={layers.localName}
          open={showStyleJson}
          onOpenChange={setShowStyleJson}
        />
      )}
    </div>
  );
}
