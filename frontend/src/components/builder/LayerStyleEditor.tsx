import { useState, useMemo, useCallback, memo, lazy, Suspense } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronDown, ChevronRight, Code, AlertTriangle } from 'lucide-react';
import { Switch } from '@/components/ui/switch';
import { Button } from '@/components/ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { StyleColorPicker } from './StyleColorPicker';
const DataDrivenStyleEditor = lazy(() => import('./DataDrivenStyleEditor').then(m => ({ default: m.DataDrivenStyleEditor })));
import { HeatmapStyleControls, SliderRow } from './HeatmapStyleControls';
import { ZoomExpressionEditor } from './ZoomExpressionEditor';
import { LazyLoadErrorBoundary } from '@/components/error';
import { getLayerType } from '@/components/builder/map-sync';
import { isNumericColumn } from '@/lib/column-utils';
import { MAP_COLORS } from '@/lib/map-colors';
import { stripLegacyBuilderPaint } from '@/lib/normalize-style-config';
import { cn } from '@/lib/utils';
import type { BuilderStyleConfig, MapLayerResponse, StyleConfig } from '@/types/api';

interface LayerStyleEditorProps {
  layer: MapLayerResponse;
  onPaintChange: (layerId: string, paint: Record<string, unknown>) => void;
  onOpacityChange: (layerId: string, opacity: number) => void;
  onStyleConfigChange: (layerId: string, config: StyleConfig | null, paint: Record<string, unknown>) => void;
  onLayoutChange: (layerId: string, layout: Record<string, unknown>) => void;
  onRenderModeChange?: (layerId: string, mode: 'points' | 'heatmap') => void;
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
  const layoutObj = (layer.layout as Record<string, unknown>) ?? {};
  const isDataDriven = !!layer.style_config?.column;
  const renderMode: 'points' | 'heatmap' = layer.style_config?.render_mode ?? 'points';
  const builderConfig = layer.style_config?.builder ?? {};

  const fillEnabled = !(builderConfig.fillDisabled ?? paint['_fill-disabled']);
  const strokeEnabled = !(builderConfig.strokeDisabled ?? paint['_stroke-disabled']);

  const isPolygon = (layer.dataset_geometry_type ?? '').toUpperCase().includes('POLYGON');
  const numericColumns = useMemo(
    () => (layer.dataset_column_info ?? []).filter((col) => isNumericColumn(col.type)),
    [layer.dataset_column_info],
  );
  const currentHeightCol = builderConfig.heightColumn ?? (layer.paint?.['_height_column'] as string) ?? '';

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

  return (
    <div className="space-y-2">
      {/* Render as dropdown — point layers only */}
      {geomType === 'circle' && (
        <div className="space-y-1">
          <div className="text-xs font-medium">{t('style.renderAs')}</div>
          <Select
            value={renderMode}
            onValueChange={(mode) => onRenderModeChange?.(layer.id, mode as 'points' | 'heatmap')}
          >
            <SelectTrigger className="h-8 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="points">{t('style.renderPoints')}</SelectItem>
              <SelectItem value="heatmap">{t('style.renderHeatmap')}</SelectItem>
            </SelectContent>
          </Select>
        </div>
      )}

      {/* Heatmap controls — shown when render mode is heatmap */}
      {geomType === 'circle' && renderMode === 'heatmap' && (
        <HeatmapStyleControls
          layer={{ ...layer, paint: controlPaint }}
          onPaintChange={handleHeatmapPaintChange}
        />
      )}

      {/* Data-driven style editor — hidden when in heatmap mode */}
      {renderMode !== 'heatmap' && (
        <LazyLoadErrorBoundary>
          <Suspense fallback={null}>
            <DataDrivenStyleEditor
              layer={layer}
              onStyleConfigChange={onStyleConfigChange}
            />
          </Suspense>
        </LazyLoadErrorBoundary>
      )}

      {/* Flat color controls */}
      <div className="space-y-3 p-3 bg-muted/30 rounded-md border">
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
            onPaintProp={handlePaintProp} onLayoutChange={onLayoutChange}
            t={t}
          />
        )}
        {geomType === 'circle' && renderMode !== 'heatmap' && (
          <CircleControls
            layer={layer} paint={controlPaint} isDataDriven={isDataDriven}
            strokeEnabled={strokeEnabled} onToggleStroke={handleToggleStroke}
            onPaintProp={handlePaintProp}
            t={t}
          />
        )}

        {/* Master opacity - all geometry types */}
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
      </div>

      <AdvancedJsonEditor
        paint={paint}
        layout={(layer.layout as Record<string, unknown>) ?? {}}
        onPaintChange={(p) => onPaintChange(layer.id, p)}
        onLayoutChange={(l) => onLayoutChange(layer.id, l)}
        layerType={geomType}
      />
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
}

function LineControls({ layer, paint, isDataDriven, onPaintProp, onLayoutChange, t }: LineControlsProps) {
  const isWidthDataDriven = isDataDriven && layer.style_config?.target === 'width';

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
        <StyleColorPicker
          label={t('style.color')}
          color={getPaintValue(paint, 'line-color', LINE_DEFAULTS['line-color'])}
          onChange={(hex) => onPaintProp('line-color', hex)}
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
                'flex-1 px-2 py-1 text-xs rounded border transition-colors',
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
// line-gradient remains JSON-only for now: safe first-class authoring needs
// source lineMetrics=true and gradient expression editing designed together.
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
        className="flex items-center gap-1 text-xs font-medium text-muted-foreground hover:text-foreground w-full"
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
          className="text-xs text-muted-foreground hover:text-foreground underline"
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
