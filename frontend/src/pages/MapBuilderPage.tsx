import { useState, useEffect, useRef, useCallback, useMemo, lazy, Suspense } from 'react';
import { useParams, Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { Save, Loader2, X, PanelLeftOpen } from 'lucide-react';
import type { Map as MaplibreMap } from 'maplibre-gl';
import { ApiError } from '@/api/client';
import { Button } from '@/components/ui/button';
import { BuilderMap } from '@/components/builder/BuilderMap';
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
import { Badge } from '@/components/ui/badge';
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
import { WidgetHost, WidgetToolbar, getWidgets, usePartitionedWidgets } from '@/components/map-widgets';
import { useWidgetStore } from '@/stores/map-widget-store';
import { VisibilityIcon } from '@/components/maps/VisibilityIcon';
import { BuilderSidebar, SidebarContent } from '@/pages/components/BuilderSidebar';

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
      {!isMobile && (
        <BuilderSidebar
          layers={layers}
          save={save}
          localName={localName}
          setLocalName={setLocalName}
          localDescription={localDescription}
          setLocalDescription={setLocalDescription}
          mapData={mapData}
          mapInstanceRef={mapInstanceRef}
          aiAvailable={aiAvailable}
          mapId={id}
          inspectorMode={useInspector}
          saveShortcut={saveShortcut}
          sidebarCollapsed={dialogs.sidebarCollapsed}
          setSidebarCollapsed={dialogs.setSidebarCollapsed}
          showChat={dialogs.showChat}
          setShowChat={dialogs.setShowChat}
          onShowAddData={() => dialogs.setShowAddData(true)}
          onShowShare={() => dialogs.setShowShare(true)}
          onShowInfo={() => dialogs.setShowInfo(true)}
        />
      )}

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
