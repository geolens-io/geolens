import { useState, useMemo, useCallback, memo, lazy, Suspense, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, RotateCcw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { SliderRow } from './HeatmapStyleControls';
import { AdvancedJsonEditor } from './LayerStyleEditor/AdvancedJsonEditor';
import { RenderModeSwitch } from './LayerStyleEditor/RenderModeSwitch';
import type { EditorDispatchKey } from './LayerStyleEditor/RenderModeSwitch';
import {
  FILL_DEFAULTS, LINE_DEFAULTS, CIRCLE_DEFAULTS, getPaintValue,
  withBuilderConfig, stylePreviewStyle, hasUnsupportedBuilderState,
  hasUnsavedStyleChanges as hasUnsavedStyleChangesImpl,
} from './LayerStyleEditor/utils';
import { LazyLoadErrorBoundary } from '@/components/error';
import { getLayerType } from '@/components/builder/map-sync';
import { isNumericColumn } from '@/lib/column-utils';
import { stripLegacyBuilderPaint } from '@/lib/normalize-style-config';
import { GeometrySwatch } from '@/components/map/LegendEntries';
import { getLayerColors } from '@/components/map/layer-icons';
import { getRenderAsOptions } from './renderAs';
import type { BuilderStyleConfig, MapLayerResponse, StyleConfig, SymbolStyleConfig } from '@/types/api';

const DataDrivenStyleEditor = lazy(() => import('./DataDrivenStyleEditor').then(m => ({ default: m.DataDrivenStyleEditor })));

type PointRenderMode = 'points' | 'heatmap' | 'symbol' | 'cluster';

interface LayerStyleEditorProps {
  layer: MapLayerResponse;
  /**
   * SP-05: server-state baseline for the layer. Provided when the editor is
   * mounted from MapBuilderPage (which holds `savedLayerBaseline`). When set,
   * the "Pending style preview" banner is shown only if `layer` diverges from
   * `savedLayer` in paint / layout / style_config. When undefined (e.g. in
   * isolated tests or when the parent has no baseline source), the banner is
   * hidden — the assumption is "no baseline => nothing to diff against".
   */
  savedLayer?: MapLayerResponse;
  onPaintChange: (layerId: string, paint: Record<string, unknown>) => void;
  /** Omit to hide the master opacity slider (e.g. when the parent owns opacity via a separate control). */
  onOpacityChange?: (layerId: string, opacity: number) => void;
  onStyleConfigChange: (layerId: string, config: StyleConfig | null, paint: Record<string, unknown>) => void;
  onLayoutChange: (layerId: string, layout: Record<string, unknown>) => void;
  onRenderModeChange?: (layerId: string, mode: PointRenderMode) => void;
}

// Re-export hasUnsavedStyleChanges so existing callers (tests etc.) can still
// import it from './LayerStyleEditor' (the implementation lives in utils.ts).
export { hasUnsavedStyleChanges } from './LayerStyleEditor/utils';

function StyleControlSection({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-3 rounded-md border bg-muted/25 p-3">
      <div className="space-y-0.5">
        <div className="text-xs font-semibold text-foreground">{title}</div>
        {description && <p className="text-[11px] leading-snug text-muted-foreground">{description}</p>}
      </div>
      {children}
    </section>
  );
}

function StylePreview({ layer, onReset }: { layer: MapLayerResponse; onReset: () => void }) {
  const { t } = useTranslation('builder');
  const colors = getLayerColors(layer);
  const swatchColor = colors[0] ?? '#6366f1';
  return (
    <div className="flex items-center justify-between gap-3 rounded-md border bg-background p-2">
      <div className="flex min-w-0 items-center gap-2">
        <GeometrySwatch geometryType={layer.dataset_geometry_type} color={swatchColor} style={stylePreviewStyle(layer)} />
        <div className="min-w-0">
          <div className="truncate text-xs font-medium">{t('style.preview.title')}</div>
          <p className="truncate text-[11px] text-muted-foreground">{t('style.preview.description')}</p>
        </div>
      </div>
      <Button
        type="button"
        variant="ghost"
        size="xs"
        className="shrink-0"
        onClick={onReset}
        title={t('style.resetTitle')}
      >
        <RotateCcw className="h-3 w-3" />
        {t('style.reset')}
      </Button>
    </div>
  );
}

/**
 * LayerStyleEditor orchestrator.
 *
 * Responsibilities:
 *  - Compute geomType, renderMode, dispatchKey from layer props
 *  - Maintain the master opacity debounce (PB-02, Plan 03)
 *  - Render the "Render as" dropdown (point layers only)
 *  - Delegate per-mode appearance controls to RenderModeSwitch
 *  - Render master opacity + zoom range sliders (cross-mode)
 *  - Render lazy DataDrivenStyleEditor (cross-mode)
 *  - Render AdvancedJsonEditor (cross-mode)
 */
export const LayerStyleEditor = memo(function LayerStyleEditor({
  layer,
  savedLayer,
  onPaintChange,
  onOpacityChange,
  onStyleConfigChange,
  onLayoutChange,
  onRenderModeChange,
}: LayerStyleEditorProps) {
  const { t } = useTranslation('builder');
  const geomType = getLayerType(layer.dataset_geometry_type);
  const paint = layer.paint;
  const layoutObj = useMemo(
    () => (layer.layout as Record<string, unknown>) ?? {},
    [layer.layout],
  );
  const isDataDriven = !!layer.style_config?.column;
  const renderMode: PointRenderMode = layer.style_config?.render_mode === 'heatmap'
    ? 'heatmap'
    : layer.style_config?.render_mode === 'symbol'
      ? 'symbol'
      : layer.style_config?.render_mode === 'cluster'
        ? 'cluster'
        : 'points';

  // Compute the dispatch key for RenderModeSwitch
  // For circle/point layers, sub-dispatch by renderMode
  const dispatchKey: EditorDispatchKey = useMemo(() => {
    if (geomType === 'fill') return 'fill';
    if (geomType === 'line') return 'line';
    if (geomType === 'circle') {
      if (renderMode === 'heatmap') return 'heatmap';
      if (renderMode === 'symbol') return 'symbol';
      if (renderMode === 'cluster') return 'cluster';
      return 'circle';
    }
    return 'raster';
  }, [geomType, renderMode]);

  const builderConfig = useMemo(
    () => layer.style_config?.builder ?? {},
    [layer.style_config?.builder],
  );
  const symbolConfig = useMemo(
    () => ({
      ...(builderConfig.symbol ?? {}),
      ...(layer.style_config?.symbol ?? {}),
    }) as SymbolStyleConfig,
    [builderConfig.symbol, layer.style_config?.symbol],
  );

  const fillEnabled = !(builderConfig.fillDisabled ?? paint['_fill-disabled']);
  const strokeEnabled = !(builderConfig.strokeDisabled ?? paint['_stroke-disabled']);

  const isPolygon = (layer.dataset_geometry_type ?? '').toUpperCase().includes('POLYGON');
  const numericColumns = useMemo(
    () => (layer.dataset_column_info ?? []).filter((col) => isNumericColumn(col.type)),
    [layer.dataset_column_info],
  );
  const currentHeightCol = builderConfig.heightColumn ?? (layer.paint?.['_height_column'] as string) ?? '';
  const clusterAvailable = useMemo(
    () => renderMode === 'cluster' || getRenderAsOptions(layer).some((option) => option.id === 'cluster'),
    [layer, renderMode],
  );

  // PB-02 (PERF-04): 100ms debounce for master opacity slider.
  // Local state holds the slider's displayed value so drags feel instant,
  // while the debounced effect coalesces rapid changes into a single
  // onOpacityChange call. The `opacityFromPropRef` tracks the last value
  // received via the `layer.opacity` prop so we can skip emitting on external
  // resets (undo, layer swap) — only user-initiated drags emit debounced calls.
  const [localOpacity, setLocalOpacity] = useState(layer.opacity ?? 1);
  const opacityTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const opacityFromPropRef = useRef(layer.opacity ?? 1);
  // Sync local opacity when the external prop changes (e.g., undo / layer swap)
  useEffect(() => {
    const next = layer.opacity ?? 1;
    opacityFromPropRef.current = next;
    setLocalOpacity(next);
  }, [layer.opacity]);
  // Debounced emission — only fires when localOpacity diverges from last prop value
  useEffect(() => {
    if (!onOpacityChange) return;
    if (localOpacity === opacityFromPropRef.current) return;
    clearTimeout(opacityTimerRef.current);
    opacityTimerRef.current = setTimeout(() => {
      onOpacityChange(layer.id, localOpacity);
    }, 100);
    return () => clearTimeout(opacityTimerRef.current);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [localOpacity, layer.id]);

  const controlPaint = useMemo(() => ({
    ...paint,
    ...(builderConfig.outlineColor !== undefined ? { '_outline-color': builderConfig.outlineColor } : {}),
    ...(builderConfig.outlineWidth !== undefined ? { '_outline-width': builderConfig.outlineWidth } : {}),
    ...(builderConfig.fillDisabled !== undefined ? { '_fill-disabled': builderConfig.fillDisabled } : {}),
    ...(builderConfig.strokeDisabled !== undefined ? { '_stroke-disabled': builderConfig.strokeDisabled } : {}),
    ...(builderConfig.fillOpacitySaved !== undefined ? { '_fill-opacity-saved': builderConfig.fillOpacitySaved } : {}),
    ...(builderConfig.outlineWidthSaved !== undefined ? { '_outline-width-saved': builderConfig.outlineWidthSaved } : {}),
    ...(builderConfig.heightColumn !== undefined ? { '_height_column': builderConfig.heightColumn } : {}),
    ...(builderConfig.heatmapRamp !== undefined ? { '_heatmap-ramp': builderConfig.heatmapRamp } : {}),
    ...(builderConfig.heatmapWeightColumn !== undefined ? { '_heatmap-weight-column': builderConfig.heatmapWeightColumn } : {}),
  }), [paint, builderConfig]);

  const updateBuilderConfig = useCallback((patch: BuilderStyleConfig, nextPaint: Record<string, unknown> = paint) => {
    onStyleConfigChange(layer.id, withBuilderConfig(layer.style_config, patch), stripLegacyBuilderPaint(nextPaint));
  }, [layer.id, layer.style_config, paint, onStyleConfigChange]);

  const handlePaintProp = useCallback((key: string, value: unknown) => {
    if (key === '_outline-color') {
      updateBuilderConfig({ outlineColor: value as string });
      return;
    }
    if (key === '_outline-width') {
      updateBuilderConfig({ outlineWidth: value as number });
      return;
    }
    onPaintChange(layer.id, { ...paint, [key]: value });
  }, [layer.id, paint, onPaintChange, updateBuilderConfig]);

  const handleToggleFill = useCallback(() => {
    const next = { ...paint };
    if (fillEnabled) {
      const saved = getPaintValue(paint, 'fill-opacity', FILL_DEFAULTS['fill-opacity']);
      next['fill-opacity'] = 0;
      updateBuilderConfig({ fillDisabled: true, fillOpacitySaved: saved }, next);
    } else {
      const saved = builderConfig.fillOpacitySaved ?? getPaintValue(paint, '_fill-opacity-saved', FILL_DEFAULTS['fill-opacity']);
      next['fill-opacity'] = saved;
      updateBuilderConfig({ fillDisabled: undefined, fillOpacitySaved: undefined }, next);
    }
  }, [paint, fillEnabled, builderConfig.fillOpacitySaved, updateBuilderConfig]);

  const handleToggleStroke = useCallback(() => {
    const next = { ...paint };
    const widthKey = geomType === 'circle' ? 'circle-stroke-width' : '_outline-width';
    const defaultWidth = geomType === 'circle' ? CIRCLE_DEFAULTS['circle-stroke-width'] : FILL_DEFAULTS['_outline-width'];
    if (strokeEnabled) {
      const saved = geomType === 'circle'
        ? getPaintValue(paint, widthKey, defaultWidth)
        : builderConfig.outlineWidth ?? getPaintValue(paint, widthKey, defaultWidth);
      if (geomType === 'circle') next[widthKey] = 0;
      updateBuilderConfig({
        strokeDisabled: true,
        outlineWidthSaved: saved,
        ...(geomType !== 'circle' ? { outlineWidth: 0 } : {}),
      }, next);
    } else {
      const saved = builderConfig.outlineWidthSaved ?? getPaintValue(paint, '_outline-width-saved', defaultWidth);
      if (geomType === 'circle') next[widthKey] = saved;
      updateBuilderConfig({
        strokeDisabled: undefined,
        outlineWidthSaved: undefined,
        ...(geomType !== 'circle' ? { outlineWidth: saved } : {}),
      }, next);
    }
  }, [paint, geomType, strokeEnabled, builderConfig.outlineWidth, builderConfig.outlineWidthSaved, updateBuilderConfig]);

  const handleHeatmapPaintChange = useCallback((layerId: string, nextPaint: Record<string, unknown>) => {
    const heatmapRamp = typeof nextPaint['_heatmap-ramp'] === 'string'
      ? nextPaint['_heatmap-ramp'] as string
      : builderConfig.heatmapRamp;
    const heatmapWeightColumn = typeof nextPaint['_heatmap-weight-column'] === 'string'
      ? nextPaint['_heatmap-weight-column'] as string
      : nextPaint['heatmap-weight'] === 1
        ? undefined
        : builderConfig.heatmapWeightColumn;
    onStyleConfigChange(
      layerId,
      withBuilderConfig(layer.style_config, { heatmapRamp, heatmapWeightColumn }),
      stripLegacyBuilderPaint(nextPaint),
    );
  }, [builderConfig.heatmapRamp, builderConfig.heatmapWeightColumn, layer.style_config, onStyleConfigChange]);

  const handleSymbolConfigChange = useCallback((patch: SymbolStyleConfig) => {
    const nextSymbol = { ...symbolConfig, ...patch };
    const nextConfig = {
      ...(layer.style_config ?? {}),
      render_mode: 'symbol',
      symbol: nextSymbol,
    } as StyleConfig;
    onStyleConfigChange(layer.id, nextConfig, stripLegacyBuilderPaint(paint));
  }, [layer.id, layer.style_config, onStyleConfigChange, paint, symbolConfig]);

  const handleResetStyle = useCallback(() => {
    if (geomType === 'fill') {
      onStyleConfigChange(layer.id, null, FILL_DEFAULTS);
    } else if (geomType === 'line') {
      const nextLayout = { ...layoutObj };
      delete nextLayout['line-dasharray'];
      delete nextLayout['_minzoom'];
      delete nextLayout['_maxzoom'];
      onStyleConfigChange(layer.id, null, LINE_DEFAULTS);
      onLayoutChange(layer.id, nextLayout);
    } else {
      onStyleConfigChange(layer.id, null, CIRCLE_DEFAULTS);
    }
    onOpacityChange?.(layer.id, 1);
  }, [geomType, layer.id, layoutObj, onLayoutChange, onOpacityChange, onStyleConfigChange]);

  const unsupportedBuilderState = hasUnsupportedBuilderState(layer, geomType);

  // SP-05 (Phase 1045): Gate the "Pending style preview" banner on real dirty
  // tracking instead of unconditionally rendering it.
  const isStyleDirty = useMemo(
    () => hasUnsavedStyleChangesImpl(layer, savedLayer),
    [layer, savedLayer],
  );

  // Shared props passed to every per-mode editor via RenderModeSwitch
  const editorProps = useMemo(() => ({
    layer,
    paint: controlPaint,
    isDataDriven,
    builderConfig,
    styleConfig: layer.style_config ?? null,
    symbolConfig,
    renderMode,
    isPolygon,
    numericColumns,
    currentHeightCol,
    strokeEnabled,
    fillEnabled,
    clusterAvailable,
    onPaintChange,
    onLayoutChange,
    onStyleConfigChange,
    onRenderModeChange,
    onPaintProp: handlePaintProp,
    onToggleFill: handleToggleFill,
    onToggleStroke: handleToggleStroke,
    onHeatmapPaintChange: handleHeatmapPaintChange,
    onSymbolConfigChange: handleSymbolConfigChange,
    onBuilderChange: updateBuilderConfig,
    t,
  }), [
    layer, controlPaint, isDataDriven, builderConfig, symbolConfig, renderMode,
    isPolygon, numericColumns, currentHeightCol, strokeEnabled, fillEnabled,
    clusterAvailable, onPaintChange, onLayoutChange, onStyleConfigChange,
    onRenderModeChange, handlePaintProp, handleToggleFill, handleToggleStroke,
    handleHeatmapPaintChange, handleSymbolConfigChange, updateBuilderConfig, t,
  ]);

  return (
    <div className="space-y-2">
      {isStyleDirty && <StylePreview layer={layer} onReset={handleResetStyle} />}

      {unsupportedBuilderState && (
        <div className="flex items-start gap-2 rounded-md border border-warning/40 bg-warning/10 p-2 text-xs text-warning-foreground">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{t('style.unsupportedBuilderState')}</span>
        </div>
      )}

      {/* Render as dropdown — point layers only */}
      {geomType === 'circle' && (
        <StyleControlSection title={t('style.sections.render')} description={t('style.sections.renderDescription')}>
          <Select
            value={renderMode}
            onValueChange={(mode) => onRenderModeChange?.(layer.id, mode as PointRenderMode)}
          >
            <SelectTrigger className="h-8 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="points">{t('style.renderPoints')}</SelectItem>
              <SelectItem value="symbol">{t('style.renderSymbol')}</SelectItem>
              <SelectItem value="heatmap">{t('style.renderHeatmap')}</SelectItem>
              {clusterAvailable && <SelectItem value="cluster">{t('style.renderCluster')}</SelectItem>}
            </SelectContent>
          </Select>
        </StyleControlSection>
      )}

      {/* Data-driven style editor — hidden when in heatmap/symbol/cluster mode */}
      {renderMode !== 'heatmap' && renderMode !== 'symbol' && renderMode !== 'cluster' && (
        <StyleControlSection title={t('style.sections.dataDriven')} description={t('style.sections.dataDrivenDescription')}>
          <LazyLoadErrorBoundary>
            <Suspense fallback={null}>
              <DataDrivenStyleEditor
                layer={layer}
                onStyleConfigChange={onStyleConfigChange}
              />
            </Suspense>
          </LazyLoadErrorBoundary>
        </StyleControlSection>
      )}

      {/* Per-render-mode appearance controls — dispatched via RenderModeSwitch
          Section title/description adapts to the active mode (heatmap/symbol/cluster
          have their own section labels; fill/line/circle share the generic appearance label). */}
      <StyleControlSection
        title={t(
          dispatchKey === 'heatmap' ? 'style.sections.heatmap'
          : dispatchKey === 'symbol' ? 'style.sections.symbol'
          : dispatchKey === 'cluster' ? 'style.sections.cluster'
          : 'style.sections.appearance',
        )}
        description={t(
          dispatchKey === 'heatmap' ? 'style.sections.heatmapDescription'
          : dispatchKey === 'symbol' ? 'style.sections.symbolDescription'
          : dispatchKey === 'cluster' ? 'style.sections.clusterDescription'
          : 'style.sections.appearanceDescription',
        )}
      >
        <RenderModeSwitch {...editorProps} dispatchKey={dispatchKey} />

        {/* Master opacity — all geometry types; omitted when parent owns the opacity control */}
        {onOpacityChange && (
          <>
            <div className="text-xs font-medium mt-2 pt-2 border-t">{t('style.opacity')}</div>
            <SliderRow
              label={t('style.layer')}
              value={localOpacity}
              min={0}
              max={1}
              step={0.01}
              format="percent"
              onChange={setLocalOpacity}
            />
          </>
        )}

        {/* Layer zoom range */}
        <div className="text-xs font-medium mt-2 pt-2 border-t">{t('style.zoomRange')}</div>
        <SliderRow
          label={t('style.minZoom')}
          value={layoutObj['_minzoom'] as number ?? 0}
          min={0}
          max={(layoutObj['_maxzoom'] as number ?? 22) - 1}
          step={1}
          format="zoom"
          onChange={(val) => onLayoutChange(layer.id, { ...layoutObj, '_minzoom': val })}
        />
        <SliderRow
          label={t('style.maxZoom')}
          value={layoutObj['_maxzoom'] as number ?? 22}
          min={(layoutObj['_minzoom'] as number ?? 0) + 1}
          max={22}
          step={1}
          format="zoom"
          onChange={(val) => onLayoutChange(layer.id, { ...layoutObj, '_maxzoom': val })}
        />
      </StyleControlSection>

      <StyleControlSection title={t('style.sections.advanced')} description={t('style.sections.advancedDescription')}>
        <AdvancedJsonEditor
          paint={paint}
          layout={(layer.layout as Record<string, unknown>) ?? {}}
          onPaintChange={(p) => onPaintChange(layer.id, p)}
          onLayoutChange={(l) => onLayoutChange(layer.id, l)}
          layerType={geomType}
        />
      </StyleControlSection>
    </div>
  );
});
