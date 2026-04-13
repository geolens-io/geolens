import React, { useState, useRef, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { Save, Loader2, Download, MessageSquare, PanelLeftClose, Share2, Copy, Info, MoreHorizontal, GripVertical } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { LayerPanel } from '@/components/builder/LayerPanel';
import { BasemapPicker } from '@/components/builder/BasemapPicker';
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
import { VisibilityIcon } from '@/components/maps/VisibilityIcon';
import { getVisibilityLabel } from '@/i18n/labels';
import type { Map as MaplibreMap } from 'maplibre-gl';
import type { useBuilderLayers } from '@/hooks/use-builder-layers';
import type { useBuilderSave } from '@/hooks/use-builder-save';

const SIDEBAR_WIDTH_KEY = 'geolens-builder-sidebar-width';
const SIDEBAR_MIN = 200;
const SIDEBAR_MAX = 600;

export function SidebarContent({
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

interface BuilderSidebarProps {
  layers: ReturnType<typeof useBuilderLayers>;
  save: ReturnType<typeof useBuilderSave>;
  localName: string;
  setLocalName: (v: string) => void;
  localDescription: string;
  setLocalDescription: (v: string) => void;
  mapData: { visibility: string; name?: string } | undefined;
  mapInstanceRef: React.RefObject<MaplibreMap | null>;
  aiAvailable: boolean;
  mapId: string | undefined;
  inspectorMode: boolean;
  saveShortcut: string;
  sidebarCollapsed: boolean;
  setSidebarCollapsed: (v: boolean) => void;
  showChat: boolean;
  setShowChat: (v: boolean | ((prev: boolean) => boolean)) => void;
  onShowAddData: () => void;
  onShowShare: () => void;
  onShowInfo: () => void;
}

export const BuilderSidebar = React.memo(function BuilderSidebar({
  layers,
  save,
  localName,
  setLocalName,
  localDescription,
  setLocalDescription,
  mapData,
  mapInstanceRef,
  aiAvailable,
  inspectorMode,
  saveShortcut,
  sidebarCollapsed,
  setSidebarCollapsed,
  showChat,
  setShowChat,
  onShowAddData,
  onShowShare,
  onShowInfo,
}: BuilderSidebarProps) {
  const { t } = useTranslation('builder');

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
  }, [mapInstanceRef]);

  return (
    <div
      data-testid="builder-sidebar"
      className={cn(
        "relative border-e bg-background flex flex-col shrink-0 overflow-hidden",
        sidebarCollapsed ? "w-0 border-e-0 transition-[width,border-width] duration-200 ease-out" : "",
        !sidebarCollapsed && !isDraggingRef.current ? "transition-[width,border-width] duration-200 ease-out" : ""
      )}
      style={sidebarCollapsed ? undefined : { width: sidebarWidth }}
      onTransitionEnd={() => { mapInstanceRef.current?.resize(); }}
      {...(sidebarCollapsed ? { inert: true } : {})}
    >
      {/* Drag handle for resize */}
      {!sidebarCollapsed && (
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
      {!sidebarCollapsed && (
        <button
          onClick={() => setSidebarCollapsed(true)}
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
                      variant={showChat ? 'default' : 'outline'}
                      size="icon-xs"
                      onClick={() => setShowChat((v: boolean) => !v)}
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
              {save && (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      variant="outline"
                      size="sm"
                      className="h-7 text-xs gap-1"
                      onClick={onShowShare}
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
                  <DropdownMenuItem onClick={onShowInfo}>
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
      <SidebarContent layers={layers} inspectorMode={inspectorMode} onAddDataClick={onShowAddData} />
    </div>
  );
});
