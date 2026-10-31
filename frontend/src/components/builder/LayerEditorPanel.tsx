import { memo, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronLeft, Table2, X } from 'lucide-react';
import { LayerStyleEditor } from './LayerStyleEditor';
import { LayerFilterEditor } from './LayerFilterEditor';
import { LabelEditor } from './LabelEditor';
import { PopupConfigEditor } from './PopupConfigEditor';
import { RasterLayerControls } from './RasterLayerControls';
import { InlineDeleteConfirm } from './row-chrome';
import { cn } from '@/lib/utils';
import { canOpenAttributeTable, getLayerCapabilities } from '@/lib/layer-capabilities';
import { getGeometryTypeLabel } from '@/i18n/labels';
import { getRenderAsOptions, getCurrentRenderAs, hasCustomizedRenderAsStyle, type RenderAsId } from './renderAs';
import { ColorizedGeometryIcon, getLayerColors, extractStyleHints, isDiscreteColorStyle } from '@/components/map/layer-icons';
import { legendFacts } from '@/components/map/legend-facts';
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
  onStyleConfigChange: (layerId: string, config: StyleConfig | null, paint: Record<string, unknown>, opts?: { replace?: boolean; restore?: boolean }) => void;
  onLayoutChange: (layerId: string, layout: Record<string, unknown>) => void;
  onRenderModeChange?: (layerId: string, mode: RenderAsId) => void;
  onRemove: (layerId: string) => void;
  /** Called after a banner Revert so the page can re-derive whether
   *  the map is still dirty (the revert itself routes through the ordinary
   *  mutation handlers, which all mark it dirty). */
  onRevertToSaved?: () => void;
}

interface LayerEditorPanelProps {
  layer: MapLayerResponse;
  /**
   * Server-state baseline for `layer`. When set, the embedded LayerStyleEditor
   * gates its "Pending style preview" banner on a deep-equal diff against this
   * baseline.
   */
  savedLayer?: MapLayerResponse;
  activeTab?: LayerEditorTab | null;
  handlers: LayerEditorHandlers;
  /** Closes the flyout and deselects the row */
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
  /** Opens the read-only attribute-table drawer for this layer. Rendered in
   *  the default scene only, and only for layers whose dataset carries a
   *  data table. */
  onOpenAttributeTable?: (layerId: string) => void;
  /**
   * Rendered-feature count for the active layer; forwarded to the filter-tab
   * LayerFilterEditor so it can render the empty-state hint when a filter is
   * applied but 0 features are visible.
   */
  featureCount?: number | null;
}

function LayerEditorTypePill({ layer }: { layer: MapLayerResponse }) {
  const { t } = useTranslation('builder');
  const caps = getLayerCapabilities(layer);
  const geometryType = layer.dataset_geometry_type;
  const renderMode = (layer.style_config as Record<string, unknown> | null)?.render_mode as string | undefined;

  let label: string;
  if (caps.kind === 'raster' || caps.kind === 'vrt') {
    if (layer.is_dem) {
      const modeLabel = renderMode === 'hillshade'
        ? t('layerEditor.typePill.hillshade', { defaultValue: 'Hillshade' })
        : renderMode === 'terrain'
          ? t('layerEditor.typePill.terrain', { defaultValue: 'Terrain' })
          : renderMode;
      label = modeLabel ? `DEM · ${modeLabel}` : 'DEM';
    } else {
      label = caps.kind === 'vrt' ? 'VRT' : t('search.raster', { defaultValue: 'Raster' });
    }
  } else {
    label = geometryType
      ? getGeometryTypeLabel(t, geometryType)
      : t('search.vector', { defaultValue: 'Vector' });
  }

  return (
    <span className={cn(
      'inline-flex items-center rounded-sm px-1.5 py-0.5 text-2xs font-semibold uppercase tracking-[0.08em]',
      caps.kind === 'vector' && 'bg-type-vector-bg text-type-vector',
      (caps.kind === 'raster' || caps.kind === 'vrt') && 'bg-type-raster-bg text-type-raster',
    )}>
      {label}
    </span>
  );
}

function Pip({ count, on }: { count?: number | null; on?: boolean }) {
  if (typeof count === 'number') {
    return (
      <span
        aria-hidden="true"
        className="inline-flex h-[14px] min-w-[14px] items-center justify-center rounded-full bg-primary px-1 text-2xs font-semibold leading-none text-primary-foreground"
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

// Filter condition counter, best-effort: handles {match,conditions[]} and raw
// maplibre expression arrays. Falls back to "1" for any non-null/empty filter
// so the pip never lies in the false-negative direction.
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
  onOpenAttributeTable,
  featureCount,
}: LayerEditorPanelProps) {
  const { t } = useTranslation('builder');
  const columns = layer.dataset_column_info ?? [];
  const caps = useMemo(() => getLayerCapabilities(layer), [layer]);
  const isRaster = caps.kind !== 'vector';
  const isHeatmap = layer.style_config?.render_mode === 'heatmap';
  const facts = useMemo(() => legendFacts(layer), [layer]);
  const layerColors = useMemo(() => getLayerColors(facts), [facts]);
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

  const renderAsOptions = useMemo(() => getRenderAsOptions(layer, t), [layer, t]);
  const currentRenderAs = useMemo(() => getCurrentRenderAs(layer), [layer]);

  const layerName = layer.display_name ?? layer.dataset_name;
  const isPureSettings = editorScene === 'settings';
  const panelTitle = isPureSettings ? t('settings.panelTitle', { defaultValue: 'Settings' }) : layerName;
  const isDefaultScene = editorScene === 'default' || editorScene === undefined;

  // Which tabs are available for this layer? Style is always present; Filter /
  // Labels / Popup depend on layer capabilities. Source lives in the row (···)
  // menu in StackRow.
  const availableTabs = useMemo<LayerEditorTab[]>(() => {
    const tabs: LayerEditorTab[] = ['style'];
    if (caps.supportsFilterEditor) tabs.push('filter');
    // Labels are independent layer decoration. Symbol render mode controls icon
    // rendering for points; it is not the only path for feature labels.
    const showLabelsTab = caps.supportsLabelEditor && !isHeatmap;
    if (showLabelsTab) tabs.push('labels');
    if (caps.supportsFilterEditor || caps.supportsLabelEditor) tabs.push('popup');
    return tabs;
  }, [caps.supportsFilterEditor, caps.supportsLabelEditor, isHeatmap]);

  // Resolve the active tab against availability — fall back to 'style' if the
  // requested tab vanished (e.g. layer changed to a non-labelable render mode).
  const resolvedActiveTab: LayerEditorTab = useMemo(() => {
    if (activeTab && availableTabs.includes(activeTab)) return activeTab;
    return 'style';
  }, [activeTab, availableTabs]);

  // Roving-tabindex tablists need an arrow-key handler: inactive tabs carry
  // tabIndex=-1, so a keyboard-only user would otherwise have no path to the
  // Filter/Labels/Popup editors. Selection follows focus (WAI-ARIA
  // automatic-activation tabs pattern).
  const handleTablistKeyDown = (event: React.KeyboardEvent<HTMLButtonElement>) => {
    const currentIndex = availableTabs.indexOf(resolvedActiveTab);
    let nextTab: LayerEditorTab | undefined;
    if (event.key === 'ArrowRight') {
      nextTab = availableTabs[(currentIndex + 1) % availableTabs.length];
    } else if (event.key === 'ArrowLeft') {
      nextTab = availableTabs[(currentIndex - 1 + availableTabs.length) % availableTabs.length];
    } else if (event.key === 'Home') {
      nextTab = availableTabs[0];
    } else if (event.key === 'End') {
      nextTab = availableTabs[availableTabs.length - 1];
    }
    if (!nextTab) return;
    event.preventDefault();
    if (nextTab !== resolvedActiveTab) handlers.onTabChange(layer.id, nextTab);
    document.getElementById(`tab-${layer.id}-${nextTab}`)?.focus();
  };

  // Destructive render-as switch — when the user clicks a different render-as
  // pill, hold the intended target until they confirm. null = no pending switch.
  const [pendingRenderAs, setPendingRenderAs] = useState<RenderAsId | null>(null);

  // Reset local state when the layer changes (defensive: keyed remount upstream
  // is the primary mechanism, but a caller that omits the key would carry over
  // stale pendingRenderAs).
  useEffect(() => {
    setPendingRenderAs(null);
  }, [layer.id, editorScene]);

  // Scroll + focus preservation across scene transitions
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

  const filterCount = countFilterConditions(layer.filter);
  const popupOn = layer.popup_config?.enabled === true;
  const labelsOn = Boolean(layer.label_config?.column);

  function handleRenderAsClick(target: RenderAsId) {
    if (target === currentRenderAs) return;
    // Only confirm when the CURRENT mode carries mode-specific style settings
    // that diverge from that mode's defaults (see hasCustomizedRenderAsStyle).
    // A fresh/default layer has nothing mode-specific to lose, so switch
    // immediately; a customized one (e.g. a non-default cluster radius or arrow
    // size) confirms before applying.
    if (hasCustomizedRenderAsStyle(layer)) {
      setPendingRenderAs(target);
      return;
    }
    handlers.onRenderModeChange?.(layer.id, target);
  }

  function confirmRenderAsSwitch() {
    if (pendingRenderAs) {
      handlers.onRenderModeChange?.(layer.id, pendingRenderAs);
      setPendingRenderAs(null);
      // The confirm held focus (autofocused button); hand it to the
      // pill that just became active instead of dropping to <body>.
      document.getElementById(`renderas-${layer.id}-${pendingRenderAs}`)?.focus();
    }
  }

  function cancelRenderAsSwitch() {
    setPendingRenderAs(null);
    // Return focus to the still-active pill instead of <body>.
    document.getElementById(`renderas-${layer.id}-${currentRenderAs}`)?.focus();
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
              className="block text-mini leading-tight tracking-[0.04em] text-muted-foreground hover:text-foreground hover:underline"
            >
              {/* Translated so the visible text agrees with the translated
                  aria-label above. */}
              {t('basemapSublayer.breadcrumb', {
                defaultValue: 'Basemap · {{name}} ›',
                name:
                  breadcrumbPresetName ??
                  t('basemapSublayer.breadcrumbUntitled', { defaultValue: 'Untitled' }),
              })}
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
              swatch={facts?.swatch ?? null}
              ramp={facts?.ramp ?? null}
              discrete={isDiscreteColorStyle(facts)}
            />
          )}

          <div className="flex flex-col min-w-0 flex-1">
            <div className="flex items-center gap-2 min-w-0">
              <span
                id="layer-editor-title"
                title={panelTitle}
                className="text-sm font-semibold truncate min-w-0"
              >
                {panelTitle}
              </span>
              {!isPureSettings && editorScene !== 'basemap-group' && editorScene !== 'basemap-sublayer' && (
                <LayerEditorTypePill layer={layer} />
              )}
            </div>
            {!isPureSettings && editorScene !== 'basemap-group' && editorScene !== 'basemap-sublayer' &&
              (caps.kind === 'raster' || caps.kind === 'vrt') &&
              typeof layer.band_count === 'number' && layer.band_count >= 1 && (
              <span className="text-mini text-muted-foreground truncate">
                {t('style.raster.bandCount', { count: layer.band_count })}
              </span>
            )}
          </div>

          {/* Read-only data inspection from the editor header, mirroring the
              layer-row kebab action. Default scene only: the DEM, basemap and
              settings scenes have no dataset-backed layer behind them. */}
          {isDefaultScene && onOpenAttributeTable && canOpenAttributeTable(layer) && (
            <button
              type="button"
              data-testid="layer-editor-open-attribute-table"
              onClick={() => onOpenAttributeTable(layer.id)}
              aria-label={t('layerEditor.openAttributeTable', { defaultValue: 'Open attribute table' })}
              title={t('layerEditor.openAttributeTable', { defaultValue: 'Open attribute table' })}
              className="flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-[var(--surface-2)] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <Table2 className="h-4 w-4" aria-hidden="true" />
            </button>
          )}
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
            {/* Tab strip — Style / Filter / Labels / Popup */}
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
                    onKeyDown={handleTablistKeyDown}
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
                    // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions -- keydown is an Escape-cancel guard for the pending confirm, not an interaction affordance
                    <section
                      aria-labelledby={`section-renderas-${layer.id}`}
                      className="rounded-md border bg-muted/25 p-3"
                      // Escape with the render-as confirm pending cancels the
                      // pending switch (consumed) instead of bubbling to the
                      // editor <aside> and closing the whole panel with the
                      // confirm still open. Section-level so it also covers
                      // focus resting on the pills.
                      onKeyDown={(e) => {
                        if (e.key === 'Escape' && pendingRenderAs) {
                          e.preventDefault();
                          e.stopPropagation();
                          cancelRenderAsSwitch();
                        }
                      }}
                    >
                      <p
                        id={`section-renderas-${layer.id}`}
                        className="eyebrow mb-2"
                      >
                        {t('layerEditor.section.renderAs', { defaultValue: 'Render as' })}
                      </p>
                      <div className="flex flex-wrap gap-2">
                        {renderAsOptions.map((option) => {
                          const isActive = option.id === currentRenderAs;
                          return (
                            <button
                              key={option.id}
                              // Stable id so confirm/cancel can
                              // restore keyboard focus to the pill.
                              id={`renderas-${layer.id}-${option.id}`}
                              type="button"
                              data-active={isActive ? 'true' : 'false'}
                              aria-pressed={isActive}
                              onClick={() => handleRenderAsClick(option.id)}
                              className={cn(
                                'rounded-md border border-transparent px-2.5 py-1 text-xs transition-colors',
                                isActive
                                  ? 'bg-primary text-primary-foreground border-transparent'
                                  : 'bg-surface-2 text-foreground hover:bg-surface-3',
                              )}
                            >
                              {option.label}
                            </button>
                          );
                        })}
                      </div>
                      {pendingRenderAs && (
                        // Shared builder-wide inline confirm: safe action left,
                        // destructive right, cancel autofocused. The shared
                        // component supplies the group+alert semantics and
                        // Escape-to-cancel; onCancel (cancelRenderAsSwitch)
                        // restores focus to the pill.
                        <InlineDeleteConfirm
                          confirmId={`confirm-render-as-${layer.id}`}
                          message={t('layerEditor.confirmRenderAs.message', {
                            defaultValue: 'Compatible style is carried over; only mode-specific settings will reset. Continue?',
                          })}
                          confirmLabel={t('layerEditor.confirmRenderAs.confirm', { defaultValue: 'Switch mode' })}
                          cancelLabel={t('layerEditor.confirmRenderAs.cancel', { defaultValue: 'Keep style' })}
                          onConfirm={confirmRenderAsSwitch}
                          onCancel={cancelRenderAsSwitch}
                          className="mx-0 mt-3 mb-0"
                        />
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
                      bandCount={layer.band_count}
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
                      onRevertToSaved={handlers.onRevertToSaved}
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
                    featureCount={featureCount ?? null}
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

        {/* Non-default scene body: the scene component arrives via
            sceneContent. */}
        {!isDefaultScene && sceneContent}
      </div>

      {/* Footer: only rendered for non-default scenes that supply a
          sceneFooter. Delete lives in the row (···) menu (StackRow). */}
      {!isDefaultScene && !!sceneFooter && (
        <footer data-testid="layer-editor-footer" className="shrink-0 border-t p-3">
          {sceneFooter}
        </footer>
      )}
    </div>
  );
});
