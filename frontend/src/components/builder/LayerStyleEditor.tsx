import { useState, useMemo, useCallback, memo, lazy, Suspense, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, RotateCcw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { SliderRow } from './HeatmapStyleControls';
import { AdvancedJsonEditor } from './LayerStyleEditor/AdvancedJsonEditor';
import { RenderModeSwitch } from './LayerStyleEditor/RenderModeSwitch';
import type { EditorDispatchKey } from './LayerStyleEditor/RenderModeSwitch';
import { buildBuilderControlPaint, routeBuilderPaintProp } from './LayerStyleEditor/builder-paint-map';
import {
  FILL_DEFAULTS, LINE_DEFAULTS, CIRCLE_DEFAULTS, getPaintValue,
  withBuilderConfig, stylePreviewStyle, hasUnsupportedBuilderState,
  hasUnsavedStyleChanges as hasUnsavedStyleChangesImpl,
} from './LayerStyleEditor/utils';
import { LazyLoadErrorBoundary } from '@/components/error';
import { getLayerType, resolveAdapterType } from '@/components/builder/map-sync';
import { isNumericColumn } from '@/lib/column-utils';
import { stripLegacyBuilderPaint } from '@/lib/normalize-style-config';
import { GeometrySwatch } from '@/components/map/LegendEntries';
import { getLayerColors } from '@/components/map/layer-icons';
import { getRenderAsOptions } from './renderAs';
import type { BuilderStyleConfig, MapLayerResponse, StyleConfig, SymbolStyleConfig } from '@/types/api';

const DataDrivenStyleEditor = lazy(() => import('./DataDrivenStyleEditor').then(m => ({ default: m.DataDrivenStyleEditor })));

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
}

// Re-export hasUnsavedStyleChanges so existing callers (tests etc.) can still
// import it from './LayerStyleEditor' (the implementation lives in utils.ts).
export { hasUnsavedStyleChanges } from './LayerStyleEditor/utils';

function StyleControlSection({
  title,
  description,
  headerAction,
  children,
}: {
  title: string;
  description?: string;
  headerAction?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-3 rounded-md border bg-muted/25 p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="space-y-0.5 min-w-0">
          <div className="text-xs font-semibold text-foreground">{title}</div>
          {description && <p className="text-mini leading-snug text-muted-foreground">{description}</p>}
        </div>
        {headerAction}
      </div>
      {children}
    </section>
  );
}

function StylePreview({ layer, onRevert }: { layer: MapLayerResponse; onRevert: () => void }) {
  const { t } = useTranslation('builder');
  const colors = getLayerColors(layer);
  const swatchColor = colors[0] ?? '#6366f1';
  return (
    <div className="flex items-center justify-between gap-3 rounded-md border bg-background p-2">
      <div className="flex min-w-0 items-center gap-2">
        <GeometrySwatch geometryType={layer.dataset_geometry_type} color={swatchColor} style={stylePreviewStyle(layer)} />
        <div className="min-w-0">
          <div className="truncate text-xs font-medium">{t('style.preview.title')}</div>
          <p className="truncate text-mini text-muted-foreground">{t('style.preview.description')}</p>
        </div>
      </div>
      <Button
        type="button"
        variant="ghost"
        size="xs"
        className="shrink-0"
        onClick={onRevert}
        title={t('style.preview.revertTitle')}
      >
        <RotateCcw className="h-3 w-3" />
        {t('style.preview.revert')}
      </Button>
    </div>
  );
}

/**
 * LayerStyleEditor orchestrator.
 *
 * Responsibilities:
 *  - Compute geomType, renderMode, dispatchKey from layer props
 *  - Maintain the master opacity debounce (Phase 20260526-builder-audit #338 BLD-20260526-11)
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
}: LayerStyleEditorProps) {
  const { t } = useTranslation('builder');
  const geomType = getLayerType(layer.dataset_geometry_type);
  const paint = layer.paint;
  const layoutObj = useMemo(
    () => (layer.layout as Record<string, unknown>) ?? {},
    [layer.layout],
  );
  // Advanced JSON editor edits real MapLibre paint/layout, so strip builder-private
  // keys before showing them — MapLibre's validateStyleMin rejects them as
  // 'unknown property' on Apply (B-010). stripLegacyBuilderPaint removes the known
  // vector allowlist (incl. non-underscore outline-color/outline-width); the
  // _-prefix drop covers layout _minzoom/_maxzoom and any future _-prefixed keys.
  const stripBuilderPrivate = useCallback(
    (obj: Record<string, unknown>) =>
      Object.fromEntries(
        Object.entries(stripLegacyBuilderPaint(obj)).filter(([k]) => !k.startsWith('_')),
      ),
    [],
  );
  const editorPaint = useMemo(() => stripBuilderPrivate(paint), [paint, stripBuilderPrivate]);
  const editorLayout = useMemo(() => stripBuilderPrivate(layoutObj), [layoutObj, stripBuilderPrivate]);
  // fix(#394) ST-02/B-031: the Advanced JSON editor must validate against the
  // RENDERED layer type, not the geometry-derived one — a heatmap-rendered
  // point layer rejected valid heatmap-* paint and accepted dead circle-*
  // paint. Cluster renders as circles for validation purposes.
  const advancedJsonLayerType = useMemo(() => {
    const resolved = resolveAdapterType(layer.dataset_geometry_type, layer.style_config, editorPaint);
    // 'mixed' passes through — AdvancedJsonEditor validates each family's keys
    // against its own sublayer type (fix #431 codex r2), so line-*/circle-*
    // keys stay authorable for the line/point sublayers.
    return resolved === 'cluster' ? 'circle' : resolved;
  }, [layer.dataset_geometry_type, layer.style_config, editorPaint]);
  const isDataDriven = !!layer.style_config?.column;
  const renderMode: 'points' | 'heatmap' | 'symbol' | 'cluster' = layer.style_config?.render_mode === 'heatmap'
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

  // Phase 20260526-builder-audit #338 BLD-20260526-11: 100ms debounce for master opacity slider.
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
  // eslint-disable-next-line react-hooks/exhaustive-deps -- push opacity only on local/layer change; the sync setter is stable
  }, [localOpacity, layer.id]);

  // builder-audit #338 DRY-01: forward map derived from the single BUILDER_PAINT_FIELDS
  // table (builder-paint-map.ts), which also backs handlePaintProp's reverse router
  // and the strip allowlist — so the three can no longer drift.
  const controlPaint = useMemo(
    () => buildBuilderControlPaint(paint, builderConfig),
    [paint, builderConfig],
  );

  const updateBuilderConfig = useCallback((patch: BuilderStyleConfig, nextPaint: Record<string, unknown> = paint) => {
    onStyleConfigChange(layer.id, withBuilderConfig(layer.style_config, patch), stripLegacyBuilderPaint(nextPaint));
  }, [layer.id, layer.style_config, paint, onStyleConfigChange]);

  const handlePaintProp = useCallback((key: string, value: unknown) => {
    // builder-audit #338 DRY-01: reverse router derived from BUILDER_PAINT_FIELDS.
    const builderKey = routeBuilderPaintProp(key);
    if (builderKey) {
      updateBuilderConfig({ [builderKey]: value } as BuilderStyleConfig);
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

  // EDIT-05: Dedicated fill-pattern handler that enforces mutual exclusion between
  // fill-color and fill-pattern. Setting a pattern deletes fill-color; clearing the
  // pattern (solid / None) deletes fill-pattern. The KEY is removed — never set to
  // undefined — so saved paint never carries both keys or an undefined value.
  const handleFillPatternChange = useCallback((id: string | undefined) => {
    const next = { ...paint };
    if (id) {
      // switching to pattern: remove fill-color, set fill-pattern
      delete next['fill-color'];
      next['fill-pattern'] = id;
    } else {
      // switching to solid / None: remove fill-pattern
      delete next['fill-pattern'];
      // Restore default fill-color if absent
      if (!next['fill-color']) {
        next['fill-color'] = FILL_DEFAULTS['fill-color'];
      }
    }
    onPaintChange(layer.id, next);
  }, [layer.id, paint, onPaintChange]);

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

  // Bumped by handleRevertToSaved to force-remount the data-driven editor.
  const [revertNonce, setRevertNonce] = useState(0);

  // fix(#461): banner Reset misbehaved — the "Pending style
  // preview" banner promises to reflect "this layer before save", so its action
  // must REVERT the unsaved edits to the server baseline — not apply library
  // defaults (which silently flattened hand-authored expressions like the
  // wind-speed line-width). The banner only renders when `savedLayer` exists
  // (isStyleDirty is false without a baseline), but we guard and fall back to the
  // defaults reset if it is ever missing. The section-header Reset keeps its
  // distinct "reset appearance to defaults" behavior via handleResetStyle.
  const handleRevertToSaved = useCallback(() => {
    if (!savedLayer) {
      handleResetStyle();
      return;
    }
    onStyleConfigChange(layer.id, savedLayer.style_config ?? null, savedLayer.paint ?? {});
    onLayoutChange(layer.id, savedLayer.layout ?? {});
    onOpacityChange?.(layer.id, savedLayer.opacity ?? 1);
    // Remount DataDrivenStyleEditor so its local ramp/mode/column re-seed from the
    // restored config instead of re-applying the just-discarded selection.
    setRevertNonce((n) => n + 1);
  }, [savedLayer, layer.id, onStyleConfigChange, onLayoutChange, onOpacityChange, handleResetStyle]);

  const unsupportedBuilderState = hasUnsupportedBuilderState(layer, geomType);

  // SP-05 (Phase 1045): Gate the "Pending style preview" banner on real dirty
  // tracking instead of unconditionally rendering it.
  const isStyleDirty = useMemo(
    () => hasUnsavedStyleChangesImpl(layer, savedLayer),
    [layer, savedLayer],
  );

  // Shared props passed to every per-mode editor via RenderModeSwitch.
  // builder-audit #338 MAINT-01: this ~25-field mega-prop is a deliberate trade-off —
  // a single uniform BaseStyleEditorProps keeps RenderModeSwitch's lookup-table
  // dispatch trivial; most editors consume only a subset. Acceptable as-is; if it
  // grows further, split into a common core + per-mode prop slices.
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
    onPaintProp: handlePaintProp,
    onToggleFill: handleToggleFill,
    onToggleStroke: handleToggleStroke,
    onHeatmapPaintChange: handleHeatmapPaintChange,
    onSymbolConfigChange: handleSymbolConfigChange,
    onBuilderChange: updateBuilderConfig,
    onFillPatternChange: handleFillPatternChange,
    t,
  }), [
    layer, controlPaint, isDataDriven, builderConfig, symbolConfig, renderMode,
    isPolygon, numericColumns, currentHeightCol, strokeEnabled, fillEnabled,
    clusterAvailable, onPaintChange, onLayoutChange, onStyleConfigChange,
    handlePaintProp, handleToggleFill, handleToggleStroke,
    handleHeatmapPaintChange, handleSymbolConfigChange, updateBuilderConfig,
    handleFillPatternChange, t,
  ]);

  return (
    <div className="space-y-2">
      {isStyleDirty && <StylePreview layer={layer} onRevert={handleRevertToSaved} />}

      {unsupportedBuilderState && (
        <div className="flex items-start gap-2 rounded-md border border-warning/40 bg-warning/10 p-2 text-xs text-warning-foreground">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{t('style.unsupportedBuilderState')}</span>
        </div>
      )}

      {/* Data-driven style editor — hidden when in heatmap/symbol/cluster mode */}
      {renderMode !== 'heatmap' && renderMode !== 'symbol' && renderMode !== 'cluster' && (
        <StyleControlSection title={t('style.sections.dataDriven')} description={t('style.sections.dataDrivenDescription')}>
          <LazyLoadErrorBoundary>
            <Suspense fallback={null}>
              <DataDrivenStyleEditor
                // fix(#461): DataDrivenStyleEditor seeds its
                // ramp/mode/column into local useState on mount. A banner Revert
                // rewrites layer.style_config externally, but that local state
                // stays stale and its effect would immediately re-apply the
                // discarded ramp. Bumping this key on revert remounts the editor
                // so it re-seeds from the restored config. (Normal edits don't
                // bump it, so typing/interaction is unaffected.)
                key={`dds-${revertNonce}`}
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
        headerAction={
          <Button
            type="button"
            variant="ghost"
            size="xs"
            className="shrink-0"
            onClick={handleResetStyle}
            title={t('style.resetTitle')}
          >
            <RotateCcw className="h-3 w-3" />
            {t('style.reset')}
          </Button>
        }
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
          paint={editorPaint}
          layout={editorLayout}
          onPaintChange={(p) => onPaintChange(layer.id, p)}
          onLayoutChange={(l) => onLayoutChange(layer.id, l)}
          layerType={advancedJsonLayerType}
        />
      </StyleControlSection>
    </div>
  );
});
