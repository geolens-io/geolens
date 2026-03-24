import { useState, useEffect, useRef, useCallback } from 'react';
import { useParams, Link, useSearchParams } from 'react-router';
import { useTranslation } from 'react-i18next';
import { Save, Loader2, Download, MessageSquare, X, PanelLeftClose, PanelLeftOpen, Share2, Copy, Info, Globe, Users, Lock, MoreHorizontal } from 'lucide-react';
import type { Map as MaplibreMap } from 'maplibre-gl';
import { Button } from '@/components/ui/button';
import { BuilderMap } from '@/components/builder/BuilderMap';
import { LayerPanel } from '@/components/builder/LayerPanel';
import { BasemapPicker } from '@/components/builder/BasemapPicker';
import { DatasetSearchPanel } from '@/components/builder/DatasetSearchPanel';
import { ShareDialog } from '@/components/builder/SharePanel';
import { ChatPanel } from '@/components/builder/ChatPanel';
import { EphemeralBadge } from '@/components/builder/EphemeralBadge';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from '@/components/ui/sheet';
import { MapLegend } from '@/components/map/MapLegend';
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
import { useAIStatus } from '@/hooks/use-admin';
import { usePermissions } from '@/hooks/use-permissions';
import { getVisibilityLabel } from '@/i18n/labels';
import { useDocumentTitle } from '@/hooks/use-document-title';
import { useBuilderLayout } from '@/hooks/use-builder-layout';
import { useBuilderDialogs } from '@/hooks/use-builder-dialogs';
import { useBuilderLayers } from '@/hooks/use-builder-layers';
import { useBuilderSave } from '@/hooks/use-builder-save';

export function MapBuilderPage() {
  const { id } = useParams<{ id: string }>();
  const { t } = useTranslation('builder');
  const { data: mapData, isLoading, error } = useMap(id);
  const addLayer = useAddLayer();
  const removeLayer = useRemoveLayer();

  const { data: aiStatus } = useAIStatus();
  const { can } = usePermissions();
  useDocumentTitle(mapData?.name ?? 'Map Builder');
  const aiAvailable = aiStatus?.configured && aiStatus?.enabled && can('use_ai_chat');
  const { isCompact } = useBuilderLayout();

  const mapInstanceRef = useRef<MaplibreMap | null>(null);
  const [searchParams, setSearchParams] = useSearchParams();

  // Composed hooks
  const dialogs = useBuilderDialogs(aiAvailable);
  const layers = useBuilderLayers(
    mapData,
    mapInstanceRef,
    id,
    addLayer,
    removeLayer,
    searchParams,
    setSearchParams,
  );

  const [localName, setLocalName] = useState('');
  const [localDescription, setLocalDescription] = useState('');

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
    localName,
    localDescription,
    mapInstanceRef,
    setHasUnsavedChanges: layers.setHasUnsavedChanges,
    hasUnsavedChanges: layers.hasUnsavedChanges,
    hasThumbnail: !!mapData?.thumbnail,
  });

  const handleMapRef = useCallback((map: MaplibreMap | null) => {
    layers.handleMapRef(map);
    if (map) save.maybeAutoCaptureThumbnail(map);
  }, [layers.handleMapRef, save.maybeAutoCaptureThumbnail]);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-[calc(100vh-3.5rem)]">
        <LoadingState message={t('loadingMap')} />
      </div>
    );
  }

  if (error || !mapData) {
    return (
      <div className="flex items-center justify-center h-[calc(100vh-3.5rem)]">
        <div className="text-center space-y-4">
          <ErrorState message={t('common:errors.mapNotFound')} />
          <Link to="/maps" className="text-sm text-primary hover:underline">
            {t('backToMaps')}
          </Link>
        </div>
      </div>
    );
  }

  const isMac = typeof navigator !== 'undefined' && /Mac/i.test(navigator.platform);
  const saveShortcut = isMac ? '\u2318S' : 'Ctrl+S';

  function VisibilityIcon({ visibility }: { visibility: string }) {
    if (visibility === 'public') return <Globe className="h-3 w-3 text-emerald-500" />;
    if (visibility === 'internal') return <Users className="h-3 w-3 text-amber-500" />;
    return <Lock className="h-3 w-3 text-muted-foreground" />;
  }

  const existingDatasetIds = layers.localLayers.map((l) => l.dataset_id);

  const legendLayers = layers.localLayers.map((l) => ({
    name: l.display_name ?? l.dataset_name,
    styleConfig: l.style_config,
    visible: l.visible,
  }));

  return (
    <div className="flex h-[calc(100vh-3.5rem)]">
      {/* Sidebar */}
      <div
        className={cn(
          "relative border-r bg-background flex flex-col shrink-0 overflow-hidden transition-all duration-200",
          dialogs.sidebarCollapsed ? "w-0 border-r-0" : "w-64 lg:w-80"
        )}
        onTransitionEnd={() => { mapInstanceRef.current?.resize(); }}
        {...(dialogs.sidebarCollapsed ? { inert: true } : {})}
      >
        {/* Edge collapse button */}
        {!dialogs.sidebarCollapsed && (
          <button
            onClick={() => dialogs.setSidebarCollapsed(true)}
            title={t('tooltips.collapseSidebar')}
            aria-label={t('tooltips.collapseSidebar')}
            className="absolute -right-3.5 top-1/2 -translate-y-1/2 z-20 flex items-center justify-center h-10 w-7 rounded-r-md bg-background border border-l-0 shadow-sm hover:bg-accent/50 transition-colors"
          >
            <PanelLeftClose className="h-4 w-4 text-foreground/70 hover:text-foreground transition-colors" />
          </button>
        )}

        {/* Header */}
        <div className="p-3 border-b space-y-2">
          <div className="flex items-center gap-1.5">
            <input
              type="text"
              value={localName}
              onChange={(e) => {
                setLocalName(e.target.value);
                layers.markDirty();
              }}
              className="text-sm font-semibold truncate bg-transparent border-none outline-none focus:ring-1 focus:ring-ring rounded px-1 -ml-1 w-full hover:bg-accent/30 transition-colors"
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
            className="text-xs text-muted-foreground bg-transparent border-none outline-none focus:ring-1 focus:ring-ring rounded px-1 -ml-1 w-full placeholder:text-muted-foreground/50 hover:bg-accent/30 transition-colors"
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
                    {id && (
                      <DropdownMenuItem onClick={() => dialogs.setShowShare(true)}>
                        <Share2 className="h-3.5 w-3.5 mr-2" />
                        {t('tooltips.share')}
                      </DropdownMenuItem>
                    )}
                    <DropdownMenuItem onClick={() => dialogs.setShowInfo(true)}>
                      <Info className="h-3.5 w-3.5 mr-2" />
                      {t('tooltips.mapInfo')}
                    </DropdownMenuItem>
                    <DropdownMenuItem onClick={save.handleExportPNG}>
                      <Download className="h-3.5 w-3.5 mr-2" />
                      {t('tooltips.downloadPng')}
                    </DropdownMenuItem>
                    <DropdownMenuItem onClick={save.handleFork} disabled={save.isForkPending}>
                      <Copy className="h-3.5 w-3.5 mr-2" />
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
                        <span className="absolute -top-0.5 -right-0.5 h-2 w-2 rounded-full bg-amber-500" />
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
            onToggleVisibility={layers.handleToggleVisibility}
            onMoveUp={layers.handleMoveUp}
            onMoveDown={layers.handleMoveDown}
            onReorder={layers.handleReorder}
            onRename={layers.handleDisplayNameChange}
            onRemove={layers.handleRemove}
            onZoomToLayer={layers.handleZoomToLayer}
            onAddDataClick={() => dialogs.setShowAddData(true)}
          />

          <div className="border-t pt-3 px-2">
            <h3 className="text-sm font-medium mb-2">{t('basemap.title')}</h3>
            <BasemapPicker
              value={layers.localBasemap}
              onChange={(key) => {
                layers.setLocalBasemap(key);
                layers.markDirty();
              }}
              showLabels={layers.showBasemapLabels}
              onToggleLabels={layers.setShowBasemapLabels}
            />
          </div>


        </div>
      </div>

      {/* Map */}
      <div className="flex-1 relative">
        {dialogs.sidebarCollapsed && (
          <button
            onClick={() => dialogs.setSidebarCollapsed(false)}
            title={t('tooltips.expandSidebar')}
            aria-label={t('tooltips.expandSidebar')}
            className="absolute left-0 top-1/2 -translate-y-1/2 z-10 flex items-center justify-center h-10 w-7 rounded-r-md bg-background/95 backdrop-blur-sm border border-l-0 shadow-md hover:bg-accent/50 transition-colors"
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
        <MapLegend layers={legendLayers} />
      </div>

      {/* Chat panel - compact: Sheet overlay, wide: inline rail */}
      {isCompact && dialogs.showChat && id && (
        <Sheet open={dialogs.showChat} onOpenChange={dialogs.setShowChat}>
          <SheetContent side="right" className="w-80 p-0" showCloseButton={false}>
            <SheetHeader className="sr-only">
              <SheetTitle>{t('aiChat')}</SheetTitle>
              <SheetDescription>{t('tooltips.aiChat')}</SheetDescription>
            </SheetHeader>
            <div className="p-3 border-b flex items-center justify-between">
              <div className="flex items-center gap-2">
                <h3 className="text-sm font-medium">{t('aiChat')}</h3>
                <Badge variant="outline" className="text-[10px] px-1.5 py-0 border-amber-500/50 text-amber-600 dark:text-amber-400">
                  {t('chat.experimental')}
                </Badge>
              </div>
              <Button variant="ghost" size="icon-xs" onClick={() => dialogs.setShowChat(false)} aria-label={t('tooltips.closeChat')}>
                <X className="h-3 w-3" />
              </Button>
            </div>
            <div className="flex-1 overflow-hidden">
              <ChatPanel
                mapId={id}
                layers={layers.localLayers}
                onFilterChange={layers.handleFilterChange}
                onPaintChange={layers.handlePaintChange}
                onStyleConfigChange={layers.handleStyleConfigChange}
                onLabelChange={layers.handleLabelChange}
                onToggleVisibility={layers.handleToggleVisibility}
                onAddDataset={layers.handleAiAddDataset}
                onRemove={layers.handleAiRemoveLayer}
                onQueryResult={layers.handleQueryResult}
                onOpacityChange={layers.handleOpacityChange}
              />
            </div>
          </SheetContent>
        </Sheet>
      )}
      {!isCompact && dialogs.showChat && id && (
        <div className="w-80 border-l bg-background flex flex-col shrink-0 overflow-hidden">
          <div className="p-3 border-b flex items-center justify-between">
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-medium">{t('aiChat')}</h3>
              <Badge variant="outline" className="text-[10px] px-1.5 py-0 border-amber-500/50 text-amber-600 dark:text-amber-400">
                {t('chat.experimental')}
              </Badge>
            </div>
            <Button variant="ghost" size="icon-xs" onClick={() => dialogs.setShowChat(false)} aria-label={t('tooltips.closeChat')}>
              <X className="h-3 w-3" />
            </Button>
          </div>
          <div className="flex-1 overflow-hidden">
            <ChatPanel
              mapId={id}
              layers={layers.localLayers}
              onFilterChange={layers.handleFilterChange}
              onPaintChange={layers.handlePaintChange}
              onStyleConfigChange={layers.handleStyleConfigChange}
              onLabelChange={layers.handleLabelChange}
              onToggleVisibility={layers.handleToggleVisibility}
              onAddDataset={layers.handleAiAddDataset}
              onRemove={layers.handleAiRemoveLayer}
              onQueryResult={layers.handleQueryResult}
              onOpacityChange={layers.handleOpacityChange}
            />
          </div>
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

