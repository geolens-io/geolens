import { useId, useState, useMemo, useCallback, memo, lazy, Suspense, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, RotateCcw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { InlineDeleteConfirm } from './row-chrome';
import { SliderRow } from './HeatmapStyleControls';
import { AdvancedJsonEditor } from './LayerStyleEditor/AdvancedJsonEditor';
import { RenderModeSwitch } from './LayerStyleEditor/RenderModeSwitch';
import type { EditorDispatchKey } from './LayerStyleEditor/RenderModeSwitch';
import { buildBuilderControlPaint, routeBuilderPaintProp } from './LayerStyleEditor/builder-paint-map';
import {
  FILL_DEFAULTS, LINE_DEFAULTS, CIRCLE_DEFAULTS, getPaintValue,
  withBuilderConfig, compactBuilder, hasUnsupportedBuilderState,
  hasUnsavedStyleChanges as hasUnsavedStyleChangesImpl,
} from './LayerStyleEditor/utils';
import { LazyLoadErrorBoundary } from '@/components/error';
import { getLayerType, resolveAdapterType } from '@/components/builder/map-sync';
import { TILE_FEATURE_LIMIT, exceedsTileFeatureLimit } from './cluster-source';
import { formatNumber } from '@/lib/format';
import { isNumericColumn } from '@/lib/column-utils';
import { stripLegacyBuilderPaint } from '@/lib/normalize-style-config';
import { GeometrySwatch } from '@/components/map/LegendEntries';
import { getLayerColors } from '@/components/map/layer-icons';
import { legendFacts } from '@/components/map/legend-facts';
import { MAP_COLORS } from '@/lib/map-colors';
import type { BuilderStyleConfig, MapLayerResponse, StyleConfig, SymbolStyleConfig } from '@/types/api';

const DataDrivenStyleEditor = lazy(() => import('./DataDrivenStyleEditor').then(m => ({ default: m.DataDrivenStyleEditor })));

interface LayerStyleEditorProps {
  layer: MapLayerResponse;
  /**
   * Server-state baseline for the layer, provided by MapBuilderPage (which
   * holds `savedLayerBaseline`). When set, the "Pending style preview" banner
   * shows only if `layer` diverges from `savedLayer` in paint / layout /
   * style_config. When undefined (isolated tests, no baseline source) the
   * banner is hidden: nothing to diff against.
   */
  savedLayer?: MapLayerResponse;
  onPaintChange: (layerId: string, paint: Record<string, unknown>) => void;
  /** Omit to hide the master opacity slider (when the parent owns opacity separately). */
  onOpacityChange?: (layerId: string, opacity: number) => void;
  onStyleConfigChange: (layerId: string, config: StyleConfig | null, paint: Record<string, unknown>, opts?: { replace?: boolean; restore?: boolean }) => void;
  onLayoutChange: (layerId: string, layout: Record<string, unknown>) => void;
  /**
   * Banner Revert restores the baseline through the ordinary mutation handlers,
   * each of which marks the map dirty, so the owner of the baseline re-derives
   * cleanliness here; it clears only when the whole map is clean.
   */
  onRevertToSaved?: () => void;
}

// Re-exported for existing callers; the implementation lives in utils.ts.
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
  const facts = legendFacts(layer);
  const swatchColor = getLayerColors(facts)[0] ?? MAP_COLORS.icon.fallback;
  return (
    <div className="flex items-center justify-between gap-3 rounded-md border bg-background p-2">
      <div className="flex min-w-0 items-center gap-2">
        <GeometrySwatch geometryType={layer.dataset_geometry_type} color={swatchColor} style={facts?.swatch} />
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

// The `_`-prefixed builder-private subset of a paint/layout object. The
// Advanced JSON editor shows a copy with these stripped (stripBuilderPrivate)
// and Apply replaces the block wholesale, so the onApply wrappers must
// re-merge them; otherwise open→Apply silently resets _minzoom/_maxzoom (the
// zoom sliders' only storage) to 0–22 and the paint block loses its `_` keys.
function builderPrivateKeys(obj: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(Object.entries(obj).filter(([k]) => k.startsWith('_')));
}

/**
 * LayerStyleEditor orchestrator.
 *
 * Responsibilities:
 *  - Compute geomType, renderMode, dispatchKey from layer props
 *  - Maintain the master opacity debounce
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
  onRevertToSaved,
}: LayerStyleEditorProps) {
  const layerOpacityHelpId = useId();
  const { t } = useTranslation('builder');
  const geomType = getLayerType(layer.dataset_geometry_type);
  const paint = layer.paint;
  const layoutObj = useMemo(
    () => (layer.layout as Record<string, unknown>) ?? {},
    [layer.layout],
  );
  // The Advanced JSON editor edits real MapLibre paint/layout, so builder-private
  // keys are stripped: validateStyleMin rejects them as 'unknown property' on
  // Apply. stripLegacyBuilderPaint removes the known vector allowlist (incl.
  // non-underscore outline-color/outline-width); the `_` prefix drop covers
  // layout _minzoom/_maxzoom and future `_` keys.
  const stripBuilderPrivate = useCallback(
    (obj: Record<string, unknown>) =>
      Object.fromEntries(
        Object.entries(stripLegacyBuilderPaint(obj)).filter(([k]) => !k.startsWith('_')),
      ),
    [],
  );
  const editorPaint = useMemo(() => stripBuilderPrivate(paint), [paint, stripBuilderPrivate]);
  const editorLayout = useMemo(() => stripBuilderPrivate(layoutObj), [layoutObj, stripBuilderPrivate]);
  // The Advanced JSON editor validates against the rendered layer type, not
  // the geometry-derived one: a heatmap-rendered point layer must accept
  // heatmap-* paint and reject dead circle-* paint. Cluster validates as circle.
  const advancedJsonLayerType = useMemo(() => {
    const resolved = resolveAdapterType(layer.dataset_geometry_type, layer.style_config, editorPaint);
    // 'mixed' passes through: AdvancedJsonEditor validates each family's keys
    // against its own sublayer type, so line-*/circle-* stay authorable.
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

  // Dispatch key for RenderModeSwitch; circle/point layers sub-dispatch by
  // renderMode. getLayerType returns only 'circle' | 'line' | 'fill'; real
  // raster layers are routed to RasterLayerControls by LayerEditorPanel.
  const dispatchKey: EditorDispatchKey = useMemo(() => {
    if (geomType === 'fill') return 'fill';
    if (geomType === 'line') return 'line';
    if (renderMode === 'heatmap') return 'heatmap';
    if (renderMode === 'symbol') return 'symbol';
    if (renderMode === 'cluster') return 'cluster';
    return 'circle';
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
  // 100ms debounce for the master opacity slider. Local state holds the
  // displayed value so drags feel instant while the debounced effect coalesces
  // changes into one onOpacityChange. `opacityFromPropRef` tracks the last
  // `layer.opacity` prop so external resets (undo, layer swap) don't emit; only
  // user drags do.
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
      opacityTimerRef.current = undefined;
      onOpacityChange(layer.id, localOpacity);
    }, 100);
    return () => clearTimeout(opacityTimerRef.current);
  // eslint-disable-next-line react-hooks/exhaustive-deps -- push opacity only on local/layer change; the sync setter is stable
  }, [localOpacity, layer.id]);
  // Flush a still-debouncing value on unmount, or the final slider movement is
  // lost when the editor closes inside the 100ms window. Commit-on-release was
  // rejected: Radix fires onValueCommit per keyboard step, which is spammy.
  const opacityFlushRef = useRef<(() => void) | undefined>(undefined);
  opacityFlushRef.current = () => {
    if (opacityTimerRef.current === undefined) return;
    clearTimeout(opacityTimerRef.current);
    opacityTimerRef.current = undefined;
    onOpacityChange?.(layer.id, localOpacity);
  };
  useEffect(() => () => opacityFlushRef.current?.(), []);

  // Forward map derived from the single BUILDER_PAINT_FIELDS table
  // (builder-paint-map.ts), which also backs handlePaintProp's reverse router
  // and the strip allowlist.
  const controlPaint = useMemo(
    () => buildBuilderControlPaint(paint, builderConfig),
    [paint, builderConfig],
  );

  const updateBuilderConfig = useCallback((patch: BuilderStyleConfig, nextPaint: Record<string, unknown> = paint) => {
    const nextConfig = withBuilderConfig(layer.style_config, patch);
    const strippedPaint = stripLegacyBuilderPaint(nextPaint);
    // A patch that empties the builder must replace, not merge. withBuilderConfig
    // drops the builder key once every field compacts away (collapsing the config
    // to null when nothing else is left), and handleStyleConfigChange reads a
    // missing builder as "keep the existing one", so a default merge undoes the
    // clear (fill/stroke visibility switches springing back on, a line gradient
    // surviving a switch to Solid). Detected centrally because `onBuilderChange`
    // is one prop shared by every builder control; a per-caller flag would go
    // stale when a control learns to clear a key.
    if (!nextConfig?.builder && layer.style_config?.builder) {
      onStyleConfigChange(layer.id, nextConfig, strippedPaint, { replace: true });
      return;
    }
    onStyleConfigChange(layer.id, nextConfig, strippedPaint);
  }, [layer.id, layer.style_config, paint, onStyleConfigChange]);

  const handlePaintProp = useCallback((key: string, value: unknown) => {
    // Reverse router derived from BUILDER_PAINT_FIELDS.
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
    // Persist the ramp direction with the ramp name so Reverse round-trips.
    const heatmapReversed = typeof nextPaint['_heatmap-reversed'] === 'boolean'
      ? nextPaint['_heatmap-reversed'] as boolean
      : builderConfig.heatmapReversed;
    const heatmapWeightColumn = typeof nextPaint['_heatmap-weight-column'] === 'string'
      ? nextPaint['_heatmap-weight-column'] as string
      : nextPaint['heatmap-weight'] === 1
        ? undefined
        : builderConfig.heatmapWeightColumn;
    onStyleConfigChange(
      layerId,
      withBuilderConfig(layer.style_config, { heatmapRamp, heatmapReversed, heatmapWeightColumn }),
      stripLegacyBuilderPaint(nextPaint),
    );
  }, [builderConfig.heatmapRamp, builderConfig.heatmapReversed, builderConfig.heatmapWeightColumn, layer.style_config, onStyleConfigChange]);

  const handleSymbolConfigChange = useCallback((patch: SymbolStyleConfig) => {
    const nextSymbol = { ...symbolConfig, ...patch };
    const nextConfig = {
      ...(layer.style_config ?? {}),
      render_mode: 'symbol',
      symbol: nextSymbol,
    } as StyleConfig;
    onStyleConfigChange(layer.id, nextConfig, stripLegacyBuilderPaint(paint));
  }, [layer.id, layer.style_config, onStyleConfigChange, paint, symbolConfig]);

  // Dedicated fill-pattern handler enforcing mutual exclusion between
  // fill-color and fill-pattern. Setting a pattern deletes fill-color; clearing
  // it (solid / None) deletes fill-pattern. The key is removed, never set to
  // undefined, so saved paint never carries both keys or an undefined value.
  // The solid color is stashed in the builder config first (as fillOpacitySaved
  // above) and restored on None, so a pattern round-trip doesn't return the
  // default blue. Only a string is stashable; an expression means the layer is
  // data-driven, and FillEditor's truth table keeps the picker out of reach.
  const handleFillPatternChange = useCallback((id: string | undefined) => {
    const next = { ...paint };
    // Seed from the existing stash: pattern-to-pattern (Hatch then Dots) finds
    // no fill-color to stash, and an undefined would drop the stash and lose the
    // original color on the eventual None.
    let fillColorSaved = builderConfig.fillColorSaved;
    if (id) {
      // Switching to pattern: stash and remove a solid fill-color, set
      // fill-pattern. An expression is left alone: the picker is reachable on a
      // data-driven layer that already has a pattern (Advanced JSON or the AI
      // action), where the only useful action is None.
      if (typeof next['fill-color'] === 'string') {
        fillColorSaved = next['fill-color'];
        delete next['fill-color'];
      }
      next['fill-pattern'] = id;
    } else {
      // Switching to solid / None: remove fill-pattern
      delete next['fill-pattern'];
      // Restore the stashed color, or the default when there is none. The stash
      // is typed `string` but comes from an open `style_config` with size
      // validation only, so an API-authored layer can hold a number or object;
      // painting that would hand MapLibre a rejected colour. An unusable stash
      // falls through to the default, as `fill-adapter.ts` and the backend
      // export do.
      if (!next['fill-color']) {
        next['fill-color'] =
          typeof fillColorSaved === 'string' ? fillColorSaved : FILL_DEFAULTS['fill-color'];
      }
      fillColorSaved = undefined;
    }
    // A colour classification orphaned by this change (None installed a solid
    // fill where an expression used to be) is not reconciled here: the picker is
    // one of several writers that can strand one, and the rule lives at the
    // commit boundary in use-layer-map-sync.ts, keyed off the resolved paint.
    //
    // Not updateBuilderConfig: this needs `replace`. withBuilderConfig collapses
    // to null once fillColorSaved was the only builder field, and
    // handleStyleConfigChange reads null as "keep the existing builder", which
    // would resurrect the stash this clears. The config built here is already
    // complete, so replacing it verbatim is also the honest signal.
    onStyleConfigChange(
      layer.id,
      withBuilderConfig(layer.style_config, { fillColorSaved }),
      stripLegacyBuilderPaint(next),
      { replace: true },
    );
  }, [layer.id, layer.style_config, paint, builderConfig.fillColorSaved, onStyleConfigChange]);

  const handleResetStyle = useCallback(() => {
    // Every branch clears the zoom clamp, or fill/point layers keep a stale
    // _minzoom/_maxzoom after Reset and can stay invisible at every zoom.
    const nextLayout = { ...layoutObj };
    delete nextLayout['_minzoom'];
    delete nextLayout['_maxzoom'];
    // A plain null config makes the funnel preserve the builder block
    // wholesale, stash included, so a pattern applied later (Advanced JSON) and
    // cleared with None would restore a pre-reset colour.
    //
    // Builder-only, deliberately not withBuilderConfig(layer.style_config, ...):
    // that copies the whole config and `replace` would persist mode / column /
    // render_mode verbatim, but Reset must destroy the classification and render
    // mode. This keeps just the builder block, minus the stash.
    const resetBuilder = compactBuilder({ ...builderConfig, fillColorSaved: undefined });
    const resetConfig = resetBuilder ? ({ builder: resetBuilder } as StyleConfig) : null;
    if (geomType === 'fill') {
      onStyleConfigChange(layer.id, resetConfig, FILL_DEFAULTS, { replace: true });
    } else if (geomType === 'line') {
      delete nextLayout['line-dasharray'];
      onStyleConfigChange(layer.id, resetConfig, LINE_DEFAULTS, { replace: true });
    } else {
      onStyleConfigChange(layer.id, resetConfig, CIRCLE_DEFAULTS, { replace: true });
    }
    onLayoutChange(layer.id, nextLayout);
    onOpacityChange?.(layer.id, 1);
  }, [builderConfig, geomType, layer.id, layoutObj, onLayoutChange, onOpacityChange, onStyleConfigChange]);

  // Reset destroys render mode + classification, so it sits behind the builder's
  // shared inline confirm (as the DEM editor's delete footer).
  const [confirmReset, setConfirmReset] = useState(false);
  // The inline confirm owns focus (autofocused Cancel), so both exits hand focus
  // back to the always-mounted Reset trigger instead of <body>, as StackRow's
  // delete confirm does.
  const resetButtonRef = useRef<HTMLButtonElement>(null);
  const handleConfirmReset = useCallback(() => {
    setConfirmReset(false);
    handleResetStyle();
    resetButtonRef.current?.focus();
  }, [handleResetStyle]);
  const handleCancelReset = useCallback(() => {
    setConfirmReset(false);
    resetButtonRef.current?.focus();
  }, []);

  // Bumped by handleRevertToSaved to force-remount the data-driven editor.
  const [revertNonce, setRevertNonce] = useState(0);

  // The "Pending style preview" banner promises to reflect "this layer before
  // save", so its action reverts unsaved edits to the server baseline rather
  // than applying library defaults (which would flatten hand-authored
  // expressions like a wind-speed line-width). The banner renders only when
  // `savedLayer` exists; a missing one falls back to the defaults reset. The
  // section-header Reset keeps "reset appearance to defaults" via
  // handleResetStyle.
  const handleRevertToSaved = useCallback(() => {
    if (!savedLayer) {
      handleResetStyle();
      return;
    }
    // `restore` as well as `replace`: this is the one caller that reproduces a
    // saved baseline verbatim, so commit-boundary normalization must not touch
    // it, or the dirty check (against that baseline) would see the layer as
    // permanently dirty. The other `replace` callers are forward edits and do
    // need normalizing.
    onStyleConfigChange(layer.id, savedLayer.style_config ?? null, savedLayer.paint ?? {}, { replace: true, restore: true });
    onLayoutChange(layer.id, savedLayer.layout ?? {});
    onOpacityChange?.(layer.id, savedLayer.opacity ?? 1);
    // Remount DataDrivenStyleEditor so its local ramp/mode/column re-seed from the
    // restored config instead of re-applying the just-discarded selection.
    setRevertNonce((n) => n + 1);
    // The handlers above mark the map dirty; ask the baseline owner to recheck.
    onRevertToSaved?.();
  }, [savedLayer, layer.id, onStyleConfigChange, onLayoutChange, onOpacityChange, handleResetStyle, onRevertToSaved]);

  // Symbol mode keeps circle paint on the layer, and switching back to Point
  // restores style_config.savedCirclePaint, not layer.paint (renderAs.ts). The
  // Paint block accepts circle keys in symbol mode, so an edit touching only
  // layer.paint would be discarded on switch-back; keep the saved copy in step.
  const handleAdvancedPaintChange = useCallback((next: Record<string, unknown>) => {
    const merged = { ...builderPrivateKeys(paint), ...next };
    if (renderMode === 'symbol') {
      onStyleConfigChange(
        layer.id,
        { ...(layer.style_config ?? {}), savedCirclePaint: { ...merged } } as StyleConfig,
        merged,
      );
      return;
    }
    onPaintChange(layer.id, merged);
  }, [layer.id, layer.style_config, paint, renderMode, onPaintChange, onStyleConfigChange]);

  const unsupportedBuilderState = hasUnsupportedBuilderState(layer, geomType);

  // Gate the "Pending style preview" banner on real dirty tracking.
  const isStyleDirty = useMemo(
    () => hasUnsavedStyleChangesImpl(layer, savedLayer),
    [layer, savedLayer],
  );

  // Shared props for every per-mode editor via RenderModeSwitch. The ~25-field
  // prop is a deliberate trade-off: one uniform BaseStyleEditorProps keeps
  // RenderModeSwitch's lookup-table dispatch trivial, and most editors consume a
  // subset.
  const editorProps = useMemo(() => ({
    layer,
    paint: controlPaint,
    isDataDriven,
    builderConfig,
    styleConfig: layer.style_config ?? null,
    symbolConfig,
    isPolygon,
    numericColumns,
    currentHeightCol,
    strokeEnabled,
    fillEnabled,
    onPaintChange,
    onLayoutChange,
    onPaintProp: handlePaintProp,
    onToggleFill: handleToggleFill,
    onToggleStroke: handleToggleStroke,
    onHeatmapPaintChange: handleHeatmapPaintChange,
    onSymbolConfigChange: handleSymbolConfigChange,
    onBuilderChange: updateBuilderConfig,
    onFillPatternChange: handleFillPatternChange,
    t,
  }), [
    layer, controlPaint, isDataDriven, builderConfig, symbolConfig,
    isPolygon, numericColumns, currentHeightCol, strokeEnabled, fillEnabled,
    onPaintChange, onLayoutChange,
    handlePaintProp, handleToggleFill, handleToggleStroke,
    handleHeatmapPaintChange, handleSymbolConfigChange, updateBuilderConfig,
    handleFillPatternChange, t,
  ]);

  return (
    <div className="space-y-2">
      {isStyleDirty && <StylePreview layer={layer} onRevert={handleRevertToSaved} />}

      {unsupportedBuilderState && (
        <div className="flex items-start gap-2 rounded-md border border-warning/40 bg-warning/10 p-2 text-xs text-warning">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{t('style.unsupportedBuilderState')}</span>
        </div>
      )}

      {/* Per-render-mode appearance controls via RenderModeSwitch. The section
          title/description adapts to the active mode (heatmap/symbol/cluster have
          their own labels; fill/line/circle share the generic one). */}
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
            ref={resetButtonRef}
            type="button"
            variant="ghost"
            size="xs"
            className="shrink-0"
            onClick={() => setConfirmReset(true)}
            title={t('style.resetTitle')}
          >
            <RotateCcw className="h-3 w-3" />
            {t('style.reset')}
          </Button>
        }
      >
        {confirmReset && (
          <InlineDeleteConfirm
            confirmId={`style-reset-confirm-${layer.id}`}
            message={t('style.resetConfirmMessage')}
            confirmLabel={t('style.resetConfirmAction')}
            cancelLabel={t('style.resetConfirmCancel')}
            onConfirm={handleConfirmReset}
            onCancel={handleCancelReset}
            className="mx-0 mb-0"
          />
        )}
        <RenderModeSwitch {...editorProps} dispatchKey={dispatchKey} />

        {/* Master opacity — all geometry types; omitted when parent owns the opacity control */}
        {onOpacityChange && (
          <>
            {/* One "Layer opacity" row, no separate "Opacity" heading: the
                per-geometry sliders above already say what they scope. */}
            <div className="mt-2 pt-2 border-t" />
            <SliderRow
              label={t('style.layerOpacity')}
              value={localOpacity}
              min={0}
              max={1}
              step={0.01}
              format="percent"
              describedBy={layerOpacityHelpId}
              onChange={setLocalOpacity}
            />
            <p id={layerOpacityHelpId} className="text-xs text-muted-foreground">{t('style.layerOpacityHelp')}</p>
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
        {renderMode !== 'cluster' && !layoutObj['_minzoom'] && exceedsTileFeatureLimit(layer) && (
          <p className="text-xs text-muted-foreground">
            {t('style.tileCapHint', {
              limit: formatNumber(TILE_FEATURE_LIMIT),
              count: formatNumber(layer.dataset_feature_count),
            })}
          </p>
        )}
      </StyleControlSection>

      {/* Data-driven style editor — hidden when in heatmap/symbol/cluster mode */}
      {renderMode !== 'heatmap' && renderMode !== 'symbol' && renderMode !== 'cluster' && (
        <StyleControlSection title={t('style.sections.dataDriven')} description={t('style.sections.dataDrivenDescription')}>
          <LazyLoadErrorBoundary>
            <Suspense fallback={null}>
              <DataDrivenStyleEditor
                // DataDrivenStyleEditor seeds ramp/mode/column into local
                // useState on mount. A banner Revert rewrites layer.style_config
                // externally, but that local state stays stale and its effect
                // would re-apply the discarded ramp. Bumping this key on revert
                // remounts the editor so it re-seeds from the restored config.
                key={`dds-${revertNonce}`}
                layer={layer}
                onStyleConfigChange={onStyleConfigChange}
              />
            </Suspense>
          </LazyLoadErrorBoundary>
        </StyleControlSection>
      )}

      <StyleControlSection title={t('style.sections.advanced')} description={t('style.sections.advancedDescription')}>
        <AdvancedJsonEditor
          paint={editorPaint}
          layout={editorLayout}
          // Re-merge the stripped `_`-prefixed private keys on Apply: the editor
          // never showed them, so a wholesale replace would drop them (layout
          // _minzoom/_maxzoom reset the zoom range to 0–22).
          onPaintChange={handleAdvancedPaintChange}
          onLayoutChange={(l) => onLayoutChange(layer.id, { ...builderPrivateKeys(layoutObj), ...l })}
          layerType={advancedJsonLayerType}
        />
      </StyleControlSection>
    </div>
  );
});
