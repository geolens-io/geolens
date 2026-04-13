import { useState, useEffect, useRef, useCallback, useMemo, lazy, Suspense } from 'react';
import { useParams, Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { Save, Loader2, Download, MessageSquare, X, PanelLeftClose, PanelLeftOpen, Share2, Copy, Info, MoreHorizontal, GripVertical } from 'lucide-react';
import type { Map as MaplibreMap } from 'maplibre-gl';
import { ApiError } from '@/api/client';
import { Button } from '@/components/ui/button';
import { BuilderMap } from '@/components/builder/BuilderMap';
import { LayerPanel } from '@/components/builder/LayerPanel';
import { LayerInspector } from '@/components/builder/LayerInspector';
import { DatasetSearchPanel } from '@/components/builder/DatasetSearchPanel';
import { ShareDialog } from '@/components/builder/SharePanel';
const ChatPanel = lazy(() => import('@/components/builder/ChatPanel').then(m => ({ default: m.ChatPanel })));
import { EphemeralBadge } from '@/components/builder/EphemeralBadge';
import { experimentalBadgeColor } from '@/lib/status-colors';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from '@/components/ui/sheet';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import { formatRelativeDate } from '@/lib/format';
import { LoadingState } from '@/components/layout/LoadingState';
import { ErrorState } from '@/components/layout/ErrorState';
import { MapErrorBoundary } from '@/components/error';
import { useMap, useAddLayer, useRemoveLayer } from '@/hooks/use-maps';
import { useAIAvailability } from '@/hooks/use-ai-availability';
import { getVisibilityLabel } from '@/i18n/labels';
import { useDocumentTitle } from '@/hooks/use-document-title';
import { useBuilderLayout } from '@/hooks/use-builder-layout';
import { useBuilderDialogs } from '@/hooks/use-builder-dialogs';
import { useBuilderLayers } from '@/hooks/use-builder-layers';
import { useBuilderSave } from '@/hooks/use-builder-save';
import { BasemapPicker } from '@/components/builder/BasemapPicker';
import { WidgetHost, WidgetToolbar, getWidgets, usePartitionedWidgets } from '@/components/map-widgets';
import { useWidgetStore } from '@/stores/map-widget-store';
import { VisibilityIcon } from '@/components/maps/VisibilityIcon';

const SIDEBAR_WIDTH_KEY = 'geolens-builder-sidebar-width';
const SIDEBAR_MIN = 200;
const SIDEBAR_MAX = 600;

function ChatPanelContent({
  mapId,
  layers,
  dialogs,
}: {
  mapId: string;
  layers: ReturnType<typeof useBuilderLayers>;
  dialogs: ReturnType<typeof useBuilderDialogs>;
}) {
  const { t } = useTranslation('builder');
  return (
    <>
      <div className="p-3 border-b flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-medium">{t('aiChat')}</h3>
          <Badge variant="outline" className={`text-[10px] px-1.5 py-0 ${experimentalBadgeColor}`}>
            {t('chat.experimental')}
          </Badge>
        </div>
        <Button variant="ghost" size="icon-xs" onClick={() => dialogs.setShowChat(false)} aria-label={t('tooltips.closeChat')}>
          <X className="h-3 w-3" />
        </Button>
      </div>
      <div className="flex-1 overflow-hidden">
        <Suspense fallback={<div className="flex-1 flex items-center justify-center p-4"><Loader2 className="h-4 w-4 animate-spin text-muted-foreground" /></div>}>
          <ChatPanel
            mapId={mapId}
            layers={layers.localLayers}
            layerActions={{
              onFilterChange: layers.handleFilterChange,
              onPaintChange: layers.handlePaintChange,
              onStyleConfigChange: layers.handleStyleConfigChange,
              onLabelChange: layers.handleLabelChange,
              onToggleVisibility: layers.handleToggleVisibility,
              onAddDataset: layers.handleAddDataset,
              onRemove: layers.handleAiRemoveLayer,
              onOpacityChange: layers.handleOpacityChange,
            }}
            onQueryResult={layers.handleQueryResult}
          />
        </Suspense>
      </div>
    </>
  );
}

function SidebarContent({
  layers,
  inspectorMode,
  onAddDataClick,
}: {
  layers: ReturnType<typeof useBuilderLayers>;
  inspectorMode: boolean;
  onAddDataClick: () => void;
}) {
  const { t } = useTranslation('builder');
  return (
    <div className="flex-1 overflow-y-auto space-y-4 py-3">
      <LayerPanel
        layers={layers.localLayers}
        expandedLayerId={layers.expandedLayerId}
        activeTab={layers.activeEditorTab}
        onToggleExpand={layers.handleToggleExpand}
        onTabChange={layers.handleTabChange}
        onPaintChange={layers.handlePaintChange}
        onOpacityChange={layers.handleOpacityChange}
        onFilterChange={layers.handleFilterChange}
        onLabelChange={layers.handleLabelChange}
        onStyleConfigChange={layers.handleStyleConfigChange}
        onLayoutChange={layers.handleLayoutChange}
        onToggleVisibility={layers.handleToggleVisibility}
        onMoveUp={layers.handleMoveUp}
        onMoveDown={layers.handleMoveDown}
        onReorder={layers.handleReorder}
        onRename={layers.handleDisplayNameChange}
        onRemove={layers.handleRemove}
        onZoomToLayer={layers.handleZoomToLayer}
        onToggleLegend={layers.handleToggleLegend}
        onAddDataClick={onAddDataClick}
        inspectorMode={inspectorMode}
      />
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
}

export function MapBuilderPage() {
  const { id } = useParams<{ id: string }>();
  const { t } = useTranslation('builder');
  const { data: mapData, isLoading, error } = useMap(id);
  const addLayer = useAddLayer();
  const removeLayer = useRemoveLayer();

  const { isAIAvailable: aiAvailable } = useAIAvailability();
  useDocumentTitle(mapData?.name ?? t('common:pageTitle.mapBuilder'));
  const { isCompact, isMobile } = useBuilderLayout();

  const mapInstanceRef = useRef<MaplibreMap | null>(null);
  const [mapInstance, setMapInstance] = useState<MaplibreMap | null>(null);

  // Resizable sidebar state (persisted to localStorage)
  const [sidebarWidth, setSidebarWidth] = useState(() => {
    const stored = localStorage.getItem(SIDEBAR_WIDTH_KEY);
    if (stored) {
      const parsed = Number(stored);
      if (Number.isFinite(parsed) && parsed >= SIDEBAR_MIN && parsed <= SIDEBAR_MAX) return parsed;
    }
    return window.innerWidth >= 1024 ? 320 : 256;
  });
  const sidebarWidthRef = useRef(sidebarWidth);
  const isDraggingRef = useRef(false);

  const handleDragStart = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    e.preventDefault();
    const target = e.currentTarget;
    target.setPointerCapture(e.pointerId);
    isDraggingRef.current = true;
    const startX = e.clientX;
    const startWidth = sidebarWidthRef.current;

    let rafPending = false;
    const onMove = (moveEvent: PointerEvent) => {
      const w = Math.min(Math.max(startWidth + (moveEvent.clientX - startX), SIDEBAR_MIN), SIDEBAR_MAX);
      sidebarWidthRef.current = w;
      if (!rafPending) {
        rafPending = true;
        requestAnimationFrame(() => {
          rafPending = false;
          setSidebarWidth(sidebarWidthRef.current);
        });
      }
    };

    const onUp = () => {
      target.removeEventListener('pointermove', onMove);
      target.removeEventListener('pointerup', onUp);
      isDraggingRef.current = false;
      localStorage.setItem(SIDEBAR_WIDTH_KEY, String(sidebarWidthRef.current));
      mapInstanceRef.current?.resize();
    };

    target.addEventListener('pointermove', onMove);
    target.addEventListener('pointerup', onUp);
  }, []);

  // Composed hooks
  const dialogs = useBuilderDialogs(aiAvailable);
  const layers = useBuilderLayers(
    mapData,
    mapInstanceRef,
    id,
    addLayer,
    removeLayer,
  );
  const [localName, setLocalName] = useState('');
  const [localDescription, setLocalDescription] = useState('');

  // Open all defaultVisible widgets on mount
  useEffect(() => {
    const store = useWidgetStore.getState();
    getWidgets().filter((w) => w.defaultVisible).forEach((w) => store.open(w.id));
  }, []);

  // Initialize name/description from API data (once)
  const nameInitRef = useRef(false);
  useEffect(() => {
    if (mapData && !nameInitRef.current) {
      setLocalName(mapData.name);
      setLocalDescription(mapData.description ?? '');
      nameInitRef.current = true;
    }
  }, [mapData]);

  const save = useBuilderSave({
    mapId: id,
    localLayers: layers.localLayers,
    localBasemap: layers.localBasemap,
    showBasemapLabels: layers.showBasemapLabels,
    localName,
    localDescription,
    mapInstanceRef,
    setHasUnsavedChanges: layers.setHasUnsavedChanges,
    hasUnsavedChanges: layers.hasUnsavedChanges,
    hasThumbnail: !!mapData?.thumbnail_url,
  });

  const handleMapRef = useCallback((map: MaplibreMap | null) => {
    (mapInstanceRef as React.MutableRefObject<MaplibreMap | null>).current = map;
    setMapInstance(map);
    if (map) save.maybeAutoCaptureThumbnail(map);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only the method reference matters, not the whole `save` object
  }, [save.maybeAutoCaptureThumbnail]);

  const widgetCtx = useMemo(
    () => ({ mapInstance, layers: layers.localLayers, mapId: id! }),
    [mapInstance, layers.localLayers, id],
  );

  const { byAnchor } = usePartitionedWidgets();
  const existingDatasetIds = useMemo(() => layers.localLayers.map((l) => l.dataset_id), [layers.localLayers]);

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

  const isMac = typeof navigator !== 'undefined' && /Mac/i.test(navigator.platform);
  const saveShortcut = isMac ? '\u2318S' : 'Ctrl+S';

  const useInspector = !isCompact;
  const selectedLayer = useInspector && layers.expandedLayerId
    ? layers.localLayers.find((l) => l.id === layers.expandedLayerId) ?? null
    : null;

  return (
    <div className="flex h-[calc(100vh-3.5rem)]">
      {/* Mobile sidebar as Sheet */}
      {isMobile && (
        <Sheet open={!dialogs.sidebarCollapsed} onOpenChange={(open) => dialogs.setSidebarCollapsed(!open)}>
          <SheetContent side="left" className="w-80 max-w-[calc(100vw-3rem)] p-0 flex flex-col" showCloseButton={false}>
            <SheetHeader className="sr-only">
              <SheetTitle>{localName || t('mapBuilder')}</SheetTitle>
              <SheetDescription>{t('descriptionLabel')}</SheetDescription>
            </SheetHeader>
            <div className="p-3 border-b space-y-2">
              <div className="flex items-center gap-1.5">
                <input
                  type="text"
                  value={localName}
                  onChange={(e) => { setLocalName(e.target.value); layers.markDirty(); }}
                  aria-label={t('mapNameLabel')}
                  className="text-sm font-semibold truncate bg-transparent border-none outline-none focus:ring-1 focus:ring-ring rounded px-1 -ms-1 min-h-7 w-full hover:bg-accent/30 transition-colors"
                  title={localName}
                />
                {mapData && (
                  <Badge variant="outline" className="flex items-center gap-1 text-[10px] px-1.5 py-0 shrink-0">
                    <VisibilityIcon visibility={mapData.visibility} />
                    {getVisibilityLabel(t, mapData.visibility)}
                  </Badge>
                )}
              </div>
              <div className="flex items-center gap-1 justify-end">
                <Button variant={layers.hasUnsavedChanges ? 'default' : 'outline'} size="sm" className="h-7 text-xs gap-1" onClick={save.handleSave} disabled={save.isSaving}>
                  {save.isSaving ? <Loader2 className="h-3 w-3 animate-spin" /> : <Save className="h-3 w-3" />}
                  {t('actions.save')}
                </Button>
              </div>
            </div>
            <SidebarContent layers={layers} inspectorMode={false} onAddDataClick={() => dialogs.setShowAddData(true)} />
          </SheetContent>
        </Sheet>
      )}

      {/* Desktop sidebar */}
      {!isMobile && <div
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
            data-testid="builder-sidebar-resize-handle"
            role="separator"
            aria-orientation="vertical"
            aria-label={t('tooltips.resizeSidebar', { defaultValue: 'Drag to resize sidebar' })}
            title={t('tooltips.resizeSidebar', { defaultValue: 'Drag to resize sidebar' })}
            className="group absolute right-0 top-0 bottom-0 w-3 cursor-col-resize z-10 transition-colors hover:bg-primary/10 active:bg-primary/15"
          >
            <div className="pointer-events-none absolute right-0 top-1/2 hidden -translate-y-1/2 lg:flex">
              <div className="me-1 flex h-16 w-5 items-center justify-center rounded-full border border-border/70 bg-background/95 shadow-sm transition-colors group-hover:border-primary/40 group-hover:bg-accent">
                <GripVertical className="h-4 w-4 text-muted-foreground transition-colors group-hover:text-foreground" />
              </div>
            </div>
          </div>
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

        {/* Header */}
        <div className="p-3 border-b space-y-2">
          <h1 className="sr-only">{localName || t('mapBuilder')}</h1>
          <div className="flex items-center gap-1.5">
            <input
              type="text"
              value={localName}
              onChange={(e) => {
                setLocalName(e.target.value);
                layers.markDirty();
              }}
              aria-label={t('mapNameLabel')}
              className="text-sm font-semibold truncate bg-transparent border-none outline-none focus:ring-1 focus:ring-ring rounded px-1 -ms-1 min-h-7 w-full hover:bg-accent/30 transition-colors"
              title={localName}
            />
            {mapData && (
              <Badge variant="outline" className="flex items-center gap-1 text-[10px] px-1.5 py-0 shrink-0">
                <VisibilityIcon visibility={mapData.visibility} />
                {getVisibilityLabel(t, mapData.visibility)}
              </Badge>
            )}
          </div>
          <input
            type="text"
            value={localDescription}
            onChange={(e) => {
              setLocalDescription(e.target.value);
              layers.markDirty();
            }}
            placeholder={t('descriptionPlaceholder')}
            aria-label={t('descriptionLabel')}
            title={localDescription}
            className="text-xs text-muted-foreground bg-transparent border-none outline-none focus:ring-1 focus:ring-ring rounded px-1 -ms-1 min-h-6 w-full placeholder:text-muted-foreground/50 hover:bg-accent/30 transition-colors"
          />
          {/* Button tray */}
          <TooltipProvider delayDuration={300}>
            <div className="flex items-center justify-between pt-1.5">
              <div className="flex gap-1 lg:gap-1.5">
                {aiAvailable && (
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button
                        variant={dialogs.showChat ? 'default' : 'outline'}
                        size="icon-xs"
                        onClick={() => dialogs.setShowChat((v) => !v)}
                        aria-label={t('tooltips.aiChat')}
                      >
                        <MessageSquare className="h-3 w-3" />
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent side="bottom">{t('tooltips.aiChat')}</TooltipContent>
                  </Tooltip>
                )}
              </div>

              <div className="flex items-center gap-1 lg:gap-1.5">
                {id && (
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button
                        variant="outline"
                        size="sm"
                        className="h-7 text-xs gap-1"
                        onClick={() => dialogs.setShowShare(true)}
                        aria-label={t('tooltips.share')}
                      >
                        <Share2 className="h-3 w-3" />
                        {t('tooltips.share')}
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent side="bottom">{t('tooltips.share')}</TooltipContent>
                  </Tooltip>
                )}

                <DropdownMenu>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <DropdownMenuTrigger asChild>
                        <Button
                          variant="outline"
                          size="icon-xs"
                          aria-label={t('tooltips.moreActions')}
                        >
                          <MoreHorizontal className="h-3 w-3" />
                        </Button>
                      </DropdownMenuTrigger>
                    </TooltipTrigger>
                    <TooltipContent side="bottom">{t('tooltips.moreActions')}</TooltipContent>
                  </Tooltip>
                  <DropdownMenuContent align="end">
                    <DropdownMenuItem onClick={() => dialogs.setShowInfo(true)}>
                      <Info className="h-3.5 w-3.5 me-2" />
                      {t('tooltips.mapInfo')}
                    </DropdownMenuItem>
                    <DropdownMenuItem onClick={save.handleExportPNG}>
                      <Download className="h-3.5 w-3.5 me-2" />
                      {t('tooltips.downloadPng')}
                    </DropdownMenuItem>
                    <DropdownMenuItem onClick={save.handleFork} disabled={save.isForkPending}>
                      <Copy className="h-3.5 w-3.5 me-2" />
                      {t('tooltips.duplicateMap')}
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>

                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      variant={layers.hasUnsavedChanges ? 'default' : 'outline'}
                      size="sm"
                      className="h-7 text-xs gap-1 relative"
                      onClick={save.handleSave}
                      disabled={save.isSaving}
                      aria-label={t('tooltips.save', { shortcut: saveShortcut })}
                    >
                      {save.isSaving ? (
                        <Loader2 className="h-3 w-3 animate-spin" />
                      ) : (
                        <Save className="h-3 w-3" />
                      )}
                      {t('actions.save')}
                      {layers.hasUnsavedChanges && (
                        <>
                          <span className="absolute -top-0.5 -right-0.5 h-2 w-2 rounded-full bg-warning" />
                          <span className="sr-only">Unsaved changes</span>
                        </>
                      )}
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent side="bottom">
                    {layers.hasUnsavedChanges
                      ? t('tooltips.save', { shortcut: saveShortcut })
                      : t('tooltips.allSaved')}
                  </TooltipContent>
                </Tooltip>
              </div>
            </div>
          </TooltipProvider>
        </div>

        {/* Scrollable content */}
        <SidebarContent layers={layers} inspectorMode={useInspector} onAddDataClick={() => dialogs.setShowAddData(true)} />
      </div>}

      {/* Layer Inspector panel (wide screens only) */}
      {selectedLayer && (
        <div className="w-72 border-e bg-background flex flex-col shrink-0 overflow-hidden">
          <LayerInspector
            layer={selectedLayer}
            activeTab={layers.activeEditorTab}
            onTabChange={layers.handleTabChange}
            onPaintChange={layers.handlePaintChange}
            onOpacityChange={layers.handleOpacityChange}
            onFilterChange={layers.handleFilterChange}
            onLabelChange={layers.handleLabelChange}
            onStyleConfigChange={layers.handleStyleConfigChange}
            onLayoutChange={layers.handleLayoutChange}
            onRenderModeChange={layers.handleRenderModeChange}
            onClose={() => layers.handleToggleExpand('')}
          />
        </div>
      )}

      {/* Map */}
      <div className="flex-1 relative">
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
        <WidgetToolbar />
        <WidgetHost byAnchor={byAnchor} ctx={widgetCtx} />
      </div>

      {/* Chat panel - compact: Sheet overlay, wide: inline rail */}
      {isCompact && dialogs.showChat && id && (
        <Sheet open={dialogs.showChat} onOpenChange={dialogs.setShowChat}>
          <SheetContent side="right" className="w-80 p-0" showCloseButton={false}>
            <SheetHeader className="sr-only">
              <SheetTitle>{t('aiChat')}</SheetTitle>
              <SheetDescription>{t('tooltips.aiChat')}</SheetDescription>
            </SheetHeader>
            <ChatPanelContent mapId={id} layers={layers} dialogs={dialogs} />
          </SheetContent>
        </Sheet>
      )}
      {!isCompact && dialogs.showChat && id && (
        <div className="w-80 border-s bg-background flex flex-col shrink-0 overflow-hidden">
          <ChatPanelContent mapId={id} layers={layers} dialogs={dialogs} />
        </div>
      )}

      {/* Add Data dialog */}
      <Dialog open={dialogs.showAddData} onOpenChange={dialogs.setShowAddData}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{t('search.title')}</DialogTitle>
            <DialogDescription>{t('search.dialogDescription')}</DialogDescription>
          </DialogHeader>
          <DatasetSearchPanel
            onAddDataset={(datasetId) => {
              layers.handleAddDataset(datasetId);
            }}
            existingDatasetIds={existingDatasetIds}
            isAdding={addLayer.isPending}
          />
        </DialogContent>
      </Dialog>

      {/* Share dialog */}
      {id && (
        <ShareDialog
          mapId={id}
          visibility={mapData.visibility ?? 'private'}
          open={dialogs.showShare}
          onOpenChange={dialogs.setShowShare}
        />
      )}

      {/* Map Info dialog */}
      <Dialog open={dialogs.showInfo} onOpenChange={dialogs.setShowInfo}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>{t('info.title')}</DialogTitle>
            <DialogDescription>{t('info.dialogDescription')}</DialogDescription>
          </DialogHeader>
          <div className="space-y-3 text-sm">
            <div className="flex justify-between">
              <span className="text-muted-foreground">{t('info.author')}</span>
              <span className="font-medium">{mapData?.created_by_username ?? t('info.unknown')}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">{t('info.created')}</span>
              <span>{formatRelativeDate(mapData?.created_at ?? null)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">{t('info.updated')}</span>
              <span>{formatRelativeDate(mapData?.updated_at ?? null)}</span>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-muted-foreground">{t('info.visibility')}</span>
              <Badge variant="outline" className="flex items-center gap-1 text-xs">
                <VisibilityIcon visibility={mapData?.visibility ?? 'private'} />
                {getVisibilityLabel(t, mapData?.visibility ?? 'private')}
              </Badge>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">{t('info.layers')}</span>
              <span>{mapData?.layer_count ?? 0}</span>
            </div>
            {mapData?.forked_from_id && (
              <div className="flex justify-between">
                <span className="text-muted-foreground">{t('info.forkedFrom')}</span>
                {mapData.forked_from_name ? (
                  <Link
                    to={`/maps/${mapData.forked_from_id}`}
                    className="text-primary underline hover:text-primary/80"
                    onClick={() => dialogs.setShowInfo(false)}
                  >
                    {mapData.forked_from_name}
                  </Link>
                ) : (
                  <span className="text-muted-foreground/60">{t('info.deletedMap')}</span>
                )}
              </div>
            )}
          </div>
        </DialogContent>
      </Dialog>

      {/* Unsaved changes leave warning */}
      <Dialog open={save.blocker.state === 'blocked'} onOpenChange={() => save.blocker.reset?.()}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>{t('leaveWarning.title')}</DialogTitle>
            <DialogDescription>{t('leaveWarning.description')}</DialogDescription>
          </DialogHeader>
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => save.blocker.reset?.()}>
              {t('leaveWarning.stay')}
            </Button>
            <Button variant="destructive" onClick={() => save.blocker.proceed?.()}>
              {t('leaveWarning.leave')}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
