import { useState, useMemo, useCallback, memo, lazy, Suspense } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronDown, ChevronRight, Code, AlertTriangle, RotateCcw } from 'lucide-react';
import { Switch } from '@/components/ui/switch';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { StyleColorPicker } from './StyleColorPicker';
import { LineGradientControls } from './LineGradientControls';
const DataDrivenStyleEditor = lazy(() => import('./DataDrivenStyleEditor').then(m => ({ default: m.DataDrivenStyleEditor })));
import { HeatmapStyleControls, SliderRow } from './HeatmapStyleControls';
import { ZoomExpressionEditor } from './ZoomExpressionEditor';
import { IconPicker } from './IconPicker';
import { LazyLoadErrorBoundary } from '@/components/error';
import { getLayerType } from '@/components/builder/map-sync';
import { isNumericColumn } from '@/lib/column-utils';
import { MAP_COLORS } from '@/lib/map-colors';
import { stripLegacyBuilderPaint } from '@/lib/normalize-style-config';
import { cn } from '@/lib/utils';
import { GeometrySwatch } from '@/components/map/LegendEntries';
import { getLayerColors } from '@/components/map/layer-icons';
import { getRenderAsOptions } from './renderAs';
import type { BuilderStyleConfig, MapLayerResponse, StyleConfig, SymbolStyleConfig } from '@/types/api';

type PointRenderMode = 'points' | 'heatmap' | 'symbol' | 'cluster';

interface LayerStyleEditorProps {
  layer: MapLayerResponse;
  onPaintChange: (layerId: string, paint: Record<string, unknown>) => void;
  /** Omit to hide the master opacity slider (e.g. when the parent owns opacity via a separate control). */
  onOpacityChange?: (layerId: string, opacity: number) => void;
  onStyleConfigChange: (layerId: string, config: StyleConfig | null, paint: Record<string, unknown>) => void;
  onLayoutChange: (layerId: string, layout: Record<string, unknown>) => void;
  onRenderModeChange?: (layerId: string, mode: PointRenderMode) => void;
}

const LINE_DASH_PRESETS = [
  { key: 'solid', value: undefined },
  { key: 'dashed', value: [4, 2] },
  { key: 'dotted', value: [1, 2] },
  { key: 'dashDot', value: [4, 2, 1, 2] },
] as const;

const LINE_DASH_SERIALIZED = LINE_DASH_PRESETS.map((p) => JSON.stringify(p.value));

// Defaults per geometry type
const FILL_DEFAULTS = {
  'fill-color': MAP_COLORS.default.fill,
  'fill-opacity': MAP_COLORS.default.fillOpacity,
  '_outline-color': MAP_COLORS.default.stroke,
  '_outline-width': 1,
};

const LINE_DEFAULTS = {
  'line-color': MAP_COLORS.default.fill,
  'line-width': 2,
};

const CIRCLE_DEFAULTS = {
  'circle-color': MAP_COLORS.default.fill,
  'circle-radius': 5,
  'circle-stroke-color': MAP_COLORS.default.stroke,
  'circle-stroke-width': 1,
};

function getPaintValue<T>(paint: Record<string, unknown>, key: string, fallback: T): T {
  const val = paint[key];
  // Expression arrays (data-driven styles) aren't valid for scalar controls
  if (Array.isArray(val)) return fallback;
  return val !== undefined && val !== null ? (val as T) : fallback;
}

function getEditableNumericPaintValue(paint: Record<string, unknown>, key: string, fallback: number): number | unknown {
  const val = paint[key];
  return val !== undefined && val !== null ? val : fallback;
}

function compactBuilder(builder: BuilderStyleConfig): BuilderStyleConfig | undefined {
  const compacted = Object.fromEntries(
    Object.entries(builder).filter(([, value]) => value !== undefined),
  ) as BuilderStyleConfig;
  return Object.keys(compacted).length > 0 ? compacted : undefined;
}

function withBuilderConfig(styleConfig: StyleConfig | null | undefined, patch: BuilderStyleConfig): StyleConfig | null {
  const nextBuilder = compactBuilder({ ...(styleConfig?.builder ?? {}), ...patch });
  const nextConfig = { ...(styleConfig ?? {}) } as StyleConfig;
  if (nextBuilder) nextConfig.builder = nextBuilder;
  else delete nextConfig.builder;
  return Object.keys(nextConfig).length > 0 ? nextConfig : null;
}

function stylePreviewStyle(layer: MapLayerResponse) {
  const paint = layer.paint ?? {};
  const gt = (layer.dataset_geometry_type ?? '').toUpperCase();
  if (gt.includes('POLYGON')) {
    return {
      outlineColor: typeof paint['_outline-color'] === 'string' ? paint['_outline-color'] as string : undefined,
      strokeDisabled: Boolean(layer.style_config?.builder?.strokeDisabled ?? paint['_stroke-disabled']),
      opacity: layer.opacity,
      fillOpacity: typeof paint['fill-opacity'] === 'number' ? paint['fill-opacity'] as number : undefined,
      strokeWidth: typeof layer.style_config?.builder?.outlineWidth === 'number'
        ? layer.style_config.builder.outlineWidth
        : typeof paint['_outline-width'] === 'number'
          ? paint['_outline-width'] as number
          : undefined,
    };
  }
  if (gt.includes('POINT')) {
    return {
      outlineColor: typeof paint['circle-stroke-color'] === 'string' ? paint['circle-stroke-color'] as string : undefined,
      strokeDisabled: Boolean(layer.style_config?.builder?.strokeDisabled ?? paint['_stroke-disabled']),
      opacity: layer.opacity,
      fillOpacity: typeof paint['circle-opacity'] === 'number' ? paint['circle-opacity'] as number : undefined,
      strokeWidth: typeof paint['circle-stroke-width'] === 'number' ? paint['circle-stroke-width'] as number : undefined,
    };
  }
  return {
    opacity: layer.opacity,
    fillOpacity: typeof paint['line-opacity'] === 'number' ? paint['line-opacity'] as number : undefined,
    strokeWidth: typeof paint['line-width'] === 'number' ? paint['line-width'] as number : undefined,
  };
}

function hasUnsupportedBuilderState(layer: MapLayerResponse, geomType: string): boolean {
  const config = layer.style_config;
  if (!config) return false;
  if (config.render_mode === 'heatmap' || config.render_mode === 'symbol') return false;
  if (config.mode !== undefined && config.mode !== 'categorical' && config.mode !== 'graduated') return true;
  if (geomType === 'circle' || geomType === 'line' || geomType === 'fill') return false;
  return true;
}

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

/* ---------- Shared stroke toggle + color + width controls ---------- */

interface StrokeControlsProps {
  paint: Record<string, unknown>;
  strokeEnabled: boolean;
  onToggleStroke: () => void;
  colorKey: string;
  colorDefault: string;
  widthKey: string;
  widthDefault: number;
  onPaintProp: (key: string, value: unknown) => void;
  t: (key: string) => string;
}

function StrokeControls({
  paint,
  strokeEnabled,
  onToggleStroke,
  colorKey,
  colorDefault,
  widthKey,
  widthDefault,
  onPaintProp,
  t,
}: StrokeControlsProps) {
  return (
    <>
      <div className="flex items-center justify-between">
        <div className="text-xs font-medium mt-2">{t('style.stroke')}</div>
        <Switch
          checked={strokeEnabled}
          onCheckedChange={onToggleStroke}
          aria-label={t('style.toggleStroke')}
          className="scale-75 mt-2"
        />
      </div>
      {strokeEnabled && (
        <>
          <StyleColorPicker
            label={t('style.color')}
            color={getPaintValue(paint, colorKey, colorDefault)}
            onChange={(hex) => onPaintProp(colorKey, hex)}
          />
          <SliderRow
            label={t('style.width')}
            value={getPaintValue(paint, widthKey, widthDefault)}
            min={0}
            max={10}
            step={0.5}
            format="px"
            onChange={(val) => onPaintProp(widthKey, val)}
          />
        </>
      )}
    </>
  );
}

export const LayerStyleEditor = memo(function LayerStyleEditor({
  layer,
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

  return (
    <div className="space-y-2">
      <StylePreview layer={layer} onReset={handleResetStyle} />

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

      {/* Heatmap controls — shown when render mode is heatmap */}
      {geomType === 'circle' && renderMode === 'heatmap' && (
        <StyleControlSection title={t('style.sections.heatmap')} description={t('style.sections.heatmapDescription')}>
          <HeatmapStyleControls
            layer={{ ...layer, paint: controlPaint }}
            onPaintChange={handleHeatmapPaintChange}
          />
        </StyleControlSection>
      )}

      {geomType === 'circle' && renderMode === 'symbol' && (
        <StyleControlSection title={t('style.sections.symbol')} description={t('style.sections.symbolDescription')}>
          <SymbolControls
            layer={layer}
            config={symbolConfig}
            onChange={handleSymbolConfigChange}
            t={t}
          />
        </StyleControlSection>
      )}

      {geomType === 'circle' && renderMode === 'cluster' && (
        <StyleControlSection title={t('style.sections.cluster')} description={t('style.sections.clusterDescription')}>
          <ClusterControls
            layer={layer}
            builder={builderConfig}
            onBuilderChange={updateBuilderConfig}
            t={t}
          />
        </StyleControlSection>
      )}

      {/* Data-driven style editor — hidden when in heatmap mode */}
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

      {/* Flat color controls */}
      <StyleControlSection title={t('style.sections.appearance')} description={t('style.sections.appearanceDescription')}>
        {geomType === 'fill' && (
          <FillControls
            layer={layer} paint={controlPaint} isDataDriven={isDataDriven}
            fillEnabled={fillEnabled} strokeEnabled={strokeEnabled}
            onToggleFill={handleToggleFill} onToggleStroke={handleToggleStroke}
            onPaintProp={handlePaintProp} onBuilderChange={updateBuilderConfig}
            isPolygon={isPolygon} numericColumns={numericColumns} currentHeightCol={currentHeightCol}
            t={t}
          />
        )}
        {geomType === 'line' && (
          <LineControls
            layer={layer} paint={paint} isDataDriven={isDataDriven}
            styleConfig={layer.style_config ?? null}
            onPaintProp={handlePaintProp} onLayoutChange={onLayoutChange}
            onBuilderChange={(patch, nextPaint) => updateBuilderConfig(patch, nextPaint)}
            t={t}
          />
        )}
        {geomType === 'circle' && renderMode !== 'heatmap' && renderMode !== 'symbol' && (
          <CircleControls
            layer={layer} paint={controlPaint} isDataDriven={isDataDriven}
            strokeEnabled={strokeEnabled} onToggleStroke={handleToggleStroke}
            onPaintProp={handlePaintProp}
            t={t}
          />
        )}

        {/* Master opacity - all geometry types; omitted when parent owns the opacity control */}
        {onOpacityChange && (
          <>
            <div className="text-xs font-medium mt-2 pt-2 border-t">{t('style.opacity')}</div>
            <SliderRow
              label={t('style.layer')}
              value={layer.opacity}
              min={0}
              max={1}
              step={0.01}
              format="percent"
              onChange={(val) => onOpacityChange(layer.id, val)}
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

/* ---------- Geometry-specific control sub-components ---------- */

interface GeomControlProps {
  layer: MapLayerResponse;
  paint: Record<string, unknown>;
  isDataDriven: boolean;
  onPaintProp: (key: string, value: unknown) => void;
  t: (key: string, opts?: Record<string, unknown>) => string;
}

interface FillControlsProps extends GeomControlProps {
  fillEnabled: boolean;
  strokeEnabled: boolean;
  onToggleFill: () => void;
  onToggleStroke: () => void;
  onBuilderChange: (patch: BuilderStyleConfig, nextPaint?: Record<string, unknown>) => void;
  isPolygon: boolean;
  numericColumns: { name: string; type: string }[];
  currentHeightCol: string;
}

function FillControls({
  layer, paint, isDataDriven,
  fillEnabled, strokeEnabled, onToggleFill, onToggleStroke,
  onPaintProp, onBuilderChange, isPolygon, numericColumns, currentHeightCol, t,
}: FillControlsProps) {
  return (
    <>
      <div className="flex items-center justify-between">
        <div className="text-xs font-medium">{t('style.fill')}</div>
        <Switch
          checked={fillEnabled}
          onCheckedChange={onToggleFill}
          aria-label={t('style.toggleFill')}
          className="scale-75"
        />
      </div>
      {fillEnabled && (
        <>
          {isDataDriven ? (
            <div className="text-xs text-muted-foreground italic">
              {t('style.styledBy', { column: layer.style_config?.column })}
            </div>
          ) : (
            <StyleColorPicker
              label={t('style.color')}
              color={getPaintValue(paint, 'fill-color', FILL_DEFAULTS['fill-color'])}
              onChange={(hex) => onPaintProp('fill-color', hex)}
            />
          )}
          <SliderRow
            label={t('style.opacity')}
            value={getPaintValue(paint, 'fill-opacity', FILL_DEFAULTS['fill-opacity'])}
            min={0} max={1} step={0.01} format="percent"
            onChange={(val) => onPaintProp('fill-opacity', val)}
          />
        </>
      )}
      <StrokeControls
        paint={paint} strokeEnabled={strokeEnabled} onToggleStroke={onToggleStroke}
        colorKey="_outline-color" colorDefault={FILL_DEFAULTS['_outline-color']}
        widthKey="_outline-width" widthDefault={FILL_DEFAULTS['_outline-width']}
        onPaintProp={onPaintProp} t={t}
      />
      {isPolygon && numericColumns.length > 0 && (
        <div className="flex items-center justify-between gap-2">
          <span className="text-xs text-muted-foreground">{t('style.heightColumn', { defaultValue: 'Height column' })}</span>
          <Select
            value={currentHeightCol}
            onValueChange={(val) => {
              onBuilderChange({ heightColumn: val === '' || val === '__none__' ? undefined : val });
            }}
          >
            <SelectTrigger className="h-8 text-xs w-36">
              <SelectValue placeholder={t('style.none', { defaultValue: 'None' })} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__none__">{t('style.none', { defaultValue: 'None' })}</SelectItem>
              {numericColumns.map((col) => (
                <SelectItem key={col.name} value={col.name}>{col.name}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}
      {isPolygon && currentHeightCol && !(layer.dataset_column_info ?? []).some((col) => col.name === currentHeightCol) && (
        <div className="flex items-start gap-2 rounded bg-warning/15 p-2">
          <AlertTriangle className="h-4 w-4 shrink-0 text-warning-foreground mt-0.5" />
          <span className="text-xs text-warning-foreground">
            Height column &ldquo;{currentHeightCol}&rdquo; was removed during re-upload. Select a new column or clear this setting.
          </span>
        </div>
      )}
    </>
  );
}

interface LineControlsProps extends GeomControlProps {
  onLayoutChange: (layerId: string, layout: Record<string, unknown>) => void;
  onBuilderChange: (patch: BuilderStyleConfig, nextPaint?: Record<string, unknown>) => void;
  styleConfig: StyleConfig | null;
}

function LineControls({ layer, paint, isDataDriven, onPaintProp, onLayoutChange, onBuilderChange, styleConfig, t }: LineControlsProps) {
  const isWidthDataDriven = isDataDriven && layer.style_config?.target === 'width';
  const builder = styleConfig?.builder ?? {};
  const isArrow = styleConfig?.render_mode === 'arrow';
  const arrowColor = builder.arrowColor
    ?? (typeof paint['line-color'] === 'string' ? paint['line-color'] as string : LINE_DEFAULTS['line-color']);

  return (
    <>
      <div className="text-xs font-medium">{t('style.line')}</div>
      {isDataDriven ? (
        <div className="text-xs text-muted-foreground italic">
          {layer.style_config?.target === 'width'
            ? t('style.widthByColumn', { column: layer.style_config?.column })
            : t('style.styledBy', { column: layer.style_config?.column })}
        </div>
      ) : (
        <LineGradientControls
          paint={paint}
          styleConfig={styleConfig}
          onPaintProp={onPaintProp}
          onBuilderChange={onBuilderChange}
          t={t}
        />
      )}
      <ZoomExpressionEditor
        label={t('style.opacity')}
        value={getEditableNumericPaintValue(paint, 'line-opacity', 1)}
        defaultValue={1}
        min={0} max={1} step={0.01} format="percent"
        onChange={(val) => onPaintProp('line-opacity', val)}
      />
      {!isWidthDataDriven && (
        <ZoomExpressionEditor
          label={t('style.width')}
          value={getEditableNumericPaintValue(paint, 'line-width', LINE_DEFAULTS['line-width'])}
          defaultValue={LINE_DEFAULTS['line-width']}
          min={0.5} max={20} step={0.25} format="px"
          onChange={(val) => onPaintProp('line-width', val)}
        />
      )}
      <SliderRow
        label={t('style.gapWidth')} value={getPaintValue(paint, 'line-gap-width', 0)}
        min={0} max={20} step={0.25} format="px"
        onChange={(val) => onPaintProp('line-gap-width', val)}
      />
      <SliderRow
        label={t('style.blur')} value={getPaintValue(paint, 'line-blur', 0)}
        min={0} max={10} step={0.25} format="px"
        onChange={(val) => onPaintProp('line-blur', val)}
      />
      <SliderRow
        label={t('style.offset')} value={getPaintValue(paint, 'line-offset', 0)}
        min={-20} max={20} step={0.25} format="px"
        onChange={(val) => onPaintProp('line-offset', val)}
      />
      {isArrow && (
        <div className="space-y-2 rounded-md border border-border/70 bg-muted/20 p-2">
          <div className="text-xs font-medium">{t('style.arrow.title')}</div>
          <StyleColorPicker
            label={t('style.arrow.color')}
            color={arrowColor}
            onChange={(hex) => onBuilderChange({ arrowColor: hex })}
          />
          <SliderRow
            label={t('style.arrow.size')}
            value={builder.arrowSize ?? 14}
            min={8} max={28} step={1} format="px"
            onChange={(val) => onBuilderChange({ arrowSize: val })}
          />
          <SliderRow
            label={t('style.arrow.spacing')}
            value={builder.arrowSpacing ?? 80}
            min={24} max={240} step={4} format="px"
            onChange={(val) => onBuilderChange({ arrowSpacing: val })}
          />
        </div>
      )}
      <div className="text-xs font-medium mt-2">{t('style.pattern')}</div>
      <div className="flex gap-1">
        {LINE_DASH_PRESETS.map((preset, idx) => {
          const currentDashValue = (layer.layout as Record<string, unknown>)?.['line-dasharray'];
          const activeIdx = LINE_DASH_SERIALIZED.findIndex((s) => s === JSON.stringify(currentDashValue));
          const isActive = (activeIdx === -1 ? 0 : activeIdx) === idx;
          return (
            <button
              key={preset.key} type="button"
              className={cn(
                'flex-1 cursor-pointer px-2 py-1 text-xs rounded border transition-colors',
                isActive ? 'bg-primary text-primary-foreground border-primary' : 'bg-muted/50 text-muted-foreground border-border hover:bg-muted',
              )}
              onClick={() => {
                const newLayout = { ...(layer.layout ?? {}), 'line-dasharray': preset.value } as Record<string, unknown>;
                if (!preset.value) delete newLayout['line-dasharray'];
                onLayoutChange(layer.id, newLayout);
              }}
            >
              {t(`style.dash.${preset.key}`)}
            </button>
          );
        })}
      </div>
    </>
  );
}

interface CircleControlsProps extends GeomControlProps {
  strokeEnabled: boolean;
  onToggleStroke: () => void;
}

interface ClusterControlsProps {
  layer: MapLayerResponse;
  builder: BuilderStyleConfig;
  onBuilderChange: (patch: BuilderStyleConfig, nextPaint?: Record<string, unknown>) => void;
  t: (key: string, opts?: Record<string, unknown>) => string;
}

interface SymbolControlsProps {
  layer: MapLayerResponse;
  config: SymbolStyleConfig;
  onChange: (patch: SymbolStyleConfig) => void;
  t: (key: string, opts?: Record<string, unknown>) => string;
}

function ClusterControls({ layer, builder, onBuilderChange, t }: ClusterControlsProps) {
  const paint = layer.paint ?? {};
  const clusterColor = builder.clusterColor
    ?? (typeof paint['circle-color'] === 'string' ? paint['circle-color'] as string : CIRCLE_DEFAULTS['circle-color']);
  const clusterTextColor = builder.clusterTextColor ?? '#ffffff';

  return (
    <div className="space-y-3">
      <SliderRow
        label={t('style.cluster.radius')}
        value={builder.clusterRadius ?? 48}
        min={1}
        max={120}
        step={1}
        format="px"
        onChange={(val) => onBuilderChange({ clusterRadius: val })}
      />
      <SliderRow
        label={t('style.cluster.maxZoom')}
        value={builder.clusterMaxZoom ?? 14}
        min={0}
        max={22}
        step={1}
        format="zoom"
        onChange={(val) => onBuilderChange({ clusterMaxZoom: val })}
      />
      <StyleColorPicker
        label={t('style.cluster.color')}
        color={clusterColor}
        onChange={(hex) => onBuilderChange({ clusterColor: hex })}
      />
      <StyleColorPicker
        label={t('style.cluster.countColor')}
        color={clusterTextColor}
        onChange={(hex) => onBuilderChange({ clusterTextColor: hex })}
      />
      <SliderRow
        label={t('style.cluster.countSize')}
        value={builder.clusterTextSize ?? 12}
        min={8}
        max={24}
        step={1}
        format="px"
        onChange={(val) => onBuilderChange({ clusterTextSize: val })}
      />
    </div>
  );
}

function SymbolControls({ layer, config, onChange, t }: SymbolControlsProps) {
  const sampleColumns = layer.dataset_column_info ?? [];
  const categoryColumn = config.categoryColumn ?? '';
  const sampleValues = categoryColumn
    ? (layer.dataset_sample_values?.[categoryColumn] ?? []).slice(0, 6)
    : [];
  const currentCategories = config.categories ?? [];

  function updateCategory(value: string | number | null, icon: string) {
    const existing = currentCategories.filter((entry) => entry.value !== value);
    onChange({ categories: [...existing, { value, icon }], categoryColumn });
  }

  return (
    <div className="space-y-3">
      <div className="text-xs font-medium">{t('style.symbol.title')}</div>
      <IconPicker
        label={t('style.symbol.iconImage')}
        uploadAriaLabel={t('style.symbol.uploadIcon')}
        value={config.iconImage ?? 'marker'}
        onChange={(iconImage) => onChange({ iconImage })}
      />
      <SliderRow
        label={t('style.symbol.size')}
        value={config.iconSize ?? 1}
        min={0.25}
        max={3}
        step={0.05}
        display={String(config.iconSize ?? 1)}
        onChange={(val) => onChange({ iconSize: val })}
      />
      <SliderRow
        label={t('style.symbol.rotation')}
        value={config.iconRotation ?? 0}
        min={0}
        max={360}
        step={1}
        display={`${config.iconRotation ?? 0}°`}
        onChange={(val) => onChange({ iconRotation: val })}
      />
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs text-muted-foreground">{t('style.symbol.anchor')}</span>
        <Select
          value={config.iconAnchor ?? 'center'}
          onValueChange={(value) => onChange({ iconAnchor: value as SymbolStyleConfig['iconAnchor'] })}
        >
          <SelectTrigger className="h-8 text-xs w-36">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {['center', 'top', 'bottom', 'left', 'right', 'top-left', 'top-right', 'bottom-left', 'bottom-right'].map((anchor) => (
              <SelectItem key={anchor} value={anchor}>{anchor}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <SliderRow
          label={t('style.symbol.offsetX')}
          value={config.iconOffset?.[0] ?? 0}
          min={-4}
          max={4}
          step={0.25}
          display={String(config.iconOffset?.[0] ?? 0)}
          onChange={(val) => onChange({ iconOffset: [val, config.iconOffset?.[1] ?? 0] })}
        />
        <SliderRow
          label={t('style.symbol.offsetY')}
          value={config.iconOffset?.[1] ?? 0}
          min={-4}
          max={4}
          step={0.25}
          display={String(config.iconOffset?.[1] ?? 0)}
          onChange={(val) => onChange({ iconOffset: [config.iconOffset?.[0] ?? 0, val] })}
        />
      </div>
      {sampleColumns.length > 0 && (
        <div className="space-y-2 border-t pt-2">
          <div className="text-xs font-medium">{t('style.symbol.categoryMapping')}</div>
          <Select
            value={categoryColumn || '__none__'}
            onValueChange={(value) => onChange({
              categoryColumn: value === '__none__' ? undefined : value,
              categories: value === '__none__' ? undefined : currentCategories,
            })}
          >
            <SelectTrigger className="h-8 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__none__">{t('style.none', { defaultValue: 'None' })}</SelectItem>
              {sampleColumns.map((column) => (
                <SelectItem key={column.name} value={column.name}>{column.name}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          {sampleValues.map((value) => {
            const mapped = currentCategories.find((entry) => entry.value === value)?.icon ?? config.iconImage ?? 'marker';
            return (
              <div key={String(value)} className="flex items-center gap-2">
                <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground">{String(value)}</span>
                <Input
                  className="h-7 text-xs"
                  value={mapped}
                  aria-label={t('style.symbol.categoryIcon', { value: String(value) })}
                  onChange={(event) => updateCategory(value as string | number | null, event.target.value)}
                />
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function CircleControls({ layer, paint, isDataDriven, strokeEnabled, onToggleStroke, onPaintProp, t }: CircleControlsProps) {
  const isRadiusDataDriven = isDataDriven && layer.style_config?.target === 'radius';

  return (
    <>
      <div className="text-xs font-medium">{t('style.point')}</div>
      {isDataDriven ? (
        <div className="text-xs text-muted-foreground italic">
          {layer.style_config?.target === 'radius'
            ? t('style.radiusByColumn', { column: layer.style_config?.column })
            : t('style.styledBy', { column: layer.style_config?.column })}
        </div>
      ) : (
        <StyleColorPicker
          label={t('style.color')}
          color={getPaintValue(paint, 'circle-color', CIRCLE_DEFAULTS['circle-color'])}
          onChange={(hex) => onPaintProp('circle-color', hex)}
        />
      )}
      <ZoomExpressionEditor
        label={t('style.opacity')}
        value={getEditableNumericPaintValue(paint, 'circle-opacity', 1)}
        defaultValue={1}
        min={0} max={1} step={0.01} format="percent"
        onChange={(val) => onPaintProp('circle-opacity', val)}
      />
      {!isRadiusDataDriven && (
        <ZoomExpressionEditor
          label={t('style.radius')}
          value={getEditableNumericPaintValue(paint, 'circle-radius', CIRCLE_DEFAULTS['circle-radius'])}
          defaultValue={CIRCLE_DEFAULTS['circle-radius']}
          min={1} max={30} step={1} format="px"
          onChange={(val) => onPaintProp('circle-radius', val)}
        />
      )}
      <StrokeControls
        paint={paint} strokeEnabled={strokeEnabled} onToggleStroke={onToggleStroke}
        colorKey="circle-stroke-color" colorDefault={CIRCLE_DEFAULTS['circle-stroke-color']}
        widthKey="circle-stroke-width" widthDefault={CIRCLE_DEFAULTS['circle-stroke-width']}
        onPaintProp={onPaintProp} t={t}
      />
    </>
  );
}

/* ---------- Advanced JSON editor ---------- */

interface AdvancedJsonEditorProps {
  paint: Record<string, unknown>;
  layout: Record<string, unknown>;
  onPaintChange: (paint: Record<string, unknown>) => void;
  onLayoutChange: (layout: Record<string, unknown>) => void;
  defaultOpen?: boolean;
  layerType?: string;
}

// Valid MapLibre paint properties per layer type for client-side validation.
// line-gradient gets first-class authoring through LineGradientControls (Phase 256)
// on top of the lineMetrics + adapter expression-preservation engine (Phase 255).
// AdvancedJsonEditor remains available for power-user / paste-in workflows.
const VALID_PAINT_KEYS: Record<string, Set<string>> = {
  fill: new Set(['fill-color', 'fill-opacity', 'fill-outline-color', 'fill-antialias', 'fill-translate', 'fill-translate-anchor', 'fill-pattern']),
  line: new Set(['line-color', 'line-opacity', 'line-width', 'line-gap-width', 'line-blur', 'line-dasharray', 'line-translate', 'line-translate-anchor', 'line-offset', 'line-gradient', 'line-pattern']),
  circle: new Set(['circle-color', 'circle-opacity', 'circle-radius', 'circle-blur', 'circle-stroke-color', 'circle-stroke-opacity', 'circle-stroke-width', 'circle-translate', 'circle-translate-anchor', 'circle-pitch-scale', 'circle-pitch-alignment']),
  heatmap: new Set(['heatmap-radius', 'heatmap-weight', 'heatmap-intensity', 'heatmap-color', 'heatmap-opacity']),
};

function validatePaintJson(paint: Record<string, unknown>, layerType?: string): string[] {
  if (!layerType) return [];
  const validKeys = VALID_PAINT_KEYS[layerType];
  if (!validKeys) return [];
  const errors: string[] = [];
  for (const key of Object.keys(paint)) {
    if (!validKeys.has(key)) {
      errors.push(`"${key}" is not a valid ${layerType} paint property`);
    }
  }
  return errors;
}

function AdvancedJsonEditor({ paint, layout, onPaintChange, onLayoutChange, defaultOpen = false, layerType }: AdvancedJsonEditorProps) {
  const { t } = useTranslation('builder');
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className="border-t pt-2">
      <button
        className="flex cursor-pointer items-center gap-1 text-xs font-medium text-muted-foreground hover:text-foreground w-full"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3 rtl-mirror" />}
        <Code className="h-3 w-3" />
        {t('style.advancedJson')}
      </button>
      {open && (
        <div className="mt-2 space-y-3">
          <JsonBlock
            label={t('style.paintJson')}
            value={paint}
            onApply={onPaintChange}
            layerType={layerType}
          />
          <JsonBlock
            label={t('style.layoutJson')}
            value={layout}
            onApply={onLayoutChange}
          />
        </div>
      )}
    </div>
  );
}

function JsonBlock({ label, value, onApply, layerType }: { label: string; value: Record<string, unknown>; onApply: (v: Record<string, unknown>) => void; layerType?: string }) {
  const { t } = useTranslation('builder');
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState('');
  const [error, setError] = useState<string | null>(null);

  function handleOpen() {
    setText(JSON.stringify(value, null, 2));
    setError(null);
    setEditing(true);
  }

  function handleApply() {
    try {
      const parsed = JSON.parse(text) as Record<string, unknown>;
      if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
        setError(t('style.jsonError'));
        return;
      }
      // Validate paint properties against MapLibre spec if layerType is available
      if (layerType) {
        const validationErrors = validatePaintJson(parsed, layerType);
        if (validationErrors.length > 0) {
          setError(validationErrors.join('; '));
          return;
        }
      }
      onApply(parsed);
      setError(null);
      setEditing(false);
    } catch {
      setError(t('style.jsonError'));
    }
  }

  if (!editing) {
    return (
      <div>
        <button
          className="cursor-pointer text-xs text-muted-foreground hover:text-foreground underline"
          onClick={handleOpen}
        >
          {label}
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-1.5">
      <div className="text-xs font-medium text-muted-foreground">{label}</div>
      <textarea
        className="w-full rounded border border-input bg-background p-2 text-xs font-mono resize-y min-h-[80px] outline-none focus:ring-1 focus:ring-ring"
        value={text}
        onChange={(e) => { setText(e.target.value); setError(null); }}
        spellCheck={false}
      />
      {error && <div className="text-xs text-destructive">{error}</div>}
      <div className="flex gap-1.5">
        <Button size="sm" className="h-6 text-xs px-2" onClick={handleApply}>
          {t('style.jsonApply')}
        </Button>
        <Button size="sm" variant="ghost" className="h-6 text-xs px-2" onClick={() => setEditing(false)}>
          {t('style.jsonCancel')}
        </Button>
      </div>
    </div>
  );
}
