import { lazy, Suspense, useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { useParams, Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { FileText, History, Loader2, Save, Sparkles } from 'lucide-react';
import type { Map as MaplibreMap } from 'maplibre-gl';
import { ApiError } from '@/api/client';
import { Button } from '@/components/ui/button';
// PERF-06 (Phase 274): lazy-load BuilderMap so map-vendor chunk loads
// only when the builder is about to render (post-data-fetch).
const BuilderMap = lazy(() =>
  import('@/components/builder/BuilderMap').then((m) => ({ default: m.BuilderMap }))
);
import { MapStackPanel } from '@/components/builder/MapStackPanel';
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
import { WidgetHost, WidgetSidebar, getDefaultWidgetIds, resolveAvailableWidgetIds, usePartitionedWidgets } from '@/components/map-widgets';
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
  const [showStyleJson, setShowStyleJson] = useState(false);

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

  const { byAnchor, sidebar } = usePartitionedWidgets();
  const activeWidgetSet = useWidgetStore((state) => state.activeWidgets);
  const activeWidgetIds = useMemo(() => Array.from(activeWidgetSet), [activeWidgetSet]);

  // selectedLayerId: the layer currently open in the flyout editor
  // Maps to existing expandedLayerId in use-builder-layers (same field, new semantic name)
  const editingLayer = useMemo(
    () => layers.expandedLayerId ? layers.localLayers.find((l) => l.id === layers.expandedLayerId) ?? null : null,
    [layers.expandedLayerId, layers.localLayers],
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
    [layers],
  );

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
    () => dialogs.setShowAddData(true),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- stable setter from useBuilderDialogs
    [dialogs.setShowAddData],
  );

  const handleClearFilter = useCallback(
    (layerId: string) => layers.handleFilterChange(layerId, null),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- stable handler from useLayerMapSync
    [layers.handleFilterChange],
  );

  const handleCloseEditor = useCallback(() => {
    const expandedId = layers.expandedLayerId;
    layers.handleToggleExpand('');
    // Return focus to the row that opened the flyout.
    // Resolver covers: new Plan 02 stack-row-{id} AND legacy layer-expand-{id} from MapStackItem.
    if (expandedId) {
      requestAnimationFrame(() => {
        const rowEl =
          document.getElementById(`stack-row-${expandedId}`) ??
          document.getElementById(`layer-expand-${expandedId}`);
        rowEl?.focus();
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- stable refs
  }, [layers.handleToggleExpand, layers.expandedLayerId]);

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
    // Editor open and not hidden
    editingLayer && !isEditorHidden && (
      isRail ? 'grid-cols-[64px_380px_1fr]' : 'grid-cols-[340px_380px_1fr]'
    ),
  );

  return (
    <div className="flex flex-col h-[calc(100vh-3.5rem)]">
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

      <div className="flex flex-1 min-h-0">

      {/* Mobile sidebar as Sheet — shown when isEditorHidden (<800px) */}
      {isEditorHidden && (
        <Sheet open={!dialogs.sidebarCollapsed} onOpenChange={(open) => dialogs.setSidebarCollapsed(!open)}>
          <SheetContent side="left" className="w-[22rem] max-w-[calc(100vw-5rem)] p-0 flex flex-col">
            <SheetHeader className="sr-only">
              <SheetTitle>{layers.localName || t('mapBuilder')}</SheetTitle>
              <SheetDescription>{t('descriptionLabel')}</SheetDescription>
            </SheetHeader>
            <div className="p-3 border-b flex items-center justify-between">
              <span className="text-sm font-semibold truncate">{layers.localName}</span>
              <Button variant={layers.hasUnsavedChanges ? 'default' : 'outline'} size="sm" className="min-h-11 gap-1 shrink-0 px-3 text-xs" onClick={save.handleSave} disabled={save.isSaving}>
                {save.isSaving ? <Loader2 className="h-3 w-3 animate-spin" /> : <Save className="h-3 w-3" />}
                {t('actions.save')}
              </Button>
            </div>
            <div className="flex-1 overflow-y-auto py-3">
              <MapStackPanel
                layers={layers.localLayers}
                expandedLayerId={layers.expandedLayerId}
                basemapStyle={layers.localBasemap}
                showBasemapLabels={layers.showBasemapLabels}
                basemapConfig={layers.basemapConfig}
                terrainConfig={layers.localTerrainConfig}
                widgets={activeWidgetIds}
                onToggleExpand={layers.handleToggleExpand}
                onToggleVisibility={layers.handleToggleVisibility}
                onMoveUp={layers.handleMoveUp}
                onMoveDown={layers.handleMoveDown}
                onReorder={layers.handleReorder}
                onRename={layers.handleDisplayNameChange}
                onRemove={layers.handleRemove}
                onZoomToLayer={layers.handleZoomToLayer}
                onToggleLegend={layers.handleToggleLegend}
                onOpacityChange={layers.handleOpacityChange}
                onLayoutChange={layers.handleLayoutChange}
                onRenderAsChange={layers.handleRenderAsChange}
                onDuplicateRendering={layers.handleDuplicateRendering}
                onAddDataClick={handleAddDataClick}
                onBasemapChange={(key) => { layers.setLocalBasemap(key); layers.markDirty(); }}
                onBasemapLabelsChange={(show) => { layers.setShowBasemapLabels(show); layers.setHasUnsavedChanges(true); }}
                onBasemapConfigChange={(next) => {
                  layers.setBasemapConfig(next);
                  layers.setShowBasemapLabels(next.label_mode !== 'hidden');
                  layers.markDirty();
                }}
                onTerrainChange={(next) => {
                  layers.setLocalTerrainConfig(next);
                  layers.markDirty();
                }}
                widgetSidebar={<WidgetSidebar widgets={sidebar} ctx={widgetCtx} />}
              />
            </div>
          </SheetContent>
        </Sheet>
      )}

      {/* Three-column builder body grid */}
      <div
        className={builderBodyGridClass}
        data-builder-editor-open={!!editingLayer}
      >
        {/* Column 1: sidebar (340px full or 64px rail) */}
        {/* Plan 01: still renders MapStackPanel; Plan 02 will replace with UnifiedStackPanel/rail */}
        {!isEditorHidden && (
          <aside
            data-testid="builder-sidebar"
            className="border-e bg-background flex flex-col overflow-hidden"
          >
            <div className="flex-1 overflow-y-auto py-3">
              <MapStackPanel
                layers={layers.localLayers}
                expandedLayerId={layers.expandedLayerId}
                basemapStyle={layers.localBasemap}
                showBasemapLabels={layers.showBasemapLabels}
                basemapConfig={layers.basemapConfig}
                terrainConfig={layers.localTerrainConfig}
                widgets={activeWidgetIds}
                onToggleExpand={layers.handleToggleExpand}
                onToggleVisibility={layers.handleToggleVisibility}
                onMoveUp={layers.handleMoveUp}
                onMoveDown={layers.handleMoveDown}
                onReorder={layers.handleReorder}
                onRename={layers.handleDisplayNameChange}
                onRemove={layers.handleRemove}
                onZoomToLayer={layers.handleZoomToLayer}
                onToggleLegend={layers.handleToggleLegend}
                onOpacityChange={layers.handleOpacityChange}
                onLayoutChange={layers.handleLayoutChange}
                onRenderAsChange={layers.handleRenderAsChange}
                onDuplicateRendering={layers.handleDuplicateRendering}
                onAddDataClick={handleAddDataClick}
                onBasemapChange={(key) => { layers.setLocalBasemap(key); layers.markDirty(); }}
                onBasemapLabelsChange={(show) => { layers.setShowBasemapLabels(show); layers.setHasUnsavedChanges(true); }}
                onBasemapConfigChange={(next) => {
                  layers.setBasemapConfig(next);
                  layers.setShowBasemapLabels(next.label_mode !== 'hidden');
                  layers.markDirty();
                }}
                onTerrainChange={(next) => {
                  layers.setLocalTerrainConfig(next);
                  layers.markDirty();
                }}
                widgetSidebar={<WidgetSidebar widgets={sidebar} ctx={widgetCtx} />}
              />
            </div>
          </aside>
        )}

        {/* Column 2: LayerEditorPanel flyout (380px) — only when layer selected and viewport >= 800px */}
        {editingLayer && !isEditorHidden && (
          <aside
            data-testid="builder-layer-editor"
            className="border-e bg-background flex flex-col overflow-hidden"
          >
            <LazyLoadErrorBoundary>
              <LayerEditorPanel
                layer={editingLayer}
                onClose={handleCloseEditor}
                isDrillDown={false}
                handlers={layerEditorHandlers}
                activeTab={layers.activeEditorTab}
                enableLegacyTabs={true}
              />
            </LazyLoadErrorBoundary>
          </aside>
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
        onShowAddDataChange={dialogs.setShowAddData}
        onAddDataset={layers.handleAddDataset}
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
