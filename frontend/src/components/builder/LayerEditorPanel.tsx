import { memo, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronLeft, ChevronRight, X } from 'lucide-react';
import { LayerStyleEditor } from './LayerStyleEditor';
import { LayerFilterEditor } from './LayerFilterEditor';
import { LabelEditor } from './LabelEditor';
import { PopupConfigEditor } from './PopupConfigEditor';
import { RasterLayerControls } from './RasterLayerControls';
import { ColumnsReference } from './ColumnsReference';
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible';
import { Slider } from '@/components/ui/slider';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { cn } from '@/lib/utils';
import { getLayerCapabilities } from '@/lib/layer-capabilities';
import { getRenderAsOptions, getCurrentRenderAs } from './renderAs';
import { ColorizedGeometryIcon, getLayerColors, extractStyleHints } from '@/components/map/layer-icons';
import type { FilterSpecification } from 'maplibre-gl';
import type { MapLayerResponse, LabelConfig, PopupConfig, StyleConfig } from '@/types/api';

export interface LayerEditorHandlers {
  onTabChange: (layerId: string, tab: 'style' | 'filter' | 'labels' | 'popup') => void;
  onPaintChange: (layerId: string, paint: Record<string, unknown>) => void;
  onOpacityChange: (layerId: string, opacity: number) => void;
  onFilterChange: (layerId: string, expression: FilterSpecification | null) => void;
  onLabelChange: (layerId: string, config: LabelConfig | null) => void;
  onPopupChange: (layerId: string, config: PopupConfig | null) => void;
  onStyleConfigChange: (layerId: string, config: StyleConfig | null, paint: Record<string, unknown>) => void;
  onLayoutChange: (layerId: string, layout: Record<string, unknown>) => void;
  onRenderModeChange?: (layerId: string, mode: 'points' | 'heatmap' | 'symbol' | 'cluster') => void;
  onRemove: (layerId: string) => void;
}

interface LayerEditorPanelProps {
  layer: MapLayerResponse;
  activeTab?: 'style' | 'filter' | 'labels' | 'popup' | null;
  handlers: LayerEditorHandlers;
  /** New: closes the flyout and deselects the row */
  onClose: () => void;
  /** When true, shows a leading ‹ back arrow (used at <800px drill-down mode) */
  isDrillDown?: boolean;
  /**
   * When false (Plan 03 default), renders the new section-based body.
   * When true, renders the legacy tab-based body for backward compat.
   */
  enableLegacyTabs?: boolean;
  /**
   * Editor scene variant. Controls which content renders in the body slot.
   * - 'default' (or undefined): existing section-based body
   * - 'dem': caller supplies sceneContent rendering DEMEditorScene (Plan 04)
   * - 'basemap-group': caller supplies sceneContent rendering BasemapGroupEditorScene (Plan 02)
   * - 'basemap-sublayer': caller supplies sceneContent rendering BasemapSublayerEditorScene (Plan 02); header shows breadcrumb
   */
  editorScene?: 'default' | 'dem' | 'basemap-group' | 'basemap-sublayer' | 'settings';
  /** Caller-supplied body content for non-default scenes (Plans 02/03/04 pass their scene component). */
  sceneContent?: React.ReactNode;
  /** Caller-supplied footer content for non-default scenes. */
  sceneFooter?: React.ReactNode;
  /** Display name shown in the breadcrumb when editorScene === 'basemap-sublayer'. Falls back to "Untitled". */
  breadcrumbPresetName?: string;
  /** Click handler for the breadcrumb element when editorScene === 'basemap-sublayer'. */
  onBreadcrumbClick?: () => void;
}

// ---------------------------------------------------------------------------
// LayerEditorTypePill — small inline chip showing layer type in the header
// ---------------------------------------------------------------------------
function LayerEditorTypePill({ layer }: { layer: MapLayerResponse }) {
  const caps = getLayerCapabilities(layer);
  const geometryType = layer.dataset_geometry_type;
  const renderMode = (layer.style_config as Record<string, unknown> | null)?.render_mode as string | undefined;

  let label: string;
  if (caps.kind === 'raster' || caps.kind === 'vrt') {
    if (layer.is_dem) {
      label = renderMode ? `DEM · ${renderMode}` : 'DEM';
    } else {
      label = caps.kind === 'vrt' ? 'VRT' : 'Raster';
    }
  } else {
    label = geometryType ?? 'Vector';
  }

  return (
    <span className={cn(
      'inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.08em]',
      caps.kind === 'vector' && 'bg-[var(--type-vector-bg)] text-[var(--type-vector)]',
      (caps.kind === 'raster' || caps.kind === 'vrt') && 'bg-[var(--type-raster-bg)] text-[var(--type-raster)]',
      caps.kind === 'basemap' && 'bg-[var(--primary-50)] text-[var(--primary-700)]',
      !['vector', 'raster', 'vrt', 'basemap'].includes(caps.kind) && 'bg-[var(--surface-2)] text-muted-foreground',
    )}>
      {label}
    </span>
  );
}

function clampZoom(v: number): number {
  return Math.max(0, Math.min(22, Math.round(v)));
}

function layerLayout(layer: MapLayerResponse): Record<string, unknown> {
  return { ...(layer.layout ?? {}) };
}

function zoomValue(value: unknown, fallback: number): number {
  if (typeof value === 'number' && !Number.isNaN(value)) return clampZoom(value);
  return fallback;
}

export const LayerEditorPanel = memo(function LayerEditorPanel({
  layer,
  activeTab,
  handlers,
  onClose,
  isDrillDown = false,
  enableLegacyTabs = false,
  editorScene = 'default',
  sceneContent,
  sceneFooter,
  breadcrumbPresetName,
  onBreadcrumbClick,
}: LayerEditorPanelProps) {
  const { t } = useTranslation('builder');
  const columns = layer.dataset_column_info ?? [];
  const caps = useMemo(() => getLayerCapabilities(layer), [layer]);
  const isRaster = caps.kind !== 'vector';
  const isHeatmap = layer.style_config?.render_mode === 'heatmap';
  const layerColors = useMemo(() => getLayerColors(layer), [layer]);
  const styleHints = useMemo(
    () => extractStyleHints(
      layer.paint ?? {},
      layer.layout ?? {},
      layer.dataset_geometry_type,
      layer.opacity,
      layer.style_config,
    ),
    [layer.paint, layer.layout, layer.dataset_geometry_type, layer.opacity, layer.style_config],
  );

  const renderAsOptions = useMemo(() => getRenderAsOptions(layer), [layer]);
  const currentRenderAs = useMemo(() => getCurrentRenderAs(layer), [layer]);

  const layerName = layer.display_name ?? layer.dataset_name;
  const resolvedActiveTab = activeTab ?? 'style';
  const isPureSettings = editorScene === 'settings';

  // Section open/close state — Filter, Labels, Source are collapsed by default
  const [filterOpen, setFilterOpen] = useState(false);
  const [labelsOpen, setLabelsOpen] = useState(false);
  const [sourceOpen, setSourceOpen] = useState(false);

  // Footer delete confirm state
  const [confirmingDelete, setConfirmingDelete] = useState(false);

  // Reset all local state when the layer changes. This is defensive: the
  // production caller passes key={editingLayer.id} which remounts the panel,
  // but any future caller that omits the key would otherwise carry over stale
  // confirmingDelete=true from a prior layer — causing the destructive dialog
  // to appear immediately for the newly-selected layer.
  useEffect(() => {
    setConfirmingDelete(false);
    setFilterOpen(false);
    setLabelsOpen(false);
    setSourceOpen(false);
  }, [layer.id, editorScene]);

  // POL-18: Scroll + focus preservation across scene transitions
  const bodyRef = useRef<HTMLDivElement>(null);
  const savedScrollTopRef = useRef<number>(0);
  const prevSceneRef = useRef(editorScene);
  const headerRef = useRef<HTMLElement>(null);

  // Save scrollTop before navigating away (when editorScene changes)
  useEffect(() => {
    const bodyEl = bodyRef.current;
    return () => {
      if (bodyEl) {
        savedScrollTopRef.current = bodyEl.scrollTop;
      }
    };
  }, [editorScene]);

  // Restore scrollTop on remount / scene return
  useEffect(() => {
    if (bodyRef.current && savedScrollTopRef.current > 0) {
      bodyRef.current.scrollTop = savedScrollTopRef.current;
    }
  }, [layer.id, editorScene]);

  // Restore keyboard focus to panel header when transitioning back from basemap-sublayer to basemap-group
  useEffect(() => {
    if (editorScene === 'basemap-group' && prevSceneRef.current === 'basemap-sublayer') {
      headerRef.current?.focus();
    }
    prevSceneRef.current = editorScene;
  }, [editorScene]);

  // Zoom range from layout
  const layout = layerLayout(layer);
  const minZoom = zoomValue(layout._minzoom, 0);
  const maxZoom = zoomValue(layout._maxzoom, 22);

  function handleZoomChange(nextMin: number, nextMax: number) {
    const min = clampZoom(Math.min(nextMin, nextMax - 1));
    const max = clampZoom(Math.max(nextMax, nextMin + 1));
    handlers.onLayoutChange(layer.id, {
      ...layout,
      _minzoom: min,
      _maxzoom: max,
    });
  }

  // Filter hint: count of conditions or "No filter"
  const filterHint = layer.filter == null
    ? t('layerEditor.filter.noFilter', { defaultValue: 'No filter' })
    : t('layerEditor.filter.active', { defaultValue: 'Active' });

  // Labels hint
  const labelsHint = layer.label_config == null
    ? t('layerEditor.labels.off', { defaultValue: 'Off' })
    : String(layer.label_config.column || 'On');

  // Source hint: layer kind
  const sourceHint = caps.kind;

  return (
    <div
      className="flex flex-col h-full overflow-hidden"
      role={isPureSettings ? 'region' : undefined}
      aria-label={isPureSettings ? t('settings.regionLabel', { defaultValue: 'Map settings' }) : undefined}
    >
      {/* Header: back (drill-down only) | [breadcrumb for sublayer] | type icon | layer name | close × */}
      <header
        ref={headerRef}
        data-testid="layer-editor-header"
        className="flex flex-col px-4 py-3 border-b shrink-0"
        tabIndex={-1}
      >
        {/* Breadcrumb: only shown when editorScene === 'basemap-sublayer' */}
        {editorScene === 'basemap-sublayer' && (
          <div className="w-full mb-0.5">
            <button
              type="button"
              aria-label={t('basemapSublayer.breadcrumbLabel', { defaultValue: 'Back to basemap group' })}
              onClick={onBreadcrumbClick}
              style={{ fontSize: '11px', lineHeight: 1.2, letterSpacing: '0.04em' }}
              className="text-muted-foreground hover:text-foreground hover:underline block"
            >
              Basemap · {breadcrumbPresetName ?? 'Untitled'} ›
            </button>
          </div>
        )}
        {/* Title row: back (drill-down only) | type icon | layer name | close × */}
        <div className="flex items-center gap-2">
        {/* Back arrow: only shown in <800px drill-down mode */}
        {isDrillDown && (
          <button
            type="button"
            onClick={onClose}
            aria-label={t('layerItem.backToLayers', { defaultValue: 'Back to layers' })}
            title={t('layerItem.backToLayers', { defaultValue: 'Back to layers' })}
            className="flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <ChevronLeft className="h-4 w-4 rtl-mirror" />
          </button>
        )}

        {/* Type icon — suppressed for settings scene */}
        {!isPureSettings && (
          <ColorizedGeometryIcon
            geometryType={layer.dataset_geometry_type}
            colors={layerColors}
            layerId={layer.id}
            layerType={caps.kind}
            styleHints={styleHints}
          />
        )}

        {/* Layer name / Settings title + type pill + subtitle */}
        <div className="flex flex-col min-w-0 flex-1">
          <div className="flex items-center gap-2 min-w-0">
            <span
              id="layer-editor-title"
              className="text-sm font-semibold truncate min-w-0"
            >
              {isPureSettings ? t('settings.panelTitle', { defaultValue: 'Settings' }) : layerName}
            </span>
            {!isPureSettings && editorScene !== 'basemap-group' && editorScene !== 'basemap-sublayer' && (
              <LayerEditorTypePill layer={layer} />
            )}
          </div>
          {!isPureSettings && editorScene !== 'basemap-group' && editorScene !== 'basemap-sublayer' && (layer.dataset_geometry_type || caps.kind === 'raster' || caps.kind === 'vrt') && (
            <span className="text-[11px] text-muted-foreground truncate">
              {layer.dataset_geometry_type ?? (caps.kind === 'raster' || caps.kind === 'vrt' ? '1 band' : '')}
            </span>
          )}
        </div>

        {/* Close × button */}
        <button
          type="button"
          onClick={onClose}
          aria-label={isPureSettings
            ? t('settings.closePanel', { defaultValue: 'Close settings' })
            : t('layerEditor.close', { defaultValue: 'Close layer editor' })}
          className="flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <X className="h-4 w-4" aria-hidden="true" />
        </button>
        </div>
      </header>

      {/* Scrollable body */}
      <div
        ref={bodyRef}
        data-testid="layer-editor-body"
        className="flex-1 overflow-y-auto"
      >
        {!enableLegacyTabs && (editorScene === 'default' || editorScene === undefined) && (
          <>
            {/* 1. Render as — always expanded */}
            <section
              aria-labelledby={`section-renderas-${layer.id}`}
              className="border-b"
            >
              <div className="px-4 py-2">
                <p
                  id={`section-renderas-${layer.id}`}
                  className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground mb-2"
                >
                  {t('layerEditor.section.renderAs', { defaultValue: 'Render as' })}
                </p>
                {renderAsOptions.length > 0 ? (
                  <div className="flex flex-wrap gap-2">
                    {renderAsOptions.map((option) => {
                      const isActive = option.id === currentRenderAs;
                      return (
                        <button
                          key={option.id}
                          type="button"
                          data-active={isActive ? 'true' : 'false'}
                          onClick={() => {
                            if (!isActive) {
                              handlers.onRenderModeChange?.(layer.id, option.id as 'points' | 'heatmap' | 'symbol' | 'cluster');
                            }
                          }}
                          className={cn(
                            'rounded-full border border-transparent px-[10px] py-[5px] text-[12px] transition-colors',
                            isActive
                              ? 'bg-primary text-primary-foreground border-transparent'
                              : 'bg-[var(--surface-2,theme(colors.muted.DEFAULT))] text-foreground hover:bg-[var(--surface-3,theme(colors.muted.DEFAULT))]',
                          )}
                        >
                          {option.label}
                        </button>
                      );
                    })}
                  </div>
                ) : (
                  <p className="text-xs text-muted-foreground">—</p>
                )}
              </div>
            </section>

            {/* 2. Appearance — always expanded */}
            <section
              aria-labelledby={`section-appearance-${layer.id}`}
              className="border-b"
            >
              <div className="px-4 py-2">
                <p
                  id={`section-appearance-${layer.id}`}
                  className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground mb-2"
                >
                  {t('layerEditor.section.appearance', { defaultValue: 'Appearance' })}
                </p>
                {/* onOpacityChange intentionally omitted: opacity is owned by Visibility §3 */}
                {isRaster ? (
                  <RasterLayerControls
                    paint={layer.paint ?? {}}
                    onPaintChange={(nextPaint) => handlers.onPaintChange(layer.id, nextPaint)}
                    opacity={layer.opacity ?? 1}
                    isDem={layer.is_dem}
                    styleConfig={layer.style_config}
                    onStyleConfigChange={(nextConfig, nextPaint) =>
                      handlers.onStyleConfigChange(layer.id, nextConfig, nextPaint)
                    }
                  />
                ) : (
                  <LayerStyleEditor
                    key={layer.id}
                    layer={layer}
                    onPaintChange={handlers.onPaintChange}
                    onStyleConfigChange={handlers.onStyleConfigChange}
                    onLayoutChange={handlers.onLayoutChange}
                    onRenderModeChange={handlers.onRenderModeChange}
                  />
                )}
              </div>
            </section>

            {/* 3. Visibility — always expanded: opacity slider + zoom range */}
            <section
              aria-labelledby={`section-visibility-${layer.id}`}
              className="border-b"
            >
              <div className="px-4 py-2">
                <p
                  id={`section-visibility-${layer.id}`}
                  className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground mb-2"
                >
                  {t('layerEditor.section.visibility', { defaultValue: 'Visibility' })}
                </p>
                <div className="space-y-3">
                  {/* Opacity slider */}
                  <div className="space-y-1">
                    <Label className="text-xs text-muted-foreground">
                      {t('layerEditor.visibility.opacity', { defaultValue: 'Opacity' })}
                    </Label>
                    <Slider
                      aria-label={t('layerEditor.visibility.opacity', { defaultValue: 'Opacity' })}
                      aria-valuetext={`${Math.round((layer.opacity ?? 1) * 100)}%`}
                      value={[layer.opacity ?? 1]}
                      min={0}
                      max={1}
                      step={0.05}
                      className="w-full"
                      onValueChange={([value]) => {
                        handlers.onOpacityChange(layer.id, Number((value ?? layer.opacity ?? 1).toFixed(2)));
                      }}
                    />
                  </div>
                  {/* Zoom range */}
                  <div className="grid grid-cols-2 gap-2">
                    <div className="space-y-1">
                      <Label
                        htmlFor={`${layer.id}-section-minzoom`}
                        className="text-xs text-muted-foreground"
                      >
                        {t('layerEditor.visibility.minZoom', { defaultValue: 'Minimum zoom' })}
                      </Label>
                      <Input
                        id={`${layer.id}-section-minzoom`}
                        type="number"
                        min={0}
                        max={Math.max(0, maxZoom - 1)}
                        value={minZoom}
                        onChange={(e) => handleZoomChange(Number(e.target.value), maxZoom)}
                        className="h-8 text-xs"
                        aria-label={t('layerEditor.visibility.minZoom', { defaultValue: 'Minimum zoom' })}
                      />
                    </div>
                    <div className="space-y-1">
                      <Label
                        htmlFor={`${layer.id}-section-maxzoom`}
                        className="text-xs text-muted-foreground"
                      >
                        {t('layerEditor.visibility.maxZoom', { defaultValue: 'Maximum zoom' })}
                      </Label>
                      <Input
                        id={`${layer.id}-section-maxzoom`}
                        type="number"
                        min={Math.min(22, minZoom + 1)}
                        max={22}
                        value={maxZoom}
                        onChange={(e) => handleZoomChange(minZoom, Number(e.target.value))}
                        className="h-8 text-xs"
                        aria-label={t('layerEditor.visibility.maxZoom', { defaultValue: 'Maximum zoom' })}
                      />
                    </div>
                  </div>
                </div>
              </div>
            </section>

            {/* 4. Filter — collapsed by default, only for filterable layers */}
            {caps.supportsFilterEditor && (
              <Collapsible open={filterOpen} onOpenChange={setFilterOpen}>
                <CollapsibleTrigger asChild>
                  <button
                    type="button"
                    className="flex w-full items-center gap-2 px-4 py-2 hover:bg-[var(--surface-2,theme(colors.muted.DEFAULT))] border-b"
                  >
                    <ChevronRight
                      className={cn('h-4 w-4 shrink-0 transition-transform duration-[--motion-fast]', filterOpen && 'rotate-90')}
                      aria-hidden="true"
                    />
                    <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
                      {t('layerEditor.section.filter', { defaultValue: 'Filter' })}
                    </span>
                    {!filterOpen && (
                      <span className="ml-auto text-xs text-muted-foreground">
                        {filterHint}
                      </span>
                    )}
                  </button>
                </CollapsibleTrigger>
                <CollapsibleContent>
                  <div className="px-4 py-2 border-b">
                    <LayerFilterEditor
                      columnInfo={columns}
                      filter={layer.filter ?? null}
                      layerName={layerName}
                      onFilterChange={(expr) => handlers.onFilterChange(layer.id, expr)}
                    />
                  </div>
                </CollapsibleContent>
              </Collapsible>
            )}

            {/* 5. Labels — collapsed by default, only for labelable layers (not heatmap) */}
            {caps.supportsLabelEditor && !isHeatmap && (
              <Collapsible open={labelsOpen} onOpenChange={setLabelsOpen}>
                <CollapsibleTrigger asChild>
                  <button
                    type="button"
                    className="flex w-full items-center gap-2 px-4 py-2 hover:bg-[var(--surface-2,theme(colors.muted.DEFAULT))] border-b"
                  >
                    <ChevronRight
                      className={cn('h-4 w-4 shrink-0 transition-transform duration-[--motion-fast]', labelsOpen && 'rotate-90')}
                      aria-hidden="true"
                    />
                    <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
                      {t('layerEditor.section.labels', { defaultValue: 'Labels' })}
                    </span>
                    {!labelsOpen && (
                      <span className="ml-auto text-xs text-muted-foreground">
                        {labelsHint}
                      </span>
                    )}
                  </button>
                </CollapsibleTrigger>
                <CollapsibleContent>
                  <div className="px-4 py-2 border-b">
                    <LabelEditor
                      columns={columns}
                      labelConfig={layer.label_config ?? null}
                      onLabelChange={(config) => handlers.onLabelChange(layer.id, config)}
                      geometryType={layer.dataset_geometry_type}
                    />
                  </div>
                </CollapsibleContent>
              </Collapsible>
            )}

            {/* 6. Source — collapsed by default, always rendered */}
            <Collapsible open={sourceOpen} onOpenChange={setSourceOpen}>
              <CollapsibleTrigger asChild>
                <button
                  type="button"
                  className="flex w-full items-center gap-2 px-4 py-2 hover:bg-[var(--surface-2,theme(colors.muted.DEFAULT))] border-b"
                >
                  <ChevronRight
                    className={cn('h-4 w-4 shrink-0 transition-transform duration-[--motion-fast]', sourceOpen && 'rotate-90')}
                    aria-hidden="true"
                  />
                  <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
                    {t('layerEditor.section.source', { defaultValue: 'Source' })}
                  </span>
                  {!sourceOpen && (
                    <span className="ml-auto text-xs text-muted-foreground">
                      {sourceHint}
                    </span>
                  )}
                </button>
              </CollapsibleTrigger>
              <CollapsibleContent>
                <div className="px-4 py-2 space-y-2 border-b">
                  {layer.dataset_name && (
                    <div>
                      <span className="text-[10px] text-muted-foreground uppercase tracking-[0.08em]">Dataset</span>
                      <p className="text-xs truncate">{layer.dataset_name}</p>
                    </div>
                  )}
                  {layer.dataset_feature_count != null && (
                    <div>
                      <span className="text-[10px] text-muted-foreground uppercase tracking-[0.08em]">Features</span>
                      <p className="text-xs">{layer.dataset_feature_count.toLocaleString()}</p>
                    </div>
                  )}
                  {layer.dataset_record_type && (
                    <div>
                      <span className="text-[10px] text-muted-foreground uppercase tracking-[0.08em]">Type</span>
                      <p className="text-xs">{layer.dataset_record_type}</p>
                    </div>
                  )}
                  {layer.dataset_geometry_type && (
                    <div>
                      <span className="text-[10px] text-muted-foreground uppercase tracking-[0.08em]">Geometry</span>
                      <p className="text-xs">{layer.dataset_geometry_type}</p>
                    </div>
                  )}
                  {columns.length === 0 && (
                    <p className="text-xs text-muted-foreground">
                      {t('layerEditor.source.noColumns', { defaultValue: 'No queryable columns indexed for this layer.' })}
                    </p>
                  )}
                  {columns.length > 0 && (
                    <ColumnsReference columns={columns} />
                  )}
                  {(caps.supportsFilterEditor || caps.supportsLabelEditor) && (
                    <PopupConfigEditor
                      columns={columns}
                      popupConfig={layer.popup_config ?? null}
                      onPopupChange={(config) => handlers.onPopupChange(layer.id, config)}
                    />
                  )}
                </div>
              </CollapsibleContent>
            </Collapsible>
          </>
        )}

        {/* Non-default scene body — Plans 02/03/04 pass their scene component via sceneContent */}
        {!enableLegacyTabs && editorScene && editorScene !== 'default' && sceneContent}

        {/* Legacy tab-based body — preserved for backward compat */}
        {enableLegacyTabs && (
          <>
            {/* Raster: simple opacity control */}
            {isRaster && (
              <div className="p-3">
                <RasterLayerControls
                  paint={layer.paint ?? {}}
                  onPaintChange={(nextPaint) => handlers.onPaintChange(layer.id, nextPaint)}
                  opacity={layer.opacity ?? 1}
                  onOpacityChange={(v) => handlers.onOpacityChange(layer.id, v)}
                  isDem={layer.is_dem}
                  styleConfig={layer.style_config}
                  onStyleConfigChange={(nextConfig, nextPaint) => handlers.onStyleConfigChange(layer.id, nextConfig, nextPaint)}
                />
              </div>
            )}

            {/* Vector: tabbed editor */}
            {!isRaster && (
              <>
                <div className="flex gap-1 overflow-x-auto px-3.5 border-b shrink-0" role="tablist">
                  {(['style', 'filter', 'labels', 'popup'] as const)
                    .filter((tab) => {
                      if (tab === 'filter') return caps.supportsFilterEditor;
                      if (tab === 'labels') return caps.supportsLabelEditor && !isHeatmap;
                      if (tab === 'popup') return caps.supportsFilterEditor || caps.supportsLabelEditor;
                      return true;
                    })
                    .map((tab) => (
                    <button
                      key={tab}
                      id={`tab-${layer.id}-${tab}`}
                      role="tab"
                      aria-selected={resolvedActiveTab === tab}
                      aria-controls={`tabpanel-${layer.id}-${tab}`}
                      className={cn(
                        'h-9 shrink-0 cursor-pointer rounded-t-sm px-2.5 text-xs font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1',
                        resolvedActiveTab === tab
                          ? 'text-foreground border-b-2 border-primary'
                          : 'text-muted-foreground hover:text-foreground'
                      )}
                      onClick={() => handlers.onTabChange(layer.id, tab)}
                    >
                      {t(`layerItem.${tab}Tab`)}
                    </button>
                  ))}
                </div>

                <div className="flex-1 p-3">
                  {resolvedActiveTab === 'style' && (
                    <div role="tabpanel" id={`tabpanel-${layer.id}-style`} aria-labelledby={`tab-${layer.id}-style`}>
                      <LayerStyleEditor
                        key={layer.id}
                        layer={layer}
                        onPaintChange={handlers.onPaintChange}
                        onOpacityChange={handlers.onOpacityChange}
                        onStyleConfigChange={handlers.onStyleConfigChange}
                        onLayoutChange={handlers.onLayoutChange}
                        onRenderModeChange={handlers.onRenderModeChange}
                      />
                      {columns.length > 0 && (
                        <ColumnsReference columns={columns} />
                      )}
                    </div>
                  )}
                  {resolvedActiveTab === 'filter' && (
                    <div role="tabpanel" id={`tabpanel-${layer.id}-filter`} aria-labelledby={`tab-${layer.id}-filter`}>
                      <LayerFilterEditor
                        columnInfo={columns}
                        filter={layer.filter ?? null}
                        layerName={layerName}
                        onFilterChange={(expr) => handlers.onFilterChange(layer.id, expr)}
                      />
                    </div>
                  )}
                  {resolvedActiveTab === 'labels' && (
                    <div role="tabpanel" id={`tabpanel-${layer.id}-labels`} aria-labelledby={`tab-${layer.id}-labels`}>
                      <LabelEditor
                        columns={columns}
                        labelConfig={layer.label_config ?? null}
                        onLabelChange={(config) => handlers.onLabelChange(layer.id, config)}
                        geometryType={layer.dataset_geometry_type}
                      />
                    </div>
                  )}
                  {resolvedActiveTab === 'popup' && (
                    <div role="tabpanel" id={`tabpanel-${layer.id}-popup`} aria-labelledby={`tab-${layer.id}-popup`}>
                      <PopupConfigEditor
                        key={layer.id}
                        columns={columns}
                        popupConfig={layer.popup_config ?? null}
                        onPopupChange={(config) => handlers.onPopupChange(layer.id, config)}
                      />
                    </div>
                  )}
                </div>
              </>
            )}
          </>
        )}
      </div>

      {/* Footer — Delete button + inline confirm (default scene) or sceneFooter (non-default) */}
      {((!enableLegacyTabs && (editorScene === 'default' || editorScene === undefined)) ||
        enableLegacyTabs ||
        (!enableLegacyTabs && editorScene && editorScene !== 'default' && !!sceneFooter)) && (
      <footer data-testid="layer-editor-footer" className="shrink-0 border-t p-3">
        {(!enableLegacyTabs && (editorScene === 'default' || editorScene === undefined)) && (
          <>
            {!confirmingDelete ? (
              <Button
                type="button"
                variant="ghost"
                className="w-full text-destructive hover:bg-[oklch(0.97_0.02_27)] hover:text-destructive"
                onClick={() => setConfirmingDelete(true)}
              >
                {t('layerEditor.footer.deleteLayer', { defaultValue: 'Delete layer' })}
              </Button>
            ) : (
              <div role="alertdialog" aria-labelledby={`confirm-delete-${layer.id}`} className="space-y-2">
                <p id={`confirm-delete-${layer.id}`} className="text-sm text-destructive text-center">
                  {t('layerEditor.confirmDelete.message', { defaultValue: 'Are you sure? This cannot be undone.' })}
                </p>
                <div className="flex gap-2">
                  <Button
                    type="button"
                    variant="destructive"
                    className="flex-1"
                    onClick={() => handlers.onRemove(layer.id)}
                  >
                    {t('layerEditor.confirmDelete.delete', { defaultValue: 'Delete' })}
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    className="flex-1"
                    onClick={() => setConfirmingDelete(false)}
                    // eslint-disable-next-line jsx-a11y/no-autofocus -- moves focus to safe action so Enter dismisses, not destroys (AUD-09)
                    autoFocus
                  >
                    {t('layerEditor.confirmDelete.keep', { defaultValue: 'Keep layer' })}
                  </Button>
                </div>
              </div>
            )}
          </>
        )}
        {enableLegacyTabs && (
          <>
            {!confirmingDelete ? (
              <Button
                type="button"
                variant="ghost"
                className="w-full text-destructive hover:bg-[oklch(0.97_0.02_27)] hover:text-destructive"
                onClick={() => setConfirmingDelete(true)}
              >
                {t('layerEditor.footer.deleteLayer', { defaultValue: 'Delete layer' })}
              </Button>
            ) : (
              <div role="alertdialog" aria-labelledby={`confirm-delete-${layer.id}`} className="space-y-2">
                <p id={`confirm-delete-${layer.id}`} className="text-sm text-destructive text-center">
                  {t('layerEditor.confirmDelete.message', { defaultValue: 'Are you sure? This cannot be undone.' })}
                </p>
                <div className="flex gap-2">
                  <Button
                    type="button"
                    variant="destructive"
                    className="flex-1"
                    onClick={() => handlers.onRemove(layer.id)}
                  >
                    {t('layerEditor.confirmDelete.delete', { defaultValue: 'Delete' })}
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    className="flex-1"
                    onClick={() => setConfirmingDelete(false)}
                    // eslint-disable-next-line jsx-a11y/no-autofocus -- moves focus to safe action so Enter dismisses, not destroys (AUD-09)
                    autoFocus
                  >
                    {t('layerEditor.confirmDelete.keep', { defaultValue: 'Keep layer' })}
                  </Button>
                </div>
              </div>
            )}
          </>
        )}
        {!enableLegacyTabs && editorScene && editorScene !== 'default' && sceneFooter}
      </footer>
      )}
    </div>
  );
});
