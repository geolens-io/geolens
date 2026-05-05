import { useState, useEffect, useRef, useCallback, useMemo, memo } from 'react';
import { useParams, Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { Save, Loader2, PanelLeftClose, PanelLeftOpen } from 'lucide-react';
import type { Map as MaplibreMap } from 'maplibre-gl';
import { ApiError } from '@/api/client';
import { Button } from '@/components/ui/button';
import { BuilderMap } from '@/components/builder/BuilderMap';
import { LayerPanel } from '@/components/builder/LayerPanel';
import { LayerEditorPanel } from '@/components/builder/LayerEditorPanel';
import { EphemeralBadge } from '@/components/builder/EphemeralBadge';
import { MapToolbar } from '@/components/builder/MapToolbar';
import { MapTitleBar } from '@/components/builder/MapTitleBar';
import { BuilderRail, type RailPanel } from '@/components/builder/BuilderRail';
import { BuilderDialogs } from '@/components/builder/BuilderDialogs';
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
import { BasemapPicker } from '@/components/builder/BasemapPicker';
import { WidgetHost, WidgetSidebar, getDefaultWidgetIds, resolveAvailableWidgetIds, usePartitionedWidgets } from '@/components/map-widgets';
import { useWidgetStore } from '@/components/map-widgets/map-widget-store';


const SIDEBAR_WIDTH_KEY = 'geolens-builder-sidebar-width';
const SIDEBAR_MIN = 200;
const SIDEBAR_MAX = 600;

const SidebarContent = memo(function SidebarContent({
  layers,
  onAddDataClick,
  widgetSidebar,
}: {
  layers: ReturnType<typeof useBuilderLayers>;
  onAddDataClick: () => void;
  widgetSidebar?: React.ReactNode;
}) {
  const { t } = useTranslation('builder');
  return (
    <div className="flex-1 overflow-y-auto space-y-4 py-3">
      <LayerPanel
        layers={layers.localLayers}
        expandedLayerId={layers.expandedLayerId}
        onToggleExpand={layers.handleToggleExpand}
        onToggleVisibility={layers.handleToggleVisibility}
        onMoveUp={layers.handleMoveUp}
        onMoveDown={layers.handleMoveDown}
        onReorder={layers.handleReorder}
        onRename={layers.handleDisplayNameChange}
        onRemove={layers.handleRemove}
        onZoomToLayer={layers.handleZoomToLayer}
        onToggleLegend={layers.handleToggleLegend}
        onAddDataClick={onAddDataClick}
      />
      {widgetSidebar}
      <div className="border-t pt-3 px-2">
        <h2 className="text-sm font-medium mb-2">{t('basemap.title')}</h2>
        <BasemapPicker
          value={layers.localBasemap}
          onChange={(key) => { layers.setLocalBasemap(key); layers.markDirty(); }}
          showLabels={layers.showBasemapLabels}
          onToggleLabels={(v: boolean) => { layers.setShowBasemapLabels(v); layers.setHasUnsavedChanges(true); }}
        />
      </div>
    </div>
  );
});

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
  const { isMobile } = useBuilderLayout();

  const mapInstanceRef = useRef<MaplibreMap | null>(null);
  // mapInstance state duplicates the ref — needed to trigger re-renders for
  // widgetCtx useMemo. The ref provides stable imperative access without re-renders.
  const [mapInstance, setMapInstance] = useState<MaplibreMap | null>(null);
  const [railPanel, setRailPanel] = useState<RailPanel>(null);
  const [dockNotes, setDockNotes] = useState('');

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

  // Resizable sidebar state (persisted to localStorage)
  const [sidebarWidth, setSidebarWidth] = useState(() => {
    const stored = localStorage.getItem(SIDEBAR_WIDTH_KEY);
    if (stored) {
      const parsed = Number(stored);
      if (Number.isFinite(parsed) && parsed >= SIDEBAR_MIN && parsed <= SIDEBAR_MAX) return parsed;
    }
    return 260;
  });
  const sidebarWidthRef = useRef(sidebarWidth);
  const sidebarElRef = useRef<HTMLDivElement>(null);
  const isDraggingRef = useRef(false);

  const handleDragStart = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    e.preventDefault();
    const target = e.currentTarget;
    target.setPointerCapture(e.pointerId);
    isDraggingRef.current = true;
    const startX = e.clientX;
    const startWidth = sidebarWidthRef.current;

    const onMove = (moveEvent: PointerEvent) => {
      const w = Math.min(Math.max(startWidth + (moveEvent.clientX - startX), SIDEBAR_MIN), SIDEBAR_MAX);
      sidebarWidthRef.current = w;
      // P-12: Set DOM style directly during drag, skip React state
      if (sidebarElRef.current) {
        sidebarElRef.current.style.width = `${w}px`;
      }
    };

    const onUp = () => {
      target.removeEventListener('pointermove', onMove);
      target.removeEventListener('pointerup', onUp);
      isDraggingRef.current = false;
      // Commit final width to React state on pointerup
      setSidebarWidth(sidebarWidthRef.current);
      localStorage.setItem(SIDEBAR_WIDTH_KEY, String(sidebarWidthRef.current));
      mapInstanceRef.current?.resize();
    };

    target.addEventListener('pointermove', onMove);
    target.addEventListener('pointerup', onUp);
  }, []);

  // UX-13: Arrow-key resize on sidebar separator
  const handleSeparatorKeyDown = useCallback((e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
    e.preventDefault();
    const step = e.shiftKey ? 50 : 10;
    const delta = e.key === 'ArrowRight' ? step : -step;
    setSidebarWidth((prev) => {
      const next = Math.min(Math.max(prev + delta, SIDEBAR_MIN), SIDEBAR_MAX);
      sidebarWidthRef.current = next;
      localStorage.setItem(SIDEBAR_WIDTH_KEY, String(next));
      return next;
    });
  }, []);

  // Composed hooks
  const dialogs = useBuilderDialogs(aiAvailable, isMobile);
  const layers = useBuilderLayers(
    mapData,
    mapInstanceRef,
    id,
    addLayer,
    removeLayer,
  );
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
    // eslint-disable-next-line react-hooks/exhaustive-deps -- key strings avoid resetting local toggles on unrelated mapData identity changes
  }, [savedWidgetKey, enabledWidgetKey]);

  const save = useBuilderSave({
    mapId: id,
    localLayers: layers.localLayers,
    localBasemap: layers.localBasemap,
    showBasemapLabels: layers.showBasemapLabels,
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
  const existingDatasetIds = useMemo(() => layers.localLayers.map((l) => l.dataset_id), [layers.localLayers]);

  const editingLayer = useMemo(
    () => layers.expandedLayerId ? layers.localLayers.find((l) => l.id === layers.expandedLayerId) ?? null : null,
    [layers.expandedLayerId, layers.localLayers],
  );

  const layerEditorHandlers = useMemo(() => ({
    onTabChange: layers.handleTabChange,
    onPaintChange: layers.handlePaintChange,
    onOpacityChange: layers.handleOpacityChange,
    onFilterChange: layers.handleFilterChange,
    onLabelChange: layers.handleLabelChange,
    onPopupChange: layers.handlePopupChange,
    onStyleConfigChange: layers.handleStyleConfigChange,
    onLayoutChange: layers.handleLayoutChange,
    onRenderModeChange: layers.handleRenderModeChange,
  }), [layers.handleTabChange, layers.handlePaintChange, layers.handleOpacityChange, layers.handleFilterChange, layers.handleLabelChange, layers.handlePopupChange, layers.handleStyleConfigChange, layers.handleLayoutChange, layers.handleRenderModeChange]);

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
    // Return focus to the expand button that opened the flyout
    if (expandedId) {
      requestAnimationFrame(() => {
        document.getElementById(`layer-expand-${expandedId}`)?.focus();
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
      {/* Mobile sidebar as Sheet */}
      {isMobile && (
        <Sheet open={!dialogs.sidebarCollapsed} onOpenChange={(open) => dialogs.setSidebarCollapsed(!open)}>
          <SheetContent side="left" className="w-80 max-w-[calc(100vw-3rem)] p-0 flex flex-col">
            <SheetHeader className="sr-only">
              <SheetTitle>{layers.localName || t('mapBuilder')}</SheetTitle>
              <SheetDescription>{t('descriptionLabel')}</SheetDescription>
            </SheetHeader>
            <div className="p-3 border-b flex items-center justify-between">
              <span className="text-sm font-semibold truncate">{layers.localName}</span>
              <Button variant={layers.hasUnsavedChanges ? 'default' : 'outline'} size="sm" className="h-7 text-xs gap-1 shrink-0" onClick={save.handleSave} disabled={save.isSaving}>
                {save.isSaving ? <Loader2 className="h-3 w-3 animate-spin" /> : <Save className="h-3 w-3" />}
                {t('actions.save')}
              </Button>
            </div>
            <SidebarContent
              layers={layers}
              onAddDataClick={handleAddDataClick}
              widgetSidebar={<WidgetSidebar widgets={sidebar} ctx={widgetCtx} />}
            />
          </SheetContent>
        </Sheet>
      )}

      {/* Desktop sidebar */}
      {!isMobile && <div
        ref={sidebarElRef}
        data-testid="builder-sidebar"
        className={cn(
          "relative border-e bg-background flex flex-col shrink-0 overflow-hidden",
          dialogs.sidebarCollapsed ? "w-0 border-e-0 transition-[width,border-width] duration-200 ease-out" : "",
          !dialogs.sidebarCollapsed && !isDraggingRef.current ? "transition-[width,border-width] duration-200 ease-out" : ""
        )}
        style={dialogs.sidebarCollapsed ? undefined : { width: sidebarWidth }}
        onTransitionEnd={() => { mapInstanceRef.current?.resize(); }}
        {...(dialogs.sidebarCollapsed ? { inert: true } : {})}
      >
        {/* Drag handle for resize */}
        {!dialogs.sidebarCollapsed && (
          <div
            onPointerDown={handleDragStart}
            onKeyDown={handleSeparatorKeyDown}
            tabIndex={0}
            data-testid="builder-sidebar-resize-handle"
            role="slider"
            aria-orientation="horizontal"
            aria-label={t('tooltips.resizeSidebar', { defaultValue: 'Drag to resize sidebar' })}
            aria-valuenow={sidebarWidth}
            aria-valuemin={SIDEBAR_MIN}
            aria-valuemax={SIDEBAR_MAX}
            title={t('tooltips.resizeSidebar', { defaultValue: 'Drag to resize sidebar' })}
            className="absolute right-0 top-0 bottom-0 w-3 cursor-col-resize z-10 transition-colors hover:bg-primary/10 active:bg-primary/15"
          />
        )}
        {/* Edge collapse button */}
        {!dialogs.sidebarCollapsed && (
          <button
            onClick={() => dialogs.setSidebarCollapsed(true)}
            title={t('tooltips.collapseSidebar')}
            aria-label={t('tooltips.collapseSidebar')}
            aria-expanded={true}
            className="absolute -right-3.5 top-1/2 -translate-y-1/2 z-20 flex items-center justify-center h-10 w-7 rounded-e-md bg-background border border-s-0 shadow-sm hover:bg-accent/50 transition-colors"
          >
            <PanelLeftClose className="h-4 w-4 text-foreground/70 hover:text-foreground transition-colors" />
          </button>
        )}

        {/* Scrollable content */}
        <SidebarContent
          layers={layers}
          onAddDataClick={handleAddDataClick}
          widgetSidebar={<WidgetSidebar widgets={sidebar} ctx={widgetCtx} />}
        />
      </div>}

      {/* Map canvas (center) */}
      <div className="flex-1 relative min-h-0 min-w-0">
        {dialogs.sidebarCollapsed && (
          <button
            onClick={() => dialogs.setSidebarCollapsed(false)}
            title={t('tooltips.expandSidebar')}
            aria-label={t('tooltips.expandSidebar')}
            aria-expanded={false}
            className="absolute left-0 top-1/2 -translate-y-1/2 z-10 flex items-center justify-center h-10 w-7 rounded-e-md bg-background/95 backdrop-blur-sm border border-s-0 shadow-md hover:bg-accent/50 transition-colors"
          >
            <PanelLeftOpen className="h-4 w-4 text-foreground/70 hover:text-foreground transition-colors" />
          </button>
        )}
        <MapErrorBoundary hasUnsavedChanges={layers.hasUnsavedChanges}>
          <BuilderMap
            layers={layers.localLayers}
            basemapStyle={layers.localBasemap}
            initialViewState={layers.initialViewState}
            onMapRef={handleMapRef}
            showBasemapLabels={layers.showBasemapLabels}
          />
        </MapErrorBoundary>
        {layers.ephemeralResult && (
          <EphemeralBadge
            featureCount={layers.ephemeralResult.geojson.features.length}
            onDismiss={layers.handleDismissEphemeral}
          />
        )}

        {/* Layer editor flyout — extends from sidebar into map area */}
        {editingLayer && !isMobile && (
          <div className="absolute left-0 top-0 bottom-0 z-20 w-72 bg-background border-e shadow-md flex flex-col overflow-hidden">
            <LazyLoadErrorBoundary>
              <LayerEditorPanel
                layer={editingLayer}
                activeTab={layers.activeEditorTab ?? 'style'}
                handlers={layerEditorHandlers}
                onBack={handleCloseEditor}
              />
            </LazyLoadErrorBoundary>
          </div>
        )}

        {/* Centered toolbar */}
        <MapToolbar />

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

      {/* Right rail + panel */}
      {!isMobile && <BuilderRail {...railProps} />}

      {/* Mobile rail as Sheet overlay */}
      {isMobile && railPanel && (
        <Sheet open={!!railPanel} onOpenChange={(open) => { if (!open) setRailPanel(null); }}>
          <SheetContent side="right" className="w-80 p-0 flex flex-col">
            <SheetHeader className="sr-only">
              <SheetTitle>{t('dock.notes')}</SheetTitle>
              <SheetDescription>{t('dock.notesPlaceholder')}</SheetDescription>
            </SheetHeader>
            <BuilderRail {...railProps} />
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
        existingDatasetIds={existingDatasetIds}
        isAdding={addLayer.isPending}
        showShare={dialogs.showShare}
        onShowShareChange={dialogs.setShowShare}
        showInfo={dialogs.showInfo}
        onShowInfoChange={dialogs.setShowInfo}
        blockerState={save.blocker.state}
        onBlockerReset={save.blocker.reset}
        onBlockerProceed={save.blocker.proceed}
      />
    </div>
  );
}
