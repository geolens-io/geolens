import { memo, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronLeft, X } from 'lucide-react';
import { LayerStyleEditor } from './LayerStyleEditor';
import { LayerFilterEditor } from './LayerFilterEditor';
import { LabelEditor } from './LabelEditor';
import { PopupConfigEditor } from './PopupConfigEditor';
import { RasterLayerControls } from './RasterLayerControls';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { getLayerCapabilities } from '@/lib/layer-capabilities';
import { getRenderAsOptions, getCurrentRenderAs, type RenderAsId } from './renderAs';
import { ColorizedGeometryIcon, getLayerColors, extractStyleHints } from '@/components/map/layer-icons';
import type { FilterSpecification } from 'maplibre-gl';
import type { MapLayerResponse, LabelConfig, PopupConfig, StyleConfig } from '@/types/api';

export type LayerEditorTab = 'style' | 'filter' | 'labels' | 'popup';

export interface LayerEditorHandlers {
  onTabChange: (layerId: string, tab: LayerEditorTab) => void;
  onPaintChange: (layerId: string, paint: Record<string, unknown>) => void;
  onOpacityChange: (layerId: string, opacity: number) => void;
  onFilterChange: (layerId: string, expression: FilterSpecification | null) => void;
  onLabelChange: (layerId: string, config: LabelConfig | null) => void;
  onPopupChange: (layerId: string, config: PopupConfig | null) => void;
  onStyleConfigChange: (layerId: string, config: StyleConfig | null, paint: Record<string, unknown>) => void;
  onLayoutChange: (layerId: string, layout: Record<string, unknown>) => void;
  // SF-02 (Phase 1049): widened to all RenderAsId values. use-builder-layers'
  // handleRenderModeChange now dispatches non-circle modes through
  // handleRenderAsChange to avoid stale layout/paint keys leaking across adapter
  // boundaries (e.g. line→arrow leaving behind line-cap / line-join).
  onRenderModeChange?: (layerId: string, mode: RenderAsId) => void;
  onRemove: (layerId: string) => void;
}

interface LayerEditorPanelProps {
  layer: MapLayerResponse;
  /**
   * SP-05 (Phase 1045): server-state baseline for `layer`. When set, the
   * embedded LayerStyleEditor gates its "Pending style preview" banner on a
   * deep-equal diff against this baseline.
   */
  savedLayer?: MapLayerResponse;
  activeTab?: LayerEditorTab | null;
  handlers: LayerEditorHandlers;
  /** New: closes the flyout and deselects the row */
  onClose: () => void;
  /** When true, shows a leading ‹ back arrow (used at <800px drill-down mode) */
  isDrillDown?: boolean;
  /**
   * Editor scene variant. Controls which content renders in the body slot.
   * - 'default' (or undefined): tab-based body (Style/Filter/[Labels]/Popup)
   * - 'dem' / 'basemap-group' / 'basemap-sublayer' / 'settings': caller supplies sceneContent
   */
  editorScene?: 'default' | 'dem' | 'basemap-group' | 'basemap-sublayer' | 'settings';
  /** Caller-supplied body content for non-default scenes. */
  sceneContent?: React.ReactNode;
  /** Caller-supplied footer content for non-default scenes. */
  sceneFooter?: React.ReactNode;
  /** Display name shown in the breadcrumb when editorScene === 'basemap-sublayer'. */
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
    )}>
      {label}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Pip — tab status indicator (count badge or on/off dot)
// ---------------------------------------------------------------------------
function Pip({ count, on }: { count?: number | null; on?: boolean }) {
  if (typeof count === 'number') {
    return (
      <span
        aria-hidden="true"
        className="inline-flex h-[14px] min-w-[14px] items-center justify-center rounded-full bg-primary px-1 text-[9px] font-semibold leading-none text-primary-foreground"
      >
        {count}
      </span>
    );
  }
  if (!on) return null;
  return (
    <span
      aria-hidden="true"
      className="inline-block h-1.5 w-1.5 rounded-full bg-primary"
    />
  );
}

// ---------------------------------------------------------------------------
// Filter condition counter — best-effort: handles {match,conditions[]} shape
// and raw maplibre expression arrays. Falls back to "1" for any non-null/empty
// filter so the pip never lies in the false-negative direction.
// ---------------------------------------------------------------------------
function countFilterConditions(filter: FilterSpecification | null | undefined): number {
  if (filter == null) return 0;
  if (typeof filter === 'object' && !Array.isArray(filter)) {
    const conditions = (filter as { conditions?: unknown[] }).conditions;
    if (Array.isArray(conditions)) return conditions.length;
    return 1;
  }
  if (Array.isArray(filter)) {
    const head = filter[0];
    // ["all", ...subExpressions] or ["any", ...]
    if (head === 'all' || head === 'any') return Math.max(0, filter.length - 1);
    // Single comparison like ["==", "col", value]
    return 1;
  }
  return 1;
}

export const LayerEditorPanel = memo(function LayerEditorPanel({
  layer,
  savedLayer,
  activeTab,
  handlers,
  onClose,
  isDrillDown = false,
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
  const isPureSettings = editorScene === 'settings';
  const isDefaultScene = editorScene === 'default' || editorScene === undefined;

  // Which tabs are available for this layer? Style is always present.
  // Filter / Labels / Popup depend on layer capabilities. Source is gone — it
  // lives in the row (···) menu in StackRow.
  const availableTabs = useMemo<LayerEditorTab[]>(() => {
    const tabs: LayerEditorTab[] = ['style'];
    if (caps.supportsFilterEditor) tabs.push('filter');
    // Labels tab is only meaningful when the layer is rendered as a Labels-mode
    // (symbol render_mode). Per the v3 design, Labels is no longer a peer
    // section — it's a render-as choice that surfaces its own tab.
    const showLabelsTab = caps.supportsLabelEditor && !isHeatmap && currentRenderAs === 'symbol';
    if (showLabelsTab) tabs.push('labels');
    if (caps.supportsFilterEditor || caps.supportsLabelEditor) tabs.push('popup');
    return tabs;
  }, [caps.supportsFilterEditor, caps.supportsLabelEditor, isHeatmap, currentRenderAs]);

  // Resolve the active tab against availability — fall back to 'style' if the
  // requested tab vanished (e.g. layer changed render mode and Labels tab went away).
  const resolvedActiveTab: LayerEditorTab = useMemo(() => {
    if (activeTab && availableTabs.includes(activeTab)) return activeTab;
    return 'style';
  }, [activeTab, availableTabs]);

  // Destructive render-as switch — when the user clicks a different render-as
  // pill, hold the intended target until they confirm. null = no pending switch.
  const [pendingRenderAs, setPendingRenderAs] = useState<RenderAsId | null>(null);

  // Reset local state when the layer changes (defensive — keyed remount upstream
  // is the primary mechanism, but a future caller that omits the key would
  // otherwise carry over stale pendingRenderAs).
  useEffect(() => {
    setPendingRenderAs(null);
  }, [layer.id, editorScene]);

  // POL-18: Scroll + focus preservation across scene transitions
  const bodyRef = useRef<HTMLDivElement>(null);
  const savedScrollTopRef = useRef<number | null>(null);
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
    if (bodyRef.current && savedScrollTopRef.current !== null) {
      bodyRef.current.scrollTop = savedScrollTopRef.current;
      savedScrollTopRef.current = null;
    }
  }, [layer.id, editorScene]);

  // Restore keyboard focus to panel header when transitioning back from basemap-sublayer to basemap-group
  useEffect(() => {
    if (editorScene === 'basemap-group' && prevSceneRef.current === 'basemap-sublayer') {
      headerRef.current?.focus();
    }
    prevSceneRef.current = editorScene;
  }, [editorScene]);

  // Pip data per tab — see commentary above availableTabs.
  const filterCount = countFilterConditions(layer.filter);
  const popupOn = layer.popup_config?.enabled === true;
  const labelsOn = layer.label_config != null;

  function handleRenderAsClick(target: RenderAsId) {
    if (target === currentRenderAs) return;
    // Destructive switch — confirm before applying. Always confirm: switching
    // render-as resets the paint properties owned by the prior mode (line color
    // & width when going line→arrow → fill color when going fill→3D, etc.),
    // and we'd rather force a deliberate click than silently nuke styling.
    setPendingRenderAs(target);
  }

  function confirmRenderAsSwitch() {
    if (pendingRenderAs) {
      handlers.onRenderModeChange?.(layer.id, pendingRenderAs);
      setPendingRenderAs(null);
    }
  }

  function cancelRenderAsSwitch() {
    setPendingRenderAs(null);
  }

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
        <div className="flex items-center gap-2">
          {isDrillDown && (
            <button
              type="button"
              onClick={onClose}
              aria-label={t('layerItem.backToLayers', { defaultValue: 'Back to layers' })}
              title={t('layerItem.backToLayers', { defaultValue: 'Back to layers' })}
              className="flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-[var(--surface-2)] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <ChevronLeft className="h-4 w-4 rtl-mirror" />
            </button>
          )}

          {!isPureSettings && (
            <ColorizedGeometryIcon
              geometryType={layer.dataset_geometry_type}
              colors={layerColors}
              layerId={layer.id}
              layerType={caps.kind}
              styleHints={styleHints}
            />
          )}

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

          <button
            type="button"
            onClick={onClose}
            aria-label={isPureSettings
              ? t('settings.closePanel', { defaultValue: 'Close settings' })
              : t('layerEditor.close', { defaultValue: 'Close layer editor' })}
            className="flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-[var(--surface-2)] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
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
        {isDefaultScene && (
          <>
            {/* Tab strip — Style / Filter / [Labels] / Popup */}
            <div
              role="tablist"
              aria-label={t('layerEditor.tabsLabel', { defaultValue: 'Layer editor tabs' })}
              className="flex gap-1 overflow-x-auto px-3 border-b shrink-0 sticky top-0 bg-background z-10"
            >
              {availableTabs.map((tab) => {
                const isActive = resolvedActiveTab === tab;
                let pip: React.ReactNode = null;
                if (tab === 'filter' && filterCount > 0) pip = <Pip count={filterCount} />;
                if (tab === 'labels' && labelsOn) pip = <Pip on />;
                if (tab === 'popup' && popupOn) pip = <Pip on />;
                return (
                  <button
                    key={tab}
                    id={`tab-${layer.id}-${tab}`}
                    role="tab"
                    aria-selected={isActive}
                    aria-controls={`tabpanel-${layer.id}-${tab}`}
                    tabIndex={isActive ? 0 : -1}
                    className={cn(
                      'inline-flex items-center gap-1.5 h-9 shrink-0 cursor-pointer rounded-t-sm px-2.5 text-xs font-semibold uppercase tracking-[0.04em] transition-colors',
                      'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1',
                      isActive
                        ? 'text-foreground border-b-2 border-primary -mb-px'
                        : 'text-muted-foreground hover:text-foreground border-b-2 border-transparent',
                    )}
                    onClick={() => handlers.onTabChange(layer.id, tab)}
                  >
                    <span>{t(`layerItem.${tab}Tab`)}</span>
                    {pip}
                  </button>
                );
              })}
            </div>

            {/* Tab panels */}
            <div className="p-3">
              {resolvedActiveTab === 'style' && (
                <div
                  role="tabpanel"
                  id={`tabpanel-${layer.id}-style`}
                  aria-labelledby={`tab-${layer.id}-style`}
                  className="space-y-3"
                >
                  {/* Render-as pill row — destructive switch with inline confirm */}
                  {renderAsOptions.length > 0 && (
                    <section
                      aria-labelledby={`section-renderas-${layer.id}`}
                      className="rounded-md border bg-muted/25 p-3"
                    >
                      <p
                        id={`section-renderas-${layer.id}`}
                        className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground mb-2"
                      >
                        {t('layerEditor.section.renderAs', { defaultValue: 'Render as' })}
                      </p>
                      <div className="flex flex-wrap gap-2">
                        {renderAsOptions.map((option) => {
                          const isActive = option.id === currentRenderAs;
                          return (
                            <button
                              key={option.id}
                              type="button"
                              data-active={isActive ? 'true' : 'false'}
                              onClick={() => handleRenderAsClick(option.id)}
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
                      {pendingRenderAs && (
                        <div
                          role="alertdialog"
                          aria-labelledby={`confirm-render-as-${layer.id}`}
                          className="mt-3 space-y-2 rounded-md border border-destructive/30 bg-destructive/5 p-2"
                        >
                          <p
                            id={`confirm-render-as-${layer.id}`}
                            className="text-xs text-foreground"
                          >
                            {t('layerEditor.confirmRenderAs.message', {
                              defaultValue: 'Switching render mode will reset the current style. Continue?',
                            })}
                          </p>
                          <div className="flex gap-2">
                            <Button
                              type="button"
                              variant="destructive"
                              size="sm"
                              className="flex-1"
                              onClick={confirmRenderAsSwitch}
                            >
                              {t('layerEditor.confirmRenderAs.confirm', { defaultValue: 'Switch mode' })}
                            </Button>
                            <Button
                              type="button"
                              variant="ghost"
                              size="sm"
                              className="flex-1"
                              onClick={cancelRenderAsSwitch}
                              // eslint-disable-next-line jsx-a11y/no-autofocus -- safe action so Enter dismisses, not destroys
                              autoFocus
                            >
                              {t('layerEditor.confirmRenderAs.cancel', { defaultValue: 'Keep style' })}
                            </Button>
                          </div>
                        </div>
                      )}
                    </section>
                  )}

                  {/* Style body: raster controls or vector style editor.
                      For vectors the editor handles its own opacity + zoom + advanced JSON. */}
                  {isRaster ? (
                    <RasterLayerControls
                      paint={layer.paint ?? {}}
                      onPaintChange={(nextPaint) => handlers.onPaintChange(layer.id, nextPaint)}
                      opacity={layer.opacity ?? 1}
                      onOpacityChange={(v) => handlers.onOpacityChange(layer.id, v)}
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
                      savedLayer={savedLayer}
                      onPaintChange={handlers.onPaintChange}
                      onOpacityChange={handlers.onOpacityChange}
                      onStyleConfigChange={handlers.onStyleConfigChange}
                      onLayoutChange={handlers.onLayoutChange}
                      // PointRenderMode uses legacy 'points' (plural) while
                      // our handler expects RenderAsId ('point'); adapt at the
                      // call site so the dropdown wiring stays clean.
                      onRenderModeChange={(id, mode) =>
                        handlers.onRenderModeChange?.(
                          id,
                          (mode === 'points' ? 'point' : mode) as RenderAsId,
                        )
                      }
                    />
                  )}
                </div>
              )}

              {resolvedActiveTab === 'filter' && caps.supportsFilterEditor && (
                <div
                  role="tabpanel"
                  id={`tabpanel-${layer.id}-filter`}
                  aria-labelledby={`tab-${layer.id}-filter`}
                >
                  <LayerFilterEditor
                    columnInfo={columns}
                    filter={layer.filter ?? null}
                    layerName={layerName}
                    onFilterChange={(expr) => handlers.onFilterChange(layer.id, expr)}
                  />
                </div>
              )}

              {resolvedActiveTab === 'labels' && (
                <div
                  role="tabpanel"
                  id={`tabpanel-${layer.id}-labels`}
                  aria-labelledby={`tab-${layer.id}-labels`}
                >
                  <LabelEditor
                    columns={columns}
                    labelConfig={layer.label_config ?? null}
                    onLabelChange={(config) => handlers.onLabelChange(layer.id, config)}
                    geometryType={layer.dataset_geometry_type}
                  />
                </div>
              )}

              {resolvedActiveTab === 'popup' && (caps.supportsFilterEditor || caps.supportsLabelEditor) && (
                <div
                  role="tabpanel"
                  id={`tabpanel-${layer.id}-popup`}
                  aria-labelledby={`tab-${layer.id}-popup`}
                >
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

        {/* Non-default scene body — Plans 02/03/04 pass their scene component via sceneContent */}
        {!isDefaultScene && sceneContent}
      </div>

      {/* Footer — only rendered for non-default scenes that supply a sceneFooter.
          Per v3 design, Delete moved into the row (···) menu (StackRow). */}
      {!isDefaultScene && !!sceneFooter && (
        <footer data-testid="layer-editor-footer" className="shrink-0 border-t p-3">
          {sceneFooter}
        </footer>
      )}
    </div>
  );
});
