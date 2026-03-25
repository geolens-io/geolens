import { useTranslation } from 'react-i18next';
import { Slider } from '@/components/ui/slider';
import { Switch } from '@/components/ui/switch';
import { StyleColorPicker } from './StyleColorPicker';
import { DataDrivenStyleEditor } from './DataDrivenStyleEditor';
import { getLayerType } from '@/components/builder/map-sync';
import { MAP_COLORS } from '@/lib/map-colors';
import { cn } from '@/lib/utils';
import type { MapLayerResponse, StyleConfig } from '@/types/api';

interface LayerStyleEditorProps {
  layer: MapLayerResponse;
  onPaintChange: (layerId: string, paint: Record<string, unknown>) => void;
  onOpacityChange: (layerId: string, opacity: number) => void;
  onStyleConfigChange: (layerId: string, config: StyleConfig | null, paint: Record<string, unknown>) => void;
  onLayoutChange: (layerId: string, layout: Record<string, unknown>) => void;
}

const LINE_DASH_PRESETS = [
  { key: 'solid', value: undefined },
  { key: 'dashed', value: [4, 2] },
  { key: 'dotted', value: [1, 2] },
  { key: 'dashDot', value: [4, 2, 1, 2] },
] as const;

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

export function LayerStyleEditor({
  layer,
  onPaintChange,
  onOpacityChange,
  onStyleConfigChange,
  onLayoutChange,
}: LayerStyleEditorProps) {
  const { t } = useTranslation('builder');
  const geomType = getLayerType(layer.dataset_geometry_type);
  const paint = layer.paint;
  const isDataDriven = !!layer.style_config?.column;

  const fillEnabled = !paint['_fill-disabled'];
  const strokeEnabled = !paint['_stroke-disabled'];

  function handlePaintProp(key: string, value: unknown) {
    onPaintChange(layer.id, { ...paint, [key]: value });
  }

  function handleToggleFill() {
    const next = { ...paint };
    if (fillEnabled) {
      next['_fill-opacity-saved'] = getPaintValue(paint, 'fill-opacity', FILL_DEFAULTS['fill-opacity']);
      next['fill-opacity'] = 0;
      next['_fill-disabled'] = true;
    } else {
      const saved = getPaintValue(paint, '_fill-opacity-saved', FILL_DEFAULTS['fill-opacity']);
      next['fill-opacity'] = saved;
      delete next['_fill-disabled'];
      delete next['_fill-opacity-saved'];
    }
    onPaintChange(layer.id, next);
  }

  function handleToggleStroke() {
    const next = { ...paint };
    if (geomType === 'circle') {
      if (strokeEnabled) {
        next['_outline-width-saved'] = getPaintValue(paint, 'circle-stroke-width', CIRCLE_DEFAULTS['circle-stroke-width']);
        next['circle-stroke-width'] = 0;
        next['_stroke-disabled'] = true;
      } else {
        next['circle-stroke-width'] = getPaintValue(paint, '_outline-width-saved', CIRCLE_DEFAULTS['circle-stroke-width']);
        delete next['_stroke-disabled'];
        delete next['_outline-width-saved'];
      }
    } else {
      // polygon
      if (strokeEnabled) {
        next['_outline-width-saved'] = getPaintValue(paint, '_outline-width', FILL_DEFAULTS['_outline-width']);
        next['_outline-width'] = 0;
        next['_stroke-disabled'] = true;
      } else {
        next['_outline-width'] = getPaintValue(paint, '_outline-width-saved', FILL_DEFAULTS['_outline-width']);
        delete next['_stroke-disabled'];
        delete next['_outline-width-saved'];
      }
    }
    onPaintChange(layer.id, next);
  }

  return (
    <div className="space-y-3">
      {/* Data-driven style editor */}
      <DataDrivenStyleEditor
        layer={layer}
        onStyleConfigChange={onStyleConfigChange}
      />

      {/* Flat color controls */}
      <div className="space-y-3 p-3 bg-muted/30 rounded-md border">
        {/* Polygon (fill) controls */}
        {geomType === 'fill' && (
          <>
            <div className="flex items-center justify-between">
              <div className="text-xs font-medium">{t('style.fill')}</div>
              <Switch
                checked={fillEnabled}
                onCheckedChange={handleToggleFill}
                aria-label={t('style.toggleFill')}
                className="scale-75"
              />
            </div>
            {fillEnabled && (
              <>
                {isDataDriven ? (
                  <div className="text-xs text-muted-foreground italic">
                    {t('style.styledBy', { column: layer.style_config!.column })}
                  </div>
                ) : (
                  <StyleColorPicker
                    label={t('style.color')}
                    color={getPaintValue(paint, 'fill-color', FILL_DEFAULTS['fill-color'])}
                    onChange={(hex) => handlePaintProp('fill-color', hex)}
                  />
                )}
                <SliderRow
                  label={t('style.opacity')}
                  value={getPaintValue(paint, 'fill-opacity', FILL_DEFAULTS['fill-opacity'])}
                  min={0}
                  max={1}
                  step={0.01}
                  format="percent"
                  onChange={(val) => handlePaintProp('fill-opacity', val)}
                />
              </>
            )}
            <div className="flex items-center justify-between">
              <div className="text-xs font-medium mt-2">{t('style.stroke')}</div>
              <Switch
                checked={strokeEnabled}
                onCheckedChange={handleToggleStroke}
                aria-label={t('style.toggleStroke')}
                className="scale-75 mt-2"
              />
            </div>
            {strokeEnabled && (
              <>
                <StyleColorPicker
                  label={t('style.color')}
                  color={getPaintValue(paint, '_outline-color', FILL_DEFAULTS['_outline-color'])}
                  onChange={(hex) => handlePaintProp('_outline-color', hex)}
                />
                <SliderRow
                  label={t('style.width')}
                  value={getPaintValue(paint, '_outline-width', FILL_DEFAULTS['_outline-width'])}
                  min={0}
                  max={10}
                  step={0.5}
                  format="px"
                  onChange={(val) => handlePaintProp('_outline-width', val)}
                />
              </>
            )}
          </>
        )}

        {/* Line controls */}
        {geomType === 'line' && (
          <>
            <div className="text-xs font-medium">{t('style.line')}</div>
            {isDataDriven ? (
              <div className="text-xs text-muted-foreground italic">
                {t('style.styledBy', { column: layer.style_config!.column })}
              </div>
            ) : (
              <StyleColorPicker
                label={t('style.color')}
                color={getPaintValue(paint, 'line-color', LINE_DEFAULTS['line-color'])}
                onChange={(hex) => handlePaintProp('line-color', hex)}
              />
            )}
            <SliderRow
              label={t('style.opacity')}
              value={getPaintValue(paint, 'line-opacity', 1)}
              min={0}
              max={1}
              step={0.01}
              format="percent"
              onChange={(val) => handlePaintProp('line-opacity', val)}
            />
            <SliderRow
              label={t('style.width')}
              value={getPaintValue(paint, 'line-width', LINE_DEFAULTS['line-width'])}
              min={1}
              max={20}
              step={0.5}
              format="px"
              onChange={(val) => handlePaintProp('line-width', val)}
            />
            <div className="text-xs font-medium mt-2">{t('style.pattern')}</div>
            <div className="flex gap-1">
              {LINE_DASH_PRESETS.map((preset) => {
                const currentDashValue = (layer.layout as Record<string, unknown>)?.['line-dasharray'];
                const currentDash = LINE_DASH_PRESETS.find(
                  (p) => JSON.stringify(p.value) === JSON.stringify(currentDashValue),
                )?.key ?? 'solid';
                return (
                  <button
                    key={preset.key}
                    type="button"
                    className={cn(
                      'flex-1 px-2 py-1 text-xs rounded border transition-colors',
                      currentDash === preset.key
                        ? 'bg-primary text-primary-foreground border-primary'
                        : 'bg-muted/50 text-muted-foreground border-border hover:bg-muted',
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
        )}

        {/* Circle (point) controls */}
        {geomType === 'circle' && (
          <>
            <div className="text-xs font-medium">{t('style.point')}</div>
            {isDataDriven ? (
              <div className="text-xs text-muted-foreground italic">
                {t('style.styledBy', { column: layer.style_config!.column })}
              </div>
            ) : (
              <StyleColorPicker
                label={t('style.color')}
                color={getPaintValue(paint, 'circle-color', CIRCLE_DEFAULTS['circle-color'])}
                onChange={(hex) => handlePaintProp('circle-color', hex)}
              />
            )}
            <SliderRow
              label={t('style.opacity')}
              value={getPaintValue(paint, 'circle-opacity', 1)}
              min={0}
              max={1}
              step={0.01}
              format="percent"
              onChange={(val) => handlePaintProp('circle-opacity', val)}
            />
            <SliderRow
              label={t('style.radius')}
              value={getPaintValue(paint, 'circle-radius', CIRCLE_DEFAULTS['circle-radius'])}
              min={1}
              max={30}
              step={1}
              format="px"
              onChange={(val) => handlePaintProp('circle-radius', val)}
            />
            <div className="flex items-center justify-between">
              <div className="text-xs font-medium mt-2">{t('style.stroke')}</div>
              <Switch
                checked={strokeEnabled}
                onCheckedChange={handleToggleStroke}
                aria-label={t('style.toggleStroke')}
                className="scale-75 mt-2"
              />
            </div>
            {strokeEnabled && (
              <>
                <StyleColorPicker
                  label={t('style.color')}
                  color={getPaintValue(paint, 'circle-stroke-color', CIRCLE_DEFAULTS['circle-stroke-color'])}
                  onChange={(hex) => handlePaintProp('circle-stroke-color', hex)}
                />
                <SliderRow
                  label={t('style.width')}
                  value={getPaintValue(paint, 'circle-stroke-width', CIRCLE_DEFAULTS['circle-stroke-width'])}
                  min={0}
                  max={10}
                  step={0.5}
                  format="px"
                  onChange={(val) => handlePaintProp('circle-stroke-width', val)}
                />
              </>
            )}
          </>
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
      </div>
    </div>
  );
}

// Internal slider row helper
interface SliderRowProps {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  format: 'percent' | 'px';
  onChange: (val: number) => void;
}

function SliderRow({ label, value, min, max, step, format, onChange }: SliderRowProps) {
  const display =
    format === 'percent'
      ? `${Math.round(value * 100)}%`
      : `${value}px`;

  return (
    <div className="flex items-center gap-2">
      <span className="text-xs text-muted-foreground w-20">{label}</span>
      <Slider
        value={[value]}
        min={min}
        max={max}
        step={step}
        onValueChange={([v]) => onChange(v)}
        className="flex-1"
      />
      <span className="text-xs text-muted-foreground w-10 text-right">{display}</span>
    </div>
  );
}
